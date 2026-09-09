"""RAG Retriever — recherche par similarité cosinus TF-IDF dans le STDTemplateStore.

Usage :
  from src.rag import STDRetriever

  retriever = STDRetriever.build(
      word_paths=[Path("STD-template.docx")],
      sql_paths=[Path("DWH_UCMS.sql"), Path("DWH_CRM.sql")],
  )
  context = retriever.retrieve("mapping MERGE INTO staging DWH", top_k=3)
  # context → str avec les chunks les plus pertinents formatés pour injection dans prompt
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from .template_store import STDTemplateStore, Chunk, _tokenize

LOGGER = logging.getLogger(__name__)


class STDRetriever:
    """Retriever TF-IDF sur le store de template STD.

    Méthode principale :
      retrieve(query, top_k=3) → str  (contexte formaté pour injection dans un prompt LLM)

    Constructeur de classe :
      STDRetriever.build(word_paths, sql_paths) → STDRetriever
    """

    def __init__(self, store: STDTemplateStore) -> None:
        self._store = store

    # ---- Constructeur de classe ----

    @classmethod
    def build(
        cls,
        word_paths: list[Path] | None = None,
        sql_paths: list[Path] | None = None,
    ) -> "STDRetriever":
        """Construit un retriever à partir de fichiers Word et SQL.

        Args:
            word_paths: Liste de fichiers .docx à indexer (templates STD).
            sql_paths: Liste de fichiers .sql à indexer (patterns de référence).

        Returns:
            STDRetriever prêt à l'emploi.
        """
        store = STDTemplateStore()

        for path in (word_paths or []):
            if path and path.exists():
                store.load_word(path)

        for path in (sql_paths or []):
            if path and path.exists():
                store.load_sql(path)

        if store.chunks:
            store.build_index()
        else:
            LOGGER.warning("STDRetriever: aucun document chargé dans le store RAG.")

        return cls(store)

    # ---- Retrieval ----

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        chunk_types: list[str] | None = None,
    ) -> str:
        """Recherche les chunks les plus pertinents par similarité cosinus TF-IDF.

        Args:
            query: La requête textuelle (ex: titre de section + mots-clés).
            top_k: Nombre maximum de chunks à retourner.
            chunk_types: Filtrer par types (ex: ['template_word']). None = tous.

        Returns:
            Contexte formaté prêt pour injection dans un prompt LLM.
            Retourne une chaîne vide si le store est vide.
        """
        if not self._store.index_built or not self._store.chunks:
            return ""

        query_tokens = _tokenize(query)
        if not query_tokens:
            return ""

        # Vecteur TF-IDF de la query (simple TF, pas d'IDF pour la query)
        from collections import Counter
        query_tf: dict[str, float] = {}
        counts = Counter(query_tokens)
        n_qtoks = len(query_tokens) or 1
        for tok, freq in counts.items():
            idf = self._store._idf.get(tok, 0.0)
            query_tf[tok] = (freq / n_qtoks) * idf

        # Normalisation L2 de la query
        q_norm = math.sqrt(sum(v ** 2 for v in query_tf.values())) or 1.0
        query_vec = {tok: v / q_norm for tok, v in query_tf.items()}

        # Calcul de similarité cosinus pour chaque chunk
        candidates = self._store.chunks
        if chunk_types:
            candidates = [c for c in candidates if c.chunk_type in chunk_types]

        scored: list[tuple[float, Chunk]] = []
        for chunk in candidates:
            score = _cosine_similarity(query_vec, chunk.tfidf)
            if score > 0.0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        if not top:
            return ""

        # Formatage du contexte pour injection dans un prompt LLM
        parts: list[str] = ["### Contexte RAG (extraits du template STD de référence)\n"]
        for i, (score, chunk) in enumerate(top, start=1):
            header = f"**[Extrait {i} — {chunk.source} / {chunk.section}]** (pertinence: {score:.2f})"
            body = chunk.text[:600].replace("\n", " ").strip()
            parts.append(f"{header}\n{body}\n")

        return "\n".join(parts)

    def retrieve_for_section(self, section_id: str) -> str:
        """Retourne du contexte RAG adapté à une section STD spécifique.

        Utilise des requêtes pré-définies par section pour maximiser la pertinence.

        Args:
            section_id: Identifiant de la section ('mapping', 'dwh', 'etl', etc.)

        Returns:
            Contexte formaté.
        """
        _SECTION_QUERIES = {
            "intro": "introduction périmètre projet décisionnel architecture technique détaillée",
            "sources": "données sources fichier source staging area connexion système",
            "staging": "staging area table STG chargement données brutes zone temporaire",
            "dwh": "data warehouse table DWH modèle dimensionnel colonnes types clés",
            "mapping": "mapping règles transformation MERGE INTO source cible colonne",
            "etl": "package ETL SSIS MASTER alimentation chargement orchestration",
            "performance": "volumétrie performance temps chargement optimisation index partition",
            "data_quality": "qualité données contrôle validation règle nettoyage",
            "security": "sécurité accès rôle profil permission authentification",
            "monitoring": "monitoring traçabilité log audit table suivi traitements",
        }
        query = _SECTION_QUERIES.get(section_id, section_id)
        return self.retrieve(query, top_k=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Calcule la similarité cosinus entre deux vecteurs sparses (dicts)."""
    dot = sum(vec_a[tok] * vec_b[tok] for tok in vec_a if tok in vec_b)
    return dot
