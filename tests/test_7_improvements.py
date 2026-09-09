"""Tests unitaires pour les 7 actions d'amélioration et les compléments stratégiques."""
import unittest
from pathlib import Path
from src.core.fingerprint import build_fingerprint, _split_into_tokens
from src.core.semantic_graph import (
    UnifiedSemanticGraph,
    DataEntity,
    DataField,
    DataFlow,
    EntityType,
    StorageEngine,
    DataSourceInfo,
)
from src.core.graph_builder import GraphBuilder
from src.composer.plan_synthesizer import DynamicPlanSynthesizer
from src.composer.generators import (
    generate_security_chapter,
    generate_performance_chapter,
    generate_executive_summary_node,
    generate_transformations_chapter,
    generate_introduction,
)
from src.extractors.pbix_extractor import PBIXExtractor


class TestSevenImprovements(unittest.TestCase):

    def test_action_1_fingerprint_extraction(self):
        """Action 1 & Ajout 4 : Extraction du fingerprint sans stopwords linguistiques ni techniques."""
        graph = UnifiedSemanticGraph(
            project_name="Quality Project",
            dominant_domain="Manufacturing",
            entities={
                "defect_table": DataEntity(
                    id="defect_table",
                    name="Defect Analysis",
                    entity_type=EntityType.WAREHOUSE_TABLE,
                    fields=[
                        DataField(name="DEFECT_ID", data_type="INT"),
                        DataField(name="DEFECT_SEVERITY_CODE", data_type="VARCHAR"),
                        DataField(name="PLANT_NAME", data_type="VARCHAR"),
                        DataField(name="MATERIAL_TYPE", data_type="VARCHAR"),
                    ],
                    measures=[{"name": "Total Defect Count", "expression": "COUNT(Defect)"}]
                )
            }
        )
        fp = build_fingerprint(graph)
        tokens = [t.strip() for t in fp.split(",")]
        # Doit contenir des termes métier
        self.assertIn("defect", tokens)
        self.assertIn("plant", tokens)
        self.assertIn("material", tokens)
        self.assertIn("severity", tokens)
        # Ne doit PAS contenir de stopwords techniques filtrés
        self.assertNotIn("id", tokens)
        self.assertNotIn("table", tokens)
        self.assertNotIn("code", tokens)
        self.assertNotIn("count", tokens)

    def test_action_2_reference_data_classification(self):
        """Action 2 : Classification générique REFERENCE_DATA basée sur score > 0.4."""
        # Cas 1 : Fichier avec colonnes type config
        graph = GraphBuilder.build(
            project_name="Config Test",
            excel_metadata=[{
                "file_path": "orchestration_matrix.csv",
                "tables": [{
                    "name": "matrix",
                    "columns": [
                        {"name": "batch_id"},
                        {"name": "source_table"},
                        {"name": "target_table"},
                        {"name": "load_type"},
                        {"name": "order_priority"},
                    ]
                }]
            }]
        )
        ref_entities = graph.get_entities_by_type(EntityType.REFERENCE_DATA)
        self.assertEqual(len(ref_entities), 1)
        self.assertEqual(ref_entities[0].name, "matrix")

        # Vérification du chapitre dédié dans le plan
        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph)
        titles = [ch.title for ch in chapters]
        self.assertTrue(any("Fichiers de Paramétrage & Référentiels" in t for t in titles))

    def test_action_3_no_empty_subsections_or_backticks(self):
        """Action 3 : Sous-section transformations remarquables conditionnée et sans backticks vides."""
        # Graphe avec mappings simples uniquement (copie directe)
        graph = UnifiedSemanticGraph(
            project_name="Direct Copy Project",
            dominant_domain="CRM",
            flows=[
                DataFlow(
                    id="f1",
                    name="Flow 1",
                    field_mappings=[
                        {"target_table": "DIM_USER", "target_column": "ID", "transformation_rule": "Copie directe"},
                        {"target_table": "DIM_USER", "target_column": "NAME", "transformation_rule": ""},
                        {"target_table": "DIM_USER", "target_column": "CODE", "transformation_rule": " "},
                    ]
                )
            ]
        )
        rendered = generate_transformations_chapter(graph, {})
        # Ne doit PAS afficher "Transformations et Fonctions Remarquables" s'il n'y a que des copies directes
        self.assertNotIn("Transformations et Fonctions Remarquables", rendered)
        self.assertNotIn("``", rendered)

    def test_action_4_security_chapter_by_default_and_engine_aware(self):
        """Action 4 : Section Sécurité toujours incluse et adaptée aux moteurs."""
        # Cas SQL
        graph_sql = UnifiedSemanticGraph(
            project_name="SQL Security",
            entities={"t_sql": DataEntity(id="t_sql", name="t_sql", storage_engine=StorageEngine.SQL)}
        )
        md_sql = generate_security_chapter(graph_sql, {})
        self.assertIn("RBAC", md_sql)
        self.assertIn("TDE", md_sql)
        self.assertNotIn("RLS", md_sql)

        # Cas Power BI
        graph_pbi = UnifiedSemanticGraph(
            project_name="PBI Security",
            entities={"t_pbi": DataEntity(id="t_pbi", name="t_pbi", storage_engine=StorageEngine.POWERBI)}
        )
        md_pbi = generate_security_chapter(graph_pbi, {})
        self.assertIn("RLS", md_pbi)
        self.assertIn("USERPRINCIPALNAME", md_pbi)

        # Vérification de présence systématique dans le plan
        synthesizer = DynamicPlanSynthesizer()
        chapters = synthesizer.synthesize(graph_pbi)
        titles = [ch.title for ch in chapters]
        self.assertTrue(any("Sécurité & Gouvernance des Données" in t for t in titles))

    def test_action_5_lineage_diagram_conditioned(self):
        """Action 5 : Lineage diagramme omis si pas de STG/DWH/Flows, présent si réunis."""
        synthesizer = DynamicPlanSynthesizer()

        # Sans STG/DWH
        graph_pbi = UnifiedSemanticGraph(
            project_name="PBI Only",
            entities={"m": DataEntity(id="m", name="m", entity_type=EntityType.SEMANTIC_MODEL)}
        )
        chapters_pbi = synthesizer.synthesize(graph_pbi)
        titles_pbi = [ch.title for ch in chapters_pbi]
        self.assertFalse(any("Lineage" in t or "Cartographie" in t for t in titles_pbi))

        # Avec STG + DWH + Flows
        graph_etl = UnifiedSemanticGraph(
            project_name="ETL Complete",
            entities={
                "stg": DataEntity(id="stg", name="stg", entity_type=EntityType.STAGING),
                "dwh": DataEntity(id="dwh", name="dwh", entity_type=EntityType.WAREHOUSE_TABLE),
            },
            flows=[DataFlow(id="f", name="f", field_mappings=[{"col": "val"}])]
        )
        chapters_etl = synthesizer.synthesize(graph_etl)
        titles_etl = [ch.title for ch in chapters_etl]
        self.assertTrue(any("Lineage" in t or "Cartographie" in t for t in titles_etl))

    def test_action_6_pbix_m_code_extraction(self):
        """Action 6 : Extraction du code M Power Query depuis PBIX."""
        pbix_file = Path("Supplier-Quality-Analysis-Sample-PBIX.pbix")
        if pbix_file.exists():
            extractor = PBIXExtractor(pbix_file)
            tables = extractor.extract()
            self.assertGreater(len(tables), 0)
            # Vérifier qu'au moins une table a une source_query non nulle
            has_m = any(bool(t.source_query and "let" in t.source_query.lower()) for t in tables)
            self.assertTrue(has_m, "Au moins une table doit contenir du code M Power Query")
            # Vérifier que les sources de données ont été trouvées
            self.assertGreater(len(extractor.raw_metadata.get("sources", [])), 0)

    def test_action_7_enrich_column_descriptions_fallback(self):
        """Action 7 : Post-processing résilient pour descriptions colonnes PBIX."""
        class MockFailingLLM:
            def generate(self, prompt):
                raise RuntimeError("LLM API Timeout")

        graph = UnifiedSemanticGraph(
            project_name="Test Resil",
            entities={
                "pbi_tbl": DataEntity(
                    id="pbi_tbl",
                    name="Plant",
                    entity_type=EntityType.SEMANTIC_MODEL,
                    fields=[DataField(name="PlantID", data_type="Int64", description="---")]
                )
            }
        )
        # Appel post-processing avec LLM défaillant : ne doit pas crasher et conserver '---'
        GraphBuilder._enrich_semantic_model_descriptions(graph, MockFailingLLM())
        self.assertEqual(graph.entities["pbi_tbl"].fields[0].description, "---")

    def test_strategic_addition_1_excel_performance(self):
        """Ajout 1 (Action 3.5) : Performance Excel selon has_power_query."""
        # Cas has_power_query = False
        graph_raw = UnifiedSemanticGraph(
            project_name="Raw Excel",
            entities={"e": DataEntity(id="e", name="sheet", storage_engine=StorageEngine.EXCEL)}
        )
        res_raw = generate_performance_chapter(graph_raw, {})
        self.assertIn("Pandas", res_raw)
        self.assertIn("archivage", res_raw.lower())

        # Cas has_power_query = True
        graph_pq = UnifiedSemanticGraph(
            project_name="PQ Excel",
            entities={"e": DataEntity(id="e", name="sheet", storage_engine=StorageEngine.EXCEL, source_query="let Source = ... in Source")}
        )
        res_pq = generate_performance_chapter(graph_pq, {})
        self.assertIn("Power Query", res_pq)
        self.assertIn("Query Folding", res_pq)

    def test_strategic_addition_2_dynamic_exec_summary(self):
        """Ajout 2 (Action 4.5) : Résumé exécutif dynamique selon has_sql, has_pbix, has_excel."""
        # Cas SQL pur
        graph_sql = UnifiedSemanticGraph(
            project_name="SQL System",
            entities={
                "stg": DataEntity(id="stg", name="stg", entity_type=EntityType.STAGING, storage_engine=StorageEngine.SQL),
                "dwh": DataEntity(id="dwh", name="dwh", entity_type=EntityType.WAREHOUSE_TABLE, storage_engine=StorageEngine.SQL)
            }
        )
        summary_sql = generate_executive_summary_node(graph_sql, {})
        self.assertIn("Data Warehouse relationnel SQL d'entreprise pur", summary_sql)

        # Cas Power BI pur
        graph_pbi = UnifiedSemanticGraph(
            project_name="PBI System",
            entities={"pbi": DataEntity(id="pbi", name="pbi", entity_type=EntityType.SEMANTIC_MODEL, storage_engine=StorageEngine.POWERBI)}
        )
        summary_pbi = generate_executive_summary_node(graph_pbi, {})
        self.assertIn("modèle sémantique décisionnel Power BI autonome", summary_pbi)


if __name__ == "__main__":
    unittest.main()
