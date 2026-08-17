"""P4 mandate §18 — DiagnosticDomain: the minimal Domain Pack contract.
AutomotiveDiagnosticDomain (automotive/domain_adapter.py) is the first,
and for P4, only implementation — built from the existing v0.1 behavior
(ComplaintParser, DiagnosticEngine, questions.yaml), not a rewrite of it.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis
from pgdr.domain.observation import Observation
from pgdr.domain.question import DiagnosticQuestion


@runtime_checkable
class DiagnosticDomain(Protocol):
    def interpret_observations(self, state: DiagnosticCaseState) -> list[Observation]:
        """Turn raw case input (e.g. the initial complaint) into
        Observations. Called once per new raw input, not on every
        iteration — CaseStateUpdater decides when."""
        ...

    def generate_hypotheses(self, state: DiagnosticCaseState) -> list[DiagnosticHypothesis]:
        """Propose candidate hypotheses from the case's current
        observations. May be called more than once as observations
        accumulate; the domain decides whether to add new hypotheses or
        return an empty list when nothing new is warranted."""
        ...

    def map_evidence(self, state: DiagnosticCaseState) -> list[Evidence]:
        """Derive Evidence linking existing observations to existing
        hypotheses. See also ports/evidence_mapper.py for the more
        specific answer-driven variant used by DiagnosticLoop."""
        ...

    def available_questions(self, state: DiagnosticCaseState) -> list[DiagnosticQuestion]:
        """Return every question the domain considers relevant to the
        current state, unfiltered by answered-status or risk gating —
        QuestionSelector and the loop's answered-question check apply
        those filters afterward."""
        ...
