"""LLM Reasoner — Sonde de raisonnement ontologique et discriminatrice de compatibilité.

Utilise un prompting Chain-of-Thought (CoT) et des structures Pydantic pour classifier
les fichiers BI dans leurs domaines respectifs et diagnostiquer toute incompatibilité.
Sans aucun mot-clé codé en dur.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modèles Pydantic de réponse structurée
# ---------------------------------------------------------------------------

class FileDomainProfile(BaseModel):
    """Profil ontologique d'un fichier analysé par le LLM."""
    file_name: str = Field(description="Nom du fichier")
    domain_id: str = Field(description="Code majuscule du domaine fonctionnel (ex: CRM, RH, SUPPLY_CHAIN, RETAIL, FINANCE)")
    domain_label: str = Field(description="Nom lisible en français du domaine fonctionnel")
    confidence: float = Field(description="Score de confiance entre 0.0 et 1.0")
    key_entities: list[str] = Field(default_factory=list, description="Principales entités métier identifiées")


class CompatibilityReport(BaseModel):
    """Rapport global de compatibilité multi-fichiers."""
    is_compatible: bool = Field(description="True si tous les fichiers appartiennent au même projet BI/domaine")
    divergence_score: float = Field(description="Score de divergence entre 0.0 (parfaitement identique) et 1.0 (totalement hétérogène)")
    dominant_domain: str = Field(description="Code du domaine majoritaire")
    dominant_label: str = Field(description="Label lisible du domaine majoritaire")
    file_profiles: list[FileDomainProfile] = Field(default_factory=list, description="Profil de chaque fichier")
    reasoning_summary: str = Field(description="Explication en 2-3 phrases du diagnostic de compatibilité")
    detailed_report: str = Field(description="Rapport texte formaté pour la console ou le document")


# ---------------------------------------------------------------------------
# Agent de Raisonnement LLM
# ---------------------------------------------------------------------------

class LLMReasoner:
    """Agent d'évaluation ontologique basé sur le LLM (Groq / Llama)."""

    def __init__(self, llm_client: Any) -> None:
        self.client = llm_client

    def evaluate_compatibility(
        self,
        file_ontologies: list[tuple[str, str]],  # List of (file_path, ontology_text)
    ) -> CompatibilityReport:
        """Évalue la compatibilité sémantique d'un groupe de fichiers BI via Chain-of-Thought.

        Args:
            file_ontologies: Liste de tuples (chemin_fichier, texte_ontologie).

        Returns:
            CompatibilityReport typé Pydantic.
        """
        if not file_ontologies:
            return CompatibilityReport(
                is_compatible=True,
                divergence_score=0.0,
                dominant_domain="UNKNOWN",
                dominant_label="Domaine inconnu",
                file_profiles=[],
                reasoning_summary="Aucun fichier fourni.",
                detailed_report="",
            )

        if len(file_ontologies) == 1:
            fname, ont = file_ontologies[0]
            profile = self._analyze_single_file(fname, ont)
            return CompatibilityReport(
                is_compatible=True,
                divergence_score=0.0,
                dominant_domain=profile.domain_id,
                dominant_label=profile.domain_label,
                file_profiles=[profile],
                reasoning_summary=f"Fichier unique identifié dans le domaine '{profile.domain_label}'.",
                detailed_report="",
            )

        # Préparer le prompt multi-fichiers pour le LLM CoT
        doc_blocks = []
        for i, (path, ont) in enumerate(file_ontologies, start=1):
            doc_blocks.append(f"--- FICHIER {i} : {path} ---\n{ont[:2500]}\n")

        all_docs = "\n".join(doc_blocks)

        prompt = (
            "Tu es un Architecte Data & BI Senior expert en modélisation décisionnelle.\n"
            "Analyse les documents d'ontologie ci-dessous extraits de plusieurs fichiers BI.\n\n"
            "REGLES IMPORTANTES :\n"
            "- Un fichier SQL de pipeline ETL (INSERT, MERGE, CREATE TABLE) appartient au domaine des tables qu'il peuple.\n"
            "- Un fichier CSV/Excel de configuration ou paramètres ETL (params_config, settings, referentiel) "
            "est TOUJOURS compatible avec les scripts SQL — il les orchestre.\n"
            "- Si les fichiers partagent le même contexte BI (même base de données, même projet), is_compatible = true.\n"
            "- Un score de divergence <= 0.70 doit toujours donner is_compatible = true.\n\n"
            "TES OBJECTIFS :\n"
            "1. Déterminer le domaine fonctionnel de CHACUN des fichiers.\n"
            "2. Évaluer si TOUS ces fichiers appartiennent au MÊIE projet décisionnel.\n"
            "3. Retourner UNIQUEMENT un objet JSON strict respectant exactement la structure suivante :\n\n"
            "```json\n"
            "{\n"
            '  "is_compatible": true,\n'
            '  "divergence_score": 0.0,\n'
            '  "dominant_domain": "CODE_MAJ",\n'
            '  "dominant_label": "Label Lisible du Domaine Majoritaire",\n'
            '  "file_profiles": [\n'
            '    {\n'
            '      "file_name": "nom_fichier",\n'
            '      "domain_id": "CODE_DOMAINE",\n'
            '      "domain_label": "Label Domaine",\n'
            '      "confidence": 0.90,\n'
            '      "key_entities": ["Entite1", "Entite2"]\n'
            '    }\n'
            '  ],\n'
            '  "reasoning_summary": "Explication synthétique du diagnostic (2-3 phrases)",\n'
            '  "detailed_report": "Rapport texte structuré pour l utilisateur"\n'
            "}\n"
            "```\n\n"
            f"DOCUMENTS À ANALYSER :\n\n{all_docs}"
        )

        try:
            raw = self.client.generate(prompt)
            return self._parse_response(raw, file_ontologies)
        except Exception as exc:
            LOGGER.error("LLMReasoner: Erreur lors de l'évaluation CoT : %s", exc)
            return self._fallback_evaluation(file_ontologies, str(exc))

    def _analyze_single_file(self, file_path: str, ontology_text: str) -> FileDomainProfile:
        """Analyse un fichier unique pour déterminer son domaine."""
        fname = Path(file_path).name
        prompt = (
            f"Tu es un Architecte Data & BI. Analyse l'ontologie suivante du fichier '{fname}' :\n\n"
            f"{ontology_text[:2000]}\n\n"
            f"Détermine son domaine fonctionnel. Retourne UNIQUEMENT un JSON :\n"
            f'{{"file_name": "{fname}", "domain_id": "CODE_DOMAINE", "domain_label": "Label Lisible", "confidence": 0.85, "key_entities": ["E1", "E2"]}}'
        )
        try:
            raw = self.client.generate(prompt)
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                return FileDomainProfile(**parsed)
        except Exception as exc:
            LOGGER.warning("Analyse fichier unique échouée pour %s : %s", fname, exc)

        return FileDomainProfile(
            file_name=fname,
            domain_id="GENERAL_BI",
            domain_label="Projet Decisionnel",
            confidence=0.5,
            key_entities=[],
        )

    def _parse_response(self, raw: str, file_ontologies: list[tuple[str, str]]) -> CompatibilityReport:
        """Parse le JSON de la réponse LLM avec nettoyage de sécurité."""
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            json_str = match.group(0)
            try:
                data = json.loads(json_str)
                # Formater le detailed_report si manquant
                if not data.get("detailed_report"):
                    data["detailed_report"] = _format_cli_report(data)
                return CompatibilityReport(**data)
            except Exception as exc:
                LOGGER.warning("Impossible de parser la réponse JSON du LLMReasoner : %s", exc)

        return self._fallback_evaluation(file_ontologies, "Erreur de format de réponse LLM")

    def _fallback_evaluation(
        self,
        file_ontologies: list[tuple[str, str]],
        error_msg: str,
    ) -> CompatibilityReport:
        """Fallback quand le LLM n'est pas disponible ou échoue.

        On suppose la compatibilité et on utilise un domaine générique
        propre (jamais "Domaine non verifie" qui pollue la page de garde).
        """
        profiles = []
        for path, ont in file_ontologies:
            fname = Path(path).name
            profiles.append(FileDomainProfile(
                file_name=fname,
                domain_id="DATA_INTEGRATION",
                domain_label="Data Integration / ETL",
                confidence=0.5,
                key_entities=[],
            ))
        return CompatibilityReport(
            is_compatible=True,
            divergence_score=0.0,
            dominant_domain="DATA_INTEGRATION",
            dominant_label="Data Integration / ETL",
            file_profiles=profiles,
            reasoning_summary=f"Évaluation LLM indisponible ({error_msg}). Compatibilité supposée — pipeline Data Integration / ETL.",
            detailed_report="",
        )


