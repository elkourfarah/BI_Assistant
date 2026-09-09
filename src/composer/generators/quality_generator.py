"""Générateur contextuel de la Qualité des Données et de la Performance."""
from __future__ import annotations

import logging
from typing import Any

from ...core.semantic_graph import StorageEngine, UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)


def generate_quality_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la section Qualité des Données et Contrôles d'Intégrité."""
    lines: list[str] = [
        "*Cette section décrit les règles d'intégrité, d'unicité et de conformité "
        "mises en œuvre sur les flux de données du projet.*",
        "",
        "### 1. Contrôles d'intégrité et clés d'unicité",
        "Les contraintes d'unicité et clés primaires identifiées dans le modèle sont :",
    ]

    key_fields: list[tuple[str, str]] = []
    for ent in graph.entities.values():
        for f in ent.fields:
            if f.is_key:
                key_fields.append((ent.name, f.name))

    if key_fields:
        for ent_name, f_name in key_fields[:20]:
            lines.append(f"- **`{ent_name}.{f_name}`** : Clé primaire / identifiant unique obligatoire (NOT NULL)")
        lines.append("")
    else:
        lines.append("- Les clés techniques et fonctionnelles doivent respecter l'unicité stricte et la non-nullité.\n")

    lines.append("### 2. Règles de format et typage strict")
    lines.append("- **Dates et Horodatages** : Standardisation au format ISO 8601 (ex: `YYYY-MM-DD` / `UTC`).")
    lines.append("- **Montants et Volumétries** : Typage numérique précis (`DECIMAL`, `NUMBER`) évitant les pertes d'arrondi.")
    lines.append("- **Gestion des valeurs NULL** : Substitution systématique via des fonctions de repli (`COALESCE`, `NVL`).\n")

    return "\n".join(lines)


def generate_performance_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère les recommandations de performance contextuelles (Ajout Critique 1).

    Adapte son discours aux moteurs réellement présents dans le graphe :
      - SQL : Index B-Tree, partitionnement temporel, clauses MERGE optimisées.
      - Power BI : Modélisation en étoile, réduction de la cardinalité, moteur VertiPaq, DAX.
      - Excel : Utilisation de Power Query, limitation du volume de lignes en mémoire.
    """
    engines = graph.storage_engines
    has_sql = StorageEngine.SQL in engines or graph.has_sql
    has_pbix = StorageEngine.POWERBI in engines or graph.has_pbix
    has_excel = StorageEngine.EXCEL in engines or graph.has_excel

    lines: list[str] = [
        "*Cette section présente les recommandations d'optimisation et bonnes pratiques de performance "
        "adaptées à l'écosystème technologique du projet.*",
        "",
    ]

    # 1. Recommandations SQL Relationnel
    if has_sql:
        lines.append("### Optimisation de la Couche Relationnelle & ETL (SQL)")
        lines.append("- **Stratégie d'indexation** : Poser des index B-Tree sur toutes les clés de jointure (`ON`) et colonnes de filtrage fréquent.")
        lines.append("- **Partitionnement des tables volumineuses** : Partitionner par date (`LOAD_DATE`, `MONTH_START_DATE`) pour accélérer les rechargements incrémentaux.")
        lines.append("- **Optimisation des flux MERGE** : Garantir que les tables sources de staging disposent de statistiques à jour avant l'exécution des requêtes de fusion.")
        lines.append("- **Traitement par lots (Batching)** : Éviter les verrous de table en fractionnant les volumétries massives lors des purges et insertions.")
        lines.append("")

    # 2. Recommandations Power BI / Moteur In-Memory VertiPaq
    if has_pbix:
        lines.append("### Optimisation du Modèle Sémantique & Moteur In-Memory (Power BI)")
        lines.append("- **Réduction de la cardinalité** : Éliminer les colonnes haute cardinalité non exploitées dans les visuels (ex: GUIDs, clés de staging temporaires) pour maximiser le taux de compression VertiPaq.")
        lines.append("- **Schéma en étoile strict** : Privilégier des relations 1-à-Plusieurs directes entre dimensions et faits ; proscrire les relations bidirectionnelles inutiles.")
        lines.append("- **Optimisation DAX** : Utiliser des variables `VAR` dans les mesures complexes pour éviter les réévaluations multiples de contexte de filtre.")
        lines.append("- **Audit DAX Studio** : Profiler les visuels consommateurs via DAX Studio et l'outil Performance Analyzer.")
        lines.append("")

    # 3. Recommandations Excel / CSV / Fichiers Tabulaires (Ajout 1 / Action 3.5)
    if has_excel:
        has_power_query = (
            has_pbix
            or any(
                bool(e.source_query and "let" in e.source_query.lower())
                for e in graph.entities.values()
            )
            or any(
                "powerquery" in str(ds.source_type).lower() or "mashup" in str(ds.source_type).lower()
                for ds in graph.data_sources
            )
        )

        lines.append("### Optimisation des Référentiels & Fichiers Tabulaires (Excel / CSV)")
        if has_power_query:
            lines.append(
                "- **Optimisation des requêtes Power Query (M)** : Positionner les filtres de sélection et suppressions "
                "de colonnes dès les premières étapes du script M pour minimiser la consommation de mémoire vive.\n"
                "- **Query Folding & Délégation** : Conserver le repli de requête (Query Folding) actif le plus longtemps possible "
                "afin de déléguer le travail de jointure et filtrage au moteur source.\n"
                "- **Typage strict et précoce** : Fixer explicitement le type de chaque colonne dans Power Query dès l'import pour "
                "éviter les coûteuses conversions implicites lors des rafraîchissements."
            )
        else:
            lines.append(
                "- **Prétraitement par scripts externes (Pandas / Python)** : Pour les volumétries importantes (> 100k lignes), "
                "privilégier un prétraitement batch scripté (Pandas) plutôt qu'une manipulation manuelle dans Excel.\n"
                "- **Stratégie d'archivage & purge périodique** : Segmenter et archiver régulièrement les données historiques "
                "dans un format compressé pour ne maintenir en mémoire que les paramètres et référentiels actifs.\n"
                "- **Suppression des formules volatiles** : Proscrire les formules de calcul manuelles lourdes (`RECHERCHEV`, "
                "`INDIRECT`, `OFFSET`) dans les fichiers sources et privilégier des données aplaties avec clés stables."
            )
        lines.append("")

    return "\n".join(lines)
