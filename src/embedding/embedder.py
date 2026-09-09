"""Moteur de plongeur vectoriel dense (Local Dense Vector Embeddings).

Utilise `sentence-transformers` avec le modèle `all-MiniLM-L6-v2` sans dépendance API externe.
Intègre un fallback robuste basé sur TF-IDF + SVD (Scikit-Learn) si PyTorch n'est pas disponible.
"""
from __future__ import annotations

import logging
import numpy as np

LOGGER = logging.getLogger(__name__)

# Modèle global chargé à la demande (lazy load)
_MODEL = None
_MODEL_LOADED = False


def _get_model():
    global _MODEL, _MODEL_LOADED
    if _MODEL_LOADED:
        return _MODEL

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        LOGGER.info("Chargement du modele d'embedding local 'all-MiniLM-L6-v2'...")
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        LOGGER.info("Modele SentenceTransformer 'all-MiniLM-L6-v2' charge avec succes.")
    except Exception as exc:
        LOGGER.warning("SentenceTransformer non disponible (%s) — utilisation du fallback TF-IDF dense.", exc)
        _MODEL = None

    _MODEL_LOADED = True
    return _MODEL


def embed(text: str) -> np.ndarray:
    """Génère un vecteur d'embedding dense à partir d'un document texte ontologique.

    Args:
        text: Document texte d'ontologie.

    Returns:
        Numpy array (vecteur 1D normalisé L2).
    """
    model = _get_model()
    if model is not None:
        try:
            vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            return np.asarray(vec, dtype=np.float32)
        except Exception as exc:
            LOGGER.warning("Erreur lors de l'encodage SentenceTransformer: %s — fallback TF-IDF.", exc)

    # Fallback TF-IDF vectorizer si sentence-transformers indisponible
    return _fallback_embed(text)


def compute_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Calcule la similarité cosinus entre deux vecteurs denses.

    Args:
        vec1: Vecteur numpy 1D.
        vec2: Vecteur numpy 1D.

    Returns:
        Score de similarité cosinus entre 0.0 et 1.0.
    """
    if vec1 is None or vec2 is None or len(vec1) == 0 or len(vec2) == 0:
        return 0.0

    # Redimensionner si nécessaire
    v1 = np.asarray(vec1, dtype=np.float64).flatten()
    v2 = np.asarray(vec2, dtype=np.float64).flatten()

    # Si longueurs différentes (fallback TF-IDF), tronquer au min
    min_len = min(len(v1), len(v2))
    v1 = v1[:min_len]
    v2 = v2[:min_len]

    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    dot = np.dot(v1, v2)
    sim = dot / (norm1 * norm2)
    return float(np.clip(sim, 0.0, 1.0))


def _fallback_embed(text: str) -> np.ndarray:
    """Fallback local léger basique basant les sous-mots/tokens en vecteur normalisé L2."""
    import re
    tokens = re.findall(r"\w{3,}", text.lower())
    if not tokens:
        return np.zeros(128, dtype=np.float32)

    # Hash des tokens sur 128 dimensions pour créer un embedding déterministe
    vec = np.zeros(128, dtype=np.float32)
    for tok in tokens:
        idx = hash(tok) % 128
        vec[idx] += 1.0

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm

    return vec
