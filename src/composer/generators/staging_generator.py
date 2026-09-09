"""Générateur pour la couche Staging (Ingestion brute)."""
from __future__ import annotations

import logging
from typing import Any

from ...core.semantic_graph import EntityType, UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)


def generate_staging_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la documentation complète de la couche Staging."""
    stg_entities = graph.get_entities_by_type(EntityType.STAGING)
    if not stg_entities:
        return ""

    lines: list[str] = [
        "*Cette section recense les tables de staging (STG) recevant les données brutes "
        "extraites des systèmes sources avant transformation.*",
        "",
        "### Vue d'ensemble du Staging\n",
        "| # | Table Staging | Schéma / Origine | Nb Colonnes | Statut d'extraction |",
        "|---|---|---|---|---|",
    ]

    for idx, ent in enumerate(stg_entities, start=1):
        status = "⚠️ Partielle (à vérifier)" if ent.is_partial else "Complète"
        lines.append(f"| {idx} | `{ent.name}` | `{ent.schema_name or 'STG'}` | {len(ent.fields)} | {status} |")
    lines.append("")

    # Détail par table Staging
    lines.append("### Détail des tables de Staging\n")
    for idx, ent in enumerate(stg_entities, start=1):
        lines.append(f"#### Table `{ent.name}`")
        if ent.is_partial:
            lines.append(f"> ⚠️ **Attention :** L'extraction des colonnes est partielle pour cette table ({ent.partial_reason or 'Syntaxe complexe'}). Les colonnes manquantes doivent être vérifiées manuellement dans les scripts sources.\n")

        if ent.fields:
            lines.append("| Colonne | Type de donnée | Clé | Description / Rôle |")
            lines.append("|---|---|---|---|")
            for f in ent.fields:
                pk = "PK" if f.is_key else ""
                desc = f.description or ("Identifiant" if f.is_key else ("Champ d'audit" if f.is_audit else "Attribut brut"))
                lines.append(f"| `{f.name}` | {f.data_type} | {pk} | {desc} |")
            lines.append("")
        else:
            lines.append("*Aucune colonne individuelle n'a pu être résolue automatiquement.*\n")

    return "\n".join(lines)
