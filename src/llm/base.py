from __future__ import annotations

import os
from abc import ABC, abstractmethod


class BaseLLMClient(ABC):
    def __init__(self, api_key: str | None, api_key_env_var: str, model: str | None, default_model: str) -> None:
        self.api_key = api_key or os.getenv(api_key_env_var)
        if not self.api_key:
            raise RuntimeError(f"La variable d'environnement {api_key_env_var} est manquante.")

        self.model = model or os.getenv("GROQ_MODEL", default_model)

    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError
