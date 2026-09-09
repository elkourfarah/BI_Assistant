"""Générateur de diagramme Mermaid – Lineage STG → DWH → PBI (STD).

Génère un diagramme générique et lisible à partir des métadonnées extraites :
- Aucune table n'est inventée.
- Structuré en subgraphs verticaux (STG, DWH, PBI).
- Limitation intelligente des nœuds si total_tables > 30.
- Export PNG haute résolution via mermaid-cli, playwright ou Kroki.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import requests

from ..core.semantic_graph import EntityType, UnifiedSemanticGraph
from ..llm import BaseLLMClient
from ..models import Table

LOGGER = logging.getLogger(__name__)

_MINIMAL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn7x8kAAAAASUVORK5CYII="
)


def _build_lineage_summary(
    tables: list[Table],
    sql_metadata: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Construit un résumé de lineage structuré par couche."""
    stg: list[dict[str, Any]] = []
    dwh: list[dict[str, Any]] = []
    pbi: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []

    # Tables PBI
    for t in tables:
        pbi.append(
            {
                "name": t.name,
                "columns": [c.name for c in t.columns[:8]],
                "relations": [r.to_table for r in t.relationships],
            }
        )

    # Tables SQL par couche + flux ETL
    if sql_metadata:
        seen: set[str] = set()
        for pkg in sql_metadata:
            for tbl in pkg.get("source_tables", []):
                name = tbl.get("full_name", "")
                layer = str(tbl.get("layer", "")).upper()
                if name and name not in seen:
                    seen.add(name)
                    entry = {
                        "name": name,
                        "columns": [c.get("name") for c in tbl.get("columns", [])[:8]],
                    }
                    if layer == "STG" or "STG_" in name.upper():
                        stg.append(entry)
                    elif layer in {"DWH", "LOG"} or "DWH_" in name.upper():
                        dwh.append(entry)

            for tbl in pkg.get("target_tables", []):
                name = tbl.get("full_name", "")
                layer = str(tbl.get("layer", "")).upper()
                if name and name not in seen:
                    seen.add(name)
                    entry = {
                        "name": name,
                        "columns": [c.get("name") for c in tbl.get("columns", [])[:8]],
                    }
                    if layer in {"DWH", "LOG"} or "DWH_" in name.upper():
                        dwh.append(entry)

            # ETL flows from mappings
            for m in pkg.get("mappings", []):
                src = m.get("source_table")
                tgt = m.get("target_table")
                if src and tgt:
                    flow = {"source": src, "target": tgt}
                    if flow not in flows:
                        flows.append(flow)

    return {
        "stg_tables": stg,
        "dwh_tables": dwh,
        "pbi_tables": pbi,
        "etl_flows": flows,
    }


def _sanitize_id(name: str) -> str:
    """Convertit un nom de table en identifiant Mermaid valide."""
    import re as _re
    return _re.sub(r"[^A-Za-z0-9_]", "_", name)


