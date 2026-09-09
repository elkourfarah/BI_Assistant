"""Sérialiseur d'ontologie sémantique — Convertit métadonnées SQL et PBIX en ontologies canoniques.

Génère des représentations textuelles structurées indépendantes de tout mot-clé dur,
conçues pour être projetées dans l'espace vectoriel dense et soumises aux sondes LLM.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def serialize_sql_to_ontology(pkg: dict[str, Any], file_path: str = "") -> str:
    """Sérialise un package/script SQL en une représentation ontologique structurée.

    Args:
        pkg: Dictionnaire de métadonnées SQL (tables sources, cibles, mappings, colonnes).
        file_path: Chemin du fichier SQL.

    Returns:
        Document texte représentant l'ontologie du script SQL.
    """
    file_name = Path(file_path).name if file_path else (pkg.get("name") or "script.sql")
    pkg_name = pkg.get("name") or file_name

    lines: list[str] = [
        f"# ONTOLOGY DOCUMENT: {file_name}",
        f"File Type: SQL ETL Pipeline",
        f"Pipeline Identifier: {pkg_name}",
        "",
        "## TARGET ENTITIES (Data Warehouse Layer)",
    ]

    for tbl in pkg.get("target_tables", []):
        tname = tbl.get("full_name") or tbl.get("name") or "UNKNOWN_TARGET"
        cols = [c.get("name", "") for c in tbl.get("columns", []) if c.get("name")]
        keys = [
            c.get("name", "")
            for c in tbl.get("columns", [])
            if c.get("is_primary_key") or "Upsert Key" in (c.get("comment") or "")
        ]
        lines.append(f"- Entity: `{tname}`")
        if keys:
            lines.append(f"  Primary/Upsert Keys: {', '.join(keys)}")
        if cols:
            lines.append(f"  Attributes ({len(cols)}): {', '.join(cols[:40])}")
        lines.append("")

    lines.append("## SOURCE ENTITIES (Staging Layer)")
    for tbl in pkg.get("source_tables", []):
        tname = tbl.get("full_name") or tbl.get("name") or "UNKNOWN_SOURCE"
        cols = [c.get("name", "") for c in tbl.get("columns", []) if c.get("name")]
        lines.append(f"- Entity: `{tname}`")
        if cols:
            lines.append(f"  Attributes ({len(cols)}): {', '.join(cols[:40])}")
        lines.append("")

    lines.append("## TRANSFORMATION MAPPINGS & LINEAGE")
    mappings = pkg.get("mappings", [])
    if mappings:
        lines.append(f"Total Mapping Rules: {len(mappings)}")
        sample_rules = []
        for m in mappings[:25]:
            src_t = (m.get("source_table") or "").split(".")[-1]
            src_c = m.get("source_column") or ""
            tgt_t = (m.get("target_table") or "").split(".")[-1]
            tgt_c = m.get("target_column") or ""
            rule = m.get("transformation_rule") or ""
            sample_rules.append(f"  * {src_t}.{src_c} -> {tgt_t}.{tgt_c} [{rule}]")
        lines.extend(sample_rules)
    else:
        lines.append("No explicit column mappings extracted.")

    return "\n".join(lines)


def serialize_pbix_to_ontology(
    pbix_meta: dict[str, Any] | None = None,
    tables: list[Any] | None = None,
    file_path: str = "",
) -> str:
    """Sérialise un modèle Power BI en une représentation ontologique structurée.

    Args:
        pbix_meta: Dictionnaire de métadonnées PBIX brutes.
        tables: Liste d'objets Table ou dicts extraits de PBIXExtractor.
        file_path: Chemin du fichier .pbix.

    Returns:
        Document texte représentant l'ontologie du modèle Power BI.
    """
    file_name = Path(file_path).name if file_path else "model.pbix"
    report_name = Path(file_path).stem if file_path else "PowerBI Report"

    lines: list[str] = [
        f"# ONTOLOGY DOCUMENT: {file_name}",
        f"File Type: Power BI Semantic Model",
        f"Model Name: {report_name}",
        "",
        "## SEMANTIC MODEL ENTITIES & ATTRIBUTES",
    ]

    # Préférer les objets Table extraits s'ils sont présentés
    if tables:
        for tbl in tables:
            tname = getattr(tbl, "name", None) or (tbl.get("name") if isinstance(tbl, dict) else "UnknownTable")
            # Ignorer les tables système d'auto-date Power BI
            if "DateTableTemplate" in tname or "LocalDateTable" in tname:
                continue

            cols_raw = getattr(tbl, "columns", None) or (tbl.get("columns") if isinstance(tbl, dict) else [])
            col_names = [
                getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else str(c))
                for c in cols_raw
            ]
            measures_raw = getattr(tbl, "measures", None) or (tbl.get("measures") if isinstance(tbl, dict) else [])
            measure_names = [
                getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else str(m))
                for m in measures_raw
            ]

            lines.append(f"- Entity: `{tname}`")
            if col_names:
                lines.append(f"  Fields ({len(col_names)}): {', '.join(col_names[:40])}")
            if measure_names:
                lines.append(f"  KPIs/Measures ({len(measure_names)}): {', '.join(measure_names[:20])}")
            lines.append("")

    elif pbix_meta:
        for tbl in pbix_meta.get("tables", []):
            if isinstance(tbl, dict):
                tname = tbl.get("name", "")
                if "DateTableTemplate" in tname or "LocalDateTable" in tname:
                    continue
                cols = [c.get("name", "") for c in tbl.get("columns", []) if isinstance(c, dict) and c.get("name")]
                measures = [m.get("name", "") for m in tbl.get("measures", []) if isinstance(m, dict) and m.get("name")]
                lines.append(f"- Entity: `{tname}`")
                if cols:
                    lines.append(f"  Fields ({len(cols)}): {', '.join(cols[:40])}")
                if measures:
                    lines.append(f"  KPIs/Measures ({len(measures)}): {', '.join(measures[:20])}")
                lines.append("")

    return "\n".join(lines)


def serialize_excel_to_ontology(
    excel_meta: dict[str, Any],
    file_path: str = "",
) -> str:
    """Sérialise un fichier Excel en une représentation ontologique structurée.

    Args:
        excel_meta: Dictionnaire de métadonnées brutes issues de ExcelExtractor.
        file_path: Chemin du fichier Excel.

    Returns:
        Document texte représentant l'ontologie du fichier Excel.
    """
    file_name = Path(file_path).name if file_path else excel_meta.get("file_name", "spreadsheet.xlsx")

    lines: list[str] = [
        f"# ONTOLOGY DOCUMENT: {file_name}",
        f"File Type: Excel Spreadsheet Data & Specs",
        "",
        "## EXCEL DATA TABLES & SHEETS",
    ]

    for tbl in excel_meta.get("tables", []):
        tname = tbl.get("name") or tbl.get("sheet_name") or "ExcelTable"
        cols = [c.get("name", "") for c in tbl.get("columns", []) if c.get("name")]
        keys = [c.get("name", "") for c in tbl.get("columns", []) if c.get("is_primary_key")]
        lines.append(f"- Entity: `{tname}` (Layer: {tbl.get('layer', 'RAW')})")
        if keys:
            lines.append(f"  Primary Keys: {', '.join(keys)}")
        if cols:
            lines.append(f"  Attributes ({len(cols)}): {', '.join(cols[:40])}")
        lines.append("")

    mappings = excel_meta.get("mappings", [])
    if mappings:
        lines.append("## EXCEL SPECIFICATION MAPPINGS")
        lines.append(f"Total Excel Mapping Rules: {len(mappings)}")
        for m in mappings[:25]:
            src_t = m.get("source_table", "SRC")
            src_c = m.get("source_column", "COL")
            tgt_t = m.get("target_table", "TGT")
            tgt_c = m.get("target_column", "COL")
            rule = m.get("transformation_rule", "")
            lines.append(f"  * {src_t}.{src_c} -> {tgt_t}.{tgt_c} [{rule}]")
        lines.append("")

    return "\n".join(lines)

