"""Générateur de l'Introduction et du Résumé Exécutif contextuel enrichi."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...core.fingerprint import build_fingerprint
from ...core.semantic_graph import EntityType, StorageEngine, UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)


def generate_introduction(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère une introduction sur-mesure détaillée décrivant le périmètre réel présent dans le graphe."""
    stg_count = len(graph.get_entities_by_type(EntityType.STAGING))
    dwh_count = len(graph.get_entities_by_type(EntityType.WAREHOUSE_TABLE))
    pbi_count = len(graph.get_entities_by_type(EntityType.SEMANTIC_MODEL))
    ref_count = len(graph.get_entities_by_type(EntityType.REFERENCE_DATA))
    raw_count = len(graph.get_entities_by_type(EntityType.SOURCE_RAW))
    flow_count = len(graph.flows)
    total_fields = sum(len(e.fields) for e in graph.entities.values())

    # Extraction du fingerprint métier
    fingerprint = build_fingerprint(graph, max_tokens=35)

    lines: list[str] = [
        f"*Ce document constitue la Spécification Technique Détaillée (STD) du projet "
        f"**{graph.project_name}**, centré sur le domaine fonctionnel **{graph.dominant_domain}**.*",
        "",
        "### 1.1 Préambule & Enjeux Décisionnels",
        f"La présente Spécification Technique Détaillée a pour vocation de formaliser l'architecture "
        f"des flux de données, les modèles de stockage et les transformations appliquées au sein du "
        f"projet **{graph.project_name}**. Dans le cadre du pilotage décisionnel **{graph.dominant_domain}**, "
        f"la maîtrise de la chaîne de valeur de la donnée — depuis sa captation source jusqu'à sa restitution analytique — "
        f"constitue un levier stratégique majeur. Ce document sert de référentiel technique opposable "
        f"entre les équipes de maîtrise d'œuvre (Data Engineering, BI) et la maîtrise d'ouvrage.",
        "",
        "### 1.2 Vocabulaire Métier Clé & Périmètre Fonctionnel",
        f"L'analyse structurelle des entités et attributs manipulés met en évidence un ensemble de "
        f"concepts métier directeurs. Le lexique dominant identifié s'articule autour des termes suivants :",
        f"> **Concepts métier clés extraits :** `{fingerprint}`",
        "",
        f"Ces notions traduisent les axes d'analyse primordiaux du projet et structurent l'ensemble des "
        f"faits mesurables et dimensions de reporting associées.",
        "",
        "### 1.3 Inventaire & Rôle des Fichiers Sources Analysés",
        f"L'élaboration de ce document repose sur l'analyse automatisée de **{len(graph.raw_inputs)} fichier(s) source(s)** :",
        "",
    ]

    if graph.raw_inputs:
        lines.append("| Fichier en entrée | Type / Format | Couche / Rôle dans l'architecture |")
        lines.append("|---|---|---|")
        for f in graph.raw_inputs:
            fname = Path(f).name
            suffix = Path(f).suffix.lower()
            if suffix == ".sql":
                ftype = "Script SQL DDL / DML"
                frole = "Alimentation ETL, tables Staging et Data Warehouse"
            elif suffix == ".pbix":
                ftype = "Fichier Power BI (.pbix)"
                frole = "Modèle sémantique décisionnel, mesures DAX & reporting"
            elif suffix in (".xlsx", ".xls"):
                ftype = "Classeur Excel"
                frole = "Référentiel de données, paramètres ou source tabulaire"
            elif suffix == ".csv":
                ftype = "Fichier plat CSV"
                frole = "Paramétrage d'orchestration ou données de référence"
            elif suffix == ".zip":
                ftype = "Archive compressée ZIP"
                frole = "Paquet multi-sources d'intégration"
            else:
                ftype = f"Fichier source ({suffix or 'brut'})"
                frole = "Composant d'intégration du système"
            lines.append(f"| `{fname}` | {ftype} | {frole} |")
        lines.append("")
    else:
        lines.append("*Aucun fichier d'entrée externe spécifié explicitement (analyse sur structure interne).*\n")

    # Description dynamique selon les technologies et entités présentes
    lines.append("### 1.4 Architecture Globale en Couches")
    scope_points: list[str] = []
    if raw_count > 0:
        scope_points.append(f"**{raw_count}** source(s) de données brutes externes")
    if ref_count > 0:
        scope_points.append(f"**{ref_count}** référentiel(s) ou table(s) de paramétrage (`REFERENCE_DATA`)")
    if stg_count > 0:
        scope_points.append(f"**{stg_count}** table(s) de Staging (couche d'ingestion brute et de conformité)")
    if dwh_count > 0:
        scope_points.append(f"**{dwh_count}** table(s) de Data Warehouse relationnel (dimensions & tables de faits)")
    if pbi_count > 0:
        scope_points.append(f"**{pbi_count}** table(s) du modèle sémantique décisionnel Power BI")
    if flow_count > 0:
        scope_points.append(f"**{flow_count}** flux ou packages d'alimentation et transformation")

    if scope_points:
        lines.append(f"Le périmètre technique modélisé totalise **{len(graph.entities)} entités** et **{total_fields} attributs**, structuré comme suit :")
        for pt in scope_points:
            lines.append(f"- {pt}")
        lines.append("")

    # Architecture cible
    flow_desc: list[str] = []
    if graph.data_sources or raw_count > 0:
        flow_desc.append("Sources Externes")
    if ref_count > 0:
        flow_desc.append("Référentiels / Config")
    if stg_count > 0:
        flow_desc.append("Couche Staging (STG)")
    if dwh_count > 0:
        flow_desc.append("Data Warehouse (DWH)")
    if pbi_count > 0:
        flow_desc.append("Modèle Sémantique (Power BI)")

    if flow_desc:
        lines.append(f"**Cinématique des flux de données :** `{' → '.join(flow_desc)}`\n")

    return "\n".join(lines)


