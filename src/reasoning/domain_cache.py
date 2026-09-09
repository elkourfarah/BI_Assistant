"""Cache dynamique de domaine — Mémoire persistante pour l'analyse d'ontologie.

Permet d'accélérer l'évaluation des fichiers récurrents sans ré-exécuter le LLM.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / "output" / ".domain_cache.json"


class DomainCache:
    """Cache LRU persistant sur disque des fingerprints de domaines."""

    def __init__(self, cache_file: Path = _CACHE_FILE) -> None:
        self.cache_file = cache_file
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {}
        try:
            raw = self.cache_file.read_text(encoding="utf-8")
            return json.loads(raw)
        except Exception as exc:
            LOGGER.warning("Impossible de lire le cache de domaine %s : %s", self.cache_file, exc)
            return {}

    def _save(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            LOGGER.warning("Impossible de sauvegarder le cache %s : %s", self.cache_file, exc)

    def get(self, ontology_text: str) -> dict[str, Any] | None:
        """Récupère l'évaluation de domaine pour une ontologie donnée."""
        key = self._hash(ontology_text)
        return self._data.get(key)

    def set(self, ontology_text: str, assessment: dict[str, Any]) -> None:
        """Stocke l'évaluation de domaine dans le cache."""
        key = self._hash(ontology_text)
        self._data[key] = assessment
        self._save()

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
