from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .column import Column
from .relationship import Relationship
from .source import DataSource


class LayerEnum(str, Enum):
    """Couche architecturale BI d'une table."""

    STG = "STG"          # Staging (zone d'atterrissage brute)
    DWH = "DWH"          # Data Warehouse (zone normalisée)
    PBI = "PBI"          # Power BI (modèle sémantique)
    DATAMART = "DATAMART"  # Datamart (zone de présentation)
    SRC = "SRC"          # Source système externe
    ODS = "ODS"          # Operational Data Store
    LOG = "LOG"          # Table de log/monitoring
    UNKNOWN = "UNKNOWN"  # Non déterminé


class FunctionalRoleEnum(str, Enum):
    """Rôle fonctionnel d'une table dans l'architecture BI."""

    FACT = "FACT"        # Table de faits (métriques, volumétrie)
    DIM = "DIM"          # Table de dimension (référentiel, attributs)
    AUDIT = "AUDIT"      # Table de suivi/audit/log
    SYSTEM = "SYSTEM"    # Table système (ex: dual)
    CONFIG = "CONFIG"    # Table de paramétrage
    UNKNOWN = "UNKNOWN"  # Non déterminé


# Mapping des heuristiques de nommage vers les couches
_LAYER_HINTS: dict[str, LayerEnum] = {
    "STG": LayerEnum.STG,
    "DWH": LayerEnum.DWH,
    "DW": LayerEnum.DWH,
    "DATAWAREHOUSE": LayerEnum.DWH,
    "DATAMART": LayerEnum.DATAMART,
    "DM": LayerEnum.DATAMART,
    "SRC": LayerEnum.SRC,
    "SOURCE": LayerEnum.SOURCE if hasattr(LayerEnum, "SOURCE") else LayerEnum.SRC,
    "ODS": LayerEnum.ODS,
    "LOG": LayerEnum.LOG,
}


def infer_layer(table_name: str) -> LayerEnum:
    """Infère la couche BI d'une table depuis son nom.

    Args:
        table_name: Nom complet ou partiel de la table.

    Returns:
        LayerEnum correspondant.
    """
    upper = table_name.upper()
    for prefix, layer in _LAYER_HINTS.items():
        if f"_{prefix}_" in upper or upper.startswith(f"{prefix}_") or f".{prefix}_" in upper:
            return layer
    return LayerEnum.UNKNOWN


class Measure(BaseModel):
    """Mesure DAX d'une table Power BI."""

    model_config = ConfigDict(extra="allow")

    name: str
    expression: str | None = None
    display_folder: str | None = None
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Table(BaseModel):
    """Table du modèle de données BI (Power BI ou DWH)."""

    model_config = ConfigDict(extra="allow")

    name: str
    schema_name: str | None = None
    description: str | None = None
    data_category: str | None = None
    is_hidden: bool | None = None
    is_private: bool | None = None
    layer: LayerEnum = LayerEnum.UNKNOWN
    functional_role: FunctionalRoleEnum = FunctionalRoleEnum.UNKNOWN
    columns: list[Column] = Field(default_factory=list)
    measures: list[Measure] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    source_query: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
