from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Column(BaseModel):
    """Colonne d'une table BI (Power BI ou DWH)."""

    model_config = ConfigDict(extra="allow")

    name: str
    data_type: str | None = None
    semantic_type: str | None = None
    description: str | None = None
    expression: str | None = None
    format_string: str | None = None
    display_folder: str | None = None
    summarize_by: str | None = None
    is_hidden: bool | None = None
    is_key: bool | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_unique: bool | None = None
    is_nullable: bool | None = None
    source_column: str | None = None
    transformation: str | None = None
    comment: str | None = None
    role: str | None = None
    modified_time: datetime | None = None
    structure_modified_time: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
