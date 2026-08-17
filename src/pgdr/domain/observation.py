"""P4 mandate §4 — Observation: a piece of information available in the
case. Immutable once created (frozen) — observations are never edited,
only superseded by new ones, so the case's evidentiary history stays
auditable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pgdr.domain.enums import ObservationSource


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"OBS-{uuid4().hex[:8].upper()}")
    kind: str
    value: Any
    source_type: ObservationSource
    source_ref: str | None = None
    timestamp: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)
