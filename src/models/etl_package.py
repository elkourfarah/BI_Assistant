from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ETLStep(BaseModel):
    """Étape individuelle d'un package ETL."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    sql_fragment: str | None = None


class ETLPackage(BaseModel):
    """Package ETL décrivant un flux de données complet."""

    model_config = ConfigDict(extra="allow")

    name: str
    source_file: str | None = None
    description: str | None = None
    steps: list[ETLStep] = Field(default_factory=list)
    schedule: str | None = None
    source_tables: list[str] = Field(default_factory=list)
    target_tables: list[str] = Field(default_factory=list)
