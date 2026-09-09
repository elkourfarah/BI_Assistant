import json
import logging
import re
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from ..models import Column, DataSource, LayerEnum, Measure, Relationship, Table

if TYPE_CHECKING:
    # pyrefly: ignore [missing-import]
    from pbixray import PBIXRay as _PBIXRay


def _get_pbixray():
    """Import pbixray lazily â€“ only fails if the user actually calls extract()."""
    try:
        # pyrefly: ignore [missing-import]
        from pbixray import PBIXRay  # noqa: PLC0415
        return PBIXRay
    except ImportError as exc:
        raise ImportError(
            "Le module 'pbixray' est introuvable.\n"
            "Installez-le avec : pip install pbixray\n"
            "Ou activez votre environnement virtuel : .\\venv\\Scripts\\activate"
        ) from exc


LOGGER = logging.getLogger(__name__)


class PBIXExtractor:
    """Extrait les mÃ©tadonnÃ©es d'un fichier Power BI (.pbix) via pbixray."""

    def __init__(self, pbix_path: str | Path) -> None:
        self.pbix_path = Path(pbix_path)
        self._raw_metadata: dict[str, Any] | None = None

    @property
    def raw_metadata(self) -> dict[str, Any] | None:
        return self._raw_metadata

    def extract(self) -> list[Table]:
        """Extrait les tables, colonnes, mesures et relations du fichier PBIX."""
        if not self.pbix_path.exists():
            raise FileNotFoundError(f"Fichier PBIX introuvable: {self.pbix_path}")

        try:
            PBIXRay = _get_pbixray()
            with PBIXRay(str(self.pbix_path)) as model:
                raw_metadata = self._collect_raw_metadata(model)
                tables = self._map_tables(model, raw_metadata)
                self._raw_metadata = raw_metadata
                return tables
        except Exception as exc:
            LOGGER.exception("Ã‰chec de l'extraction PBIX: %s", exc)
            raise RuntimeError(f"Impossible d'extraire les mÃ©tadonnÃ©es du PBIX: {exc}") from exc

    def _collect_raw_metadata(self, model: Any) -> dict[str, Any]:
        schema_df = self._get_dataframe(model, "schema")
        relationships_df = self._get_dataframe(model, "relationships")
        dax_measures_df = self._get_dataframe(model, "dax_measures")
        dax_columns_df = self._get_dataframe(model, "dax_columns")
        metadata_df = self._get_dataframe(model, "metadata")
        tables_df = self._get_dataframe_from_source(model, "tables_df")
        datasources_df = self._get_dataframe_from_source(model, "datasources_df")
        tmschema_ds_df = self._get_dataframe(model, "tmschema_datasources")
        if datasources_df.empty or not any(len(str(r.get("Name", ""))) > 15 for _, r in datasources_df.iterrows() if isinstance(r, pd.Series)):
            datasources_df = tmschema_ds_df if not tmschema_ds_df.empty else datasources_df
        connections = self._to_records(getattr(model, "connections", []))

        # Extraction Power Query M (mashup_queries et/ou DataModelSchema dans ZIP)
        mashup_df = self._get_dataframe(model, "mashup_queries")
        power_query_records = self._to_records(mashup_df)
        if not power_query_records:
            zip_m = self._extract_m_from_zip_schema()
            power_query_records = list(zip_m.values())

        raw: dict[str, Any] = {
            "source_file": str(self.pbix_path),
            "tables": self._to_records(tables_df) if not tables_df.empty else self._build_table_records(schema_df),
            "columns": self._to_records(schema_df),
            "measures": self._to_records(dax_measures_df),
            "relationships": self._to_records(relationships_df),
            "sources": self._build_sources_payload(connections, datasources_df),
            "metadata": self._to_records(metadata_df),
            "dax_columns": self._to_records(dax_columns_df),
            "power_query": power_query_records,
            "summary": {
                "table_count": int(schema_df["TableName"].nunique()) if not schema_df.empty and "TableName" in schema_df else 0,
                "column_count": int(len(schema_df)),
                "measure_count": int(len(dax_measures_df)),
                "relationship_count": int(len(relationships_df)),
                "source_count": int(len(connections)),
                "power_query_count": len(power_query_records),
            },
        }
        return raw

    def _map_tables(self, model: Any, raw_metadata: dict[str, Any]) -> list[Table]:
        schema_df = self._get_dataframe(model, "schema")
        relationships_df = self._get_dataframe(model, "relationships")
        dax_measures_df = self._get_dataframe(model, "dax_measures")
        tables_df = self._get_dataframe_from_source(model, "tables_df")
        datasources = self._build_data_sources(model)

        if schema_df.empty:
            LOGGER.warning("Aucune colonne trouvÃ©e dans le modÃ¨le PBIX.")
            return []

        table_rows = (
            tables_df.set_index("Name").to_dict(orient="index")
            if not tables_df.empty and "Name" in tables_df.columns
            else {}
        )
        grouped_columns = schema_df.groupby("TableName", dropna=False)

        _PBI_INTERNAL_TABLE_PREFIXES = (
            "DateTableTemplate_",
            "LocalDateTable_",
            "_LocalDateTable_",
        )

        tables: list[Table] = []
        for table_name, columns_group in grouped_columns:
            if not table_name:
                continue

            tbl_str = str(table_name)
            if any(tbl_str.startswith(p) for p in _PBI_INTERNAL_TABLE_PREFIXES):
                LOGGER.debug("Table système / template interne Power BI ignorée : %s", tbl_str)
                continue

            table_raw = table_rows.get(table_name, {})
            table_columns = [self._map_column(row) for _, row in columns_group.iterrows()]
            table_measures = self._map_measures(dax_measures_df, table_name)
            table_relationships = self._map_relationships(relationships_df, table_name)

            tables.append(
                Table(
                    name=str(table_name),
                    layer=LayerEnum.PBI,
                    description=self._as_str(table_raw.get("Description")),
                    data_category=self._as_str(table_raw.get("DataCategory")),
                    is_hidden=self._as_bool(table_raw.get("IsHidden")),
                    is_private=self._as_bool(table_raw.get("IsPrivate")),
                    columns=table_columns,
                    measures=table_measures,
                    relationships=table_relationships,
                    data_sources=datasources,
                    source_query=self._find_source_query(model, str(table_name)),
                    raw={"table": table_raw, "source": raw_metadata},
                )
            )

        self._enrich_pk_fk_from_relationships(tables, relationships_df)
        return tables

    def _enrich_pk_fk_from_relationships(self, tables: list[Table], relationships_df: pd.DataFrame) -> None:
        """Enrichit les colonnes des tables Power BI avec is_primary_key et is_foreign_key."""
        if relationships_df.empty:
            return

        table_dict = {t.name: t for t in tables}

        for _, rel in relationships_df.iterrows():
            from_tbl = self._as_str(rel.get("FromTable")) or self._as_str(rel.get("FromTableName"))
            from_col = self._as_str(rel.get("FromColumn")) or self._as_str(rel.get("FromColumnName"))
            to_tbl = self._as_str(rel.get("ToTable")) or self._as_str(rel.get("ToTableName"))
            to_col = self._as_str(rel.get("ToColumn")) or self._as_str(rel.get("ToColumnName"))
            from_card = self._as_str(rel.get("FromCardinality")) or ""
            to_card = self._as_str(rel.get("ToCardinality")) or ""

            if not from_tbl or not from_col or not to_tbl or not to_col:
                continue

            # ToTable.ToColumn est la PK du référentiel
            if to_tbl in table_dict:
                for c in table_dict[to_tbl].columns:
                    if c.name.lower() == to_col.lower():
                        c.is_primary_key = True
                        c.is_key = True
                        LOGGER.debug("PK détectée sur PBIX [%s.%s]", to_tbl, c.name)

            # FromTable.FromColumn est la FK
            if from_tbl in table_dict:
                for c in table_dict[from_tbl].columns:
                    if c.name.lower() == from_col.lower():
                        c.is_foreign_key = True
                        LOGGER.debug("FK détectée sur PBIX [%s.%s]", from_tbl, c.name)

    def _map_column(self, row: pd.Series) -> Column:
        return Column(
            name=self._as_str(row.get("ColumnName")) or self._as_str(row.get("Name")) or "",
            data_type=self._as_str(row.get("PandasDataType")) or self._as_str(row.get("DataType")),
            semantic_type=self._as_str(row.get("SemanticType")),
            description=self._as_str(row.get("Description")),
            expression=self._as_str(row.get("Expression")),
            format_string=self._as_str(row.get("FormatString")),
            display_folder=self._as_str(row.get("DisplayFolder")),
            summarize_by=self._as_str(row.get("SummarizeBy")),
            is_hidden=self._as_bool(row.get("IsHidden")),
            is_key=self._as_bool(row.get("IsKey")),
            is_unique=self._as_bool(row.get("IsUnique")),
            is_nullable=self._as_bool(row.get("IsNullable")),
            source_column=self._as_str(row.get("SourceColumn")),
            modified_time=self._as_datetime(row.get("ModifiedTime")),
            structure_modified_time=self._as_datetime(row.get("StructureModifiedTime")),
            raw=self._to_dict(row),
        )

    def _map_measures(self, measures_df: pd.DataFrame, table_name: str) -> list[Measure]:
        if measures_df.empty or "TableName" not in measures_df.columns:
            return []

        table_measures = measures_df[measures_df["TableName"] == table_name]
        return [
            Measure(
                name=self._as_str(row.get("Name")) or "",
                expression=self._as_str(row.get("Expression")),
                display_folder=self._as_str(row.get("DisplayFolder")),
                description=self._as_str(row.get("Description")),
                raw=self._to_dict(row),
            )
            for _, row in table_measures.iterrows()
        ]

    def _map_relationships(self, relationships_df: pd.DataFrame, table_name: str) -> list[Relationship]:
        if relationships_df.empty:
            return []

        if "FromTableName" not in relationships_df.columns or "ToTableName" not in relationships_df.columns:
            return []

        relationship_rows = relationships_df[
            (relationships_df["FromTableName"] == table_name) | (relationships_df["ToTableName"] == table_name)
        ]
        relationships: list[Relationship] = []
        for _, row in relationship_rows.iterrows():
            relationships.append(
                Relationship(
                    from_table=self._as_str(row.get("FromTableName")) or "",
                    from_column=self._as_str(row.get("FromColumnName")) or "",
                    to_table=self._as_str(row.get("ToTableName")) or "",
                    to_column=self._as_str(row.get("ToColumnName")) or "",
                    cardinality=self._as_str(row.get("Cardinality")),
                    is_active=self._as_bool(row.get("IsActive")),
                    cross_filtering_behavior=self._as_str(row.get("CrossFilteringBehavior")),
                    rely_on_referential_integrity=self._as_bool(row.get("RelyOnReferentialIntegrity")),
                    from_key_count=self._as_int(row.get("FromKeyCount")),
                    to_key_count=self._as_int(row.get("ToKeyCount")),
                    raw=self._to_dict(row),
                )
            )
        return relationships

    def _build_data_sources(self, model: Any) -> list[DataSource]:
        sources: list[DataSource] = []
        connections = getattr(model, "connections", []) or []
        for idx, connection in enumerate(connections, start=1):
            sources.append(self._connection_to_source(connection, index=idx))

        datasources_df = self._get_dataframe_from_source(model, "datasources_df")
        if not datasources_df.empty:
            for _, row in datasources_df.iterrows():
                sources.append(
                    DataSource(
                        name=self._as_str(row.get("Name")) or self._as_str(row.get("DataSourceName")),
                        kind=self._as_str(row.get("Kind")) or self._as_str(row.get("Type")),
                        connection_string=self._as_str(row.get("ConnectionString")),
                        server=self._as_str(row.get("Server")),
                        database=self._as_str(row.get("Database")),
                        provider=self._as_str(row.get("Provider")),
                        query=self._as_str(row.get("Query")) or self._as_str(row.get("QueryDefinition")),
                        description=self._as_str(row.get("Description")),
                        raw=self._to_dict(row),
                    )
                )

        # Extraction des connecteurs depuis les expressions Power Query M
        mq_df = self._get_dataframe(model, "mashup_queries")
        all_expressions = []
        if not mq_df.empty and "Expression" in mq_df.columns:
            all_expressions.extend(mq_df["Expression"].dropna().tolist())
        zip_queries = self._extract_m_from_zip_schema()
        for q in zip_queries.values():
            if q.get("expression"):
                all_expressions.append(q["expression"])

        for expr in all_expressions:
            sources.extend(self._parse_m_connectors(str(expr)))

        unique_sources: list[DataSource] = []
        seen: set[tuple[Any, ...]] = set()
        for source in sources:
            fingerprint = (
                source.name,
                source.kind,
                source.connection_string,
                source.server,
                source.database,
                source.provider,
                source.query,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique_sources.append(source)
        return unique_sources

    def _parse_m_connectors(self, m_code: str) -> list[DataSource]:
        """Analyse le code M (Power Query) pour identifier les connecteurs et sources sous-jacents."""
        discovered: list[DataSource] = []
        if not m_code:
            return discovered

        # 1. SQL Database : Sql.Database("server", "dbname", [Query="..."])
        sql_matches = re.findall(r'Sql\.Database\(\s*"([^"]+)"\s*,\s*"([^"]+)"(?:\s*,\s*\[([^\]]*)\])?', m_code, re.IGNORECASE)
        for srv, db, opts in sql_matches:
            q_match = re.search(r'Query\s*=\s*"([^"]+)"', opts or "", re.IGNORECASE)
            query_val = q_match.group(1) if q_match else None
            discovered.append(
                DataSource(
                    name=f"Base SQL — {db}",
                    kind="SQL Database",
                    server=srv,
                    database=db,
                    query=query_val,
                    connection_string=f"Server={srv};Database={db}",
                    description=f"Source relationnelle SQL extraite du script Power Query M ({db})",
                )
            )

        # 2. Excel / File.Contents : Excel.Workbook(File.Contents("filepath"), ...)
        excel_matches = re.findall(r'(?:Excel\.Workbook|Csv\.Document)\s*\(\s*File\.Contents\(\s*"([^"]+)"\s*\)', m_code, re.IGNORECASE)
        for fpath in excel_matches:
            fname = Path(fpath).name
            discovered.append(
                DataSource(
                    name=f"Fichier — {fname}",
                    kind="Excel / Fichier tabulaire",
                    connection_string=fpath,
                    description=f"Source de données fichier chargée via Power Query M ({fpath})",
                )
            )

        # 3. Oracle Database : Oracle.Database("server", ...)
        ora_matches = re.findall(r'Oracle\.Database\(\s*"([^"]+)"', m_code, re.IGNORECASE)
        for srv in ora_matches:
            discovered.append(
                DataSource(
                    name=f"Base Oracle — {srv}",
                    kind="Oracle Database",
                    server=srv,
                    description=f"Source Oracle extraite du script Power Query M ({srv})",
                )
            )

        # 4. OData Feed : OData.Feed("url", ...)
        odata_matches = re.findall(r'OData\.Feed\(\s*"([^"]+)"', m_code, re.IGNORECASE)
        for url in odata_matches:
            discovered.append(
                DataSource(
                    name="Flux OData",
                    kind="OData Feed",
                    connection_string=url,
                    description="Flux de données OData externe",
                )
            )

        return discovered

    def _extract_m_from_zip_schema(self) -> dict[str, dict[str, Any]]:
        """Ouvre l'archive .pbix pour lire DataModelSchema (JSON) si présent."""
        results: dict[str, dict[str, Any]] = {}
        try:
            with zipfile.ZipFile(self.pbix_path, "r") as z:
                schema_name = None
                for name in z.namelist():
                    if name.lower() in ("datamodelschema", "datamodelschema.json"):
                        schema_name = name
                        break
                if not schema_name:
                    return results

                raw_bytes = z.read(schema_name)
                if raw_bytes.startswith(b"\xff\xfe") or raw_bytes.startswith(b"\xfe\xff"):
                    text = raw_bytes.decode("utf-16le", errors="ignore")
                else:
                    text = raw_bytes.decode("utf-8", errors="ignore")

                schema_json = json.loads(text)
                model = schema_json.get("model", {})
                for tbl in model.get("tables", []):
                    t_name = tbl.get("name")
                    if not t_name:
                        continue
                    m_expr = None
                    for part in tbl.get("partitions", []):
                        src = part.get("source", {})
                        expr = src.get("expression")
                        if isinstance(expr, list):
                            m_expr = "\n".join(expr)
                        elif isinstance(expr, str):
                            m_expr = expr
                        if m_expr:
                            break
                    if m_expr:
                        results[t_name] = {
                            "name": t_name,
                            "expression": m_expr,
                            "steps": self._parse_m_steps(m_expr),
                        }
        except Exception as exc:
            LOGGER.debug("Lecture DataModelSchema depuis ZIP non effectuée : %s", exc)
        return results

    @staticmethod
    def _parse_m_steps(m_code: str) -> list[str]:
        """Extrait les noms d'étapes d'une expression Power Query M."""
        if not m_code:
            return []
        steps: list[str] = []
        for line in m_code.splitlines():
            line = line.strip()
            m = re.match(r'^(#"[^"]+"|[A-Za-z0-9_]+)\s*=', line)
            if m:
                step = m.group(1).strip('#"')
                if step not in steps:
                    steps.append(step)
        return steps

    def _build_sources_payload(
        self, connections: list[dict[str, Any]], datasources_df: pd.DataFrame
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        payload.extend(connections)
        if not datasources_df.empty:
            payload.extend(self._to_records(datasources_df))
        return payload

    def _connection_to_source(self, connection: dict[str, Any], index: int) -> DataSource:
        return DataSource(
            name=self._as_str(connection.get("Name")) or f"Connection {index}",
            kind=self._as_str(connection.get("Kind")) or self._as_str(connection.get("Provider")),
            connection_string=self._as_str(connection.get("ConnectionString")) or self._as_str(connection.get("Server")),
            server=self._as_str(connection.get("Server")) or self._as_str(connection.get("DataSource")),
            database=self._as_str(connection.get("Database")) or self._as_str(connection.get("InitialCatalog")),
            provider=self._as_str(connection.get("Provider")),
            query=self._as_str(connection.get("Query")) or self._as_str(connection.get("QueryDefinition")),
            description=self._as_str(connection.get("Description")),
            raw=dict(connection),
        )

    def _find_source_query(self, model: Any, table_name: str) -> str | None:
        # 1. Vérifier les requêtes Power Query (M) dans mashup_queries
        mq_df = self._get_dataframe(model, "mashup_queries")
        if not mq_df.empty:
            name_col = "Name" if "Name" in mq_df.columns else ("TableName" if "TableName" in mq_df.columns else None)
            if name_col:
                matched = mq_df[mq_df[name_col] == table_name]
                if not matched.empty and "Expression" in matched.columns:
                    val = matched.iloc[0]["Expression"]
                    if val is not None and str(val).strip():
                        return str(val).strip()

        # 2. Vérifier les DAX tables ou power_query
        for attribute_name in ("power_query", "dax_tables"):
            data_frame = self._get_dataframe(model, attribute_name)
            if data_frame.empty or "TableName" not in data_frame.columns:
                continue
            rows = data_frame[data_frame["TableName"] == table_name]
            if rows.empty:
                continue
            for column_name in ("QueryDefinition", "Expression", "Source", "Definition"):
                if column_name in rows.columns:
                    value = rows.iloc[0].get(column_name)
                    if value is not None and value != "":
                        return self._as_str(value)

        # 3. Fallback : extraction depuis DataModelSchema dans le ZIP
        zip_queries = self._extract_m_from_zip_schema()
        if table_name in zip_queries:
            return zip_queries[table_name].get("expression")

        return None

    # ---------- helpers ----------

    def _get_dataframe(self, model: Any, attribute_name: str) -> pd.DataFrame:
        try:
            value = getattr(model, attribute_name)
        except Exception:
            return pd.DataFrame()
        return value if isinstance(value, pd.DataFrame) else pd.DataFrame()

    def _get_dataframe_from_source(self, model: Any, attribute_name: str) -> pd.DataFrame:
        source = getattr(getattr(model, "_metadata", None), "source", None)
        if source is None:
            return pd.DataFrame()
        try:
            value = getattr(source, attribute_name)
        except Exception:
            return pd.DataFrame()
        return value if isinstance(value, pd.DataFrame) else pd.DataFrame()

    def _build_table_records(self, schema_df: pd.DataFrame) -> list[dict[str, Any]]:
        if schema_df.empty or "TableName" not in schema_df.columns:
            return []
        table_records: list[dict[str, Any]] = []
        for table_name, group in schema_df.groupby("TableName", dropna=False):
            if not table_name:
                continue
            table_records.append({"Name": table_name, "ColumnCount": int(len(group))})
        return table_records

    def _to_records(self, data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, pd.DataFrame):
            return [] if data.empty else [self._to_dict(row) for _, row in data.iterrows()]
        if isinstance(data, list):
            records: list[dict[str, Any]] = []
            for item in data:
                if isinstance(item, dict):
                    records.append({key: self._normalize_value(value) for key, value in item.items()})
                else:
                    records.append({"value": self._normalize_value(item)})
            return records
        if isinstance(data, dict):
            return [{key: self._normalize_value(value) for key, value in data.items()}]
        return [{"value": self._normalize_value(data)}]

    def _to_dict(self, row: pd.Series) -> dict[str, Any]:
        return {key: self._normalize_value(value) for key, value in row.to_dict().items()}

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [self._normalize_value(item) for item in value]
        if isinstance(value, dict):
            return {k: self._normalize_value(v) for k, v in value.items()}
        if value is None:
            return None
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        try:
            if bool(pd.isna(value)):
                return None
        except Exception:
            pass
        return value

    def _as_str(self, value: Any) -> str | None:
        normalized = self._normalize_value(value)
        return None if normalized is None else str(normalized)

    def _as_bool(self, value: Any) -> bool | None:
        normalized = self._normalize_value(value)
        if normalized is None:
            return None
        if isinstance(normalized, str):
            lowered = normalized.strip().lower()
            if lowered in {"true", "1", "yes", "y"}:
                return True
            if lowered in {"false", "0", "no", "n"}:
                return False
        return bool(normalized)

    def _as_int(self, value: Any) -> int | None:
        normalized = self._normalize_value(value)
        if normalized is None:
            return None
        try:
            return int(normalized)
        except (TypeError, ValueError):
            return None

    def _as_datetime(self, value: Any):
        normalized = self._normalize_value(value)
        if normalized is None:
            return None
        if isinstance(normalized, str):
            try:
                return pd.Timestamp(normalized).to_pydatetime()
            except Exception:
                return None
        return normalized