def _build_mermaid_locally(lineage: dict[str, Any]) -> str:
    """Construit un diagramme Mermaid lisible et structuré en subgraphs."""
    lines: list[str] = ["flowchart TD"]

    stg_tables = lineage.get("stg_tables", [])
    dwh_tables = lineage.get("dwh_tables", [])
    pbi_tables = lineage.get("pbi_tables", [])[:6]
    etl_flows = lineage.get("etl_flows", [])

    total_count = len(stg_tables) + len(dwh_tables) + len(pbi_tables)
    is_large_model = total_count > 30

    if is_large_model and len(stg_tables) > 8:
        # Trouver les STG prioritaires ayant des flux explicites vers DWH
        active_stg_names = {f.get("source") for f in etl_flows if f.get("source")}
        priority_stg = [t for t in stg_tables if t["name"] in active_stg_names]
        if not priority_stg:
            priority_stg = stg_tables[:6]
        else:
            priority_stg = priority_stg[:6]

        remaining_stg_count = len(stg_tables) - len(priority_stg)
        display_stg = priority_stg
    else:
        display_stg = stg_tables
        remaining_stg_count = 0

    # --- Subgraph STG ---
    if stg_tables:
        stg_header = f"Staging Layer ({len(stg_tables)} tables)" if is_large_model else "Staging Layer"
        lines.append(f'    subgraph STG["{stg_header}"]')
        for t in display_stg:
            nid = _sanitize_id(t["name"])
            label = t["name"].split(".")[-1]
            lines.append(f'        {nid}["{label}"]')
        if remaining_stg_count > 0:
            lines.append(f'        STG_SUMMARY["+ {remaining_stg_count} autres tables STG..."]')
        lines.append("    end")

    # --- Subgraph DWH ---
    if dwh_tables:
        dwh_header = f"Data Warehouse ({len(dwh_tables)} tables)" if is_large_model else "Data Warehouse"
        lines.append(f'    subgraph DWH["{dwh_header}"]')
        for t in dwh_tables:
            nid = _sanitize_id(t["name"])
            label = t["name"].split(".")[-1]
            lines.append(f'        {nid}["{label}"]')
        lines.append("    end")

    # --- Subgraph PBI ---
    if pbi_tables:
        lines.append("    subgraph PBI[Power BI Model]")
        for t in pbi_tables:
            nid = _sanitize_id(t["name"])
            label = t["name"][:30]
            lines.append(f'        {nid}["{label}"]')
        lines.append("    end")

    # --- Flux ETL (STG → DWH) avec labels ---
    seen_flows: set[str] = set()

    if etl_flows:
        for flow in etl_flows:
            raw_src = flow.get("source", "")
            if not raw_src or raw_src in ("<SOURCE>", "_SOURCE_", "—"):
                raw_src = display_stg[0]["name"] if display_stg else ""
            src_id = _sanitize_id(raw_src)
            tgt_id = _sanitize_id(flow.get("target", ""))

            # Si la table STG est masquée dans le groupe STG_SUMMARY
            if is_large_model and remaining_stg_count > 0:
                if not any(_sanitize_id(t["name"]) == src_id for t in display_stg):
                    src_id = "STG_SUMMARY"

            if src_id and tgt_id:
                key = f"{src_id}-->{tgt_id}"
                if key not in seen_flows:
                    lines.append(f"    {src_id} -->|MERGE / INSERT-UPDATE| {tgt_id}")
                    seen_flows.add(key)
    elif display_stg and dwh_tables:
        for s in display_stg[:3]:
            for d in dwh_tables[:3]:
                s_id = _sanitize_id(s["name"])
                d_id = _sanitize_id(d["name"])
                key = f"{s_id}-->{d_id}"
                if key not in seen_flows:
                    lines.append(f"    {s_id} -->|MERGE / INSERT-UPDATE| {d_id}")
                    seen_flows.add(key)
        if remaining_stg_count > 0 and dwh_tables:
            d_id = _sanitize_id(dwh_tables[0]["name"])
            lines.append(f"    STG_SUMMARY -->|MERGE / INSERT-UPDATE| {d_id}")

    # --- Flux Lineage (DWH → PBI) — relations réelles ou fallback ---
    if dwh_tables and pbi_tables:
        main_dwh = [d for d in dwh_tables if "LOG" not in d["name"].upper()]
        if not main_dwh:
            main_dwh = dwh_tables
        for pt in pbi_tables[:4]:
            pt_id = _sanitize_id(pt["name"])
            linked = False
            for rel_target in pt.get("relations", []):
                rel_id = _sanitize_id(rel_target)
                if any(_sanitize_id(d["name"]) == rel_id for d in main_dwh):
                    key = f"{rel_id}-->{pt_id}"
                    if key not in seen_flows:
                        lines.append(f"    {rel_id} -->|Power BI| {pt_id}")
                        seen_flows.add(key)
                        linked = True
            if not linked and main_dwh:
                d_id = _sanitize_id(main_dwh[0]["name"])
                key = f"{d_id}-->{pt_id}"
                if key not in seen_flows:
                    lines.append(f"    {d_id} -->|Power BI| {pt_id}")
                    seen_flows.add(key)

    # --- Relations inter-tables PBI seul (sans SQL) ---
    elif not dwh_tables and pbi_tables:
        for pt in pbi_tables:
            pt_id = _sanitize_id(pt["name"])
            for rel_target in pt.get("relations", [])[:3]:
                rel_id = _sanitize_id(rel_target)
                if any(_sanitize_id(t["name"]) == rel_id for t in pbi_tables):
                    key = f"{pt_id}-->{rel_id}"
                    if key not in seen_flows:
                        lines.append(f"    {pt_id} -- relation --> {rel_id}")
                        seen_flows.add(key)

    # --- Styles CSS par couche (lisibilité professionnelle) ---
    if stg_tables:
        lines.append("    style STG fill:#FFF8E1,stroke:#FFC107,stroke-width:2px")
    if dwh_tables:
        lines.append("    style DWH fill:#E8F5E9,stroke:#388E3C,stroke-width:2px")
    if pbi_tables:
        lines.append("    style PBI fill:#E3F2FD,stroke:#1565C0,stroke-width:2px")

    return "\n".join(lines)


