"""Orchestrateur DocumentBuilder — Architecture 'Semantic Graph & Dynamic Tree Synthesizer'.

Pipeline de génération :
  1. Construction du UnifiedSemanticGraph via GraphBuilder
  2. Synthèse de l'arbre de documentation via DynamicPlanSynthesizer
  3. Rendu récursif contextuel de chaque DocumentNode
  4. Assemblage Word structuré via DocumentAssembler
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..assembler import DocumentAssembler
from ..composer.plan_synthesizer import DynamicPlanSynthesizer
from ..core.graph_builder import GraphBuilder
from ..core.semantic_graph import EntityType, UnifiedSemanticGraph
from ..generators.diagram_generator import export_mermaid_png, generate_diagram
from ..llm import BaseLLMClient
from ..sections.base import ProjectMetadata

LOGGER = logging.getLogger(__name__)


class DocumentBuilder:
    """Orchestre la génération dynamique du document STD via le Semantic Graph."""

    def __init__(self, llm_client: BaseLLMClient | None = None, retriever=None) -> None:
        self._llm = llm_client
        self._assembler = DocumentAssembler()
        self._retriever = retriever
        self._synthesizer = DynamicPlanSynthesizer()

    def build_from_graph(
        self,
        graph: UnifiedSemanticGraph,
        output_path: Path,
        project_name: str | None = None,
        user_images: list[Path] | None = None,
    ) -> Path:
        """Génère le document STD complet directement depuis un UnifiedSemanticGraph.

        Args:
            graph: Le graphe sémantique unifié.
            output_path: Chemin du fichier Word de sortie.
            project_name: Nom du projet pour la page de garde.
            user_images: Images annexes optionnelles.

        Returns:
            Chemin du fichier Word généré.
        """
        user_images = user_images or []
        proj_name = project_name or graph.project_name

        # 1. Synthèse de l'arbre documentaire
        chapters = self._synthesizer.synthesize(graph)
        LOGGER.info("DocumentBuilder : %d chapitres synthétisés", len(chapters))

        # 2. Rendu de chaque chapitre
        context: dict[str, Any] = {
            "has_sql": graph.has_sql,
            "has_pbix": graph.has_pbix,
            "has_excel": graph.has_excel,
            "storage_engines": [e.value for e in graph.storage_engines],
        }

        sections_for_assembler: list[tuple[str, str]] = []
        for chapter in chapters:
            rendered_md = chapter.render(graph, context).strip()
            if rendered_md:
                sections_for_assembler.append((chapter.title, rendered_md))

        # 3. Diagramme de lineage conditionnel (Action 5)
        has_stg = len(graph.get_entities_by_type(EntityType.STAGING)) > 0
        has_dwh = len(graph.get_entities_by_type(EntityType.WAREHOUSE_TABLE)) > 0
        has_flows = len(graph.flows) > 0
        should_generate_lineage = has_stg and has_dwh and has_flows

        diagram_png: Path | None = None
        mermaid_code = ""
        if should_generate_lineage:
            LOGGER.info("Génération du diagramme de lineage (STG, DWH et flux présents)")
            try:
                from ..generators.diagram_generator import export_mermaid_png, generate_diagram_from_graph
                mermaid_code = generate_diagram_from_graph(graph)
                mmd_path = output_path.parent / "diagramme.mmd"
                mmd_path.write_text(mermaid_code, encoding="utf-8")
                diagram_png = output_path.parent / "diagramme.png"
                export_mermaid_png(mermaid_code, diagram_png)
            except Exception as exc:
                LOGGER.warning("Diagramme Mermaid non généré : %s", exc)
                diagram_png = None
        else:
            LOGGER.info("Diagramme de lineage omis (requis : STG > 0, DWH > 0 et Flux > 0)")

        # 4. Assemblage Word final
        LOGGER.info("Assemblage du document Word")
        saved = self._assembler.assemble_std(
            sections=sections_for_assembler,
            executive_summary_markdown="",  # Déjà intégré au Chapitre 1
            glossary_markdown="",           # Déjà intégré au Chapitre Glossaire
            diagram_path=diagram_png,
            mermaid_code=mermaid_code,
            output_path=output_path,
            project_name=proj_name,
            input_files=graph.raw_inputs,
            dominant_label=graph.dominant_domain,
            user_images=user_images,
        )
        return saved

    def build(
        self,
        metadata: ProjectMetadata,
        output_path: Path,
        project_name: str = "Projet BI",
        user_images: list[Path] | None = None,
    ) -> Path:
        """Méthode compatible avec l'API existante : construit le graphe et délègue."""
        graph = GraphBuilder.build(
            project_name=project_name,
            dominant_domain=metadata.dominant_label or "Data Integration & Analytics",
            sql_packages=metadata.sql_metadata,
            pbix_tables=metadata.tables,
            pbix_metadata=metadata.pbix_metadata,
            excel_metadata=metadata.excel_metadata,
            input_files=metadata.input_files,
            llm_client=self._llm,
        )
        return self.build_from_graph(graph, output_path, project_name, user_images)


# ---------------------------------------------------------------------------
# Wrapper LLM enrichi par le contexte RAG
# ---------------------------------------------------------------------------

class _RagEnrichedLLM:
    """Wrapper transparent autour d'un BaseLLMClient qui préfixe chaque prompt
    avec le contexte RAG récupéré pour la section courante.
    """

    def __init__(self, base_client: BaseLLMClient, rag_context: str) -> None:
        self._base = base_client
        self._context = rag_context

    def generate(self, prompt: str) -> str:
        enriched = (
            f"{self._context}\n\n"
            f"---\n\n"
            f"En t'appuyant sur les extraits du template STD Keyrus ci-dessus, "
            f"génère le contenu suivant en respectant le même niveau de détail et de structure :\n\n"
            f"{prompt}"
        )
        return self._base.generate(enriched)

    def __getattr__(self, name: str):
        return getattr(self._base, name)
