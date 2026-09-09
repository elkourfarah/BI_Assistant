"""Document Tree & Node — Structure arborescente pour la composition documentaire dynamique."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.semantic_graph import UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)

GeneratorCallable = Callable[[UnifiedSemanticGraph, dict[str, Any]], str]


@dataclass
class DocumentNode:
    """Nœud hiérarchique d'un document STD (Chapitre, Sous-section, Bloc narratif)."""
    title: str
    level: int                                                         # 1 = H1, 2 = H2, 3 = H3, 4 = H4
    generator_func: GeneratorCallable | None = None
    children: list[DocumentNode] = field(default_factory=list)
    badge: str | None = None                                          # Ex: "SQL", "Power BI", "Audit"
    metadata: dict[str, Any] = field(default_factory=dict)

    def render(self, graph: UnifiedSemanticGraph, context: dict[str, Any] | None = None) -> str:
        """Rendu récursif respectant scrupuleusement la profondeur hiérarchique Markdown.

        Args:
            graph: Le graphe sémantique unifié.
            context: Dictionnaire de contexte (has_sql, has_pbix, dominant_engine...).

        Returns:
            Contenu Markdown complet du nœud et de ses sous-nœuds.
        """
        ctx = context or {}
        prefix = "#" * max(1, min(self.level, 6))

        content = ""
        if self.generator_func is not None:
            try:
                content = self.generator_func(graph, ctx).strip()
            except Exception as exc:
                LOGGER.error("Erreur de rendu pour le nœud '%s' (H%d): %s", self.title, self.level, exc)
                content = f"*Erreur de génération pour la section {self.title} : {exc}*"

        rendered_children: list[str] = []
        for child in self.children:
            child_out = child.render(graph, ctx).strip()
            if child_out:
                rendered_children.append(child_out)

        # Si le nœud n'a ni contenu propre ni enfants ayant du contenu, on ne l'affiche pas
        if not content and not rendered_children:
            return ""

        parts: list[str] = []
        
        # En-tête du nœud (si titre non vide)
        if self.title:
            badge_str = f" `[{self.badge}]`" if self.badge else ""
            parts.append(f"{prefix} {self.title}{badge_str}\n")

        # Corps narratif / tabulaire du nœud
        if content:
            parts.append(f"{content}\n")

        # Enfants récursifs
        if rendered_children:
            parts.append("\n\n".join(rendered_children))

        return "\n\n".join(p for p in parts if p.strip())
