from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    # pyrefly: ignore [missing-import]
    import sqlglot
    # pyrefly: ignore [missing-import]
    import sqlglot.expressions as exp
    logging.getLogger("sqlglot").setLevel(logging.CRITICAL)
    _SQLGLOT_AVAILABLE = True
except ImportError:
    _SQLGLOT_AVAILABLE = False


LOGGER = logging.getLogger(__name__)

from src.models.table import FunctionalRoleEnum, LayerEnum


# ---------------------------------------------------------------------------
# Data-classes résultats
# ---------------------------------------------------------------------------

@dataclass
class SQLColumnMeta:
    """Métadonnées d'une colonne extraite d'un script SQL."""

    name: str
    data_type: str | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    description: str | None = None
    transformation: str | None = None
    comment: str | None = None
    role: str | None = None


@dataclass
class SQLTableMeta:
    """Métadonnées d'une table extraite d'un script SQL."""

    name: str
    schema: str | None = None
    full_name: str = ""
    columns: list[SQLColumnMeta] = field(default_factory=list)
    description: str | None = None
    layer: str = "UNKNOWN"  # STG, DWH, SRC, LOG…
    functional_role: str = "UNKNOWN"  # FACT, DIM, AUDIT, SYSTEM, CONFIG


@dataclass
class MappingRule:
    """Règle de mapping source → cible extraite de l'AST."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    transformation_rule: str | None = None
    comment: str | None = None


@dataclass
class ETLStep:
    """Étape d'un package ETL."""

    name: str
    description: str
    sql_fragment: str | None = None


@dataclass
class ETLPackageMeta:
    """Métadonnées d'un package ETL issu d'un script SQL."""

    name: str
    source_file: str
    description: str | None = None
    source_tables: list[SQLTableMeta] = field(default_factory=list)
    target_tables: list[SQLTableMeta] = field(default_factory=list)
    mappings: list[MappingRule] = field(default_factory=list)
    steps: list[ETLStep] = field(default_factory=list)
    schedule: str | None = None
    raw_sql: str = ""


# ---------------------------------------------------------------------------
# Helpers d'exclusion et d'inférence
# ---------------------------------------------------------------------------

_RESERVED_SKIP_NAMES = {
    # Mots-clés SQL standard
    "DUAL", "INSERTED", "DELETED", "SELECT", "WHERE", "SET",
    "VALUES", "ON", "AND", "OR", "NOT", "NULL", "AS", "INTO",
    "FROM", "JOIN", "USING", "WHEN", "MATCHED", "THEN", "MERGE",
    "UPDATE", "INSERT", "DELETE", "WITH", "TABLE", "VIEW",
    "INDEX", "SEQUENCE", "TRIGGER", "PROCEDURE", "FUNCTION",
    "ROWTYPE", "ROWNUM", "ROWID", "SYSDATE", "SYSTIMESTAMP",
    "BEGIN", "END", "DECLARE", "IF", "ELSE", "RETURN", "LOOP",
    "CURSOR", "FETCH", "OPEN", "CLOSE", "COMMIT", "ROLLBACK",
    # Aliases MERGE très courants
    "TARGET", "SOURCE", "SRC", "TGT", "NEW", "OLD",
    "T", "S", "A", "B", "C", "D", "E", "F", "G", "H",
    "SI", "TI", "CI", "SD", "SC",  # alias courts Oracle/SQL Server
    # Noms génériques
    "TEMP", "TMP", "NOCOUNT", "OBJECT",
    # Mots français courants dans les commentaires SQL mal parsés
    "DANS", "POUR", "AVEC", "SANS", "SUR", "PAR", "LES", "DES",
    "UNE", "UN", "EST", "ARE", "THE", "AND", "ALL", "ANY",
    # Types de données (parfois confondus avec des tables)
    "INT", "DATE", "TIME", "CHAR", "TEXT", "JSON", "XML",
    "BIGINT", "FLOAT", "REAL", "BOOL", "BOOLEAN",
}


def _is_valid_table_name(name: str) -> bool:
    """Vérifie qu'un nom est un nom de table plausible (pas un mot-clé, variable, alias).

    Critères :
      - Longueur minimale de 3 caractères (ignorer les alias 1-2 lettres)
      - Pas dans la liste de mots réservés
      - Contient au moins une lettre majuscule (convention SQL)
      - Si c'est un nom court (< 5 chars), il doit contenir un underscore ou chiffre
    """
    if not name:
        return False
    basename = name.split(".")[-1].strip()

    if len(basename) < 3:
        return False
    if basename.upper() in _RESERVED_SKIP_NAMES:
        return False
    # Noms très courts (3-4 chars) sans underscore ni chiffre → probablement un alias
    if len(basename) < 5 and not re.search(r"[_0-9]", basename):
        return False
    # Commencer par un chiffre → invalide
    if re.match(r"^\d", basename):
        return False
    return True


def _auto_detect_dialect(raw_sql: str) -> str:
    """Détecte automatiquement le dialecte SQL à partir du contenu du script.

    Priorité : T-SQL > Snowflake > Spark > Oracle (défaut).
    Utilisé quand le dialecte n'est pas explicitement forcé par l'utilisateur.
    """
    upper = raw_sql[:4000].upper()  # Analyser seulement le début

    # Indicateurs T-SQL (SQL Server, Azure SQL)
    tsql_signals = (
        "SET NOCOUNT" in upper
        or "[DBO]." in upper
        or "HASHBYTES" in upper
        or "CONCAT_WS" in upper
        or "IDENTITY(" in upper
        or "NVARCHAR" in upper
        or "TOP " in upper
        or "NOLOCK" in upper
        or re.search(r"\[\w+\]\.\[\w+\]", raw_sql[:4000])
    )
    if tsql_signals:
        LOGGER.debug("_auto_detect_dialect: T-SQL détecté")
        return "tsql"

    # Indicateurs Snowflake
    snowflake_signals = (
        "QUALIFY " in upper
        or "FLATTEN(" in upper
        or "COPY INTO" in upper
        or "FILE_FORMAT" in upper
    )
    if snowflake_signals:
        LOGGER.debug("_auto_detect_dialect: Snowflake détecté")
        return "snowflake"

    # Indicateurs Spark/Databricks
    spark_signals = (
        "USING DELTA" in upper
        or "TBLPROPERTIES" in upper
        or "DBUTILS" in upper
    )
    if spark_signals:
        LOGGER.debug("_auto_detect_dialect: Spark détecté")
        return "spark"

    # Défaut : Oracle
    LOGGER.debug("_auto_detect_dialect: Oracle (défaut)")
    return "oracle"


