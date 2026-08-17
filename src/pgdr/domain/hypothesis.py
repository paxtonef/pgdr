"""P4 mandate §6 — DiagnosticHypothesis: unlike pgdr.models.DiagnosticHypothesis
(fixed confidence from a static lookup table — see P2 Finding #4), this
hypothesis's `confidence` is mutable analytical state, updated by
HypothesisScorer as evidence accumulates during the session. Confidence
is a plain float here — P4 does not define what confidence VALUE is
'high enough' to assert anything; that's explicitly a future GGM/CGM
concern (mandate §7).
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class DiagnosticHypothesis(BaseModel):
    id: str = Field(default_factory=lambda: f"DHYP-{uuid4().hex[:8].upper()}")
    hypothesis_type: str
    description: str

    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)

    confidence: float | None = None

    domain_ref: str | None = None
    configuration_requirements: dict[str, Any] = Field(default_factory=dict)

    active: bool = True
