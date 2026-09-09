"""RAG léger en mémoire — indexe le template Word STD + patterns SQL de référence.

Architecture :
  STDTemplateStore → lit le fichier Word template et les SQL de référence,
                     découpe en chunks et construit un index TF-IDF en mémoire.

L'index est construit une seule fois au premier appel (lazy-init) et réutilisé
durant toute l'exécution. Zéro dépendance externe : TF-IDF manuel pure Python
+ scipy si disponible, sinon fallback numpy/dict.

Usage :
  store = STDTemplateStore()
  store.load_word(Path("STD-SI-PERFORMANCE-xxxxx-V0.1.docx"))
  store.load_sql(Path("DWH_UCMS_APPLIC_SKILLS.sql"))
  store.build_index()
  # Ensuite utiliser STDRetriever
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """Un extrait de document indexé.

    Attributes:
        chunk_id: Identifiant unique.
        source: Nom du fichier source.
        section: Titre de la section d'origine (si applicable).
        text: Texte brut du chunk.
        chunk_type: 'template_word' | 'sql_pattern' | 'sql_mapping'.
        tokens: Tokens extraits pour TF-IDF.
        tfidf: Vecteur TF-IDF {token: weight}.
    """
    chunk_id: int = 0
    source: str = ""
    section: str = ""
    text: str = ""
    chunk_type: str = "template_word"
    tokens: list[str] = field(default_factory=list)
    tfidf: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# STDTemplateStore
# ---------------------------------------------------------------------------

class STDTemplateStore:
    """Store d'indexation TF-IDF du template STD Word + patterns SQL.

    Méthodes publiques :
      load_word(path)  → charge et découpe le fichier Word en chunks
      load_sql(path)   → charge et découpe un fichier SQL en pattern-chunks
      build_index()    → calcule TF-IDF sur tous les chunks
      chunks           → liste de tous les chunks indexés
    """

    def __init__(self) -> None:
        self._chunks: list[Chunk] = []
        self._idf: dict[str, float] = {}
        self._index_built: bool = False
        self._chunk_counter: int = 0

    @property
    def chunks(self) -> list[Chunk]:
        return self._chunks

    @property
    def index_built(self) -> bool:
        return self._index_built

    # ---- Chargement Word ----

    def load_word(self, path: Path) -> int:
        """Charge un fichier Word (.docx) et l'indexe en chunks.

        Args:
            path: Chemin vers le fichier .docx.

        Returns:
            Nombre de chunks créés.
        """
        if not path.exists():
            LOGGER.warning("Template Word introuvable: %s", path)
            return 0

        try:
            from docx import Document  # type: ignore
            doc = Document(str(path))
        except Exception as exc:
            LOGGER.error("Impossible de lire le template Word %s: %s", path, exc)
            return 0

        current_section = "Introduction"
        buffer: list[str] = []
        n_before = len(self._chunks)

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            is_heading = para.style.name.startswith("Heading") or para.style.name.startswith("Titre")

            if is_heading:
                # Flush buffer précédent
                if buffer:
                    self._add_text_chunk(
                        text="\n".join(buffer),
                        source=path.name,
                        section=current_section,
                        chunk_type="template_word",
                    )
                    buffer = []
                current_section = text
            else:
                buffer.append(text)
                # Flush par fenêtre de ~300 tokens pour éviter les chunks trop gros
                if len(" ".join(buffer)) > 1200:
                    self._add_text_chunk(
                        text="\n".join(buffer),
                        source=path.name,
                        section=current_section,
                        chunk_type="template_word",
                    )
                    buffer = []

        if buffer:
            self._add_text_chunk(
                text="\n".join(buffer),
                source=path.name,
                section=current_section,
                chunk_type="template_word",
            )

        n_created = len(self._chunks) - n_before
        LOGGER.info("STDTemplateStore: %d chunks créés depuis %s", n_created, path.name)
        return n_created

    # ---- Chargement SQL ----

    def load_sql(self, path: Path) -> int:
        """Charge un fichier SQL et extrait des chunks sémantiques.

        Extrait :
          - Le pattern MERGE INTO (structure ETL)
          - Les noms de tables sources et cibles
          - La logique de LOG_TABLE

        Args:
            path: Chemin vers le fichier .sql.

        Returns:
            Nombre de chunks créés.
        """
        if not path.exists():
            LOGGER.warning("Fichier SQL introuvable pour RAG: %s", path)
            return 0

        try:
            sql_text = path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception as exc:
            LOGGER.error("Impossible de lire %s: %s", path, exc)
            return 0

        n_before = len(self._chunks)

        # 1. Chunk global : structure complète du script (tronqué)
        self._add_text_chunk(
            text=sql_text[:3000],
            source=path.name,
            section="Script complet",
            chunk_type="sql_pattern",
        )

        # 2. Extraire les blocs MERGE
        merge_blocks = re.findall(
            r"MERGE\s+INTO\s+\S+.*?(?=MERGE\s+INTO|\Z)",
            sql_text,
            re.IGNORECASE | re.DOTALL,
        )
        for block in merge_blocks:
            self._add_text_chunk(
                text=block[:2000],
                source=path.name,
                section="MERGE INTO",
                chunk_type="sql_mapping",
            )

        # 3. Table source et cible
        src_match = re.search(r"FROM\s+(DEV\.\w+)", sql_text, re.IGNORECASE)
        tgt_match = re.search(r"MERGE\s+INTO\s+(DEV\.\w+)", sql_text, re.IGNORECASE)
        if src_match or tgt_match:
            flow_text = f"Flux ETL: {src_match.group(1) if src_match else '?'} → {tgt_match.group(1) if tgt_match else '?'}"
            self._add_text_chunk(
                text=flow_text,
                source=path.name,
                section="Flux ETL",
                chunk_type="sql_pattern",
            )

        # 4. Bloc LOG_TABLE (monitoring pattern)
        log_block = re.search(
            r"MERGE\s+INTO.*?LOG_TABLE.*?END;",
            sql_text,
            re.IGNORECASE | re.DOTALL,
        )
        if log_block:
            self._add_text_chunk(
                text=log_block.group(0)[:1500],
                source=path.name,
                section="LOG_TABLE Pattern",
                chunk_type="sql_pattern",
            )

        n_created = len(self._chunks) - n_before
        LOGGER.info("STDTemplateStore: %d chunks créés depuis %s", n_created, path.name)
        return n_created

    # ---- Construction de l'index TF-IDF ----

    def build_index(self) -> None:
        """Calcule les vecteurs TF-IDF pour tous les chunks chargés."""
        if not self._chunks:
            LOGGER.warning("STDTemplateStore: aucun chunk à indexer.")
            return

        # Calcul de la fréquence de document (DF)
        df: dict[str, int] = defaultdict(int)
        for chunk in self._chunks:
            tokens = _tokenize(chunk.text)
            chunk.tokens = tokens
            for tok in set(tokens):
                df[tok] += 1

        n_docs = len(self._chunks)

        # Calcul de l'IDF = log((N + 1) / (df + 1)) + 1  (smooth IDF)
        self._idf = {tok: math.log((n_docs + 1) / (freq + 1)) + 1.0 for tok, freq in df.items()}

        # Calcul du TF-IDF normalisé par chunk
        for chunk in self._chunks:
            tf_raw: dict[str, int] = defaultdict(int)
            for tok in chunk.tokens:
                tf_raw[tok] += 1
            n_toks = len(chunk.tokens) or 1

            tfidf: dict[str, float] = {}
            for tok, freq in tf_raw.items():
                tf = freq / n_toks
                idf = self._idf.get(tok, 1.0)
                tfidf[tok] = tf * idf

            # Normalisation L2
            norm = math.sqrt(sum(v ** 2 for v in tfidf.values())) or 1.0
            chunk.tfidf = {tok: v / norm for tok, v in tfidf.items()}

        self._index_built = True
        LOGGER.info(
            "STDTemplateStore: index TF-IDF construit — %d chunks, %d tokens uniques.",
            n_docs,
            len(self._idf),
        )

    # ---- Helpers privés ----

    def _add_text_chunk(
        self,
        text: str,
        source: str,
        section: str,
        chunk_type: str,
    ) -> None:
        """Ajoute un chunk au store."""
        text = text.strip()
        if not text or len(text) < 20:
            return
        chunk = Chunk(
            chunk_id=self._chunk_counter,
            source=source,
            section=section,
            text=text,
            chunk_type=chunk_type,
        )
        self._chunks.append(chunk)
        self._chunk_counter += 1


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Tokenise un texte en tokens normalisés pour TF-IDF.

    - Lowercase
    - Split sur ponctuation, underscores, espaces
    - Retire les tokens de 1-2 caractères et les stopwords FR/EN
    """
    _STOPWORDS = {
        "le", "la", "les", "de", "du", "des", "un", "une", "et", "en", "au", "aux",
        "dans", "pour", "sur", "par", "est", "sont", "être", "avoir", "avec", "qui",
        "que", "ce", "se", "sa", "son", "ses", "ils", "elles", "nous", "vous",
        "the", "a", "an", "of", "in", "to", "is", "are", "for", "with", "this",
        "that", "from", "be", "as", "at", "or", "by", "table", "set", "into",
    }
    text = text.lower()
    parts = re.split(r"[_.\s\-,;:()\[\]{}\"'`=<>\/\\]+", text)
    return [p for p in parts if len(p) >= 3 and p not in _STOPWORDS]
