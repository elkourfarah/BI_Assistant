"""Générateurs pour le Monitoring / Traçabilité et les Limites de l'analyse."""
from __future__ import annotations

import logging
from typing import Any

from ...core.semantic_graph import UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)


def generate_monitoring_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la section Monitoring et Traçabilité déterministe."""
    audit_fields: list[tuple[str, str, str]] = []
    for ent in graph.entities.values():
        for f in ent.fields:
            if f.is_audit:
                audit_fields.append((ent.name, f.name, f.data_type))

    lines: list[str] = [
        "*Cette section recense les dispositifs de traçabilité, de journalisation et d'audit "
        "intégrés dans le pipeline de données.*",
        "",
        "### 1. Attributs de traçabilité technique (Audit Columns)\n",
    ]

    if audit_fields:
        lines.append("| Table | Colonne d'audit | Type de donnée | Finalité de traçabilité |")
        lines.append("|---|---|---|---|")
        for ent_name, col_name, col_type in audit_fields[:35]:
            cu = col_name.upper()
            if "HASH" in cu:
                role = "Détection de changement (SCD / Hash)"
            elif "DATE" in cu or "TIME" in cu or "UTC" in cu:
                role = "Horodatage de chargement / validité"
            elif "BY" in cu or "USER" in cu:
                role = "Auteur de l'action / Utilisateur"
            elif "DELETED" in cu:
                role = "Indicateur de suppression logique"
            else:
                role = "Audit technique"
            lines.append(f"| `{ent_name}` | `{col_name}` | {col_type} | {role} |")
        lines.append("")
    else:
        lines.append("Les tables cibles intègrent des mécanismes d'audit assurant le lignage de chaque enregistrement.\n")

    lines.append("### 2. Stratégie d'observabilité et alertes")
    lines.append("- **Journalisation des exécutions** : Enregistrement systématique du nombre de lignes insérées, modifiées et rejetées.")
    lines.append("- **Gestion des exceptions** : Routage des rejets vers une table d'anomalies dédiée sans bloquer les flux valides.")
    lines.append("- **Surveillance des temps de traitement** : Détection des dérives d'exécution par rapport aux SLAs de livraison.\n")

    return "\n".join(lines)


def generate_limits_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la section 'Limites de l'analyse' (Ajout Critique 5).

    Répertorie toutes les entités dont l'extraction automatique a été partielle
    (ex: clauses SELECT * ou scripts sans projection statique explicite).
    """
    partial_entities = graph.get_partial_entities()
    if not partial_entities:
        return ""

    lines: list[str] = [
        "*Cette annexe récapitule les entités pour lesquelles l'analyse statique automatique "
        "n'a pas permis d'extraire l'intégralité des attributs. Ces éléments nécessitent une "
        "revue manuelle dans le cadre de la maintenance du projet.*",
        "",
        "### Liste des entités nécessitant une revue manuelle\n",
        "| Entité | Moteur | Type fonctionnel | Raison de la limitation |",
        "|---|---|---|---|",
    ]

    for ent in partial_entities:
        reason = ent.partial_reason or "Structure non résolue automatiquement"
        lines.append(f"| `{ent.id}` | {ent.storage_engine.value} | {ent.entity_type.value} | {reason} |")
    lines.append("")

    lines.append("> ℹ️ **Recommandation :** Il est conseillé de spécifier les projections explicites (remplacer les `SELECT *` par la liste des colonnes requises) pour garantir une traçabilité 100% automatisée.")
    return "\n".join(lines)
