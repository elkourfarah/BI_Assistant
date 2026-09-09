"""Classe abstraite et types partagés pour le Section Registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..llm import BaseLLMClient
from ..models import Table


@dataclass
class SectionResult:
    """Résultat produit par une section après génération."""
    title: str
    markdown: str
    section_id: str = ""


@dataclass
class ProjectMetadata:
    """Agrège toutes les métadonnées extraites en un objet unique typé."""

    # --- PBIX ---
    tables: list[Table] = field(default_factory=list)
    pbix_metadata: dict[str, Any] | None = None

    # --- SQL sérialisé ---
    sql_metadata: list[dict[str, Any]] = field(default_factory=list)

    # --- Excel sérialisé ---
    excel_metadata: list[dict[str, Any]] = field(default_factory=list)
    excel_tables: list[Table] = field(default_factory=list)

    # --- Dérivés calculés ---
    stg_tables: list[dict[str, Any]] = field(default_factory=list)
    dwh_tables: list[dict[str, Any]] = field(default_factory=list)
    pbi_tables: list[dict[str, Any]] = field(default_factory=list)
    mappings: list[dict[str, Any]] = field(default_factory=list)
    etl_packages: list[dict[str, Any]] = field(default_factory=list)
    log_tables: list[dict[str, Any]] = field(default_factory=list)
    audit_columns: list[dict[str, Any]] = field(default_factory=list)

    # --- Paramètres ---
    project_name: str = "Projet BI"
    strict: bool = True

    # --- Reasoning ---
    dominant_domain: str = "UNKNOWN"      # Domaine détecté par le reasoning engine
    dominant_label: str = ""              # Label lisible du domaine
    incompatibility_banner: str = ""      # Avertissement Markdown si --force utilisé
    input_files: list[str] = field(default_factory=list)  # Noms des fichiers fournis

    def compute(self) -> "ProjectMetadata":
        """Calcule les vues dérivées à partir des métadonnées brutes."""
        _AUDIT_KW = {"date", "time", "load", "etl", "created", "updated",
                     "modified", "insert", "flow", "nbr"}

        for pkg in self.sql_metadata:
            dwh_target_names = {
                tbl.get("full_name", "").upper()
                for tbl in pkg.get("target_tables", [])
                if str(tbl.get("layer", "")).upper() in {"DWH", "LOG"} or "DWH_" in tbl.get("full_name", "").upper()
            }

            for tbl in pkg.get("source_tables", []):
                layer = str(tbl.get("layer", "")).upper()
                name = tbl.get("full_name", "")
                if name.upper() in dwh_target_names or "DWH_" in name.upper() or layer in {"DWH", "LOG"}:
                    continue
                is_stg = layer == "STG" or "STG_" in name.upper() or "STAGING" in name.upper()
                if is_stg and not any(t["full_name"] == name for t in self.stg_tables):
                    self.stg_tables.append(tbl)

            for tbl in pkg.get("target_tables", []):
                layer = str(tbl.get("layer", "")).upper()
                name = tbl.get("full_name", "")
                is_dwh = layer in {"DWH", "LOG"} or "DWH_" in name.upper()
                if is_dwh and not any(t["full_name"] == name for t in self.dwh_tables):
                    self.dwh_tables.append(tbl)
                if layer == "LOG" or "LOG" in name.upper():
                    if not any(t["full_name"] == name for t in self.log_tables):
                        self.log_tables.append(tbl)

            self.mappings.extend(pkg.get("mappings", []))

            src = [t.get("full_name") for t in pkg.get("source_tables", [])
                   if str(t.get("layer", "")).upper() in {"STG", "SRC", "ODS"}]
            tgt = [t.get("full_name") for t in pkg.get("target_tables", [])]
            self.etl_packages.append({
                "name": pkg.get("name"),
                "source_tables": src,
                "target_tables": tgt,
                "steps": pkg.get("steps", []),
                "description": pkg.get("description"),
            })

            for tbl in pkg.get("source_tables", []) + pkg.get("target_tables", []):
                for col in tbl.get("columns", []):
                    col_name = (col.get("name") or "").lower()
                    if any(kw in col_name for kw in _AUDIT_KW):
                        self.audit_columns.append({
                            "table": tbl.get("full_name"),
                            "column": col.get("name"),
                            "type": col.get("data_type"),
                        })

        for ex_meta in self.excel_metadata:
            self.mappings.extend(ex_meta.get("mappings", []))
            for tbl in ex_meta.get("tables", []):
                layer = str(tbl.get("layer", "")).upper()
                name = tbl.get("full_name") or tbl.get("name", "")
                is_stg = layer == "STG" or "STG_" in name.upper() or "STAGING" in name.upper()
                is_dwh = layer == "DWH" or "DWH_" in name.upper() or "DIM_" in name.upper() or "FACT_" in name.upper()
                if is_stg and not any(t.get("full_name") == name for t in self.stg_tables):
                    self.stg_tables.append(tbl)
                elif is_dwh and not any(t.get("full_name") == name for t in self.dwh_tables):
                    self.dwh_tables.append(tbl)
                elif not any(t.get("full_name") == name for t in self.stg_tables):
                    self.stg_tables.append(tbl)

                for col in tbl.get("columns", []):
                    col_name = (col.get("name") or "").lower()
                    if any(kw in col_name for kw in _AUDIT_KW):
                        self.audit_columns.append({
                            "table": name,
                            "column": col.get("name"),
                            "type": col.get("data_type"),
                        })

        for tbl in self.tables:
            self.pbi_tables.append({
                "name": tbl.name,
                "columns": [{"name": c.name, "type": c.data_type,
                              "description": c.description, "is_key": c.is_key}
                             for c in tbl.columns[:30]],
                "measures": [{"name": m.name, "expression": m.expression}
                              for m in tbl.measures[:20]],
            })
            for col in tbl.columns:
                if any(kw in col.name.lower() for kw in _AUDIT_KW):
                    self.audit_columns.append({
                        "table": tbl.name, "column": col.name, "type": col.data_type,
                    })
        return self

    @property
    def pbix_summary(self) -> dict[str, Any]:
        if self.pbix_metadata:
            return self.pbix_metadata.get("summary", {})
        return {}

    @property
    def total_mapping_count(self) -> int:
        return len(self.mappings)


class SectionGenerator(ABC):
    """Interface commune pour toutes les sections du document STD."""

    section_id: str = ""
    priority: int = 0
    title: str = ""

    @abstractmethod
    def applies_to(self, metadata: ProjectMetadata) -> bool:
        raise NotImplementedError

    @abstractmethod
    def generate(self, metadata: ProjectMetadata, llm_client: BaseLLMClient) -> SectionResult:
        raise NotImplementedError
