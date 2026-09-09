"""Tests du Moteur Raisonneur Hybride v2 (HybridReasoner + Embeddings + Ontologie)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src.ontology.serializer import (
    serialize_pbix_to_ontology,
    serialize_sql_to_ontology,
)
from src.embedding.embedder import compute_similarity, embed
from src.reasoning.domain_cache import DomainCache
from src.reasoning.hybrid_reasoner import HybridReasoner


def _make_sql_pkg(
    name: str,
    source_tables: list[str],
    target_tables: list[str],
    columns: list[str] | None = None,
) -> dict:
    cols = [{"name": c, "data_type": "VARCHAR2"} for c in (columns or [])]
    return {
        "name": name,
        "source_tables": [{"full_name": t, "columns": cols} for t in source_tables],
        "target_tables": [{"full_name": t, "columns": []} for t in target_tables],
        "mappings": [],
    }


# ---------------------------------------------------------------------------
# Tests du Sérialiseur Ontologique
# ---------------------------------------------------------------------------

def test_serialize_sql_to_ontology():
    pkg = _make_sql_pkg("DWH_UCMS", ["DEV.STG_UCMS"], ["DEV.DWH_UCMS"], ["APPLICANT_ID", "SKILL_NAME"])
    ont = serialize_sql_to_ontology(pkg, file_path="DWH_UCMS.sql")
    assert "DWH_UCMS" in ont
    assert "DEV.STG_UCMS" in ont
    assert "APPLICANT_ID" in ont


def test_serialize_pbix_to_ontology():
    tables = [
        {"name": "Vendor", "columns": [{"name": "Vendor ID"}, {"name": "Vendor Name"}], "measures": []},
        {"name": "Defect", "columns": [{"name": "Defect Type"}], "measures": []},
    ]
    ont = serialize_pbix_to_ontology(pbix_meta={}, tables=tables, file_path="SupplierQuality.pbix")
    assert "Vendor" in ont
    assert "Defect Type" in ont


# ---------------------------------------------------------------------------
# Tests de l'Embedder Dense
# ---------------------------------------------------------------------------

def test_embedder_returns_vector():
    vec = embed("Data warehouse entity mapping containing sales and revenue attributes.")
    assert isinstance(vec, np.ndarray)
    assert len(vec) > 0


def test_compute_similarity_identical_high():
    text = "HR applicant recruiting skills level contract"
    vec1 = embed(text)
    vec2 = embed(text)
    sim = compute_similarity(vec1, vec2)
    assert sim >= 0.95, f"Expected high similarity for identical text, got {sim}"


def test_compute_similarity_different_lower():
    text_hr = "Human resources employee candidate skills recruitment salary contract"
    text_crm = "CRM customer relationship management sales invoice opportunity lead account"
    vec_hr = embed(text_hr)
    vec_crm = embed(text_crm)
    sim = compute_similarity(vec_hr, vec_crm)
    assert sim < 0.95, f"Expected distinct vectors, got {sim}"


# ---------------------------------------------------------------------------
# Tests du Cache de Domaine
# ---------------------------------------------------------------------------

def test_domain_cache_get_set():
    cache = DomainCache()
    ont = "Test ontology string 123"
    val = {"domain_id": "TEST", "domain_label": "Test Domain", "confidence": 0.9}
    cache.set(ont, val)
    cached = cache.get(ont)
    assert cached is not None
    assert cached["domain_id"] == "TEST"


# ---------------------------------------------------------------------------
# Tests d'HybridReasoner
# ---------------------------------------------------------------------------

def test_hybrid_reasoner_single_file():
    pkg = _make_sql_pkg("UCMS", ["DEV.STG_UCMS"], ["DEV.DWH_UCMS"], ["SKILL"])
    reasoner = HybridReasoner()
    report = reasoner.evaluate_files(sql_inputs=[("ucms.sql", pkg)], pbix_inputs=[])
    assert report.is_compatible is True


def test_hybrid_reasoner_same_domain_files():
    pkg1 = _make_sql_pkg("UCMS_A", ["DEV.STG_UCMS_A"], ["DEV.DWH_UCMS_A"], ["APPLICANT_ID", "SKILLS"])
    pkg2 = _make_sql_pkg("UCMS_B", ["DEV.STG_UCMS_B"], ["DEV.DWH_UCMS_B"], ["APPLICANT_ID", "COMPETENCE"])
    reasoner = HybridReasoner()
    report = reasoner.evaluate_files(
        sql_inputs=[("ucms_a.sql", pkg1), ("ucms_b.sql", pkg2)],
        pbix_inputs=[],
    )
    assert report.is_compatible is True


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_serialize_sql_to_ontology,
        test_serialize_pbix_to_ontology,
        test_embedder_returns_vector,
        test_compute_similarity_identical_high,
        test_compute_similarity_different_lower,
        test_domain_cache_get_set,
        test_hybrid_reasoner_single_file,
        test_hybrid_reasoner_same_domain_files,
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
