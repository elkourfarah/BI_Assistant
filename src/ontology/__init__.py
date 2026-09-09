"""Ontology Module — Extraction et sérialisation d'ontologies sémantiques.

Transforme des métadonnées brutes (SQL, PBIX) en représentations ontologiques
structurées et neutres, adaptées au plongement vectoriel et au raisonnement LLM.
"""
from .serializer import (
    serialize_pbix_to_ontology,
    serialize_sql_to_ontology,
)

__all__ = [
    "serialize_pbix_to_ontology",
    "serialize_sql_to_ontology",
]
