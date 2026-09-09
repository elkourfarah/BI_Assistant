"""Tests du RAG — STDTemplateStore + STDRetriever."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.template_store import STDTemplateStore, _tokenize
from src.rag.retriever import STDRetriever


# ---------------------------------------------------------------------------
# Tests de _tokenize
# ---------------------------------------------------------------------------

def test_tokenize_basic():
    tokens = _tokenize("Staging Area contient les données brutes")
    assert "staging" in tokens
    assert "area" in tokens
    # Stopwords filtrés
    assert "les" not in tokens


def test_tokenize_sql():
    tokens = _tokenize("MERGE INTO DEV.DWH_UCMS_APPLIC_SKILLS target")
    assert "merge" in tokens
    assert "dev" in tokens


# ---------------------------------------------------------------------------
# Tests de STDTemplateStore
# ---------------------------------------------------------------------------

def test_store_empty_index():
    """Un store vide ne doit pas lever d'exception apres build_index."""
    store = STDTemplateStore()
    store.build_index()  # Ne doit pas lever d'exception
    assert len(store.chunks) == 0
    # index_built reste False si aucun chunk -- comportement correct
    assert store.index_built is False


def test_store_load_sql_creates_chunks():
    store = STDTemplateStore()
    sql_path = Path(__file__).resolve().parent.parent / "DWH_UCMS_APPLIC_SKILLS.sql"
    if sql_path.exists():
        n = store.load_sql(sql_path)
        assert n > 0
        assert len(store.chunks) == n
    else:
        print("  ⚠ Fichier SQL de test introuvable — test ignoré")


def test_store_build_index_sets_tfidf():
    store = STDTemplateStore()
    sql_path = Path(__file__).resolve().parent.parent / "DWH_UCMS_APPLIC_SKILLS.sql"
    if not sql_path.exists():
        print("  ⚠ Fichier SQL introuvable — test ignoré")
        return
    store.load_sql(sql_path)
    store.build_index()
    assert store.index_built
    for chunk in store.chunks:
        assert isinstance(chunk.tfidf, dict)
        if chunk.tokens:
            assert len(chunk.tfidf) > 0


# ---------------------------------------------------------------------------
# Tests de STDRetriever
# ---------------------------------------------------------------------------

def test_retriever_empty_store():
    retriever = STDRetriever.build(word_paths=[], sql_paths=[])
    result = retriever.retrieve("mapping MERGE INTO")
    assert result == ""


def test_retriever_returns_context():
    sql_path = Path(__file__).resolve().parent.parent / "DWH_UCMS_APPLIC_SKILLS.sql"
    if not sql_path.exists():
        print("  ⚠ Fichier SQL introuvable — test ignoré")
        return
    retriever = STDRetriever.build(sql_paths=[sql_path])
    result = retriever.retrieve("MERGE INTO STG DWH mapping")
    # Peut être vide si aucun token commun, mais ne doit pas lever d'exception
    assert isinstance(result, str)


def test_retriever_for_section():
    sql_path = Path(__file__).resolve().parent.parent / "DWH_UCMS_APPLIC_SKILLS.sql"
    if not sql_path.exists():
        print("  ⚠ Fichier SQL introuvable — test ignoré")
        return
    retriever = STDRetriever.build(sql_paths=[sql_path])
    for section_id in ["mapping", "etl", "monitoring", "dwh"]:
        result = retriever.retrieve_for_section(section_id)
        assert isinstance(result, str)


def test_retriever_word_template():
    word_path = Path(__file__).resolve().parent.parent / "STD-SI-PERFORMANCE-xxxxx-V0.1.docx"
    if not word_path.exists():
        print("  ⚠ Template Word introuvable — test ignoré")
        return
    retriever = STDRetriever.build(word_paths=[word_path])
    assert len(retriever._store.chunks) > 0
    result = retriever.retrieve("staging area données sources chargement")
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_tokenize_basic,
        test_tokenize_sql,
        test_store_empty_index,
        test_store_load_sql_creates_chunks,
        test_store_build_index_sets_tfidf,
        test_retriever_empty_store,
        test_retriever_returns_context,
        test_retriever_for_section,
        test_retriever_word_template,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  [OK] {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {test_fn.__name__} -- {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {test_fn.__name__} -- {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passes.")
    sys.exit(0 if failed == 0 else 1)
