"""Module d'extraction du fingerprint sémantique (empreinte lexicale métier).

Extrait tous les noms de colonnes, tables, mesures, dimensions du graphe
ou des métadonnées, nettoie les stopwords (français, anglais et tokens techniques SQL/BI)
et conserve les 50 tokens les plus fréquents pour caractériser fidèlement le domaine métier.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

LOGGER = logging.getLogger(__name__)

# Stopwords linguistiques (Français & Anglais)
_LINGUISTIC_STOPWORDS = {
    # Français
    "le", "la", "les", "de", "du", "des", "un", "une", "et", "en", "pour",
    "dans", "sur", "par", "au", "aux", "avec", "sans", "sous", "ce", "cet",
    "cette", "ces", "son", "sa", "ses", "leur", "leurs", "qui", "que", "quoi",
    "dont", "ou", "mais", "donc", "or", "ni", "car", "est", "sont", "ete",
    # Anglais
    "the", "a", "an", "and", "or", "of", "in", "to", "for", "with", "on",
    "at", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "not", "but", "if",
    "this", "that", "these", "those", "then", "all", "any", "both", "each",
}

# Stopwords techniques SQL, bases de données, ETL et modélisation décisionnelle
_TECHNICAL_STOPWORDS = {
    "id", "key", "fk", "pk", "cd", "code", "dt", "date", "num", "no", "val",
    "flag", "ind", "flg", "status", "stat", "type", "stg", "dwh", "tmp",
    "temp", "dim", "fact", "ref", "tab", "tbl", "table", "col", "column",
    "src", "tgt", "target", "source", "load", "insert", "update", "delete",
    "sys", "meta", "row", "order", "desc", "int", "integer", "varchar",
    "char", "string", "bool", "boolean", "float", "number", "numeric", "decimal",
    "item", "data", "null", "none", "unknown", "na", "default", "total",
    "count", "sum", "avg", "min", "max", "created", "updated", "user",
    "value", "values", "text", "name", "label", "info", "raw", "hash",
    "log", "audit", "job", "batch", "flow", "file", "nbr", "amt", "pct",
}

_ALL_STOPWORDS = _LINGUISTIC_STOPWORDS | _TECHNICAL_STOPWORDS


def _split_into_tokens(text: str) -> list[str]:
    """Découpe une chaîne en tokens en gérant le CamelCase, snake_case et séparateurs."""
    if not text:
        return []
    # 1. Séparer CamelCase (ex: SupplierQuality -> Supplier Quality)
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    # 2. Extraire tous les mots alphanumériques
    words = re.findall(r"[A-Za-z0-9]+", s1)
    tokens: list[str] = []
    for w in words:
        low = w.lower()
        if len(low) > 2 and not low.isdigit() and low not in _ALL_STOPWORDS:
            tokens.append(low)
    return tokens


def build_fingerprint(graph_or_metadata: Any, max_tokens: int = 50) -> str:
    """Construit le fingerprint métier à partir d'un UnifiedSemanticGraph ou ProjectMetadata.

    Args:
        graph_or_metadata: Instance de UnifiedSemanticGraph ou ProjectMetadata.
        max_tokens: Nombre maximal de tokens fréquents à retenir (défaut 50).

    Returns:
        Chaîne de tokens métier séparés par des virgules (ex: "client, contrat, commande...").
    """
    token_counter: Counter[str] = Counter()

    # Cas 1 : UnifiedSemanticGraph
    if hasattr(graph_or_metadata, "entities"):
        for ent in graph_or_metadata.entities.values():
            # Nom de l'entité
            token_counter.update(_split_into_tokens(ent.name))
            # Noms des champs
            for field in getattr(ent, "fields", []):
                token_counter.update(_split_into_tokens(field.name))
            # Mesures DAX / calculs
            for m in getattr(ent, "measures", []):
                m_name = m.get("name", "") if isinstance(m, dict) else getattr(m, "name", "")
                token_counter.update(_split_into_tokens(m_name))

    # Cas 2 : ProjectMetadata ou structure avec tables
    if hasattr(graph_or_metadata, "tables") or hasattr(graph_or_metadata, "stg_tables"):
        tables = getattr(graph_or_metadata, "tables", []) or []
        for tbl in tables:
            t_name = getattr(tbl, "name", "")
            token_counter.update(_split_into_tokens(t_name))
            for col in getattr(tbl, "columns", []):
                c_name = getattr(col, "name", "")
                token_counter.update(_split_into_tokens(c_name))
            for m in getattr(tbl, "measures", []):
                m_name = getattr(m, "name", "")
                token_counter.update(_split_into_tokens(m_name))

        # Tables Staging & DWH SQL
        for tbl_dict in (getattr(graph_or_metadata, "stg_tables", []) or []) + (getattr(graph_or_metadata, "dwh_tables", []) or []):
            t_name = tbl_dict.get("name", "") or tbl_dict.get("full_name", "")
            token_counter.update(_split_into_tokens(t_name))
            for c in tbl_dict.get("columns", []):
                c_name = c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                token_counter.update(_split_into_tokens(c_name))

        # Tables Excel
        for tbl_dict in getattr(graph_or_metadata, "excel_tables", []) or []:
            t_name = tbl_dict.get("name", "")
            token_counter.update(_split_into_tokens(t_name))
            for c in tbl_dict.get("columns", []):
                c_name = c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                token_counter.update(_split_into_tokens(c_name))

    most_common = token_counter.most_common(max_tokens)
    fingerprint = ", ".join(token for token, _ in most_common)

    LOGGER.info(
        "Fingerprint calculé : %d tokens distincts trouvés, top %d retenus : [%s]",
        len(token_counter),
        len(most_common),
        fingerprint[:80] + ("..." if len(fingerprint) > 80 else ""),
    )
    return fingerprint or "Non inféré automatiquement"
