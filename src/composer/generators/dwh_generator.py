"""Générateurs pour le Data Warehouse relationnel et le Modèle Sémantique."""
from __future__ import annotations

import logging
from typing import Any

from ...core.semantic_graph import EntityType, StorageEngine, UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)


def generate_dwh_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la documentation du Data Warehouse relationnel (SQL)."""
    dwh_entities = [
        e for e in graph.get_entities_by_type(EntityType.WAREHOUSE_TABLE)
        if e.storage_engine == StorageEngine.SQL
    ]
    if not dwh_entities:
        return ""

    lines: list[str] = [
        "*Cette section décrit la modélisation relationnelle cible du Data Warehouse "
        "(tables de dimensions, tables de faits et tables de suivi).* ",
        "",
        "### Vue d'ensemble des tables DWH\n",
        "| # | Table DWH | Type fonctionnel | Nb Colonnes | Statut |",
        "|---|---|---|---|---|",
    ]

    for idx, ent in enumerate(dwh_entities, start=1):
        status = "⚠️ Partielle" if ent.is_partial else "Complète"
        lines.append(f"| {idx} | `{ent.name}` | {ent.functional_role} | {len(ent.fields)} | {status} |")
    lines.append("")

    # Détail par table
    lines.append("### Dictionnaire des tables du Data Warehouse\n")
    for idx, ent in enumerate(dwh_entities, start=1):
        lines.append(f"#### Table `{ent.name}` ({ent.functional_role})")
        if ent.is_partial:
            lines.append(f"> ⚠️ **Attention :** L'extraction des colonnes est partielle pour cette table ({ent.partial_reason or 'Syntaxe complexe'}). Les colonnes manquantes doivent être vérifiées manuellement.\n")

        if ent.fields:
            lines.append("| Colonne | Type SQL | Clé | Transformation appliquée |")
            lines.append("|---|---|---|---|")
            for f in ent.fields:
                pk = "PK / Upsert" if f.is_key else ("FK" if f.is_foreign_key else "")
                transf = f.transformation or "Copie directe"
                lines.append(f"| `{f.name}` | {f.data_type} | {pk} | {transf} |")
            lines.append("")
        else:
            lines.append("*Aucune colonne individuelle n'a pu être résolue automatiquement.*\n")

    return "\n".join(lines)


def generate_semantic_model_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la documentation du modèle sémantique décisionnel (Power BI / DAX / Relations)."""
    pbi_entities = graph.get_entities_by_type(EntityType.SEMANTIC_MODEL)
    if not pbi_entities:
        return ""

    lines: list[str] = [
        "*Cette section détaille le modèle sémantique décisionnel exposé aux utilisateurs finaux "
        "(tables du modèle, mesures DAX et relations inter-tables).* ",
        "",
        "### Tables du Modèle Sémantique\n",
        "| # | Table | Nb Colonnes | Nb Mesures DAX | Description |",
        "|---|---|---|---|---|",
    ]

    for idx, ent in enumerate(pbi_entities, start=1):
        lines.append(f"| {idx} | `{ent.name}` | {len(ent.fields)} | {len(ent.measures)} | {ent.description or 'Table du modèle'} |")
    lines.append("")

    # Détail des tables et mesures
    for ent in pbi_entities:
        lines.append(f"### Table `{ent.name}`\n")
        
        # Colonnes
        if ent.fields:
            lines.append("#### Attributs & Colonnes\n")
            lines.append("| Colonne | Type | Clé | Description |")
            lines.append("|---|---|---|---|")
            for f in ent.fields:
                pk = "PK" if f.is_key else ("FK" if f.is_foreign_key else "")
                lines.append(f"| `{f.name}` | {f.data_type} | {pk} | {f.description or '—'} |")
            lines.append("")

        # Mesures DAX
        if ent.measures:
            lines.append("#### Mesures DAX calculées\n")
            lines.append("| Mesure DAX | Expression de calcul |")
            lines.append("|---|---|")
            for m in ent.measures:
                expr = m.get("expression", "—")
                lines.append(f"| `{m.get('name')}` | `{expr}` |")
            lines.append("")

        # Relations
        if ent.relationships:
            lines.append("#### Relations du modèle\n")
            lines.append("| Colonne locale | Table cible | Colonne cible | Cardinalité |")
            lines.append("|---|---|---|---|")
            for r in ent.relationships:
                lines.append(f"| `{r.get('from_column')}` | `{r.get('to_table')}` | `{r.get('to_column')}` | {r.get('cardinality', '—')} |")
            lines.append("")

    return "\n".join(lines)
