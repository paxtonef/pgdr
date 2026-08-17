"""P4 mandate §9 — DiagnosticContradiction: unlike the pre-P4
pgdr.models.DiagnosticContradiction (detected once, never resolved or
revisited, resolution_action never actually enforced — see P2 Finding
around PGDR-HYP-002), this version is explicitly mutable: a contradiction
can remain `resolved=False` indefinitely, and the case proceeds anyway
rather than arbitrarily picking one of the conflicting observations.
"""
from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field


class DiagnosticContradiction(BaseModel):
    id: str = Field(default_factory=lambda: f"CONTRA-{uuid4().hex[:8].upper()}")
    evidence_ids: list[str] = Field(default_factory=list)
    hypothesis_ids: list[str] = Field(default_factory=list)
    description: str
    resolved: bool = False
    resolution_note: str | None = None