def _is_plsql_variable(name: str) -> bool:
    """Vérifie si un identifiant est une variable PL/SQL (ex: v_total_after) à ignorer impérativement.

    Toute table ou identifiant commençant par 'v_' (ex: v_total_after, v_inserted, v_updated)
    est traité comme une variable PL/SQL et exclu du dictionnaire des tables.
    """
    if not name:
        return True
    basename = name.split(".")[-1].strip().lower()
    if basename.startswith("v_"):
        return True
    return False


def _detect_layer(table_name: str, context_is_target: bool = False) -> str:
    """Détermine la couche BI (STG, DWH, LOG, SRC) de manière contextuelle."""
    upper = table_name.upper()

    if "DUAL" in upper:
        return "SRC"
    if "LOG_" in upper or "LOG" in upper:
        return "LOG"

    if context_is_target:
        if "STG_" in upper or "STAGING" in upper:
            return "STG"
        return "DWH"

    if "STG_" in upper or "STAGING" in upper:
        return "STG"
    if "DWH_" in upper or "DW_" in upper:
        return "DWH"

    return "DWH" if context_is_target else "STG"


def _full_table_name(node: exp.Table) -> str:
    """Reconstruit le nom complet (schema.table) d'un nœud Table sqlglot."""
    parts = [p for p in (node.catalog, node.db, node.name) if p]
    return ".".join(parts) if parts else node.name or ""


def _infer_sql_data_type(column_name: str, transformation: str | None = None) -> str:
    """Infère le type SQL de donnée d'une colonne depuis son nom et sa transformation AST."""
    if transformation:
        trans_upper = transformation.upper()
        if "TO_DATE" in trans_upper or "SYSDATE" in trans_upper:
            return "DATE"
        if "TO_CHAR" in trans_upper:
            return "VARCHAR2(255)"
        if "CAST(" in trans_upper and "NUMBER" in trans_upper:
            return "NUMBER"
        if "CAST(" in trans_upper and "VARCHAR" in trans_upper:
            return "VARCHAR2(255)"
        if "ROUND(" in trans_upper or "COUNT(" in trans_upper or "SUM(" in trans_upper:
            return "NUMBER"

    name_upper = column_name.upper()
    if any(kw in name_upper for kw in ("DATE", "DT", "TIME", "TIMESTAMP")):
        return "DATE"
    if any(kw in name_upper for kw in ("ID", "COUNT", "NBR", "NUM", "QTY", "AMOUNT", "RANK", "LEVEL", "AMT")):
        return "NUMBER"
    return "VARCHAR2(255)"


class RoleInferrer:
    """Infère le rôle fonctionnel d'une table BI (FACT, DIM, AUDIT, SYSTEM, CONFIG, UNKNOWN)."""

    @staticmethod
    def infer_role(
        table_name: str,
        columns: list[SQLColumnMeta],
        layer: str = "UNKNOWN",
        fk_count: int | None = None,
    ) -> str:
        """Détermine le rôle fonctionnel selon l'analyse contextuelle.

        Args:
            table_name: Nom complet ou court de la table.
            columns: Colonnes de la table.
            layer: Couche BI (STG, DWH, LOG, SRC).
            fk_count: Nombre de clés étrangères détectées.

        Returns:
            Libellé du rôle fonctionnel.
        """
        upper_name = table_name.upper()

        if "DUAL" in upper_name:
            return "SYSTEM"

        if "LOG" in upper_name or "HISTORY" in upper_name or "AUDIT" in upper_name or layer == "LOG":
            return "AUDIT"

        numeric_count = sum(
            1
            for c in columns
            if (c.data_type and any(t in c.data_type.upper() for t in ("NUMBER", "FLOAT", "DECIMAL", "INT", "DOUBLE")))
            or any(kw in c.name.upper() for kw in ("AMT", "AMOUNT", "QTY", "QUANTITY", "NBR", "COUNT", "LEVEL", "RANK", "OK"))
        )

        if numeric_count >= 2 or "SKILLS" in upper_name:
            return "FACT"

        if layer == "STG":
            return "Staging (données brutes)"

        if layer == "DWH":
            if numeric_count >= 1:
                return "FACT"
            return "DIM"

        return "FACT" if numeric_count >= 1 else "DIM"


# ---------------------------------------------------------------------------
# OracleMergeVisitor – AST Visitor pour MERGE Oracle
# ---------------------------------------------------------------------------

