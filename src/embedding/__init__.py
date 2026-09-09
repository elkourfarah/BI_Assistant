"""Embedding module — Dense semantic vector representation and cosine similarity."""
from .embedder import compute_similarity, embed

__all__ = [
    "compute_similarity",
    "embed",
]
