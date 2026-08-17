"""P4 mandate §5 — Evidence: the object that FINALLY makes the Evidence
concept load-bearing, closing P2 Finding #7 (the entire pre-P4 Evidence
pipeline was dormant end-to-end — pgdr.models.Evidence was never
constructed anywhere). This is a new, separate model from
pgdr.models.Evidence (which stays untouched, still used by the v0.1
request/response schema).
"""
from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pgdr.domain.enums import EvidenceDirection


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"EVD-{uuid4().hex[:8].upper()}")
    observation_ids: list[str] = Field(default_factory=list)
    direction: EvidenceDirection
    target_hypothesis_id: str | None = None
    weight: float | None = None
    rationale: str | None = None
    source_rule_id: str | None = None
