"""Générateur du Résumé Exécutif (STD).

Génère un résumé exécutif 100% générique, basé uniquement sur les
métriques extraites des fichiers en entrée (PBIX, SQL).
Aucun nom d'organisation, de secteur ou de domaine métier n'est codé en dur.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import BaseLLMClient, GroqClient

LOGGER = logging.getLogger(__name__)


def _build_exec_summary_context(
    pbix_metadata: dict[str, Any] | None,
    sql_metadata: list[dict[str, Any]] | None,
    excel_metadata: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construit le contexte compact pour le prompt du résumé exécutif."""
    ctx: dict[str, Any] = {}

    if pbix_metadata:
        s = pbix_metadata.get("summary", {})
        ctx["pbix"] = {
            "table_count": s.get("table_count", 0),
            "column_count": s.get("column_count", 0),
            "measure_count": s.get("measure_count", 0),
            "relationship_count": s.get("relationship_count", 0),
        }

    if sql_metadata:
        all_targets = []
        all_sources = []
        total_mappings = 0
        for pkg in sql_metadata:
            all_sources += [t.get("full_name") for t in pkg.get("source_tables", [])]
            all_targets += [t.get("full_name") for t in pkg.get("target_tables", [])]
            total_mappings += len(pkg.get("mappings", []))
        ctx["etl"] = {
            "package_count": len(sql_metadata),
            "source_tables": all_sources,
            "target_tables": all_targets,
            "total_mapping_rules": total_mappings,
        }

    if excel_metadata:
        total_excel_tables = sum(len(m.get("tables", [])) for m in excel_metadata)
        ctx["excel"] = {
            "file_count": len(excel_metadata),
            "table_count": total_excel_tables,
        }

    return ctx


def generate_executive_summary(
    pbix_metadata: dict[str, Any] | None,
    sql_metadata: list[dict[str, Any]] | None,
    excel_metadata: list[dict[str, Any]] | None = None,
    client: BaseLLMClient | None = None,
) -> str:
    """Génère le Résumé Exécutif adapté à l'architecture réelle (SQL, PBIX, Excel)."""
    active_client = client or GroqClient()
    ctx = _build_exec_summary_context(pbix_metadata, sql_metadata, excel_metadata)

    has_pbix = bool(pbix_metadata and pbix_metadata.get("summary", {}).get("table_count", 0) > 0)
    has_sql = bool(sql_metadata and len(sql_metadata) > 0)
    has_excel = bool(excel_metadata and len(excel_metadata) > 0)

    pbix_ctx = ctx.get("pbix", {})
    etl_ctx = ctx.get("etl", {})
    excel_ctx = ctx.get("excel", {})

    metrics_text: list[str] = []
    if has_pbix:
        metrics_text.append(
            f"- Modèle Power BI : {pbix_ctx.get('table_count', 0)} tables, "
            f"{pbix_ctx.get('column_count', 0)} colonnes, "
            f"{pbix_ctx.get('measure_count', 0)} mesures DAX, "
            f"{pbix_ctx.get('relationship_count', 0)} relations"
        )
    if has_sql:
        src_names = ", ".join(list(dict.fromkeys(etl_ctx.get("source_tables", [])))[:6])
        tgt_names = ", ".join(list(dict.fromkeys(etl_ctx.get("target_tables", [])))[:6])
        metrics_text.append(
            f"- Pipeline ETL SQL : {etl_ctx.get('package_count', 0)} package(s), "
            f"{etl_ctx.get('total_mapping_rules', 0)} règles de mapping"
        )
        if src_names:
            metrics_text.append(f"- Tables sources (STG) : {src_names}")
        if tgt_names:
            metrics_text.append(f"- Tables cibles (DWH) : {tgt_names}")
    if has_excel:
        metrics_text.append(
            f"- Référentiels & Fichiers Tabulaires : {excel_ctx.get('file_count', 0)} fichier(s), "
            f"{excel_ctx.get('table_count', 0)} table(s) / feuille(s)"
        )

    metrics_block = "\n".join(metrics_text)

    prompt = (
        "Tu es un consultant BI senior. Rédige un **Résumé Exécutif** d'une Spécification "
        "Technique Détaillée (STD) en français, au format Markdown.\n\n"
        "## RÈGLES DE DESCRIPTION ARCHITECTURALE :\n"
        f"- Composants présents : SQL={'OUI' if has_sql else 'NON'}, PowerBI={'OUI' if has_pbix else 'NON'}, Excel/CSV={'OUI' if has_excel else 'NON'}.\n"
        "- Décris UNIQUEMENT les composants présents. Si Power BI est absent, ne le mentionne pas. Si SQL est absent, ne mentionne pas de DWH relationnel.\n"
        "- Style professionnel, fluide, factuel, 200 à 300 mots. Retourner UNIQUEMENT du Markdown.\n\n"
        f"## MÉTRIQUES RÉELLES\n{metrics_block}\n\n"
        "## STRUCTURE\n"
        "## Résumé Exécutif\n\n"
        "### Périmètre du document\n"
        "[Synthèse du périmètre couvert]\n\n"
        "### Architecture de données cible\n"
        "[Description précise de l'enchaînement des couches réelles]\n\n"
        "### Points clés\n"
        "[3 à 4 puces synthétiques avec les chiffres réels]\n"
    )

    try:
        return active_client.generate(prompt)
    except Exception as exc:
        LOGGER.error("Échec génération Résumé Exécutif: %s", exc)
        desc_parts = []
        if has_sql:
            desc_parts.append(f"{etl_ctx.get('package_count', 0)} packages ETL SQL")
        if has_pbix:
            desc_parts.append(f"{pbix_ctx.get('table_count', 0)} tables Power BI")
        if has_excel:
            desc_parts.append(f"{excel_ctx.get('file_count', 0)} fichiers référentiels")
        return (
            "## Résumé Exécutif\n\n"
            f"Ce document présente la documentation technique détaillée du projet BI consolidant "
            f"{' et '.join(desc_parts) if desc_parts else 'les composants décisionnels'}.\n"
        )