class OracleMergeVisitor:
    """Visite l'AST d'un MERGE Oracle et extrait les mappings réels."""

    def __init__(self, dialect: str = "oracle") -> None:
        self.dialect = dialect

    def visit(self, merge_node: exp.Merge) -> list[MappingRule]:
        """Extrait les règles de mapping depuis un nœud MERGE sqlglot."""
        # -- Table cible --
        target_table = self._resolve_table(merge_node.this)
        if not target_table or _is_plsql_variable(target_table):
            LOGGER.warning("OracleMergeVisitor: table cible ignorée ou non valide.")
            return []

        LOGGER.debug("OracleMergeVisitor: table cible = %s", target_table)

        # -- Clause USING --
        using_node = merge_node.args.get("using")
        if using_node is None:
            LOGGER.warning("OracleMergeVisitor: clause USING absente.")
            return []

        select_node = self._unwrap_select(using_node)
        on_keys = self._extract_on_clause_columns(merge_node)

        if select_node is None:
            # Fallback pour MERGE sans sous-requête directe dans USING (ex: USING source_dedup AS src)
            # 1. Résoudre la source depuis using_node
            tbl_node = next(iter(using_node.find_all(exp.Table)), None)
            source_table = (_full_table_name(tbl_node) or tbl_node.name) if tbl_node else "<SOURCE>"
            if _is_plsql_variable(source_table) or not _is_valid_table_name(source_table):
                source_table = "<SOURCE>"

            mappings: list[MappingRule] = []
            seen_targets: set[str] = set()

            # 2. Extraire les colonnes depuis les clauses WHEN MATCHED (UPDATE SET)
            for when in merge_node.args.get("whens", []) or []:
                for eq in when.find_all(exp.EQ):
                    tgt_col_node = eq.this
                    src_expr_node = eq.expression
                    if tgt_col_node and src_expr_node:
                        tgt_col = tgt_col_node.name if isinstance(tgt_col_node, exp.Column) else str(tgt_col_node).split(".")[-1]
                        if not tgt_col or tgt_col.upper() in _RESERVED_SKIP_NAMES:
                            continue
                        if tgt_col.upper() in seen_targets:
                            continue
                        seen_targets.add(tgt_col.upper())
                        src_col = self._guess_source_col(src_expr_node) or tgt_col
                        raw_transf = src_expr_node.sql(dialect=self.dialect).strip()
                        # Normaliser la transformation
                        if raw_transf.upper() in (src_col.upper(), f"SRC.{src_col.upper()}", f"SOURCE.{src_col.upper()}", f"S.{src_col.upper()}", f"SD.{src_col.upper()}"):
                            transf = "Aucune (copie directe)"
                        else:
                            transf = raw_transf
                        is_pk = tgt_col.upper() in on_keys
                        pk_note = " [Upsert Key – Clé de la clause MERGE ON]" if is_pk else ""
                        mappings.append(
                            MappingRule(
                                source_table=source_table,
                                source_column=src_col,
                                target_table=target_table,
                                target_column=tgt_col,
                                transformation_rule=transf,
                                comment=(self._describe_transformation(transf) or "") + pk_note,
                            )
                        )

            # 3. Extraire depuis WHEN NOT MATCHED (INSERT) si UPDATE SET était vide
            if not mappings:
                insert_cols = self._extract_insert_columns(merge_node)
                for tgt_col in insert_cols:
                    if tgt_col.upper() not in seen_targets and tgt_col.upper() not in _RESERVED_SKIP_NAMES:
                        seen_targets.add(tgt_col.upper())
                        is_pk = tgt_col.upper() in on_keys
                        pk_note = " [Upsert Key – Clé de la clause MERGE ON]" if is_pk else ""
                        mappings.append(
                            MappingRule(
                                source_table=source_table,
                                source_column=tgt_col,
                                target_table=target_table,
                                target_column=tgt_col,
                                transformation_rule="Aucune (copie directe)",
                                comment="Insertion directe" + pk_note,
                            )
                        )

            LOGGER.info(
                "OracleMergeVisitor: %d règles de mapping extraites via UPDATE/INSERT clauses (%s → %s)",
                len(mappings), source_table, target_table,
            )
            return mappings

        # -- Table source si select_node existe --
        source_table = self._extract_source_table(select_node)
        LOGGER.debug("OracleMergeVisitor: table source = %s", source_table or "<inconnue>")

        # -- Projections du SELECT --
        col_map = self._extract_projections(select_node)
        LOGGER.debug("OracleMergeVisitor: %d projections extraites", len(col_map))

        # -- Ordre des colonnes INSERT (WHEN NOT MATCHED) --
        insert_cols = self._extract_insert_columns(merge_node)
        LOGGER.debug("OracleMergeVisitor: %d colonnes INSERT trouvées", len(insert_cols))
        LOGGER.debug("OracleMergeVisitor: clés ON extraites = %s", on_keys)

        mappings: list[MappingRule] = []

        if insert_cols:
            for target_col in insert_cols:
                alias_key = target_col.upper()
                entry = col_map.get(alias_key) or col_map.get(target_col.upper())
                is_pk = alias_key in on_keys

                if entry:
                    src_col, transformation = entry
                    transf_rule = "Paramètre d'exécution ETL" if (src_col == "Paramètre d'exécution" or transformation == "Paramètre d'exécution ETL" or (transformation and "?" in transformation)) else transformation
                    base_comment = self._describe_transformation(transformation)
                    pk_note = " [Upsert Key – Clé de la clause MERGE ON]" if is_pk else ""
                    mappings.append(
                        MappingRule(
                            source_table=source_table or "<SOURCE>",
                            source_column=src_col,
                            target_table=target_table,
                            target_column=target_col,
                            transformation_rule=transf_rule,
                            comment=(base_comment or "") + pk_note,
                        )
                    )
                else:
                    pk_note = " [Upsert Key – Clé de la clause MERGE ON]" if is_pk else ""
                    mappings.append(
                        MappingRule(
                            source_table=source_table or "<SOURCE>",
                            source_column=target_col,
                            target_table=target_table,
                            target_column=target_col,
                            transformation_rule="Aucune (copie directe)",
                            comment="Aucune transformation détectée" + pk_note,
                        )
                    )
        else:
            for alias, (src_col, transformation) in col_map.items():
                is_pk = alias in on_keys
                transf_rule = "Paramètre d'exécution ETL" if (src_col == "Paramètre d'exécution" or transformation == "Paramètre d'exécution ETL" or (transformation and "?" in transformation)) else transformation
                base_comment = self._describe_transformation(transformation)
                pk_note = " [Upsert Key – Clé de la clause MERGE ON]" if is_pk else ""
                mappings.append(
                    MappingRule(
                        source_table=source_table or "<SOURCE>",
                        source_column=src_col,
                        target_table=target_table,
                        target_column=alias,
                        transformation_rule=transf_rule,
                        comment=(base_comment or "") + pk_note,
                    )
                )

        LOGGER.info(
            "OracleMergeVisitor: %d règles de mapping extraites (%s → %s), %d Upsert Keys",
            len(mappings), source_table or "?", target_table, len(on_keys),
        )
        return mappings


    # ------------------------------------------------------------------
    # Helpers internes
    # ------------------------------------------------------------------

    def _resolve_table(self, node: Any) -> str | None:
        """Retourne le nom complet de la table depuis n'importe quel nœud."""
        if node is None:
            return None
        if isinstance(node, exp.Table):
            name = _full_table_name(node) or node.name or None
            return name if name and not _is_plsql_variable(name) else None
        if isinstance(node, exp.Alias):
            return self._resolve_table(node.this)
        found = next(iter(node.find_all(exp.Table)), None)
        if found:
            name = _full_table_name(found) or found.name or None
            return name if name and not _is_plsql_variable(name) else None
        return None

    def _unwrap_select(self, node: Any) -> exp.Select | None:
        """Extrait un nœud Select depuis un Subquery, Alias ou Select direct."""
        if isinstance(node, exp.Select):
            return node
        if isinstance(node, exp.Subquery):
            return self._unwrap_select(node.this)
        if isinstance(node, exp.Alias):
            return self._unwrap_select(node.this)
        found = next(iter(node.find_all(exp.Select)), None)
        return found

    def _extract_source_table(self, select_node: exp.Select) -> str | None:
        """Retourne le nom de la première table FROM du SELECT."""
        from_clause = select_node.args.get("from")
        if from_clause is None:
            return None
        tbl = next(iter(from_clause.find_all(exp.Table)), None)
        if tbl:
            name = _full_table_name(tbl) or tbl.name or None
            return name if name and not _is_plsql_variable(name) else None
        return None

    def _extract_projections(self, select_node: exp.Select) -> dict[str, tuple[str, str | None]]:
        """Retourne {alias_upper: (source_col_name, transformation_sql_ou_None)}."""
        result: dict[str, tuple[str, str | None]] = {}

        for expr in select_node.expressions:
            alias: str | None = None
            src_col: str | None = None
            transformation: str | None = None

            if isinstance(expr, exp.Alias):
                alias = expr.alias or expr.output_name or ""
                inner = expr.this
                inner_sql = inner.sql(dialect=self.dialect).strip()

                if inner_sql == "?" or isinstance(inner, (exp.Parameter, exp.Placeholder)):
                    src_col = "Paramètre d'exécution"
                    transformation = "Paramètre d'exécution ETL"
                elif isinstance(inner, exp.Column):
                    src_col = inner.name or alias
                    transformation = None
                else:
                    src_col = self._guess_source_col(inner) or alias
                    transformation = inner.sql(dialect=self.dialect)

            elif isinstance(expr, exp.Column):
                alias = expr.name or ""
                src_col = alias
                transformation = None

            elif isinstance(expr, exp.Star):
                continue

            else:
                expr_sql = expr.sql(dialect=self.dialect).strip()
                alias = expr.output_name or ""
                if expr_sql == "?" or isinstance(expr, (exp.Parameter, exp.Placeholder)):
                    src_col = "Paramètre d'exécution"
                    transformation = "Paramètre d'exécution ETL"
                else:
                    src_col = alias
                    transformation = expr_sql

            if alias:
                result[alias.upper()] = (src_col or alias, transformation if transformation else None)

        return result

    def _extract_insert_columns(self, merge_node: exp.Merge) -> list[str]:
        """Extrait les noms de colonnes de la clause WHEN NOT MATCHED THEN INSERT."""
        for when in merge_node.args.get("whens", []) or []:
            for action in when.find_all(exp.Insert):
                schema = action.this if isinstance(action.this, exp.Schema) else None
                if schema:
                    return [
                        col.name
                        for col in schema.expressions
                        if isinstance(col, (exp.Column, exp.Identifier)) and col.name
                    ]
        return []

    def _extract_on_clause_columns(self, merge_node: exp.Merge) -> set[str]:
        """Extrait les colonnes de la clause ON du MERGE (Upsert Keys).

        Ces colonnes sont les clés d'unicité utilisées pour la condition de jointure
        MERGE ON (source.col = target.col). Elles doivent être marquées comme PK/Upsert Key.

        Args:
            merge_node: Noeud MERGE de l'AST sqlglot.

        Returns:
            Ensemble des noms de colonnes utilisées dans la clause ON.
        """
        on_keys: set[str] = set()
        on_clause = merge_node.args.get("on")
        if on_clause is None:
            return on_keys

        for col in on_clause.find_all(exp.Column):
            if col.name:
                on_keys.add(col.name.upper())
                LOGGER.debug("OracleMergeVisitor: clé ON (Upsert Key) détectée : %s", col.name)

        return on_keys

    def _guess_source_col(self, expr: exp.Expression) -> str | None:
        """Tente d'extraire le nom de la colonne principale dans une expression."""
        col = next(iter(expr.find_all(exp.Column)), None)
        return col.name if col else None

    @staticmethod
    def _describe_transformation(sql_expr: str | None) -> str | None:
        """Traduit une expression SQL en description métier lisible."""
        if sql_expr is None:
            return "Aucune transformation (copie directe)"

        s = sql_expr.upper()
        if "?" in s or "PARAMÈTRE" in s or "PARAMETRE" in s:
            return "Valeur injectée par l'orchestrateur ETL (ex: ID_FLOW, timestamp)"
        if "TO_DATE" in s:
            return "Conversion chaîne → DATE"
        if "TO_CHAR" in s:
            return "Conversion → chaîne de caractères"
        if "CAST(" in s or "CONVERT(" in s:
            return "Conversion de type (CAST)"
        if "UPPER(" in s:
            return "Mise en majuscules"
        if "LOWER(" in s:
            return "Mise en minuscules"
        if "TRIM(" in s or "LTRIM(" in s or "RTRIM(" in s:
            return "Suppression des espaces"
        if "COALESCE(" in s or "NVL(" in s or "ISNULL(" in s:
            return "Valeur par défaut si NULL"
        if "CASE WHEN" in s or "DECODE(" in s:
            return "Logique conditionnelle"
        if "SYSDATE" in s or "CURRENT_DATE" in s or "GETDATE()" in s:
            return "Date système (ETL load date)"
        if "ROUND(" in s or "TRUNC(" in s or "FLOOR(" in s or "CEIL(" in s:
            return "Arrondi numérique"
        if "SUM(" in s or "COUNT(" in s or "AVG(" in s:
            return "Agrégation"
        return f"Expression SQL : {sql_expr[:80]}"


