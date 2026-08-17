"""P4 mandate §8 — DiagnosticUncertainty: activates the previously-dormant
uncertainty concept (pre-P4, PGDR-INV-007 was MISSING — pgdr.models.Uncertainty
was declared and never instantiated anywhere, per P2). This is a
diagnostic-level uncertainty (what don't we know yet that affects the
case), not a GGM epistemic status.
"""
from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field

from pgdr.domain.enums import UncertaintyKind


class DiagnosticUncertainty(BaseModel):
    id: str = Field(default_factory=lambda: f"UNC-{uuid4().hex[:8].upper()}")
    kind: UncertaintyKind
    description: str
    related_hypothesis_ids: list[str] = Field(default_factory=list)
    resolvable_by_question_ids: list[str] = Field(default_factory=list)
    severity: float | None = None
    resolved: bool = False
