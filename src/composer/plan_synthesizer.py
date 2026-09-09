"""Dynamic Plan Synthesizer — Synthétiseur de plan documentaire hiérarchique et sur-mesure.

Applique l'ordre de priorité métier strict (1 à 10) et le nesting intelligent
sur la base exclusive des faits prouvés dans le UnifiedSemanticGraph.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.semantic_graph import EntityType, StorageEngine, UnifiedSemanticGraph
from .document_tree import DocumentNode
from .generators import (
    generate_dwh_chapter,
    generate_executive_summary_node,
    generate_introduction,
    generate_limits_chapter,
    generate_mechanical_glossary,
    generate_monitoring_chapter,
    generate_performance_chapter,
    generate_quality_chapter,
    generate_reference_data_chapter,
    generate_security_chapter,
    generate_semantic_model_chapter,
    generate_sources_chapter,
    generate_staging_chapter,
    generate_transformations_chapter,
)

LOGGER = logging.getLogger(__name__)


class DynamicPlanSynthesizer:
    """Analyse le graphe sémantique et synthétise le plan documentaire optimal."""

    def synthesize(self, graph: UnifiedSemanticGraph) -> list[DocumentNode]:
        """Génère la liste ordonnée des chapitres racines (DocumentNode).

        Args:
            graph: Le graphe sémantique unifié.

        Returns:
            Liste ordonnée de DocumentNode constituant le document complet.
        """
        chapters: list[DocumentNode] = []
        chapter_idx = 1

        context: dict[str, Any] = {
            "has_sql": graph.has_sql,
            "has_pbix": graph.has_pbix,
            "has_excel": graph.has_excel,
            "storage_engines": [e.value for e in graph.storage_engines],
        }

        # ------------------------------------------------------------------ #
        # 1. Résumé Exécutif & Introduction (Toujours présent)               #
        # ------------------------------------------------------------------ #
        intro_node = DocumentNode(
            title=f"{chapter_idx}. Introduction & Périmètre",
            level=2,
            generator_func=generate_introduction,
            children=[
                DocumentNode(
                    title="1.1 Résumé Exécutif",
                    level=3,
                    generator_func=generate_executive_summary_node,
                )
            ],
        )
        chapters.append(intro_node)
        chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 2. Sources de données & Connectivité                               #
        # ------------------------------------------------------------------ #
        raw_sources = graph.get_entities_by_type(EntityType.SOURCE_RAW)
        if graph.data_sources or raw_sources:
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Sources de données & Connecteurs",
                    level=2,
                    generator_func=generate_sources_chapter,
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 3. Fichiers de Paramétrage & Référentiels (Action 2)               #
        # ------------------------------------------------------------------ #
        ref_entities = graph.get_entities_by_type(EntityType.REFERENCE_DATA)
        if ref_entities:
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Fichiers de Paramétrage & Référentiels",
                    level=2,
                    generator_func=generate_reference_data_chapter,
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 4. Couche Staging / Ingestion (STAGING)                            #
        # ------------------------------------------------------------------ #
        stg_entities = graph.get_entities_by_type(EntityType.STAGING)
        if stg_entities:
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Couche d'Ingestion & Staging",
                    level=2,
                    generator_func=generate_staging_chapter,
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 5. Modélisation Cible (DWH relationnel et/ou Modèle Sémantique PBI)#
        # Nesting intelligent                                                #
        # ------------------------------------------------------------------ #
        dwh_sql_entities = [
            e for e in graph.get_entities_by_type(EntityType.WAREHOUSE_TABLE)
            if e.storage_engine == StorageEngine.SQL
        ]
        pbi_entities = graph.get_entities_by_type(EntityType.SEMANTIC_MODEL)

        if dwh_sql_entities and pbi_entities:
            # Cas Mixte : Les deux existent -> Chapitre commun avec 2 sous-sections
            target_node = DocumentNode(
                title=f"{chapter_idx}. Architecture des Données Cibles",
                level=2,
                generator_func=lambda g, ctx: "*Cette section documente à la fois la modélisation relationnelle SQL et le modèle sémantique de reporting.*\n",
                children=[
                    DocumentNode(
                        title=f"{chapter_idx}.1 Schéma Relationnel Data Warehouse (SQL)",
                        level=3,
                        generator_func=generate_dwh_chapter,
                        badge="SQL",
                    ),
                    DocumentNode(
                        title=f"{chapter_idx}.2 Modèle Sémantique Décisionnel (Power BI)",
                        level=3,
                        generator_func=generate_semantic_model_chapter,
                        badge="Power BI",
                    ),
                ],
            )
            chapters.append(target_node)
            chapter_idx += 1
        elif dwh_sql_entities:
            # Cas SQL pur : Directement le contenu sans enfant redondant
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Data Warehouse Relationnel (SQL)",
                    level=2,
                    generator_func=generate_dwh_chapter,
                )
            )
            chapter_idx += 1
        elif pbi_entities:
            # Cas Power BI pur : Directement le modèle sémantique
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Modèle Sémantique Décisionnel (Power BI)",
                    level=2,
                    generator_func=generate_semantic_model_chapter,
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 6. Diagramme de Lineage conditionnel (Action 5)                    #
        # Uniquement si STG > 0 ET DWH > 0 ET Flows > 0                      #
        # ------------------------------------------------------------------ #
        has_stg = len(graph.get_entities_by_type(EntityType.STAGING)) > 0
        has_dwh = len(graph.get_entities_by_type(EntityType.WAREHOUSE_TABLE)) > 0
        has_flows = len(graph.flows) > 0
        if has_stg and has_dwh and has_flows:
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Cartographie & Lineage des Données",
                    level=2,
                    generator_func=lambda g, ctx: (
                        "*Ce chapitre présente la traçabilité visuelle et le lignage de bout en bout "
                        "depuis les tables sources de Staging jusqu'aux entités consolidées du Data Warehouse.*\n\n"
                        "*(Le diagramme Mermaid de lignage architectural est intégré dans les annexes visuelles du document)*\n"
                    ),
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 7. Transformations & Mappings (DataFlow)                           #
        # ------------------------------------------------------------------ #
        if graph.flows and any(len(f.field_mappings) > 0 for f in graph.flows):
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Flux de Transformation & Mappings",
                    level=2,
                    generator_func=generate_transformations_chapter,
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 8. Qualité des données                                             #
        # ------------------------------------------------------------------ #
        chapters.append(
            DocumentNode(
                title=f"{chapter_idx}. Qualité des Données & Intégrité",
                level=2,
                generator_func=generate_quality_chapter,
            )
        )
        chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 9. Volumétrie & Performance (Contextuel)                           #
        # ------------------------------------------------------------------ #
        chapters.append(
            DocumentNode(
                title=f"{chapter_idx}. Volumétrie & Recommandations de Performance",
                level=2,
                generator_func=generate_performance_chapter,
            )
        )
        chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 10. Sécurité & Gouvernance des Données (Action 4 - Toujours incluse)#
        # ------------------------------------------------------------------ #
        chapters.append(
            DocumentNode(
                title=f"{chapter_idx}. Sécurité & Gouvernance des Données",
                level=2,
                generator_func=generate_security_chapter,
            )
        )
        chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 11. Monitoring & Traçabilité                                       #
        # ------------------------------------------------------------------ #
        audit_present = any(any(f.is_audit for f in e.fields) for e in graph.entities.values())
        if audit_present or graph.flows:
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Monitoring & Traçabilité",
                    level=2,
                    generator_func=generate_monitoring_chapter,
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 12. Limites de l'analyse (Si entités partielles)                   #
        # ------------------------------------------------------------------ #
        if graph.get_partial_entities():
            chapters.append(
                DocumentNode(
                    title=f"{chapter_idx}. Limites de l'Analyse Automatique",
                    level=2,
                    generator_func=generate_limits_chapter,
                )
            )
            chapter_idx += 1

        # ------------------------------------------------------------------ #
        # 13. Glossaire Mécanique (100% extrait, 0 troncature)               #
        # ------------------------------------------------------------------ #
        chapters.append(
            DocumentNode(
                title=f"{chapter_idx}. Glossaire Technique & Fonctionnel",
                level=2,
                generator_func=generate_mechanical_glossary,
            )
        )

        LOGGER.info(
            "Plan synthétisé avec succès : %d chapitres générés pour le graphe '%s'",
            len(chapters),
            graph.project_name,
        )
        return chapters