# ---------------------------------------------------------------------------
# Regex fallback (PL/SQL DECLARE…BEGIN…END non parsable par sqlglot)
# ---------------------------------------------------------------------------

class _RegexMergeExtractor:
    """Fallback regex pour extraire les MERGE depuis des blocs PL/SQL Oracle."""

    _MERGE_RE = re.compile(
        r"MERGE\s+INTO\s+([\w$.]+(?:\.[\w$.]+)*)\s+\w+\s+USING\s*\(\s*(SELECT[\s\S]+?)\)\s+\w+\s+ON\s*\(",
        re.IGNORECASE,
    )
    _FROM_RE = re.compile(r"\bFROM\s+([\w$.]+(?:\.[\w$.]+)*)", re.IGNORECASE)
    _INSERT_COLS_RE = re.compile(
        r"WHEN\s+NOT\s+MATCHED\s+THEN\s+INSERT\s*\(([\s\S]+?)\)\s*VALUES",
        re.IGNORECASE,
    )

    def extract(self, raw_sql: str, dialect: str = "oracle") -> list[MappingRule]:
        """Extrait les mappings par regex depuis un bloc PL/SQL complet."""
        mappings: list[MappingRule] = []

        for merge_match in self._MERGE_RE.finditer(raw_sql):
            target_table = merge_match.group(1).strip()
            if _is_plsql_variable(target_table):
                continue

            select_body = merge_match.group(2).strip()

            from_match = self._FROM_RE.search(select_body)
            source_table = from_match.group(1).strip() if from_match else "<SOURCE>"
            if _is_plsql_variable(source_table):
                source_table = "<SOURCE>"

            insert_match = self._INSERT_COLS_RE.search(raw_sql)
            insert_cols = []
            if insert_match:
                insert_cols = [c.strip() for c in insert_match.group(1).split(",") if c.strip()]

            col_map = self._parse_select_columns(select_body, dialect)

            if insert_cols and col_map:
                for tgt_col in insert_cols:
                    entry = col_map.get(tgt_col.upper())
                    if entry:
                        src_col, transf = entry
                    else:
                        src_col, transf = tgt_col, None
                    transf_rule = "Paramètre d'exécution ETL" if (src_col == "Paramètre d'exécution" or transf == "Paramètre d'exécution ETL" or (transf and "?" in transf)) else transf
                    mappings.append(
                        MappingRule(
                            source_table=source_table,
                            source_column=src_col,
                            target_table=target_table,
                            target_column=tgt_col,
                            transformation_rule=transf_rule,
                            comment=OracleMergeVisitor._describe_transformation(transf),
                        )
                    )
            elif col_map:
                for alias, (src_col, transf) in col_map.items():
                    transf_rule = "Paramètre d'exécution ETL" if (src_col == "Paramètre d'exécution" or transf == "Paramètre d'exécution ETL" or (transf and "?" in transf)) else transf
                    mappings.append(
                        MappingRule(
                            source_table=source_table,
                            source_column=src_col,
                            target_table=target_table,
                            target_column=alias,
                            transformation_rule=transf_rule,
                            comment=OracleMergeVisitor._describe_transformation(transf),
                        )
                    )

            LOGGER.info(
                "_RegexMergeExtractor: %d mappings extraits (%s → %s)",
                len(mappings), source_table, target_table,
            )

        return mappings

    def _parse_select_columns(
        self, select_body: str, dialect: str
    ) -> dict[str, tuple[str, str | None]]:
        """Parse les colonnes d'un SELECT via sqlglot."""
        try:
            stmt = sqlglot.parse_one(f"SELECT {select_body} FROM dual", dialect=dialect,
                                     error_level=sqlglot.ErrorLevel.WARN)
            if isinstance(stmt, exp.Select):
                visitor = OracleMergeVisitor(dialect=dialect)
                return visitor._extract_projections(stmt)
        except Exception as exc:
            LOGGER.debug("Fallback regex parse_select échoué: %s", exc)

        result: dict[str, tuple[str, str | None]] = {}
        lines = [ln.strip().rstrip(",") for ln in select_body.splitlines() if ln.strip()]
        for line in lines:
            if re.match(r"^(FROM|WHERE|AND|OR|JOIN)\b", line, re.IGNORECASE):
                continue
            as_match = re.search(r"(.+?)\s+(?:AS\s+)?(\w+)\s*$", line, re.IGNORECASE)
            if as_match:
                inner_expr = as_match.group(1).strip()
                alias = as_match.group(2).strip()
                if inner_expr.strip() == "?":
                    result[alias.upper()] = ("Paramètre d'exécution", "Paramètre d'exécution ETL")
                elif re.search(r"[(\)]", inner_expr) or "?" in inner_expr:
                    src_col_match = re.search(r"\b([A-Z_][A-Z0-9_]*)\b", inner_expr, re.IGNORECASE)
                    src_col = src_col_match.group(1) if src_col_match else alias
                    result[alias.upper()] = (src_col, inner_expr)
                else:
                    result[alias.upper()] = (inner_expr, None)
            else:
                col = line.strip().strip(",")
                if col and re.match(r"^[A-Z_][A-Z0-9_]*$", col, re.IGNORECASE):
                    result[col.upper()] = (col, None)

        return result


