"""Générateur pour les Transformations et Règles de Mapping (DataFlow)."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from ...core.semantic_graph import UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)
_MAX_ROWS_PER_TABLE = 150
_MAX_TABLES = 25


def generate_transformations_chapter(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère la documentation exhaustive des flux de transformation et règles de mapping."""
    if not graph.flows:
        return ""

    all_mappings: list[dict[str, Any]] = []
    for f in graph.flows:
        all_mappings.extend(f.field_mappings)

    if not all_mappings:
        return "*Aucune règle de mapping explicite n'a été extraite des flux fournis.*"

    lines: list[str] = [
        "*Ce chapitre détaille les règles de mapping et transformations appliquées colonne par colonne "
        "depuis les tables sources vers les tables cibles.*",
        "",
    ]

    # Regroupement par table cible
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in all_mappings:
        tgt = m.get("target_table") or "CIBLE"
        by_target[tgt].append(m)

    # Récapitulatif global
    total_rules = len(all_mappings)
    total_transf = sum(
        1 for m in all_mappings
        if m.get("transformation_rule") not in ("", "Aucune (copie directe)", "Copie directe", "Direct copy", "—")
        and not str(m.get("transformation_rule", "")).startswith("Copie")
    )
    total_direct = total_rules - total_transf

    lines.append("### Récapitulatif des règles de mapping\n")
    lines.append("| Métrique | Valeur |")
    lines.append("|---|---|")
    lines.append(f"| **Règles totales tracées** | {total_rules} |")
    lines.append(f"| **Tables cibles alimentées** | {len(by_target)} |")
    lines.append(f"| **Transformations spécifiques** | {total_transf} |")
    lines.append(f"| **Copies directes** | {total_direct} |")
    lines.append("")

    # Détail par table cible
    lines.append("### Règles de mapping par table cible\n")
    for tidx, (tgt, mappings_for_tgt) in enumerate(sorted(by_target.items())[:_MAX_TABLES], start=1):
        tgt_short = tgt.split(".")[-1]
        src_tables_set = {
            m.get("source_table", "").split(".")[-1]
            for m in mappings_for_tgt
            if m.get("source_table") and m.get("source_table") not in ("<SOURCE>", "—", "?")
        }
        src_str = ", ".join(f"`{s}`" for s in sorted(src_tables_set)) if src_tables_set else "`STG`"

        lines.append(f"#### Table cible `{tgt_short}`")
        lines.append(f"*Source(s) : {src_str} — {len(mappings_for_tgt)} règle(s) de mapping.*\n")
        lines.append("| # | Colonne Source | Table Source | Colonne Cible | Transformation |")
        lines.append("|---|---|---|---|---|")

        displayed = mappings_for_tgt[:_MAX_ROWS_PER_TABLE]
        for i, m in enumerate(displayed, start=1):
            src_col = m.get("source_column") or "—"
            src_tbl = (m.get("source_table") or "STG").split(".")[-1]
            tgt_col = m.get("target_column") or "—"
            rule = m.get("transformation_rule") or "Copie directe"
            lines.append(f"| {i} | `{src_col}` | `{src_tbl}` | `{tgt_col}` | `{rule}` |")

        remaining = len(mappings_for_tgt) - len(displayed)
        if remaining > 0:
            lines.append(f"| *… {remaining} règles supplémentaires non affichées* | | | | |")
        lines.append("")

    # Transformations remarquables (CAST, HASH, TO_DATE, CASE...)
    def _is_complex(rule_val: Any) -> bool:
        if not rule_val:
            return False
        clean = str(rule_val).strip().strip("`'\"")
        if not clean or clean in ("—", "-", "?", "None", "NULL"):
            return False
        clean_lower = clean.lower()
        if clean_lower in ("aucune", "copie directe", "direct copy") or clean_lower.startswith("copie"):
            return False
        return True

    notable = [m for m in all_mappings if _is_complex(m.get("transformation_rule"))]

    if notable:
        lines.append("### Transformations et Fonctions Remarquables\n")
        lines.append("| Colonne Cible | Table Cible | Type de transformation | Règle SQL appliquée |")
        lines.append("|---|---|---|---|")
        seen_keys: set[str] = set()
        for m in notable[:35]:
            tc = m.get("target_column") or "—"
            tt = (m.get("target_table") or "—").split(".")[-1]
            rule = str(m.get("transformation_rule") or "").strip().strip("`")
            if not rule:
                continue
            key = f"{tt}.{tc}"
            if key not in seen_keys:
                seen_keys.add(key)
                ru = rule.upper()
                if "HASH" in ru or "SHA" in ru:
                    ttype = "Calcul de Hash / Intégrité"
                elif "TO_DATE" in ru or "DATE" in ru:
                    ttype = "Conversion Date"
                elif "CAST" in ru or "CONVERT" in ru:
                    ttype = "Conversion de type (CAST)"
                elif "CASE" in ru or "DECODE" in ru:
                    ttype = "Logique conditionnelle"
                elif "COALESCE" in ru or "ISNULL" in ru or "NVL" in ru:
                    ttype = "Gestion des valeurs NULL"
                else:
                    ttype = "Fonction SQL"
                rule_disp = rule[:65] if len(rule) > 65 else rule
                lines.append(f"| `{tc}` | `{tt}` | {ttype} | `{rule_disp}` |")
        lines.append("")

    return "\n".join(lines)
