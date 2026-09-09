from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Mapping(BaseModel):
    """Règle de mapping source → cible entre deux colonnes."""

    model_config = ConfigDict(extra="allow")

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    transformation_rule: str | None = None
    description: str | None = None
