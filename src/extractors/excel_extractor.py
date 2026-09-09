"""Extracteur de métadonnées et données à partir de fichiers Excel (.xlsx, .xls, .xlsm, .csv)."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..models.column import Column
from ..models.table import LayerEnum, Table, infer_layer

LOGGER = logging.getLogger(__name__)


def _clean_str(val: Any) -> str:
    if val is None or pd.isna(val):
        return ""
    return str(val).strip()


class ExcelExtractor:
    """Extrait les tables, schémas, dictionnaires de données et règles de mapping d'un fichier Excel."""

    def __init__(self, excel_path: str | Path) -> None:
        self.excel_path = Path(excel_path)
        self._raw_metadata: dict[str, Any] | None = None

    @property
    def raw_metadata(self) -> dict[str, Any] | None:
        return self._raw_metadata

    def extract(self) -> tuple[list[Table], dict[str, Any]]:
        """Extrait les tables et les métadonnées brutes du fichier Excel.

        Returns:
            Tuple (tables, raw_metadata).
        """
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Fichier Excel introuvable : {self.excel_path}")

        LOGGER.info("Extraction Excel depuis %s", self.excel_path)
        sheet_dict = self._read_sheets(self.excel_path)

        tables: list[Table] = []
        raw_tables: list[dict[str, Any]] = []
        raw_mappings: list[dict[str, Any]] = []
        raw_sheets_info: list[dict[str, Any]] = []

        for sheet_name, df in sheet_dict.items():
            if df.empty:
                continue

            sheet_info = {
                "sheet_name": sheet_name,
                "row_count": len(df),
                "col_count": len(df.columns),
            }

            # Tenter de détecter s'il s'agit d'une feuille de Spécification / Mapping / Dictionnaire
            is_mapping_sheet, mappings = self._try_parse_mapping_sheet(sheet_name, df)
            if is_mapping_sheet:
                raw_mappings.extend(mappings)
                sheet_info["type"] = "mapping_specification"
                sheet_info["extracted_mappings_count"] = len(mappings)
                raw_sheets_info.append(sheet_info)
                continue

            # Sinon, traiter comme une table de données (Données ou Dictionnaire)
            table_obj, table_meta = self._parse_data_sheet(sheet_name, df)
            tables.append(table_obj)
            raw_tables.append(table_meta)
            sheet_info["type"] = "data_table"
            sheet_info["table_name"] = table_obj.name
            sheet_info["column_count"] = len(table_obj.columns)
            raw_sheets_info.append(sheet_info)

        raw_metadata: dict[str, Any] = {
            "source_file": str(self.excel_path),
            "file_name": self.excel_path.name,
            "sheets": raw_sheets_info,
            "tables": raw_tables,
            "mappings": raw_mappings,
            "summary": {
                "total_sheets": len(sheet_dict),
                "data_tables_count": len(tables),
                "mappings_count": len(raw_mappings),
            },
        }

        self._raw_metadata = raw_metadata
        return tables, raw_metadata

    def _read_sheets(self, path: Path) -> dict[str, pd.DataFrame]:
        """Lit toutes les feuilles d'un fichier Excel ou CSV en un dictionnaire {sheet_name: DataFrame}."""
        suffix = path.suffix.lower()
        sheet_dict: dict[str, pd.DataFrame] = {}

        if suffix in {".csv", ".txt"}:
            try:
                # Tenter différents délimiteurs courants
                for sep in [";", ",", "\t", "|"]:
                    try:
                        df = pd.read_csv(path, sep=sep, nrows=10, encoding="utf-8-sig")
                        if len(df.columns) > 1:
                            df_full = pd.read_csv(path, sep=sep, encoding="utf-8-sig")
                            sheet_dict[path.stem] = df_full
                            break
                    except Exception:
                        continue
                if not sheet_dict:
                    df = pd.read_csv(path, encoding="utf-8-sig")
                    sheet_dict[path.stem] = df
            except Exception as exc:
                LOGGER.warning("Erreur lors de la lecture du fichier CSV %s : %s", path.name, exc)
        else:
            try:
                with pd.ExcelFile(path) as excel_file:
                    for sheet in excel_file.sheet_names:
                        try:
                            df = pd.read_excel(excel_file, sheet_name=sheet)
                            sheet_dict[sheet] = df
                        except Exception as exc:
                            LOGGER.warning("Impossible de lire la feuille '%s' dans %s : %s", sheet, path.name, exc)
            except Exception as exc:
                LOGGER.error("Erreur lors de l'ouverture du fichier Excel %s : %s", path.name, exc)

        return sheet_dict

    def _try_parse_mapping_sheet(
        self, sheet_name: str, df: pd.DataFrame
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Détecte et extrait les règles de mapping d'une feuille de spécification."""
        cols_lower = [str(c).strip().lower() for c in df.columns]

        # Détecteurs d'en-tête
        src_tbl_kw = ["source_table", "table_source", "src_table", "table source", "source table"]
        src_col_kw = ["source_column", "colonne_source", "src_col", "champ_source", "colonne source"]
        tgt_tbl_kw = ["target_table", "table_cible", "tgt_table", "table_dest", "table cible", "target table"]
        tgt_col_kw = ["target_column", "colonne_cible", "tgt_col", "champ_cible", "colonne cible"]
        rule_kw = ["transformation", "regle", "rule", "expression", "formule", "calcul", "règle"]

        src_tbl_idx = self._find_col_index(cols_lower, src_tbl_kw)
        src_col_idx = self._find_col_index(cols_lower, src_col_kw)
        tgt_tbl_idx = self._find_col_index(cols_lower, tgt_tbl_kw)
        tgt_col_idx = self._find_col_index(cols_lower, tgt_col_kw)

        # Si on a au moins une colonne source et une colonne cible (ou table cible), c'est une feuille de mapping
        has_mapping_headers = (
            (src_col_idx is not None or src_tbl_idx is not None)
            and (tgt_col_idx is not None or tgt_tbl_idx is not None)
        )

        if not has_mapping_headers:
            return False, []

        rule_idx = self._find_col_index(cols_lower, rule_kw)
        desc_idx = self._find_col_index(cols_lower, ["description", "comment", "commentaire", "note"])

        mappings: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            src_t = _clean_str(row.iloc[src_tbl_idx]) if src_tbl_idx is not None else ""
            src_c = _clean_str(row.iloc[src_col_idx]) if src_col_idx is not None else ""
            tgt_t = _clean_str(row.iloc[tgt_tbl_idx]) if tgt_tbl_idx is not None else ""
            tgt_c = _clean_str(row.iloc[tgt_col_idx]) if tgt_col_idx is not None else ""
            rule = _clean_str(row.iloc[rule_idx]) if rule_idx is not None else None
            comment = _clean_str(row.iloc[desc_idx]) if desc_idx is not None else None

            if src_c or tgt_c:
                mappings.append({
                    "source_table": src_t or "SRC_EXCEL",
                    "source_column": src_c or "N/A",
                    "target_table": tgt_t or "DWH_EXCEL",
                    "target_column": tgt_c or "N/A",
                    "transformation_rule": rule or "DIRECT_MAPPING",
                    "comment": comment,
                    "origin_file": self.excel_path.name,
                    "origin_sheet": sheet_name,
                })

        return True, mappings

    def _parse_data_sheet(self, sheet_name: str, df: pd.DataFrame) -> tuple[Table, dict[str, Any]]:
        """Parse une feuille de données classique et génère l'objet Table et ses métadonnées."""
        table_name = self._sanitize_name(sheet_name)
        if table_name.lower() in {"sheet1", "feuil1", "table1"}:
            table_name = f"{self.excel_path.stem}_{table_name}"

        layer = infer_layer(table_name)
        columns: list[Column] = []
        col_metas: list[dict[str, Any]] = []

        total_rows = len(df)

        for col_name_raw in df.columns:
            col_name = str(col_name_raw).strip()
            series = df[col_name_raw]

            inferred_type = self._infer_python_data_type(series)
            null_count = int(series.isna().sum())
            distinct_count = int(series.nunique(dropna=True))

            # Inférence clé primaire
            col_name_lower = col_name.lower()
            is_pk = (
                col_name_lower.endswith("_id")
                or col_name_lower.endswith("_key")
                or col_name_lower.endswith("_code")
                or col_name_lower in {"id", "key", "code"}
                or (distinct_count == total_rows and total_rows > 0 and null_count == 0)
            )

            # Échantillons
            sample_vals = [
                str(v) for v in series.dropna().unique()[:3]
                if str(v).strip() != ""
            ]

            col_obj = Column(
                name=col_name,
                data_type=inferred_type,
                description=f"Colonne extraite de la feuille Excel '{sheet_name}'. Ex: {', '.join(sample_vals)}" if sample_vals else None,
                is_key=is_pk,
                is_nullable=(null_count > 0),
            )
            columns.append(col_obj)

            col_metas.append({
                "name": col_name,
                "data_type": inferred_type,
                "is_primary_key": is_pk,
                "null_count": null_count,
                "distinct_count": distinct_count,
                "sample_values": sample_vals,
            })

        table_obj = Table(
            name=table_name,
            columns=columns,
            description=f"Table issue de la feuille Excel '{sheet_name}' ({total_rows} lignes, {len(columns)} colonnes).",
            layer=layer,
        )

        table_meta = {
            "name": table_name,
            "sheet_name": sheet_name,
            "full_name": table_name,
            "layer": layer.value if hasattr(layer, "value") else str(layer),
            "row_count": total_rows,
            "columns": col_metas,
            "source_file": self.excel_path.name,
        }

        return table_obj, table_meta

    @staticmethod
    def _find_col_index(cols_lower: list[str], keywords: list[str]) -> int | None:
        """Trouve l'index de la première colonne correspondant à l'un des mots-clés."""
        for idx, col in enumerate(cols_lower):
            for kw in keywords:
                if kw in col:
                    return idx
        return None

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Nettoie une chaîne pour en faire un identifiant de table valide."""
        clean = re.sub(r"[^\w\-_]", "_", str(name).strip())
        clean = re.sub(r"_+", "_", clean)
        return clean.strip("_")

    @staticmethod
    def _infer_python_data_type(series: pd.Series) -> str:
        """Infert le type de donnée BI à partir d'un Series pandas."""
        non_null = series.dropna()
        if non_null.empty:
            return "VARCHAR(255)"

        dtype_str = str(series.dtype).lower()

        if "int" in dtype_str:
            return "INTEGER"
        if "float" in dtype_str:
            return "DECIMAL(18,2)"
        if "datetime" in dtype_str:
            return "DATETIME"
        if "bool" in dtype_str:
            return "BOOLEAN"

        # Analyse empirique sur le contenu non-nul
        sample = non_null.iloc[:50]
        is_numeric = True
        is_int = True
        is_date = True

        for val in sample:
            s_val = str(val).strip()
            if not s_val:
                continue
            if is_numeric:
                try:
                    float(s_val)
                    if "." in s_val:
                        is_int = False
                except ValueError:
                    is_numeric = False
                    is_int = False
            if is_date:
                if len(s_val) < 8 or not re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}", s_val):
                    is_date = False

        if is_numeric and is_int:
            return "INTEGER"
        if is_numeric:
            return "DECIMAL(18,2)"
        if is_date:
            return "DATETIME"
        return "VARCHAR(255)"
