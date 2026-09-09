"""Tests unitaires pour InputProcessor (ZIP, répertoires, multi-fichiers)."""
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from src.extractors.input_processor import InputProcessor


class TestInputProcessor(unittest.TestCase):
    """Vérifie la décompaction ZIP, l'auto-découverte et le traitement par lot."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_discover_and_extract_zip_archive(self) -> None:
        """Vérifie le traitement d'une archive ZIP contenant SQL et Excel."""
        # Créer des fichiers dans un dossier temporaire
        sql_file = self.dir_path / "DWH_CLIENTS.sql"
        sql_file.write_text(
            "CREATE TABLE DWH_CLIENTS (CLIENT_ID NUMBER PRIMARY KEY, NAME VARCHAR2(100));\n"
            "INSERT INTO DWH_CLIENTS SELECT CUST_ID, CUST_NAME FROM STG_CUSTOMERS;\n",
            encoding="utf-8",
        )

        csv_file = self.dir_path / "stg_orders.csv"
        df_orders = pd.DataFrame({"order_id": [1, 2], "amount": [100, 200]})
        df_orders.to_csv(csv_file, index=False, sep=";")

        # Créer l'archive ZIP
        zip_path = self.dir_path / "client_inputs.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(sql_file, arcname="scripts/DWH_CLIENTS.sql")
            zf.write(csv_file, arcname="data/stg_orders.csv")

        processor = InputProcessor()
        try:
            discovered = processor.discover([zip_path])
            self.assertEqual(len(discovered.sql_files), 1)
            self.assertEqual(len(discovered.excel_files), 1)
            self.assertIn("DWH_CLIENTS.sql", discovered.sql_files[0].name)
            self.assertIn("stg_orders.csv", discovered.excel_files[0].name)

            batch_res = processor.process_all([zip_path])
            self.assertEqual(len(batch_res.sql_packages), 1)
            self.assertEqual(len(batch_res.excel_tables), 1)
        finally:
            processor.cleanup()


if __name__ == "__main__":
    unittest.main()
