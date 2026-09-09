"""Générateur du Glossaire Mécanique (100% extrait du UnifiedSemanticGraph, 0 troncature)."""
from __future__ import annotations

import logging
import re
from typing import Any

from ...core.semantic_graph import UnifiedSemanticGraph

LOGGER = logging.getLogger(__name__)

# Dictionnaire de motifs heuristiques pour la traduction automatique et déterministe
_TERM_PATTERNS = [
    (r"(?i)^id_?(.*)$", r"Identifiant unique \1"),
    (r"(?i)^(.*)_id$", r"Identifiant de \1"),
    (r"(?i)^(.*)_pk$", r"Clé primaire de \1"),
    (r"(?i)^(.*)_fk$", r"Clé étrangère vers \1"),
    (r"(?i)^cd_?(.*)$", r"Code \1"),
    (r"(?i)^(.*)_cd$", r"Code de \1"),
    (r"(?i)^code_?(.*)$", r"Code \1"),
    (r"(?i)^dt_?(.*)$", r"Date de \1"),
    (r"(?i)^(.*)_dt$", r"Date de \1"),
    (r"(?i)^(.*)_date$", r"Date de \1"),
    (r"(?i)^date_?(.*)$", r"Date \1"),
    (r"(?i)^(.*)_utc$", r"Horodatage UTC de \1"),
    (r"(?i)^lb_?(.*)$", r"Libellé de \1"),
    (r"(?i)^(.*)_desc$", r"Description de \1"),
    (r"(?i)^(.*)_name$", r"Nom de \1"),
    (r"(?i)^nom_?(.*)$", r"Nom de \1"),
    (r"(?i)^mt_?(.*)$", r"Montant de \1"),
    (r"(?i)^(.*)_amt$", r"Montant de \1"),
    (r"(?i)^(.*)_amount$", r"Montant de \1"),
    (r"(?i)^nb_?(.*)$", r"Nombre de \1"),
    (r"(?i)^nbr_?(.*)$", r"Nombre de \1"),
    (r"(?i)^(.*)_count$", r"Nombre de \1"),
    (r"(?i)^(.*)_qty$", r"Quantité de \1"),
    (r"(?i)^flg_?(.*)$", r"Indicateur booléen \1"),
    (r"(?i)^is_?(.*)$", r"Indicateur (Oui/Non) si \1"),
    (r"(?i)^has_?(.*)$", r"Indicateur présence de \1"),
    (r"(?i)^(.*)_status$", r"Statut de \1"),
    (r"(?i)^status_?(.*)$", r"Statut \1"),
    (r"(?i)^statut_?(.*)$", r"Statut \1"),
    (r"(?i)^typ_?(.*)$", r"Type de \1"),
    (r"(?i)^(.*)_type$", r"Type de \1"),
    (r"(?i)^created_by$", "Auteur de la création de la ligne"),
    (r"(?i)^created_on.*$", "Date et heure de création de l'enregistrement"),
    (r"(?i)^updated_by$", "Dernier utilisateur ayant modifié l'enregistrement"),
    (r"(?i)^updated_on.*$", "Date et heure de dernière mise à jour"),
    (r"(?i)^load_date$", "Date de chargement dans le système décisionnel"),
    (r"(?i)^row_hash$", "Empreinte numérique (Hash) pour le suivi des changements SCD"),
    (r"(?i)^valid_from.*$", "Date de début de validité de l'enregistrement"),
    (r"(?i)^valid_to.*$", "Date de fin de validité de l'enregistrement"),
    (r"(?i)^is_deleted$", "Indicateur de suppression logique"),
]


def _infer_term_definition(term: str, category: str) -> str:
    """Déduit automatiquement une définition métier lisible sans appel LLM."""
    clean_term = term.strip()

    for pattern, template in _TERM_PATTERNS:
        match = re.match(pattern, clean_term)
        if match:
            if match.groups():
                arg = match.group(1).replace("_", " ").strip()
                return template.replace(r"\1", arg).capitalize()
            return template

    words = clean_term.replace("_", " ").strip()
    if category == "Mesure DAX":
        return f"Indicateur de reporting calculé : {words}"
    if category == "Table":
        return f"Entité de données / table : {words}"
    return f"Attribut métier : {words}"


def generate_mechanical_glossary(graph: UnifiedSemanticGraph, context: dict[str, Any]) -> str:
    """Génère un glossaire mécanique complet et exhaustif (Ajout Critique 4).

    Parcourt :
      - Tous les DataField.name de toutes les entités
      - Toutes les mesures DAX
      - Toutes les tables et schémas
    Garantit 0 troncature et 100% de complétude.
    """
    glossary_dict: dict[str, tuple[str, str, str]] = {}  # term -> (term, category, definition)

    # 1. Tables et Entités
    for ent in graph.entities.values():
        t_name = ent.name
        if t_name not in glossary_dict:
            glossary_dict[t_name] = (
                t_name,
                "Table / Entité",
                ent.description or _infer_term_definition(t_name, "Table"),
            )

    # 2. Mesures DAX
    for ent, m in graph.get_all_measures():
        m_name = m.get("name", "")
        if m_name and m_name not in glossary_dict:
            expr = m.get("expression", "")
            desc = f"Mesure calculée ({expr})" if len(expr) < 60 else _infer_term_definition(m_name, "Mesure DAX")
            glossary_dict[m_name] = (m_name, "Mesure DAX", desc)

    # 3. Champs et Colonnes
    for ent, f in graph.get_all_fields():
        f_name = f.name
        if f_name and f_name not in glossary_dict:
            desc = f.description or _infer_term_definition(f_name, "Champ")
            glossary_dict[f_name] = (f_name, "Colonne / Attribut", desc)

    sorted_terms = sorted(glossary_dict.values(), key=lambda x: x[0].upper())

    lines: list[str] = [
        f"*Ce glossaire mécanique recense de manière exhaustive les **{len(sorted_terms)} termes**, "
        "entités, attributs et indicateurs extraits de l'écosystème du projet.*",
        "",
        "| Terme / Identifiant | Catégorie | Définition fonctionnelle & technique |",
        "|---|---|---|",
    ]

    for term, cat, defn in sorted_terms:
        clean_def = defn.replace("|", "/")
        lines.append(f"| `{term}` | {cat} | {clean_def} |")

    lines.append("")
    LOGGER.info("Glossaire mécanique généré avec succès : %d termes répertoriés", len(sorted_terms))
    return "\n".join(lines)
