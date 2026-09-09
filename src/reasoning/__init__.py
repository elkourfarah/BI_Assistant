"""Reasoning Engine — Module d'évaluation de la compatibilité sémantique et ontologique."""
from .domain_cache import DomainCache
from .hybrid_reasoner import HybridReasoner
from .llm_reasoner import CompatibilityReport, FileDomainProfile, LLMReasoner

__all__ = [
    "CompatibilityReport",
    "DomainCache",
    "FileDomainProfile",
    "HybridReasoner",
    "LLMReasoner",
]