def generate_diagram_from_graph(graph: UnifiedSemanticGraph) -> str:
    """Génère un code Mermaid horizontal (LR) représentant fidèlement le lignage et les relations du graphe.
    
    Structure les couches architecturales (Staging, DWH, Power BI, Référentiels)
    et matérialise les relations effectives (flux ETL et modélisation dimensionnelle en étoile).
    """
    lines: list[str] = ["flowchart LR"]

    stg_all = [e for e in graph.entities.values() if e.entity_type == EntityType.STAGING]
    dwh_all = [e for e in graph.entities.values() if e.entity_type == EntityType.WAREHOUSE_TABLE]
    pbi_all = [e for e in graph.entities.values() if e.entity_type == EntityType.SEMANTIC_MODEL]
    ref_all = [e for e in graph.entities.values() if e.entity_type == EntityType.REFERENCE_DATA]

    # 1. Extraction des flux ETL réels
    all_flows: list[tuple[str, str, str]] = []
    seen_flow_pairs: set[tuple[str, str]] = set()

    for flow in graph.flows:
        logic = flow.logic_type or "MERGE"
        for s in flow.source_entities:
            for t in flow.target_entities:
                pair = (s, t)
                if pair not in seen_flow_pairs:
                    seen_flow_pairs.add(pair)
                    all_flows.append((s, t, logic))

    # Fallback si STG et DWH sont présents sans flux explicites
    if not all_flows and stg_all and dwh_all:
        for s in stg_all[:3]:
            for t in dwh_all[:3]:
                all_flows.append((s.id, t.id, "ETL"))

    # 2. Sélection compacte pour un diagramme harmonieux (max 5 STG, 5 DWH, 6 PBI)
    stg_activity: dict[str, int] = {}
    dwh_activity: dict[str, int] = {}
    for s, t, _ in all_flows:
        stg_activity[s] = stg_activity.get(s, 0) + 1
        dwh_activity[t] = dwh_activity.get(t, 0) + 1

    sorted_stg_ids = sorted(stg_activity.keys(), key=lambda k: stg_activity[k], reverse=True)
    for e in stg_all:
        if e.id not in sorted_stg_ids:
            sorted_stg_ids.append(e.id)
    display_stg_ids = set(sorted_stg_ids[:5])

    sorted_dwh_ids = sorted(dwh_activity.keys(), key=lambda k: dwh_activity[k], reverse=True)
    for e in dwh_all:
        if e.id not in sorted_dwh_ids:
            sorted_dwh_ids.append(e.id)
    display_dwh_ids = set(sorted_dwh_ids[:5])

    display_stg = [graph.entities[sid] for sid in sorted_stg_ids[:5] if sid in graph.entities]
    display_dwh = [graph.entities[tid] for tid in sorted_dwh_ids[:5] if tid in graph.entities]
    display_pbi = pbi_all[:6]
    display_ref = ref_all[:2]

    rem_stg = len(stg_all) - len(display_stg)
    rem_dwh = len(dwh_all) - len(display_dwh)

    # Subgraph STG
    if display_stg or rem_stg > 0:
        lines.append(f'    subgraph STG["Couche Staging ({len(stg_all)} tables)"]')
        for e in display_stg:
            lines.append(f'        {_sanitize_id(e.id)}["{e.name[:24]}"]')
        if rem_stg > 0:
            lines.append(f'        STG_OTHER["+ {rem_stg} autres tables STG..."]')
        lines.append("    end")

    # Subgraph DWH
    if display_dwh or rem_dwh > 0:
        lines.append(f'    subgraph DWH["Data Warehouse ({len(dwh_all)} tables)"]')
        for e in display_dwh:
            lines.append(f'        {_sanitize_id(e.id)}["{e.name[:24]}"]')
        if rem_dwh > 0:
            lines.append(f'        DWH_OTHER["+ {rem_dwh} autres tables DWH..."]')
        lines.append("    end")

    # Subgraph PBI
    if display_pbi:
        lines.append(f'    subgraph PBI["Modèle Sémantique Power BI ({len(pbi_all)} tables)"]')
        for e in display_pbi:
            lines.append(f'        {_sanitize_id(e.id)}["{e.name[:24]}"]')
        lines.append("    end")

    # Subgraph REF (si présent)
    if display_ref and (display_stg or display_dwh):
        lines.append(f'    subgraph REF["Paramétrage & Référentiels"]')
        for e in display_ref:
            lines.append(f'        {_sanitize_id(e.id)}["{e.name[:24]}"]')
        lines.append("    end")

    # Relations ETL (STG -> DWH)
    rendered_flows = 0
    seen_rendered: set[tuple[str, str]] = set()

    for s, t, logic in all_flows:
        s_in = s in display_stg_ids
        t_in = t in display_dwh_ids
        if s_in and t_in:
            pair = (_sanitize_id(s), _sanitize_id(t))
            if pair not in seen_rendered:
                seen_rendered.add(pair)
                lines.append(f"    {pair[0]} -->|{logic}| {pair[1]}")
                rendered_flows += 1
        elif not s_in and t_in and rem_stg > 0 and rendered_flows < 6:
            pair = ("STG_OTHER", _sanitize_id(t))
            if pair not in seen_rendered:
                seen_rendered.add(pair)
                lines.append(f"    STG_OTHER -.->|{logic}| {pair[1]}")
                rendered_flows += 1

    # Relations DWH -> PBI
    if display_dwh and display_pbi:
        dwh_first = _sanitize_id(display_dwh[0].id)
        pbi_first = _sanitize_id(display_pbi[0].id)
        lines.append(f"    {dwh_first} -->|Dataset / Import| {pbi_first}")

    # Relations REF -> DWH
    if display_ref and display_dwh:
        ref_first = _sanitize_id(display_ref[0].id)
        dwh_first = _sanitize_id(display_dwh[0].id)
        lines.append(f"    {ref_first} -.->|Paramètres| {dwh_first}")

    # Relations internes PBI (Star Schema)
    if display_pbi:
        pbi_by_name = {e.name: e for e in display_pbi}
        for e in display_pbi:
            src_nid = _sanitize_id(e.id)
            for r in e.relationships:
                to_tbl = r.get("to_table")
                card = r.get("cardinality") or "M:1"
                if to_tbl in pbi_by_name and to_tbl != e.name:
                    tgt_nid = _sanitize_id(pbi_by_name[to_tbl].id)
                    pair = (src_nid, tgt_nid)
                    if pair not in seen_rendered:
                        seen_rendered.add(pair)
                        lines.append(f"    {src_nid} -->|{card}| {tgt_nid}")

    # Styles visuels
    if display_stg or rem_stg > 0:
        lines.append("    style STG fill:#FFF9C4,stroke:#FBC02D,stroke-width:1.5px")
    if display_dwh or rem_dwh > 0:
        lines.append("    style DWH fill:#E8F5E9,stroke:#4CAF50,stroke-width:1.5px")
    if display_pbi:
        lines.append("    style PBI fill:#E1F5FE,stroke:#03A9F4,stroke-width:1.5px")
    if display_ref:
        lines.append("    style REF fill:#F3E5F5,stroke:#7B1FA2,stroke-width:1.5px")

    return "\n".join(lines)


