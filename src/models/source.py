from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DataSource(BaseModel):
    """Source de données connectée au rapport BI."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    kind: str | None = None
    connection_string: str | None = None
    server: str | None = None
    database: str | None = None
    provider: str | None = None
    query: str | None = None
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
