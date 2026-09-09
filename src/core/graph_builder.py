"""Graph Builder — Constructeur du graphe sémantique unifié à partir des extracteurs.

Transforme les sorties hétérogènes (SQL, PBIX, Excel/CSV, etc.) en un unique
UnifiedSemanticGraph sans aucune hypothèse rigide.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..models.table import Table
from .semantic_graph import (
    DataEntity,
    DataField,
    DataFlow,
    DataSourceInfo,
    EntityType,
    StorageEngine,
    UnifiedSemanticGraph,
)

LOGGER = logging.getLogger(__name__)

_AUDIT_KEYWORDS = ("created_by", "created_on", "updated_by", "updated_on", "load_date", "valid_from", "valid_to", "is_deleted", "row_hash")
_CONFIG_KEYWORDS = ("param", "config", "setting", "conf", "referentiel", "mapping_ref", "parameter")
_REF_DATA_COLUMN_PATTERNS = (
    r".*id$",
    r".*key$",
    r"^load.*",
    r"^target.*",
    r"^source.*",
    r"^config.*",
    r"^order.*",
    r"^param.*",
    r"^setting.*",
    r".*code$",
)


class GraphBuilder:
    """Construit un UnifiedSemanticGraph à partir des métadonnées extraites."""

    @staticmethod
    def build(
        project_name: str = "Projet BI",
        dominant_domain: str = "Data Integration & Analytics",
        sql_packages: list[Any] | None = None,
        pbix_tables: list[Table] | None = None,
        pbix_metadata: dict[str, Any] | None = None,
        excel_metadata: list[dict[str, Any]] | None = None,
        input_files: list[str] | None = None,
        llm_client: Any = None,
    ) -> UnifiedSemanticGraph:
        """Point d'entrée principal pour construire le graphe."""
        graph = UnifiedSemanticGraph(
            project_name=project_name,
            dominant_domain=dominant_domain,
            raw_inputs=input_files or [],
        )

        # 1. Ingestion des métadonnées SQL
        if sql_packages:
            for pkg in sql_packages:
                GraphBuilder._ingest_sql_package(pkg, graph)

        # 2. Ingestion des métadonnées Power BI
        if pbix_tables or pbix_metadata:
            GraphBuilder._ingest_pbix(pbix_tables or [], pbix_metadata or {}, graph)

        # 3. Ingestion des métadonnées Excel / CSV
        if excel_metadata:
            for meta in excel_metadata:
                GraphBuilder._ingest_excel_meta(meta, graph)

        # 4. Post-processing : Enrichissement batch des descriptions de colonnes PBIX
        if llm_client:
            GraphBuilder._enrich_semantic_model_descriptions(graph, llm_client)

        LOGGER.info(
            "UnifiedSemanticGraph construit avec succès : %d entités, %d flux, %d sources, moteurs=%s",
            len(graph.entities),
            len(graph.flows),
            len(graph.data_sources),
            [e.value for e in graph.storage_engines],
        )
        return graph

    # ------------------------------------------------------------------
    # Ingestion SQL
    # ------------------------------------------------------------------

    @staticmethod
    def _ingest_sql_package(pkg: Any, graph: UnifiedSemanticGraph) -> None:
        pkg_name = getattr(pkg, "name", str(pkg.get("name", ""))) if isinstance(pkg, dict) else pkg.name
        source_tables = getattr(pkg, "source_tables", pkg.get("source_tables", [])) if isinstance(pkg, dict) else pkg.source_tables
        target_tables = getattr(pkg, "target_tables", pkg.get("target_tables", [])) if isinstance(pkg, dict) else pkg.target_tables
        mappings = getattr(pkg, "mappings", pkg.get("mappings", [])) if isinstance(pkg, dict) else pkg.mappings
        raw_sql = getattr(pkg, "raw_sql", pkg.get("raw_sql", "")) if isinstance(pkg, dict) else getattr(pkg, "raw_sql", None)

        src_ids: list[str] = []
        tgt_ids: list[str] = []

        # Tables sources (STG / RAW)
        for tbl in source_tables:
            ent = GraphBuilder._convert_sql_table(tbl, is_target=False)
            if ent:
                src_ids.append(ent.id)
                # Si l'entité existe déjà avec des colonnes, on ne l'écrase pas avec une entité vide
                if ent.id not in graph.entities or (not graph.entities[ent.id].fields and ent.fields):
                    graph.entities[ent.id] = ent

        # Tables cibles (DWH)
        for tbl in target_tables:
            ent = GraphBuilder._convert_sql_table(tbl, is_target=True)
            if ent:
                tgt_ids.append(ent.id)
                if ent.id not in graph.entities or (not graph.entities[ent.id].fields and ent.fields):
                    graph.entities[ent.id] = ent

        # Création du DataFlow
        flow_mappings = []
        for m in mappings:
            m_dict = m if isinstance(m, dict) else {
                "source_table": getattr(m, "source_table", ""),
                "source_column": getattr(m, "source_column", ""),
                "target_table": getattr(m, "target_table", ""),
                "target_column": getattr(m, "target_column", ""),
                "transformation_rule": getattr(m, "transformation_rule", ""),
                "comment": getattr(m, "comment", ""),
            }
            flow_mappings.append(m_dict)

        if src_ids or tgt_ids or flow_mappings:
            flow = DataFlow(
                id=pkg_name,
                name=f"Flux ETL {pkg_name}",
                source_entities=src_ids,
                target_entities=tgt_ids,
                field_mappings=flow_mappings,
                logic_type="MERGE" if any("MERGE" in str(getattr(m, "transformation_rule", "")) for m in mappings) else "INSERT",
                raw_script=raw_sql,
            )
            graph.flows.append(flow)

    @staticmethod
    def _convert_sql_table(tbl: Any, is_target: bool) -> DataEntity | None:
        full_name = getattr(tbl, "full_name", tbl.get("full_name", "")) if isinstance(tbl, dict) else tbl.full_name
        name = getattr(tbl, "name", tbl.get("name", "")) if isinstance(tbl, dict) else tbl.name
        schema = getattr(tbl, "schema", tbl.get("schema", None)) if isinstance(tbl, dict) else getattr(tbl, "schema", None)
        layer = str(getattr(tbl, "layer", tbl.get("layer", "UNKNOWN")) if isinstance(tbl, dict) else tbl.layer).upper()
        role = getattr(tbl, "functional_role", tbl.get("functional_role", "DIM")) if isinstance(tbl, dict) else getattr(tbl, "functional_role", "DIM")
        columns = getattr(tbl, "columns", tbl.get("columns", [])) if isinstance(tbl, dict) else tbl.columns

        if not full_name:
            full_name = name
        if not full_name:
            return None

        # Déterminer le type fonctionnel
        if layer == "STG" or (not is_target and layer in ("STG", "SRC")):
            entity_type = EntityType.STAGING
        elif layer == "LOG" or role == "AUDIT":
            entity_type = EntityType.WAREHOUSE_TABLE
        else:
            entity_type = EntityType.WAREHOUSE_TABLE

        fields: list[DataField] = []
        for col in columns:
            c_name = getattr(col, "name", col.get("name", "")) if isinstance(col, dict) else col.name
            c_type = getattr(col, "data_type", col.get("data_type", "VARCHAR2(255)")) if isinstance(col, dict) else getattr(col, "data_type", "VARCHAR2(255)")
            c_is_pk = bool(getattr(col, "is_primary_key", col.get("is_primary_key", False)) if isinstance(col, dict) else getattr(col, "is_primary_key", False))
            c_is_fk = bool(getattr(col, "is_foreign_key", col.get("is_foreign_key", False)) if isinstance(col, dict) else getattr(col, "is_foreign_key", False))
            c_transf = getattr(col, "transformation", col.get("transformation", None)) if isinstance(col, dict) else getattr(col, "transformation", None)

            is_audit = any(kw in c_name.lower() for kw in _AUDIT_KEYWORDS)
            fields.append(
                DataField(
                    name=c_name,
                    data_type=c_type or "VARCHAR2(255)",
                    is_key=c_is_pk,
                    is_foreign_key=c_is_fk,
                    is_audit=is_audit,
                    transformation=c_transf,
                )
            )

        is_partial = len(fields) == 0
        partial_reason = "Structure de projection non résolue automatiquement (syntaxe complexe ou SELECT *)" if is_partial else None

        return DataEntity(
            id=full_name,
            name=name or full_name.split(".")[-1],
            schema_name=schema,
            entity_type=entity_type,
            storage_engine=StorageEngine.SQL,
            functional_role=role,
            fields=fields,
            is_partial=is_partial,
            partial_reason=partial_reason,
        )

    # ------------------------------------------------------------------
    # Ingestion Power BI
    # ------------------------------------------------------------------

    @staticmethod
    def _ingest_pbix(tables: list[Table], metadata: dict[str, Any], graph: UnifiedSemanticGraph) -> None:
        # Sources de données
        sources_list = metadata.get("sources", [])
        for src in sources_list:
            ds = DataSourceInfo(
                name=src.get("name") or src.get("database") or "Source Power BI",
                source_type=src.get("type", "Database"),
                connection_string=src.get("connection"),
                database=src.get("database"),
                server=src.get("server"),
            )
            graph.data_sources.append(ds)

        for tbl in tables:
            fields: list[DataField] = []
            for col in tbl.columns:
                is_audit = any(kw in col.name.lower() for kw in _AUDIT_KEYWORDS)
                fields.append(
                    DataField(
                        name=col.name,
                        data_type=col.data_type or "String",
                        is_key=col.is_key or col.is_primary_key,
                        is_foreign_key=col.is_foreign_key,
                        is_audit=is_audit,
                        description=col.description,
                    )
                )

            measures_list = [{"name": m.name, "expression": m.expression} for m in tbl.measures]
            relationships_list = [
                {"from_column": r.from_column, "to_table": r.to_table, "to_column": r.to_column, "cardinality": r.cardinality}
                for r in tbl.relationships
            ]

            ent = DataEntity(
                id=tbl.name,
                name=tbl.name,
                entity_type=EntityType.SEMANTIC_MODEL,
                storage_engine=StorageEngine.POWERBI,
                functional_role="Modèle sémantique",
                description=tbl.description,
                fields=fields,
                measures=measures_list,
                relationships=relationships_list,
                source_query=tbl.source_query,
                is_partial=len(fields) == 0,
            )
            graph.entities[tbl.name] = ent

    # ------------------------------------------------------------------
    # Ingestion Excel / CSV
    # ------------------------------------------------------------------

    @staticmethod
    def _ingest_excel_meta(meta: dict[str, Any], graph: UnifiedSemanticGraph) -> None:
        file_path = meta.get("file_path", "")
        file_stem = Path(file_path).stem.lower() if file_path else ""

        is_config_file = any(kw in file_stem for kw in _CONFIG_KEYWORDS)

        for tbl in meta.get("tables", []):
            name = tbl.get("name", "ExcelTable")
            fields: list[DataField] = []
            cols = tbl.get("columns", [])
            for col in cols:
                c_name = col.get("name", "")
                c_type = col.get("data_type", "VARCHAR2")
                is_key = col.get("is_primary_key", False)
                sample = col.get("sample_values", [])
                is_audit = any(kw in c_name.lower() for kw in _AUDIT_KEYWORDS)
                fields.append(
                    DataField(
                        name=c_name,
                        data_type=c_type,
                        is_key=is_key,
                        is_audit=is_audit,
                        sample_values=sample,
                    )
                )

            # Calcul du score heuristique pour classification REFERENCE_DATA (Action 2)
            matching_cols = 0
            for col in cols:
                c_name_clean = col.get("name", "").strip().lower()
                if any(re.match(pat, c_name_clean) for pat in _REF_DATA_COLUMN_PATTERNS):
                    matching_cols += 1
            total_cols = len(cols)
            ref_score = (matching_cols / total_cols) if total_cols > 0 else 0.0

            is_reference = is_config_file or (ref_score > 0.4)
            entity_type = EntityType.REFERENCE_DATA if is_reference else EntityType.SOURCE_RAW
            functional_role = "Référentiel / Paramètres" if is_reference else "Fichier source tabulaire"

            ent = DataEntity(
                id=f"{file_stem}.{name}" if file_stem else name,
                name=name,
                entity_type=entity_type,
                storage_engine=StorageEngine.EXCEL,
                functional_role=functional_role,
                fields=fields,
                is_partial=len(fields) == 0,
            )
            graph.entities[ent.id] = ent

    # ------------------------------------------------------------------
    # Post-processing : Enrichissement batch LLM des descriptions PBIX
    # ------------------------------------------------------------------

    @staticmethod
    def _enrich_semantic_model_descriptions(graph: UnifiedSemanticGraph, llm_client: Any) -> None:
        """Enrichit les colonnes PBIX sans description par appel LLM en batch (Action 7)."""
        if not llm_client:
            return

        cols_to_enrich: list[tuple[str, DataField]] = []
        for ent in graph.entities.values():
            if ent.entity_type == EntityType.SEMANTIC_MODEL:
                for f in ent.fields:
                    desc = (f.description or "").strip()
                    if not desc or desc in ("---", "-", "—", "None"):
                        cols_to_enrich.append((ent.name, f))

        if not cols_to_enrich:
            return

        LOGGER.info("Enrichissement LLM en batch de %d colonnes PBIX sans description", len(cols_to_enrich))
        batch_size = 30
        for i in range(0, len(cols_to_enrich), batch_size):
            batch = cols_to_enrich[i : i + batch_size]
            prompt_lines = [
                "Tu es un consultant BI senior chez Keyrus.",
                "Donne pour chaque colonne du modèle Power BI ci-dessous une brève description fonctionnelle en français (une seule courte phrase claire).",
                f"Projet : {graph.project_name} (Domaine fonctionnel : {graph.dominant_domain})",
                "",
                "Colonnes :",
            ]
            for idx, (tbl_name, field) in enumerate(batch, 1):
                prompt_lines.append(f"{idx}. {tbl_name}.{field.name} ({field.data_type})")

            prompt_lines.extend([
                "",
                "Consignes STRICTES de réponse :",
                "- Réponds UNIQUEMENT par une liste numérotée correspondant exactement à chaque colonne.",
                "- Exemple : '1. Identifiant unique du défaut qualité.'",
                "- Ne génère AUCUN texte d'introduction ni de conclusion ni de calculs de mots.",
            ])
            prompt = "\n".join(prompt_lines)

            try:
                response = llm_client.generate(prompt)
                lines = [line.strip() for line in response.strip().split("\n") if line.strip()]
                idx_map: dict[int, str] = {}
                for line in lines:
                    m = re.match(r"^(\d+)[\.\)\-\:\s]+(.*)$", line)
                    if m:
                        num = int(m.group(1))
                        txt = m.group(2).strip().strip("'\"*")
                        if ":" in txt:
                            txt = txt.split(":", 1)[1].strip()
                        elif " - " in txt:
                            txt = txt.split(" - ", 1)[1].strip()
                        txt = txt.strip().strip("'\"*")
                        if txt and len(txt) > 3:
                            idx_map[num] = txt

                for idx, (tbl_name, field) in enumerate(batch, 1):
                    if idx in idx_map:
                        field.description = idx_map[idx]
                LOGGER.info("Descriptions colonnes PBIX enrichies : %d / %d pour ce batch", len(idx_map), len(batch))
            except Exception as exc:
                LOGGER.warning("Échec enrichissement batch descriptions colonnes PBIX: %s", exc)
                # Fallback : conservation de la valeur existante (--- / None)
