from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Relationship(BaseModel):
    """Relation entre deux tables du modèle de données."""

    model_config = ConfigDict(extra="allow")

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str | None = None
    is_active: bool | None = None
    cross_filtering_behavior: str | None = None
    rely_on_referential_integrity: bool | None = None
    from_key_count: int | None = None
    to_key_count: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