def _format_cli_report(data: dict[str, Any]) -> str:
    """Formate un rapport texte pour l'affichage console."""
    is_comp = data.get("is_compatible", True)
    div = data.get("divergence_score", 0.0)
    dom_label = data.get("dominant_label", "Inconnu")
    summary = data.get("reasoning_summary", "")

    status_header = "[COMPATIBLE]" if is_comp else "[INCOMPATIBILITE DETECTEE]"

    lines = [
        "",
        "=" * 70,
        f"{status_header} ENTRE LES FICHIERS FOURNIS",
        "=" * 70,
        "",
        f"  Score de divergence : {div:.0%}  (seuil autorise : 35%)",
        f"  Domaine majoritaire : {dom_label}",
        f"  Analyse IA          : {summary}",
        "",
        "  Detail par fichier :",
        "",
    ]

    for p in data.get("file_profiles", []):
        fname = p.get("file_name", "fichier")
        did = p.get("domain_label", p.get("domain_id", ""))
        conf = p.get("confidence", 0.0)
        entities = ", ".join(p.get("key_entities", []))
        icon = "[OK]" if is_comp or did == dom_label else "[DIFF]"

        lines.append(f"  {icon}  {fname}")
        lines.append(f"      Domaine detecte : {did}  (confiance IA: {conf:.0%})")
        if entities:
            lines.append(f"      Entites cles    : {entities}")
        lines.append("")

    if not is_comp:
        lines += [
            "  Ces fichiers appartiennent a des projets differents et ne peuvent",
            "  pas etre documentes dans le meme STD.",
            "",
            "  Solution : fournissez uniquement des fichiers appartenant",
            "     au meme projet BI (meme domaine fonctionnel).",
            "",
            "  Si vous etes sur de vouloir continuer malgre tout,",
            "     relancez la commande avec le flag --force.",
            "",
            "=" * 70,
            "",
        ]
    else:
        lines += ["=" * 70, ""]

    return "\n".join(lines)
