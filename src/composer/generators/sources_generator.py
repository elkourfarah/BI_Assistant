"""Générateurs pour les Sources de données et les Référentiels / Paramètres."""
from __future__ import annotations

import logging
from typing import Any

from ...core.semantic_graph import EntityType, UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)


def generate_sources_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la documentation des sources et connecteurs de données."""
    lines: list[str] = [
        "*Cette section décrit l'ensemble des points d'accès et sources de données amont alimentant le pipeline.*",
        "",
    ]

    if graph.data_sources:
        lines.append("### Connexions et Sources Externes\n")
        lines.append("| Nom / Identifiant | Type de source | Base de données / Emplacement | Serveur |")
        lines.append("|---|---|---|---|")
        for ds in graph.data_sources:
            db_val = ds.database or ds.connection_string or "Géré par le service"
            srv_val = ds.server or "Cloud / Service"
            lines.append(f"| `{ds.name}` | {ds.source_type} | {db_val} | {srv_val} |")
        lines.append("")

    raw_sources = graph.get_entities_by_type(EntityType.SOURCE_RAW)
    if raw_sources:
        lines.append("### Fichiers et Entités Sources Brutes\n")
        lines.append("| Entité / Fichier | Moteur | Nb Champs | Rôle |")
        lines.append("|---|---|---|---|")
        for ent in raw_sources:
            lines.append(f"| `{ent.name}` | {ent.storage_engine.value} | {len(ent.fields)} | {ent.functional_role} |")
        lines.append("")

    return "\n".join(lines)


def generate_reference_data_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la documentation des fichiers de paramétrage et référentiels (EntityType.REFERENCE_DATA)."""
    ref_entities = graph.get_entities_by_type(EntityType.REFERENCE_DATA)
    if not ref_entities:
        return ""

    lines: list[str] = [
        "*Cette section documente les tables de référence, tables de transcodification et fichiers "
        "de configuration nécessaires à l'orchestration et au paramétrage des flux.*",
        "",
    ]

    for ent in ref_entities:
        lines.append(f"### Référentiel `{ent.name}`\n")
        lines.append(f"- **Identifiant** : `{ent.id}`")
        lines.append(f"- **Format / Moteur** : {ent.storage_engine.value}")
        lines.append(f"- **Nombre de paramètres / colonnes** : {len(ent.fields)}\n")

        if ent.fields:
            lines.append("| Paramètre / Colonne | Type | Clé | Exemples de valeurs |")
            lines.append("|---|---|---|---|")
            for f in ent.fields:
                pk_str = "✔" if f.is_key else ""
                sample_str = ", ".join(f.sample_values[:3]) if f.sample_values else "—"
                lines.append(f"| `{f.name}` | {f.data_type} | {pk_str} | {sample_str} |")
            lines.append("")

    return "\n".join(lines)
