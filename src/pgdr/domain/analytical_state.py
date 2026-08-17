"""P4 mandate §2-3 — DiagnosticCaseState: the canonical object every
analytical step must READ, produce explicit changes against, and WRITE
back. This replaces the pre-P4 pattern of knowledge scattered across
SessionController/DiagnosticEngine/user answers/ReportBuilder (P2's
architecture map showed exactly this fragmentation — no single object
held the full analytical picture).

Mutation discipline: this class itself does not enforce
read-then-write-back — that discipline lives in CaseStateUpdater
(application/case_state_updater.py), which is the only component meant to
mutate a DiagnosticCaseState's list fields. Direct list mutation from
elsewhere is possible (Pydantic doesn't prevent it) but is a convention
violation, not a P4 concern to structurally forbid yet.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from pgdr.domain.contradiction import DiagnosticContradiction
from pgdr.domain.enums import AnalyticalStatus, DiagnosticStopReason
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis
from pgdr.domain.identity import MachineIdentityContext
from pgdr.domain.observation import Observation
from pgdr.domain.question import DiagnosticAnswer, DiagnosticQuestion
from pgdr.domain.safety_state import SafetyState
from pgdr.domain.uncertainty import DiagnosticUncertainty


class DiagnosticCaseState(BaseModel):
    case_id: str = Field(default_factory=lambda: f"CASE-{uuid4().hex[:12].upper()}")

    identity_context: MachineIdentityContext | None = None

    observations: list[Observation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list)
    uncertainties: list[DiagnosticUncertainty] = Field(default_factory=list)
    contradictions: list[DiagnosticContradiction] = Field(default_factory=list)

    questions: list[DiagnosticQuestion] = Field(default_factory=list)
    answers: list[DiagnosticAnswer] = Field(default_factory=list)

    safety_state: SafetyState | None = None

    analytical_status: AnalyticalStatus = AnalyticalStatus.ACTIVE
    stop_reason: DiagnosticStopReason | None = None

    iteration: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        """Called by CaseStateUpdater after any mutation."""
        self.updated_at = datetime.now(timezone.utc)

    def answered_question_ids(self) -> set[str]:
        return {a.question_id for a in self.answers}

    def active_hypotheses(self) -> list[DiagnosticHypothesis]:
        return [h for h in self.hypotheses if h.active]

    def unresolved_contradictions(self) -> list[DiagnosticContradiction]:
        return [c for c in self.contradictions if not c.resolved]

    def unresolved_uncertainties(self) -> list[DiagnosticUncertainty]:
        return [u for u in self.uncertainties if not u.resolved]
