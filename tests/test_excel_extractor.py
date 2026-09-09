"""Tests unitaires pour ExcelExtractor."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.extractors.excel_extractor import ExcelExtractor


class TestExcelExtractor(unittest.TestCase):
    """Vérifie l'extraction de données et de spécifications à partir de fichiers Excel / CSV."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_extract_csv_data_sheet(self) -> None:
        """Vérifie l'extraction d'un fichier CSV représentant une table de données."""
        csv_path = self.dir_path / "stg_clients.csv"
        df = pd.DataFrame({
            "client_id": [101, 102, 103],
            "client_name": ["Alice", "Bob", "Charlie"],
            "signup_date": ["2024-01-15", "2024-02-20", "2024-03-10"],
            "account_balance": [1250.50, 450.00, 3100.75],
            "is_active": [True, True, False],
        })
        df.to_csv(csv_path, index=False, sep=";")

        extractor = ExcelExtractor(csv_path)
        tables, raw_meta = extractor.extract()

        self.assertEqual(len(tables), 1)
        tbl = tables[0]
        self.assertIn("stg_clients", tbl.name.lower())
        self.assertEqual(len(tbl.columns), 5)

        # Vérification types de colonnes
        col_types = {c.name: c.data_type for c in tbl.columns}
        self.assertEqual(col_types["client_id"], "INTEGER")
        self.assertEqual(col_types["account_balance"], "DECIMAL(18,2)")
        self.assertTrue(col_types["client_name"].startswith("VARCHAR"))

        # Check primary key detection
        pk_cols = [c.name for c in tbl.columns if c.is_key]
        self.assertIn("client_id", pk_cols)

    def test_extract_excel_specification_sheet(self) -> None:
        """Vérifie l'extraction d'une feuille de mapping / dictionnaire de données dans un fichier Excel."""
        excel_path = self.dir_path / "spec_mapping.xlsx"
        df_mapping = pd.DataFrame({
            "Table Source": ["STG_CUSTOMERS", "STG_CUSTOMERS", "STG_ORDERS"],
            "Colonne Source": ["CUST_ID", "CUST_NAME", "ORDER_AMT"],
            "Table Cible": ["DWH_DIM_CUSTOMER", "DWH_DIM_CUSTOMER", "DWH_FACT_SALES"],
            "Colonne Cible": ["CUSTOMER_KEY", "CUSTOMER_NAME", "SALES_AMOUNT"],
            "Transformation": ["CAST(CUST_ID AS INT)", "UPPER(TRIM(CUST_NAME))", "ORDER_AMT * 1.2"],
            "Description": ["Clé client", "Nom client", "Montant TTC"],
        })

        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            df_mapping.to_excel(writer, sheet_name="Mapping Rules", index=False)

        extractor = ExcelExtractor(excel_path)
        tables, raw_meta = extractor.extract()

        self.assertIn("mappings", raw_meta)
        mappings = raw_meta["mappings"]
        self.assertEqual(len(mappings), 3)
        self.assertEqual(mappings[0]["source_table"], "STG_CUSTOMERS")
        self.assertEqual(mappings[0]["target_column"], "CUSTOMER_KEY")
        self.assertEqual(mappings[0]["transformation_rule"], "CAST(CUST_ID AS INT)")


if __name__ == "__main__":
    unittest.main()
