"""Unified Semantic Graph — Modèle pivot universel pour l'ingestion multi-sources BI.

Ce module définit les structures de données neutres et universelles qui
représentent n'importe quel artefact décisionnel (SQL, Power BI, Excel, Talend, Qlik, etc.)
sans présupposer de la technologie sous-jacente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    """Typologie fonctionnelle d'une entité de données dans l'architecture."""
    SOURCE_RAW = "source_raw"          # Fichier ou table source brute
    REFERENCE_DATA = "reference_data"  # Fichier de paramétrage, référentiel, configuration
    STAGING = "staging"                # Couche intermédiaire / Staging
    WAREHOUSE_TABLE = "warehouse"      # Table relationnelle Data Warehouse (Fait ou Dimension)
    SEMANTIC_MODEL = "semantic_model"  # Modèle sémantique / Table de reporting (Power BI, Qlik, Cubes)


class StorageEngine(str, Enum):
    """Moteur de stockage ou technologie associée à l'entité."""
    SQL = "SQL"                        # Base relationnelle (T-SQL, Oracle, Postgres, Snowflake...)
    POWERBI = "PowerBI"                # Moteur VertiPaq / DAX
    EXCEL = "Excel"                    # Fichier tabulaire Excel / CSV
    GENERIC = "Generic"                # Autre / Non spécifié


@dataclass
class DataField:
    """Représente une colonne, attribut ou champ d'une entité de données."""
    name: str
    data_type: str = "VARCHAR2(255)"
    is_key: bool = False
    is_foreign_key: bool = False
    fk_target: str | None = None
    is_audit: bool = False
    transformation: str | None = None
    description: str | None = None
    sample_values: list[str] = field(default_factory=list)


@dataclass
class DataEntity:
    """Représente une entité de données (table, vue, dataset, feuille de calcul)."""
    id: str                                    # Identifiant unique (ex: schema.table)
    name: str                                  # Nom court de l'entité
    schema_name: str | None = None             # Schéma ou base d'appartenance
    entity_type: EntityType = EntityType.WAREHOUSE_TABLE
    storage_engine: StorageEngine = StorageEngine.SQL
    functional_role: str = "DIM"               # FACT, DIM, AUDIT, LOOKUP, STAGING...
    description: str | None = None
    fields: list[DataField] = field(default_factory=list)
    measures: list[dict[str, str]] = field(default_factory=list)        # Mesures DAX / formules
    relationships: list[dict[str, Any]] = field(default_factory=list)   # Liens de modèle
    source_query: str | None = None
    is_partial: bool = False                   # True si des colonnes n'ont pas pu être extraites
    partial_reason: str | None = None          # Raison (ex: SELECT *, syntaxe complexe)


@dataclass
class DataFlow:
    """Représente un flux de transformation et de chargement entre entités."""
    id: str                                    # Identifiant du flux / nom du package
    name: str                                  # Libellé du flux
    source_entities: list[str] = field(default_factory=list)
    target_entities: list[str] = field(default_factory=list)
    field_mappings: list[dict[str, Any]] = field(default_factory=list)
    logic_type: str = "MERGE"                  # MERGE, INSERT, UPSERT, ELT
    raw_script: str | None = None
    description: str | None = None


@dataclass
class DataSourceInfo:
    """Représente une source ou connexion de données externe."""
    name: str
    source_type: str                           # Database, File, API, Web, Service
    connection_string: str | None = None
    database: str | None = None
    server: str | None = None


@dataclass
class UnifiedSemanticGraph:
    """Graphe de connaissances unifié représentant l'intégralité du projet BI."""
    project_name: str = "Projet BI"
    dominant_domain: str = "Data Integration & Analytics"
    entities: dict[str, DataEntity] = field(default_factory=dict)
    flows: list[DataFlow] = field(default_factory=list)
    data_sources: list[DataSourceInfo] = field(default_factory=list)
    audit_columns: list[dict[str, str]] = field(default_factory=list)
    raw_inputs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Méthodes contextuelles d'analyse du graphe
    # ------------------------------------------------------------------

    @property
    def has_sql(self) -> bool:
        """True si des entités ou des flux SQL sont présents."""
        return any(e.storage_engine == StorageEngine.SQL for e in self.entities.values()) or bool(self.flows)

    @property
    def has_pbix(self) -> bool:
        """True si un modèle sémantique Power BI est présent."""
        return any(e.storage_engine == StorageEngine.POWERBI for e in self.entities.values())

    @property
    def has_excel(self) -> bool:
        """True si des fichiers Excel / CSV sont présents."""
        return any(e.storage_engine == StorageEngine.EXCEL for e in self.entities.values())

    @property
    def storage_engines(self) -> set[StorageEngine]:
        """Retourne l'ensemble des moteurs de stockage détectés dans le graphe."""
        return {e.storage_engine for e in self.entities.values()}

    def get_entities_by_type(self, entity_type: EntityType) -> list[DataEntity]:
        """Filtre les entités par type fonctionnel."""
        return [e for e in self.entities.values() if e.entity_type == entity_type]

    def get_partial_entities(self) -> list[DataEntity]:
        """Retourne la liste des entités dont l'extraction est incomplète."""
        return [e for e in self.entities.values() if e.is_partial]

    def get_all_fields(self) -> list[tuple[DataEntity, DataField]]:
        """Retourne la liste de tous les champs de toutes les entités."""
        fields_list: list[tuple[DataEntity, DataField]] = []
        for entity in self.entities.values():
            for f in entity.fields:
                fields_list.append((entity, f))
        return fields_list

    def get_all_measures(self) -> list[tuple[DataEntity, dict[str, str]]]:
        """Retourne toutes les mesures déclarées dans le graphe."""
        measures_list: list[tuple[DataEntity, dict[str, str]]] = []
        for entity in self.entities.values():
            for m in entity.measures:
                measures_list.append((entity, m))
        return measures_list