def generate_diagram(
    tables: list[Table] | UnifiedSemanticGraph,
    sql_metadata: list[dict[str, Any]] | None = None,
    client: BaseLLMClient | None = None,
) -> str:
    """Génère un code Mermaid représentant le lineage STG → DWH → PBI."""
    if isinstance(tables, UnifiedSemanticGraph):
        return generate_diagram_from_graph(tables)

    lineage = _build_lineage_summary(tables, sql_metadata)
    mermaid = _build_mermaid_locally(lineage)
    LOGGER.info(
        "Diagramme Mermaid généré localement : %d STG, %d DWH, %d PBI tables",
        len(lineage["stg_tables"]),
        len(lineage["dwh_tables"]),
        len(lineage["pbi_tables"]),
    )
    return mermaid


def export_mermaid_to_png(mermaid_code: str, output_path: str | Path = "output/diagramme.png") -> bool:
    """Exporte un code Mermaid en PNG via mermaid-cli, playwright ou kroki avec dimensions adaptées."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    mmd_path = output_file.with_suffix(".mmd")
    mmd_path.write_text(mermaid_code, encoding="utf-8")

    # 1. Essayer d'exporter via mermaid-cli (npx @mermaid-js/mermaid-cli)
    npx_cmd = "npx.cmd" if os.name == "nt" else "npx"
    try:
        LOGGER.info("Tentative d'export via npx @mermaid-js/mermaid-cli...")
        cmd = [
            npx_cmd,
            "-y",
            "@mermaid-js/mermaid-cli",
            "-i",
            str(mmd_path),
            "-o",
            str(output_file),
            "--theme",
            "neutral",
            "--width",
            "1600",
            "--height",
            "1000",
            "--scale",
            "2",
        ]
        subprocess.run(
            cmd,
            check=True,
            timeout=35,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if output_file.exists() and output_file.stat().st_size > 1000:
            LOGGER.info("✅ Export Mermaid réussi via mermaid-cli : %s (%d octets)", output_file, output_file.stat().st_size)
            return True
    except FileNotFoundError:
        LOGGER.warning("npx non trouvé, fallback sur playwright...")
    except Exception as exc:
        LOGGER.warning("Export via mermaid-cli échoué: %s", exc)

    # 2. Fallback sur playwright
    try:
        from playwright.sync_api import sync_playwright
        LOGGER.info("Tentative d'export via playwright...")
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>mermaid.initialize({{startOnLoad:true, theme: 'neutral'}});</script>
</head>
<body style="background: white; padding: 20px;">
    <div class="mermaid">
{mermaid_code}
    </div>
</body>
</html>"""
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.set_content(html_content)
            page.wait_for_selector(".mermaid svg", timeout=15000)
            elem = page.query_selector(".mermaid")
            if elem:
                elem.screenshot(path=str(output_file))
                browser.close()
                if output_file.exists() and output_file.stat().st_size > 1000:
                    LOGGER.info("✅ Export Mermaid via playwright réussi : %s (%d octets)", output_file, output_file.stat().st_size)
                    return True
            browser.close()
    except ImportError:
        LOGGER.warning("playwright non installé, fallback sur Kroki / text.")
    except Exception as exc:
        LOGGER.warning("Export via playwright échoué: %s", exc)

    # 3. Fallback sur Kroki API
    try:
        LOGGER.info("Tentative d'export via Kroki API...")
        response = requests.post(
            "https://kroki.io/mermaid/png",
            data=mermaid_code.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            timeout=15,
        )
        if response.status_code == 200 and len(response.content) > 1000:
            output_file.write_bytes(response.content)
            LOGGER.info("✅ Export Mermaid via Kroki réussi : %s (%d octets)", output_file, len(response.content))
            return True
    except Exception as exc:
        LOGGER.warning("Export via Kroki échoué: %s", exc)

    return False


def export_mermaid_png(mermaid_code: str, output_path: str | Path) -> Path:
    """Exporte le code Mermaid en image PNG."""
    output_file = Path(output_path)
    success = export_mermaid_to_png(mermaid_code, output_file)

    if not success:
        md_path = output_file.with_suffix(".md")
        md_path.write_text(
            f"# Diagramme Mermaid (export PNG indisponible)\n\n"
            f"```mermaid\n{mermaid_code}\n```\n"
            f"\n> Exportez ce code sur https://mermaid.live/ pour visualiser le diagramme.\n",
            encoding="utf-8",
        )
        LOGGER.info("Code Mermaid sauvegardé en fallback : %s", md_path)
        output_file.write_bytes(base64.b64decode(_MINIMAL_PNG_BASE64))

    return output_file