# ---------------------------------------------------------------------------
# SQLExtractor – orchestrateur principal
# ---------------------------------------------------------------------------

class SQLExtractor:
    """Extrait les métadonnées ETL depuis des scripts SQL Oracle."""

    def __init__(self, dialect: str = "oracle") -> None:
        if not _SQLGLOT_AVAILABLE:
            raise ImportError("sqlglot n'est pas installé. Lancez : pip install sqlglot")
        self.dialect = dialect
        self._visitor = OracleMergeVisitor(dialect=dialect)
        self._regex_extractor = _RegexMergeExtractor()

    # ------------------------------------------------------------------
    # Points d'entrée publics
    # ------------------------------------------------------------------

    def extract_from_file(self, sql_path: str | Path) -> ETLPackageMeta:
        """Extrait les métadonnées ETL d'un fichier SQL avec auto-détection du dialecte."""
        sql_file = Path(sql_path)
        if not sql_file.exists():
            raise FileNotFoundError(f"Fichier SQL introuvable: {sql_file}")

        LOGGER.info("Extraction SQL depuis %s", sql_file)
        raw_sql = sql_file.read_text(encoding="utf-8", errors="replace")

        # Auto-détection du dialecte si non forcé à l'init
        effective_dialect = self.dialect
        if self.dialect == "oracle":
            detected = _auto_detect_dialect(raw_sql)
            if detected != "oracle":
                LOGGER.info(
                    "Dialecte auto-détecté pour '%s' : %s (remplace %s)",
                    sql_file.name, detected, self.dialect,
                )
                effective_dialect = detected

        try:
            return self._parse(raw_sql, str(sql_file), dialect=effective_dialect)
        except Exception as exc:
            LOGGER.exception("Échec de l'analyse SQL: %s", exc)
            raise RuntimeError(f"Impossible de parser {sql_file}: {exc}") from exc

    def extract_from_directory(self, sql_dir: str | Path) -> list[ETLPackageMeta]:
        """Extrait les métadonnées de tous les .sql d'un répertoire."""
        directory = Path(sql_dir)
        packages: list[ETLPackageMeta] = []
        for sql_file in sorted(directory.glob("**/*.sql")):
            try:
                pkg = self.extract_from_file(sql_file)
                packages.append(pkg)
            except Exception as exc:
                LOGGER.warning("Ignoré %s : %s", sql_file, exc)
        return packages

    # ------------------------------------------------------------------
    # Orchestration du parsing
    # ------------------------------------------------------------------

    def _parse(self, raw_sql: str, source_file: str, dialect: str | None = None) -> ETLPackageMeta:
        """Orchestre l'analyse AST + fallback regex d'un bloc SQL."""
        effective_dialect = dialect or self.dialect
        package_name = Path(source_file).stem

        source_tables: dict[str, SQLTableMeta] = {}
        target_tables: dict[str, SQLTableMeta] = {}
        mappings: list[MappingRule] = []
        steps: list[ETLStep] = []

        cte_names: set[str] = set()

        try:
            statements = sqlglot.parse(
                raw_sql, dialect=effective_dialect, error_level=sqlglot.ErrorLevel.WARN
            )
            valid_statements = [s for s in statements if s is not None]

            # 1. Collecter tous les noms de CTEs définis dans les clauses WITH
            for stmt in valid_statements:
                for cte in stmt.find_all(exp.CTE):
                    if cte.alias_or_name:
                        cte_names.add(cte.alias_or_name.upper())
                # Parser également les clauses WITH globales
                with_clause = stmt.args.get("with")
                if with_clause:
                    for cte_expr in with_clause.expressions:
                        if hasattr(cte_expr, "alias_or_name") and cte_expr.alias_or_name:
                            cte_names.add(cte_expr.alias_or_name.upper())

            LOGGER.debug("CTEs virtuelles identifiées pour '%s' : %s", source_file, cte_names)

            for stmt in valid_statements:
                if isinstance(stmt, exp.Merge):
                    self._handle_merge_ast(stmt, source_tables, target_tables, mappings, steps)
                elif isinstance(stmt, exp.Insert):
                    self._handle_insert_ast(stmt, source_tables, target_tables, mappings, steps)
                elif isinstance(stmt, exp.Create):
                    self._handle_create_ast(stmt, source_tables, target_tables)
                elif isinstance(stmt, exp.Select):
                    self._handle_select_ast(stmt, source_tables)
        except Exception as exc:
            LOGGER.warning("Parsing AST partiel ('%s'): %s", source_file, exc)

        if not mappings:
            LOGGER.info("Aucun mapping AST → activation du fallback regex pour '%s'", source_file)
            regex_mappings = self._regex_extractor.extract(raw_sql, dialect=effective_dialect)
            mappings.extend(regex_mappings)

            for m in regex_mappings:
                if m.source_table and m.source_table not in source_tables and not _is_plsql_variable(m.source_table):
                    layer = _detect_layer(m.source_table, context_is_target=False)
                    parts = m.source_table.split(".")
                    source_tables[m.source_table] = SQLTableMeta(
                        name=parts[-1], schema=parts[-2] if len(parts) > 1 else None,
                        full_name=m.source_table, layer=layer,
                    )
                if m.target_table and m.target_table not in target_tables and not _is_plsql_variable(m.target_table):
                    layer = _detect_layer(m.target_table, context_is_target=True)
                    parts = m.target_table.split(".")
                    target_tables[m.target_table] = SQLTableMeta(
                        name=parts[-1], schema=parts[-2] if len(parts) > 1 else None,
                        full_name=m.target_table, layer=layer,
                    )

        self._enrich_tables_from_mappings(mappings, source_tables, target_tables)

        if not source_tables and not target_tables:
            LOGGER.info("Fallback regex tables pour '%s'", source_file)
            self._regex_table_fallback(raw_sql, source_tables, target_tables)

        # Nettoyer rigoureusement toutes les CTEs, variables PL/SQL et tables DWH accidentellement dans source_tables
        tgt_names = {k.upper() for k in target_tables.keys()}
        source_tables = {
            k: v for k, v in source_tables.items()
            if not _is_plsql_variable(k)
            and k.split(".")[-1].upper() not in cte_names
            and k.upper() not in tgt_names
            and _is_valid_table_name(k)
        }
        target_tables = {
            k: v for k, v in target_tables.items()
            if not _is_plsql_variable(k)
            and k.split(".")[-1].upper() not in cte_names
            and _is_valid_table_name(k)
        }

        # Inférence des types de colonnes et des rôles fonctionnels
        for tbl in list(source_tables.values()) + list(target_tables.values()):
            for c in tbl.columns:
                if not c.data_type or c.data_type == "UNKNOWN":
                    c.data_type = _infer_sql_data_type(c.name, c.transformation)
            tbl.functional_role = RoleInferrer.infer_role(tbl.full_name, tbl.columns, layer=tbl.layer)
            LOGGER.info("Inférence table [%s] : layer=%s, role=%s, cols=%d", tbl.full_name, tbl.layer, tbl.functional_role, len(tbl.columns))

        return ETLPackageMeta(
            name=package_name,
            source_file=source_file,
            description=f"Package ETL extrait de {Path(source_file).name}",
            source_tables=list(source_tables.values()),
            target_tables=list(target_tables.values()),
            mappings=mappings,
            steps=steps,
            raw_sql=raw_sql,
        )

    # ------------------------------------------------------------------
    # Handlers AST
    # ------------------------------------------------------------------

    def _handle_merge_ast(
        self,
        stmt: exp.Merge,
        source_tables: dict[str, SQLTableMeta],
        target_tables: dict[str, SQLTableMeta],
        mappings: list[MappingRule],
        steps: list[ETLStep],
    ) -> None:
        """Analyse un MERGE avec l'OracleMergeVisitor.

        Entity Resolution strictée :
        - MERGE INTO → target_tables (layer=DWH)
        - USING (SELECT ... FROM ...) → source_tables (layer=STG)

        Si la table cible était déjà enregistrée dans source_tables avec un mauvais layer,
        elle est migrée vers target_tables et supprimée de source_tables.
        """
        target_name = self._resolve_table_name(stmt.this)
        if target_name and not _is_plsql_variable(target_name):
            # Migration : si la table cible est dans source_tables avec un layer STG/SRC
            # (enregistrée par un SELECT COUNT(*) précédent), la déplacer vers target_tables.
            if target_name in source_tables:
                LOGGER.debug(
                    "_handle_merge_ast : migration '%s' source_tables → target_tables (MERGE INTO)",
                    target_name,
                )
                tgt_meta = source_tables.pop(target_name)
                tgt_meta.layer = "DWH"
                target_tables[target_name] = tgt_meta
            else:
                self._register_table(target_name, target_tables, layer_override="DWH")

        using = stmt.args.get("using")
        if using:
            select_node = self._visitor._unwrap_select(using)
            tbl = next(iter(using.find_all(exp.Table)), None)
            if tbl:
                src_name = _full_table_name(tbl) or tbl.name
                if src_name and not _is_plsql_variable(src_name):
                    stg_meta = self._register_table(src_name, source_tables, layer_override="STG")
                    if stg_meta and select_node:
                        projs = self._visitor._extract_projections(select_node)
                        for alias_key, (src_c, transf) in projs.items():
                            existing = {c.name.upper() for c in stg_meta.columns}
                            display_name = src_c if not src_c.startswith("Paramètre") else alias_key
                            if display_name.upper() not in existing:
                                stg_meta.columns.append(
                                    SQLColumnMeta(name=display_name, transformation=transf)
                                )

            # Propager les colonnes vers la table DWH cible via INSERT columns (priorité) ou alias SELECT
            if target_name and target_name in target_tables and select_node:
                dwh_meta = target_tables[target_name]
                insert_cols = self._visitor._extract_insert_columns(stmt)
                projs = self._visitor._extract_projections(select_node)
                proj_values = list(projs.values())  # liste ordonnée (alias, (src_col, transf))
                existing_dwh = {c.name.upper() for c in dwh_meta.columns}

                if insert_cols:
                    # Stratégie 1 : Mapping par nom d'alias (exact match)
                    for target_col in insert_cols:
                        if target_col.upper() not in existing_dwh:
                            entry = projs.get(target_col.upper())
                            if entry:
                                _, transf = entry
                            else:
                                transf = None
                            dwh_meta.columns.append(
                                SQLColumnMeta(name=target_col, transformation=transf)
                            )
                            existing_dwh.add(target_col.upper())
                    # Stratégie 2 : Mapping positionnel si INSERT et SELECT ont le même nombre de colonnes
                    # et que certaines INSERT cols n'ont pas pu être résolues par alias
                    if len(insert_cols) == len(proj_values):
                        for i, target_col in enumerate(insert_cols):
                            col_exists = target_col.upper() in {c.name.upper() for c in dwh_meta.columns}
                            if not col_exists:
                                _, transf = proj_values[i]
                                dwh_meta.columns.append(
                                    SQLColumnMeta(name=target_col, transformation=transf)
                                )
                else:
                    # Pas de clause INSERT explicite : utiliser les alias du SELECT comme noms de colonnes DWH
                    for alias_key, (src_c, transf) in projs.items():
                        if alias_key.upper() not in existing_dwh:
                            dwh_meta.columns.append(
                                SQLColumnMeta(name=alias_key, transformation=transf)
                            )
                            existing_dwh.add(alias_key.upper())

        new_mappings = self._visitor.visit(stmt)
        mappings.extend(new_mappings)

        steps.append(
            ETLStep(
                name=f"MERGE → {target_name or 'CIBLE'}",
                description=f"MERGE (upsert) de {len(new_mappings)} colonnes vers {target_name or '?'}.",
                sql_fragment=stmt.sql(dialect=self.dialect)[:500],
            )
        )

    def _handle_insert_ast(
        self,
        stmt: exp.Insert,
        source_tables: dict[str, SQLTableMeta],
        target_tables: dict[str, SQLTableMeta],
        mappings: list[MappingRule],
        steps: list[ETLStep],
    ) -> None:
        """Analyse un INSERT…SELECT."""
        target_name = self._resolve_table_name(stmt.this)
        if target_name and not _is_plsql_variable(target_name):
            layer = "LOG" if "LOG" in target_name.upper() else "DWH"
            self._register_table(target_name, target_tables, layer_override=layer)

        select_expr = stmt.expression
        if isinstance(select_expr, exp.Select):
            for tbl in select_expr.find_all(exp.Table):
                src_name = _full_table_name(tbl) or tbl.name
                if src_name and not _is_plsql_variable(src_name):
                    self._register_table(src_name, source_tables, layer_override="STG")

            src_name_0 = next(
                ((_full_table_name(t) or t.name) for t in select_expr.find_all(exp.Table) if not _is_plsql_variable(_full_table_name(t) or t.name)), None
            )
            target_cols = self._extract_schema_cols(stmt.this)
            for idx, sel_col in enumerate(select_expr.expressions):
                src_col, transf = self._col_info(sel_col)
                tgt_col = target_cols[idx] if idx < len(target_cols) else src_col
                transf_rule = "Paramètre d'exécution ETL" if (src_col == "Paramètre d'exécution" or transf == "Paramètre d'exécution ETL" or (transf and "?" in transf)) else transf
                if src_col and tgt_col:
                    mappings.append(
                        MappingRule(
                            source_table=src_name_0 or "<SOURCE>",
                            source_column=src_col,
                            target_table=target_name or "<CIBLE>",
                            target_column=tgt_col,
                            transformation_rule=transf_rule,
                            comment=OracleMergeVisitor._describe_transformation(transf),
                        )
                    )

        steps.append(
            ETLStep(
                name=f"INSERT → {target_name}",
                description=f"Insertion vers {target_name}.",
                sql_fragment=stmt.sql(dialect=self.dialect)[:500],
            )
        )

    def _handle_create_ast(
        self,
        stmt: exp.Create,
        source_tables: dict[str, SQLTableMeta],
        target_tables: dict[str, SQLTableMeta],
    ) -> None:
        if not isinstance(stmt.this, exp.Schema):
            return
        table_node = stmt.this.this
        name = self._resolve_table_name(table_node)
        if not name or _is_plsql_variable(name):
            return
        layer = _detect_layer(name, context_is_target=True)
        bucket = target_tables if layer in {"DWH", "STG"} else source_tables
        tbl = self._register_table(name, bucket, layer_override=layer)
        if tbl:
            for col_def in stmt.this.expressions:
                if isinstance(col_def, exp.ColumnDef):
                    col_type = col_def.args.get("kind")
                    constraints = {type(c.kind).__name__ for c in col_def.constraints if c.kind}
                    tbl.columns.append(
                        SQLColumnMeta(
                            name=col_def.name or "",
                            data_type=col_type.sql(dialect=self.dialect) if col_type else None,
                            is_primary_key="PrimaryKeyColumnConstraint" in constraints,
                            is_foreign_key="ForeignKeyColumnConstraint" in constraints,
                        )
                    )

    def _handle_select_ast(
        self,
        stmt: exp.Select,
        source_tables: dict[str, SQLTableMeta],
    ) -> None:
        """Enregistre les tables FROM d'un SELECT autonome dans source_tables.

        IMPORTANT : les tables déjà classiées comme DWH (via MERGE INTO ou INSERT INTO)
        sont ignorées pour éviter de les rétrograder à STG.
        """
        for tbl in stmt.find_all(exp.Table):
            name = _full_table_name(tbl) or tbl.name
            if not name or _is_plsql_variable(name):
                continue
            # Ne pas rétrograder une table déjà connue comme DWH
            existing = source_tables.get(name)
            if existing and existing.layer in ("DWH", "LOG"):
                LOGGER.debug("_handle_select_ast : ignoré '%s' (déjà layer=%s)", name, existing.layer)
                continue
            self._register_table(name, source_tables, layer_override="STG")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_table_name(self, node: Any) -> str | None:
        if node is None:
            return None
        if isinstance(node, exp.Table):
            name = _full_table_name(node) or node.name or None
            return name if name and not _is_plsql_variable(name) else None
        if isinstance(node, (exp.Alias, exp.Schema)):
            return self._resolve_table_name(node.this)
        tbl = next(iter(node.find_all(exp.Table)), None)
        if tbl:
            name = _full_table_name(tbl) or tbl.name or None
            return name if name and not _is_plsql_variable(name) else None
        return None

    def _register_table(
        self,
        full_name: str,
        bucket: dict[str, SQLTableMeta],
        layer_override: str | None = None,
    ) -> SQLTableMeta | None:
        """Enregistre une table dans un bucket (source_tables ou target_tables).

        Priority de layer : DWH/LOG > STG > SRC.
        Si la table existe déjà avec un layer de moindre priorité, le layer est mis à jour.

        Args:
            full_name: Nom complet de la table (ex: DEV.DWH_UCMS_APPLIC_SKILLS).
            bucket: Dictionnaire source_tables ou target_tables.
            layer_override: Layer forcé (DWH, STG, LOG, SRC).

        Returns:
            L'objet SQLTableMeta créé ou mis à jour.
        """
        _LAYER_PRIORITY = {"DWH": 3, "LOG": 3, "STG": 2, "ODS": 2, "SRC": 1, "UNKNOWN": 0}

        if _is_plsql_variable(full_name) or not _is_valid_table_name(full_name):
            return None


        if full_name not in bucket:
            parts = full_name.split(".")
            layer = layer_override or _detect_layer(full_name)
            bucket[full_name] = SQLTableMeta(
                name=parts[-1],
                schema=parts[-2] if len(parts) > 1 else None,
                full_name=full_name,
                layer=layer,
            )
            LOGGER.debug("_register_table : ajout '%s' layer=%s", full_name, layer)
        else:
            # Mettre à jour le layer si la nouvelle information a une priorité supérieure
            existing = bucket[full_name]
            current_priority = _LAYER_PRIORITY.get(existing.layer, 0)
            override_priority = _LAYER_PRIORITY.get(layer_override or "", 0)
            if override_priority > current_priority:
                LOGGER.debug(
                    "_register_table : promotion '%s' %s → %s",
                    full_name, existing.layer, layer_override,
                )
                existing.layer = layer_override  # type: ignore[assignment]

        return bucket[full_name]

    def _extract_schema_cols(self, node: Any) -> list[str]:
        if isinstance(node, exp.Schema):
            return [
                c.name
                for c in node.expressions
                if isinstance(c, (exp.Column, exp.Identifier)) and c.name
            ]
        return []

    def _col_info(self, node: exp.Expression) -> tuple[str, str | None]:
        if isinstance(node, exp.Alias):
            alias = node.alias or node.output_name or ""
            inner = node.this
            if isinstance(inner, exp.Column):
                return inner.name or alias, None
            src = next(iter(inner.find_all(exp.Column)), None)
            return (src.name if src else alias), inner.sql(dialect=self.dialect)
        if isinstance(node, exp.Column):
            return node.name or "", None
        return node.output_name or "", node.sql(dialect=self.dialect)

    def _enrich_tables_from_mappings(
        self,
        mappings: list[MappingRule],
        source_tables: dict[str, SQLTableMeta],
        target_tables: dict[str, SQLTableMeta],
    ) -> None:
        """Complète les colonnes des tables source et cible depuis les mappings extraits.

        Garantit que chaque table source et cible a au moins les colonnes mentionnées
        dans les règles de mapping, même si la propagation AST directe a échoué.
        """
        for m in mappings:
            if m.source_table and not _is_plsql_variable(m.source_table):
                src_tbl = source_tables.get(m.source_table)
                if src_tbl:
                    existing = {c.name.upper() for c in src_tbl.columns}
                    src_col = m.source_column or ""
                    if (
                        src_col
                        and src_col.upper() not in existing
                        and not src_col.startswith("Paramètre")
                        and not src_col.startswith("<")
                    ):
                        src_tbl.columns.append(SQLColumnMeta(name=src_col))
                        LOGGER.debug("Colonne enrichie STG %s.%s (depuis mapping)", m.source_table, src_col)

            if m.target_table and not _is_plsql_variable(m.target_table):
                tgt_tbl = target_tables.get(m.target_table)
                if tgt_tbl:
                    existing = {c.name.upper() for c in tgt_tbl.columns}
                    tgt_col = m.target_column or ""
                    if (
                        tgt_col
                        and tgt_col.upper() not in existing
                        and not tgt_col.startswith("<")
                    ):
                        tgt_tbl.columns.append(
                            SQLColumnMeta(name=tgt_col, transformation=m.transformation_rule)
                        )
                        LOGGER.debug("Colonne enrichie DWH %s.%s (depuis mapping)", m.target_table, tgt_col)

    def _regex_table_fallback(
        self,
        raw_sql: str,
        source_tables: dict[str, SQLTableMeta],
        target_tables: dict[str, SQLTableMeta],
    ) -> None:
        insert_pat = re.compile(r"INSERT\s+(?:INTO\s+)?([\w$.]+(?:\.[\w$.]+)*)", re.IGNORECASE)
        from_pat = re.compile(r"(?:FROM|JOIN)\s+([\w$.]+(?:\.[\w$.]+)*)", re.IGNORECASE)
        merge_pat = re.compile(r"MERGE\s+INTO\s+([\w$.]+(?:\.[\w$.]+)*)", re.IGNORECASE)

        for match in merge_pat.finditer(raw_sql):
            tbl = match.group(1)
            if not _is_plsql_variable(tbl):
                self._register_table(tbl, target_tables, layer_override="DWH")
        for match in insert_pat.finditer(raw_sql):
            tbl = match.group(1)
            if not _is_plsql_variable(tbl):
                self._register_table(tbl, target_tables, layer_override="DWH")
        for match in from_pat.finditer(raw_sql):
            full = match.group(1)
            if full.upper() not in _RESERVED_SKIP_NAMES and full not in target_tables and not _is_plsql_variable(full):
                self._register_table(full, source_tables, layer_override="STG")

    # ------------------------------------------------------------------
    # Sérialisation JSON
    # ------------------------------------------------------------------

    def to_dict(self, pkg: ETLPackageMeta) -> dict[str, Any]:
        """Convertit un ETLPackageMeta en dict JSON-sérialisable."""
        return {
            "name": pkg.name,
            "source_file": pkg.source_file,
            "description": pkg.description,
            "schedule": pkg.schedule,
            "source_tables": [self._table_to_dict(t) for t in pkg.source_tables],
            "target_tables": [self._table_to_dict(t) for t in pkg.target_tables],
            "mappings": [
                {
                    "source_table": m.source_table,
                    "source_column": m.source_column,
                    "target_table": m.target_table,
                    "target_column": m.target_column,
                    "transformation_rule": m.transformation_rule,
                    "comment": m.comment,
                }
                for m in pkg.mappings
            ],
            "steps": [
                {"name": s.name, "description": s.description, "sql_fragment": s.sql_fragment}
                for s in pkg.steps
            ],
        }

    def _table_to_dict(self, table: SQLTableMeta) -> dict[str, Any]:
        return {
            "name": table.name,
            "schema": table.schema,
            "full_name": table.full_name,
            "layer": table.layer,
            "functional_role": table.functional_role,
            "description": table.description,
            "columns": [
                {
                    "name": c.name,
                    "data_type": c.data_type,
                    "is_primary_key": c.is_primary_key,
                    "is_foreign_key": c.is_foreign_key,
                    "description": c.description,
                    "transformation": c.transformation,
                    "comment": c.comment,
                }
                for c in table.columns
            ],
        }
