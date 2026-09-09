from __future__ import annotations

import logging
import re
from typing import Callable, TypeVar

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    Groq,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)

from .base import BaseLLMClient

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")
_RETRY_AFTER_PATTERN = re.compile(r"try again in ([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)

# Fallback model list — ordered by quality, all confirmed active on Groq.
# To refresh: python -c "from groq import Groq; import os; from dotenv import load_dotenv; load_dotenv(); [print(m.id) for m in Groq().models.list().data]"
_FALLBACK_MODELS = [
    "openai/gpt-oss-120b",    # GPT-class 120B — meilleure qualite disponible
    "openai/gpt-oss-20b",     # GPT-class 20B — bon equilibre qualite/vitesse
    "qwen/qwen3.8-27b",       # Qwen 3.8 27B — tres bon suivi d'instructions
    "qwen/qwen3.6-27b",       # Qwen 3.6 27B — fallback supplementaire
    "groq/compound",          # Groq Compound — modele composite Groq natif
]


def _status_code(error: BaseException) -> int | None:
    code = getattr(error, "status_code", None)
    if isinstance(code, int):
        return code

    response = getattr(error, "response", None)
    response_code = getattr(response, "status_code", None)
    return response_code if isinstance(response_code, int) else None


def _is_retryable_exception(error: BaseException) -> bool:
    status_code = _status_code(error)
    # Ne pas retenter sur les erreurs de modele indisponible (404, 400 decommissioned)
    if status_code in {400, 404}:
        return False
    err_str = str(error)
    if "model_not_found" in err_str or "model_decommissioned" in err_str:
        return False
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True

    return isinstance(
        error, (APITimeoutError, APIConnectionError, InternalServerError, RateLimitError)
    )


def _retry_delay_from_exception(error: BaseException) -> float | None:
    match = _RETRY_AFTER_PATTERN.search(str(error))
    if match is None:
        return None

    try:
        return max(float(match.group(1)) + 1.0, 1.0)
    except ValueError:
        return None


def _wait_for_retry(retry_state: RetryCallState) -> float:
    exception = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if exception is not None:
        retry_after = _retry_delay_from_exception(exception)
        if retry_after is not None:
            return min(retry_after, 10.0)

    return float(min(2 ** (retry_state.attempt_number - 1), 10))


def _retryable(function: Callable[..., T]) -> Callable[..., T]:
    return retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=_wait_for_retry,
        retry=retry_if_exception(_is_retryable_exception),
        before_sleep=before_sleep_log(LOGGER, logging.WARNING),
    )(function)


class GroqClient(BaseLLMClient):
    """Client pour les modèles LLM Groq avec gestion automatique du basculement (fallback)."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__(
            api_key=api_key,
            api_key_env_var="GROQ_API_KEY",
            model=model,
            default_model="openai/gpt-oss-20b",
        )
        self._client = Groq(api_key=self.api_key, max_retries=0)

    def generate(self, prompt: str) -> str:
        # Essayer avec le modèle configuré en premier, puis les fallbacks
        models_to_try = [self.model] + [m for m in _FALLBACK_MODELS if m != self.model]

        last_exception: Exception | None = None
        for m in models_to_try:
            try:
                return self._generate_with_model(prompt, model_name=m)
            except RateLimitError as exc:
                LOGGER.warning(
                    "Limitation de debit sur '%s'. Tentative avec le modele suivant...", m
                )
                last_exception = exc
            except Exception as exc:
                err_str = str(exc)
                # 404 ou modèle déprécié -> passer directement au suivant, sans retry
                if "model_not_found" in err_str or "model_decommissioned" in err_str or "404" in err_str:
                    LOGGER.warning("Modele '%s' indisponible -- passage au suivant.", m)
                    last_exception = exc
                else:
                    LOGGER.warning("Erreur avec le modele '%s': %s", m, exc)
                    last_exception = exc

        if last_exception:
            raise RuntimeError(f"Tous les modeles Groq ont echoue: {last_exception}") from last_exception
        return ""

    @_retryable
    def _generate_with_model(self, prompt: str, model_name: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
        except AuthenticationError as exc:
            message = (
                "Groq authentication failed. The value in GROQ_API_KEY is missing or invalid. "
                "Use a valid Groq API key before relaunching the script."
            )
            LOGGER.error(message)
            raise RuntimeError(message) from exc
        except APIStatusError as exc:
            if _status_code(exc) == 401:
                message = (
                    "Groq authentication failed. The value in GROQ_API_KEY is missing or invalid. "
                    "Use a valid Groq API key before relaunching the script."
                )
                LOGGER.error(message)
                raise RuntimeError(message) from exc
            raise
        except BadRequestError as exc:
            if "model_decommissioned" in str(exc) or _status_code(exc) == 400:
                LOGGER.warning("Modèle '%s' déprécié ou non disponible.", model_name)
            raise

        msg = response.choices[0].message if response.choices else None
        content = getattr(msg, "content", None) if msg else None
        if not content and msg:
            content = getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None)
        if not content:
            raise ValueError(f"Modèle {model_name} a renvoyé une réponse vide.")
        return str(content).strip()
