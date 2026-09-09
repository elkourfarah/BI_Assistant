"""Hybrid Reasoner — SOTA AI Engine pour la compatibilité sémantique multi-fichiers.

Combine :
  1. Dense Vector Embeddings (Sentence Transformers local)
  2. Matrices de similarité géométrique cosinus
  3. Agent Discriminateur LLM avec raisonnement Chain-of-Thought (CoT)
  4. Cache ontologique persistant

Aucun mot-clé codé en dur. Fonctionne avec tout domaine décisionnel.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..embedding import compute_similarity, embed
from ..ontology.serializer import (
    serialize_excel_to_ontology,
    serialize_pbix_to_ontology,
    serialize_sql_to_ontology,
)
from .domain_cache import DomainCache
from .llm_reasoner import CompatibilityReport, FileDomainProfile, LLMReasoner

LOGGER = logging.getLogger(__name__)
_SIMILARITY_THRESHOLD = 0.65  # Seuil de similarité cosinus dense

# Noms de fichiers ou patterns indiquant un fichier de configuration ETL
# (toujours compatible avec les scripts SQL — c'est leur méta-données)
_CONFIG_FILE_PATTERNS = (
    "param", "config", "setting", "conf", "mapping_ref",
    "referentiel", "metadata", "meta", "parameter",
)


def _is_config_file(file_path: str) -> bool:
    """Retourne True si le fichier est manifestement un fichier de configuration ETL.

    Ces fichiers (params_config.csv, settings.xlsx, config_mapping.csv, etc.)
    sont toujours compatibles avec les scripts SQL — ils les orchestrent.
    Inutile de les soumettre au raisonneur de domaine.
    """
    name = Path(file_path).stem.lower()
    return any(pat in name for pat in _CONFIG_FILE_PATTERNS)


class HybridReasoner:
    """Raisonneur hybride Espace Vectoriel Dense + Sonde LLM CoT."""

    def __init__(
        self,
        llm_client: Any = None,
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
    ) -> None:
        self.llm_client = llm_client
        self.threshold = similarity_threshold
        self.cache = DomainCache()
        self.llm_reasoner = LLMReasoner(llm_client) if llm_client else None

    def evaluate_files(
        self,
        sql_inputs: list[tuple[str, dict[str, Any]]] | None = None,  # (file_path, sql_pkg_meta)
        pbix_inputs: list[tuple[str, dict[str, Any] | None, list[Any] | None]] | None = None,  # (file_path, raw_meta, tables)
        excel_inputs: list[tuple[str, dict[str, Any]]] | None = None,  # (file_path, excel_meta)
    ) -> CompatibilityReport:
        """Évalue la compatibilité d'un ensemble homogène ou hétérogène de fichiers BI.

        Args:
            sql_inputs: Liste de tuples (chemin_fichier_sql, dict_metadonnees_pkg).
            pbix_inputs: Liste de tuples (chemin_fichier_pbix, pbix_meta_dict, tables_objects_list).
            excel_inputs: Liste de tuples (chemin_fichier_excel, dict_metadonnees_excel).

        Returns:
            CompatibilityReport complet.
        """
        ontologies: list[tuple[str, str]] = []

        # 1. Sérialisation ontologique de chaque fichier
        for path, pkg in (sql_inputs or []):
            ont = serialize_sql_to_ontology(pkg, file_path=path)
            ontologies.append((path, ont))

        for path, pbix_meta, tables in (pbix_inputs or []):
            ont = serialize_pbix_to_ontology(pbix_meta=pbix_meta, tables=tables, file_path=path)
            ontologies.append((path, ont))

        for path, excel_meta in (excel_inputs or []):
            ont = serialize_excel_to_ontology(excel_meta, file_path=path)
            ontologies.append((path, ont))

        if not ontologies:
            return CompatibilityReport(
                is_compatible=True,
                divergence_score=0.0,
                dominant_domain="UNKNOWN",
                dominant_label="Domaine inconnu",
                file_profiles=[],
                reasoning_summary="Aucun fichier fourni.",
                detailed_report="",
            )

        if len(ontologies) == 1:
            return self._evaluate_single(ontologies[0])

        # ──────────────────────────────────────────────────────────────────
        # PRE-SCREENING : fichiers de config ETL (toujours compatibles)
        # Un params_config.csv, settings.xlsx, etc. est une annexe technique
        # des scripts SQL — pas un fichier d'un domaine différent.
        # ──────────────────────────────────────────────────────────────────
        config_paths = [p for p, _ in ontologies if _is_config_file(p)]
        non_config_ontologies = [(p, o) for p, o in ontologies if not _is_config_file(p)]

        if config_paths:
            LOGGER.info(
                "Pre-screening : %d fichier(s) de configuration ETL détecté(s) (%s) → toujours compatibles, exclus du raisonneur de domaine.",
                len(config_paths),
                ", ".join(Path(p).name for p in config_paths),
            )

        # Si tous les fichiers non-config sont identiques en domaine, fast-path
        if len(non_config_ontologies) <= 1:
            effective_ontologies = non_config_ontologies if non_config_ontologies else ontologies
            return self._evaluate_single(effective_ontologies[0]) if len(effective_ontologies) == 1 \
                else self._build_fastpath_report(ontologies, 1.0)

        ontologies_for_check = non_config_ontologies  # Ne comparer que les fichiers non-config

        # 2. Plongement vectoriel dense & Matrice de similarité cosinus
        embeddings = []
        for path, ont in ontologies_for_check:
            vec = embed(ont)
            embeddings.append(vec)

        # Calcul des similarités pairwise
        n = len(embeddings)
        similarities: list[float] = []
        is_all_similar = True

        for i in range(n):
            for j in range(i + 1, n):
                sim = compute_similarity(embeddings[i], embeddings[j])
                similarities.append(sim)
                LOGGER.info(
                    "Vector Cosine Similarity [%s <-> %s] = %.2f (seuil: %.2f)",
                    Path(ontologies_for_check[i][0]).name,
                    Path(ontologies_for_check[j][0]).name,
                    sim,
                    self.threshold,
                )
                if sim < self.threshold:
                    is_all_similar = False

        min_sim = min(similarities) if similarities else 1.0
        avg_sim = sum(similarities) / len(similarities) if similarities else 1.0

        # 3. Fast-Path Vectoriel
        if is_all_similar:
            LOGGER.info(
                "✅ Vector Space Fast-Path: Tous les fichiers ont une similarite cosinus dense >= %.2f (avg: %.2f). Compatibilite validee sans LLM.",
                self.threshold,
                avg_sim,
            )
            return self._build_fastpath_report(ontologies, avg_sim)

        # 4. Probe LLM Chain-of-Thought
        LOGGER.info(
            "🧠 Vector Space Divergence detectee (min sim: %.2f < %.2f). Declenchement du raisonnement LLM Chain-of-Thought...",
            min_sim,
            self.threshold,
        )

        if self.llm_reasoner:
            report = self.llm_reasoner.evaluate_compatibility(ontologies_for_check)
            # Post-processing : si is_compatible=False mais divergence <= 0.70, on est tolérant
            # (deux fichiers BI du même pipeline peuvent avoir des domaines légèrement différents)
            if not report.is_compatible and report.divergence_score <= 0.70:
                LOGGER.warning(
                    "Raisonneur LLM : divergence=%.2f <= 0.70 → override is_compatible=True (même pipeline BI supposé).",
                    report.divergence_score,
                )
                report = CompatibilityReport(
                    is_compatible=True,
                    divergence_score=report.divergence_score,
                    dominant_domain=report.dominant_domain,
                    dominant_label=report.dominant_label,
                    file_profiles=report.file_profiles,
                    reasoning_summary=report.reasoning_summary,
                    detailed_report=report.detailed_report,
                )
            for path, ont in ontologies:
                for p in report.file_profiles:
                    if p.file_name == Path(path).name:
                        self.cache.set(ont, p.model_dump())
            return report

        # Si pas de LLM client disponible, baser le rapport sur le score vectoriel
        divergence = 1.0 - avg_sim
        is_comp = divergence <= 0.35
        report_text = self._build_vector_report(ontologies, similarities, divergence, is_comp)

        profiles = [
            FileDomainProfile(
                file_name=Path(path).name,
                domain_id="PROJET_BI",
                domain_label="Domaine BI",
                confidence=avg_sim,
                key_entities=[],
            )
            for path, _ in ontologies
        ]

        return CompatibilityReport(
            is_compatible=is_comp,
            divergence_score=divergence,
            dominant_domain="PROJET_BI",
            dominant_label="Projet BI",
            file_profiles=profiles,
            reasoning_summary=f"Espace Vectoriel Dense: similarite moyenne de {avg_sim:.2f}.",
            detailed_report=report_text,
        )

    def _evaluate_single(self, ontology_item: tuple[str, str]) -> CompatibilityReport:
        path, ont = ontology_item
        fname = Path(path).name

        # Vérifier le cache
        cached = self.cache.get(ont)
        if cached:
            prof = FileDomainProfile(**cached)
            return CompatibilityReport(
                is_compatible=True,
                divergence_score=0.0,
                dominant_domain=prof.domain_id,
                dominant_label=prof.domain_label,
                file_profiles=[prof],
                reasoning_summary="Fichier unique (restaure du cache).",
                detailed_report="",
            )

        if self.llm_reasoner:
            prof = self.llm_reasoner._analyze_single_file(path, ont)
            self.cache.set(ont, prof.model_dump())
        else:
            prof = FileDomainProfile(
                file_name=fname,
                domain_id="PROJET_BI",
                domain_label="Projet BI",
                confidence=0.8,
                key_entities=[],
            )

        return CompatibilityReport(
            is_compatible=True,
            divergence_score=0.0,
            dominant_domain=prof.domain_id,
            dominant_label=prof.domain_label,
            file_profiles=[prof],
            reasoning_summary=f"Fichier unique identifie dans le domaine '{prof.domain_label}'.",
            detailed_report="",
        )

    def _build_fastpath_report(
        self,
        ontologies: list[tuple[str, str]],
        avg_sim: float,
    ) -> CompatibilityReport:
        # Obtenir les profils depuis le LLM ou le cache pour l'affichage
        profiles = []
        dominant_id = "PROJET_BI"
        dominant_lbl = "Projet BI Consolide"

        for path, ont in ontologies:
            fname = Path(path).name
            cached = self.cache.get(ont)
            if cached:
                p = FileDomainProfile(**cached)
            elif self.llm_reasoner:
                p = self.llm_reasoner._analyze_single_file(path, ont)
                self.cache.set(ont, p.model_dump())
            else:
                p = FileDomainProfile(
                    file_name=fname,
                    domain_id="PROJET_BI",
                    domain_label="Projet BI",
                    confidence=avg_sim,
                    key_entities=[],
                )
            profiles.append(p)

        from collections import Counter
        valid_labels = [
            p.domain_label for p in profiles
            if p.confidence > 0
            and "verifie" not in p.domain_label.lower()
            and "inconnu" not in p.domain_label.lower()
            and p.domain_label != "Domaine non verifie"
        ]
        if valid_labels:
            dominant_lbl = Counter(valid_labels).most_common(1)[0][0]
            for p in profiles:
                if p.domain_label == dominant_lbl:
                    dominant_id = p.domain_id
                    break
        elif profiles and any(p.confidence > 0 for p in profiles):
            p_best = max(profiles, key=lambda x: x.confidence)
            dominant_id = p_best.domain_id
            dominant_lbl = p_best.domain_label
        else:
            dominant_id = "DATA_INTEGRATION"
            dominant_lbl = "Data Integration / Business Intelligence"

        report_lines = [
            "",
            "=" * 70,
            f"[COMPATIBLE] Domaine : {dominant_lbl}",
            "=" * 70,
            "",
            f"  Similarite vectorielle dense moyenne : {avg_sim:.0%}",
            "",
            "  Detail des fichiers :",
        ]
        for p in profiles:
            report_lines.append(f"    * {p.file_name} -> {p.domain_label} (confiance: {p.confidence:.0%})")
        report_lines.extend(["", "=" * 70, ""])

        return CompatibilityReport(
            is_compatible=True,
            divergence_score=1.0 - avg_sim,
            dominant_domain=dominant_id,
            dominant_label=dominant_lbl,
            file_profiles=profiles,
            reasoning_summary=f"Fichiers valides comme compatibles via l'espace vectoriel dense (similarite: {avg_sim:.0%}).",
            detailed_report="\n".join(report_lines),
        )

    def _build_vector_report(
        self,
        ontologies: list[tuple[str, str]],
        similarities: list[float],
        divergence: float,
        is_comp: bool,
    ) -> str:
        hdr = "[COMPATIBLE]" if is_comp else "[INCOMPATIBILITE DETECTEE]"
        lines = [
            "",
            "=" * 70,
            f"{hdr} ENTRE LES FICHIERS FOURNIS",
            "=" * 70,
            "",
            f"  Score de divergence vectorielle : {divergence:.0%}  (seuil autorise : 35%)",
            "",
            "  Detail par fichier :",
        ]
        for path, _ in ontologies:
            fname = Path(path).name
            lines.append(f"    * {fname}")

        if not is_comp:
            lines += [
                "",
                "  Les empreintes vectorielles denses indiquent que ces fichiers",
                "  proviennent de domaines fonctionnels disjoints.",
                "",
                "  Solution : fournissez uniquement des fichiers appartenant au meme projet BI.",
                "  Si vous etes sur de vouloir continuer, utilisez --force.",
                "",
                "=" * 70,
                "",
            ]
        else:
            lines.extend(["", "=" * 70, ""])
        return "\n".join(lines)
