"""Tests unitaires exhaustifs pour l'architecture 'Semantic Graph & Dynamic Tree Synthesizer'."""
import unittest
from src.core.semantic_graph import (
    UnifiedSemanticGraph,
    DataEntity,
    DataField,
    DataFlow,
    EntityType,
    StorageEngine,
    DataSourceInfo,
)
from src.composer.plan_synthesizer import DynamicPlanSynthesizer


class TestDynamicTree(unittest.TestCase):

    def test_only_sql(self):
        """Un projet uniquement SQL génère DWH, Staging, Mappings mais AUCUNE section Power BI."""
        graph = UnifiedSemanticGraph(
            project_name="SQL Project",
            dominant_domain="Telecommunications",
            entities={
                "stg_cust": DataEntity(
                    id="stg_cust", name="stg_customer", entity_type=EntityType.STAGING, storage_engine=StorageEngine.SQL,
                    fields=[DataField(name="CUST_ID", data_type="INT", is_key=True), DataField(name="NAME", data_type="VARCHAR(100)")]
                ),
                "dim_cust": DataEntity(
                    id="dim_cust", name="dim_customer", entity_type=EntityType.WAREHOUSE_TABLE, storage_engine=StorageEngine.SQL,
                    fields=[DataField(name="CUST_PK", data_type="INT", is_key=True), DataField(name="CUST_NAME", data_type="VARCHAR(100)")]
                )
            },
            flows=[
                DataFlow(
                    id="flow_cust", name="Load Customer",
                    source_entities=["stg_cust"], target_entities=["dim_cust"],
                    field_mappings=[{"source_table": "stg_customer", "source_column": "CUST_ID", "target_table": "dim_customer", "target_column": "CUST_PK", "transformation_rule": "Copie directe"}]
                )
            ]
        )

        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph)
        rendered_doc = "\n\n".join(ch.render(graph) for ch in chapters)

        # Vérifications
        self.assertIn("Data Warehouse Relationnel (SQL)", rendered_doc)
        self.assertIn("Couche d'Ingestion & Staging", rendered_doc)
        self.assertIn("Flux de Transformation & Mappings", rendered_doc)
        self.assertNotIn("Modèle Sémantique Décisionnel (Power BI)", rendered_doc)
        self.assertNotIn("VertiPaq", rendered_doc)
        self.assertIn("Stratégie d'indexation", rendered_doc)  # Recommandation SQL

    def test_only_pbix(self):
        """Un projet uniquement PBIX génère Modèle Sémantique mais AUCUNE section Staging / Mapping / DWH SQL."""
        graph = UnifiedSemanticGraph(
            project_name="PBIX Report",
            dominant_domain="Sales & Finance",
            data_sources=[DataSourceInfo(name="Azure SQL", source_type="Database", database="SalesDB")],
            entities={
                "Sales": DataEntity(
                    id="Sales", name="Sales", entity_type=EntityType.SEMANTIC_MODEL, storage_engine=StorageEngine.POWERBI,
                    fields=[DataField(name="SaleID", data_type="Int64", is_key=True), DataField(name="Amount", data_type="Decimal")],
                    measures=[{"name": "Total Sales", "expression": "SUM(Sales[Amount])"}]
                )
            }
        )

        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph)
        rendered_doc = "\n\n".join(ch.render(graph) for ch in chapters)

        # Vérifications
        self.assertIn("Modèle Sémantique Décisionnel (Power BI)", rendered_doc)
        self.assertIn("Total Sales", rendered_doc)
        self.assertNotIn("Couche d'Ingestion & Staging", rendered_doc)
        self.assertNotIn("Flux de Transformation & Mappings", rendered_doc)
        self.assertIn("VertiPaq", rendered_doc)  # Recommandation Power BI
        self.assertIn("DAX Studio", rendered_doc)

    def test_mixed_sql_and_pbix(self):
        """Un projet mixte génère un Chapitre Architecture Cible avec sous-sections SQL et Power BI."""
        graph = UnifiedSemanticGraph(
            project_name="Mixed BI Project",
            dominant_domain="Supply Chain",
            entities={
                "stg_stock": DataEntity(
                    id="stg_stock", name="stg_stock", entity_type=EntityType.STAGING, storage_engine=StorageEngine.SQL,
                    fields=[DataField(name="SKU", is_key=True), DataField(name="QTY")]
                ),
                "fact_stock": DataEntity(
                    id="fact_stock", name="fact_stock", entity_type=EntityType.WAREHOUSE_TABLE, storage_engine=StorageEngine.SQL,
                    fields=[DataField(name="SKU_PK", is_key=True), DataField(name="STOCK_LEVEL")]
                ),
                "Pbi_Stock": DataEntity(
                    id="Pbi_Stock", name="Stock Overview", entity_type=EntityType.SEMANTIC_MODEL, storage_engine=StorageEngine.POWERBI,
                    fields=[DataField(name="ProductSKU", is_key=True)],
                    measures=[{"name": "Current Stock", "expression": "SUM(fact_stock[STOCK_LEVEL])"}]
                )
            }
        )

        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph)
        rendered_doc = "\n\n".join(ch.render(graph) for ch in chapters)

        # Vérifications du Nesting intelligent
        self.assertIn("Architecture des Données Cibles", rendered_doc)
        self.assertIn("Schéma Relationnel Data Warehouse (SQL)", rendered_doc)
        self.assertIn("Modèle Sémantique Décisionnel (Power BI)", rendered_doc)
        self.assertIn("Couche d'Ingestion & Staging", rendered_doc)
        self.assertIn("Stratégie d'indexation", rendered_doc)
        self.assertIn("VertiPaq", rendered_doc)

    def test_config_and_reference_data(self):
        """Un fichier de configuration (params_config) est classé sous REFERENCE_DATA."""
        graph = UnifiedSemanticGraph(
            project_name="ETL Config Project",
            dominant_domain="ETL Ingestion",
            entities={
                "params_config": DataEntity(
                    id="params_config", name="params_config", entity_type=EntityType.REFERENCE_DATA, storage_engine=StorageEngine.EXCEL,
                    fields=[
                        DataField(name="ConfigId", data_type="INTEGER", is_key=True, sample_values=["101", "102"]),
                        DataField(name="TargetSchema", data_type="VARCHAR2", sample_values=["DWH", "STG"])
                    ]
                )
            }
        )

        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph)
        rendered_doc = "\n\n".join(ch.render(graph) for ch in chapters)

        # Vérifications
        self.assertTrue(
            "Fichiers de Paramétrage & Référentiels" in rendered_doc or "Référentiels & Paramétrage" in rendered_doc
        )
        self.assertIn("params_config", rendered_doc)
        self.assertIn("ConfigId", rendered_doc)
        self.assertNotIn("Couche d'Ingestion & Staging", rendered_doc)
        self.assertNotIn("Architecture des Données Cibles", rendered_doc)

    def test_partial_extraction_limits_section(self):
        """Une entité partielle déclenche la note d'avertissement et le chapitre 'Limites de l'analyse'."""
        graph = UnifiedSemanticGraph(
            project_name="Partial Project",
            dominant_domain="CRM",
            entities={
                "stg_opaque": DataEntity(
                    id="stg_opaque", name="stg_opaque", entity_type=EntityType.STAGING, storage_engine=StorageEngine.SQL,
                    fields=[], is_partial=True, partial_reason="SELECT * non analysable statiquement"
                )
            }
        )

        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph)
        rendered_doc = "\n\n".join(ch.render(graph) for ch in chapters)

        # Vérifications
        self.assertIn("Limites de l'Analyse Automatique", rendered_doc)
        self.assertIn("stg_opaque", rendered_doc)
        self.assertIn("SELECT * non analysable", rendered_doc)
        self.assertIn("L'extraction des colonnes est partielle", rendered_doc)

    def test_mechanical_glossary(self):
        """Le glossaire mécanique extrait 100% des colonnes, tables et mesures sans perte."""
        graph = UnifiedSemanticGraph(
            project_name="Glossary Test",
            dominant_domain="Finance",
            entities={
                "dim_account": DataEntity(
                    id="dim_account", name="dim_account", entity_type=EntityType.WAREHOUSE_TABLE, storage_engine=StorageEngine.SQL,
                    fields=[
                        DataField(name="ACCOUNT_ID", data_type="INT", is_key=True),
                        DataField(name="BALANCE_AMT", data_type="DECIMAL"),
                        DataField(name="IS_ACTIVE", data_type="BOOLEAN"),
                        DataField(name="CREATED_ON_UTC", data_type="TIMESTAMP", is_audit=True)
                    ]
                )
            }
        )

        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph)
        rendered_doc = "\n\n".join(ch.render(graph) for ch in chapters)

        self.assertIn("Glossaire Technique & Fonctionnel", rendered_doc)
        self.assertIn("`ACCOUNT_ID`", rendered_doc)
        self.assertIn("`BALANCE_AMT`", rendered_doc)
        self.assertIn("`IS_ACTIVE`", rendered_doc)
        self.assertIn("`CREATED_ON_UTC`", rendered_doc)
        self.assertIn("`dim_account`", rendered_doc)


if __name__ == "__main__":
    unittest.main()