def generate_executive_summary_node(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la synthèse exécutive contextuelle avec description dynamique selon has_sql, has_pbix, has_excel."""
    has_sql = graph.has_sql
    has_pbix = graph.has_pbix
    has_excel = graph.has_excel

    stg = len(graph.get_entities_by_type(EntityType.STAGING))
    dwh = len(graph.get_entities_by_type(EntityType.WAREHOUSE_TABLE))
    pbi = len(graph.get_entities_by_type(EntityType.SEMANTIC_MODEL))
    ref = len(graph.get_entities_by_type(EntityType.REFERENCE_DATA))
    total_fields = sum(len(e.fields) for e in graph.entities.values())
    total_mappings = sum(len(f.field_mappings) for f in graph.flows)

    lines: list[str] = [
        "Ce projet décisionnel consolide les données relatives au domaine "
        f"**{graph.dominant_domain}** au travers d'un ensemble structuré de "
        f"**{len(graph.entities)} entités** totalisant **{total_fields} attributs**.",
        "",
        "### Synthèse Architecturale",
    ]

    # Description dynamique selon les technologies réelles (Ajout 2 / Action 4.5)
    if has_sql and has_pbix and has_excel:
        lines.append(
            "Le système déploie une **architecture d'entreprise décisionnelle hybride complète** : "
            "les flux d'orchestration s'appuient sur des référentiels de configuration et transcodification tabulaires, "
            "alimentant un socle Data Warehouse SQL relationnel robuste via des pipelines de Staging et fusion (MERGE), "
            "tandis que la restitution s'opère sur un modèle sémantique Power BI hautement performant en mémoire."
        )
    elif has_sql and has_pbix:
        lines.append(
            "Le projet repose sur une **architecture décisionnelle moderne bi-moteur (SQL & Power BI)** : "
            "un socle relationnel structuré en couches Staging et Data Warehouse assure l'intégrité, "
            "l'historisation et la transformation des données, lesquelles sont directement exposées à un "
            "modèle sémantique Power BI optimisé pour l'analyse multi-dimensionnelle et le libre-service."
        )
    elif has_sql and has_excel:
        lines.append(
            "L'architecture s'articule autour d'un **Data Warehouse relationnel SQL piloté par des référentiels externes** : "
            "les tables de paramétrage tabulaires définissent les règles d'ingestion et les métadonnées de chargement, "
            "exécutées à travers des procédures et flux SQL assurant la traçabilité complète des données."
        )
    elif has_sql:
        lines.append(
            "L'architecture est centrée sur un **Data Warehouse relationnel SQL d'entreprise pur** : "
            f"elle comprend {stg} table(s) de staging et {dwh} table(s) DWH, "
            "avec une stricte séparation des couches d'ingestion et de modélisation relationnelle (schémas en étoile/flocon)."
        )
    elif has_pbix and has_excel:
        lines.append(
            "La solution implémente un **modèle sémantique Power BI enrichi par des référentiels tabulaires** : "
            "les sources Excel/CSV apportent les axes de nomenclature et règles de paramétrage nécessaires "
            "aux mesures de calcul DAX et tableaux de bord analytiques."
        )
    elif has_pbix:
        lines.append(
            "La solution implémente un **modèle sémantique décisionnel Power BI autonome** : "
            f"articulé autour de {pbi} table(s) de modèle et géré par le moteur colonnaire In-Memory VertiPaq, "
            "il fournit aux décideurs des mesures de calcul DAX avancées et une navigation interactive fluide."
        )
    elif has_excel:
        lines.append(
            "La solution constitue un **socle analytique et référentiel tabulaire agile** : "
            "basé sur des jeux de données et configurations structurés, il garantit la cohérence des indicateurs "
            "sans nécessiter d'infrastructure relationnelle lourde."
        )
    else:
        lines.append(
            f"L'architecture consolide l'ensemble des données du domaine **{graph.dominant_domain}** "
            "selon les standards méthodologiques d'intégration de données Keyrus."
        )

    lines.extend([
        "",
        "### Synthèse des métriques clés",
        f"- **Domaine fonctionnel principal** : {graph.dominant_domain}",
        f"- **Moteurs technologiques impliqués** : {', '.join(e.value for e in graph.storage_engines)}",
        f"- **Nombre total d'entités modélisées** : {len(graph.entities)}",
        f"- **Nombre total d'attributs / champs** : {total_fields}",
        f"- **Règles de transformation / mapping tracées** : {total_mappings}",
        f"- **Fichiers sources analysés** : {len(graph.raw_inputs)}",
    ])
    return "\n".join(lines)
