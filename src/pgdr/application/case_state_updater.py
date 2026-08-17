"""P4 mandate §13 — CaseStateUpdater. All state mutation goes through
here so DiagnosticCaseState is provably the single source of analytical
truth, rather than knowledge being scattered the way it was pre-P4
(SessionController owned session flow, DiagnosticEngine owned hypotheses,
answers were appended straight to a report — see P2's rule-extraction
map for the exact pre-P4 fragmentation this replaces).
"""
from __future__ import annotations

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.contradiction import DiagnosticContradiction
from pgdr.domain.enums import EvidenceDirection
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis
from pgdr.domain.observation import Observation
from pgdr.domain.question import DiagnosticAnswer
from pgdr.domain.uncertainty import DiagnosticUncertainty
from pgdr.ports.hypothesis_scorer import HypothesisScorer


class CaseStateUpdater:
    def __init__(self, scorer: HypothesisScorer) -> None:
        self._scorer = scorer

    def add_observations(self, state: DiagnosticCaseState, observations: list[Observation]) -> list[Observation]:
        state.observations.extend(observations)
        state.touch()
        return observations

    def add_evidence(self, state: DiagnosticCaseState, evidence: list[Evidence]) -> list[Evidence]:
        state.evidence.extend(evidence)
        state.touch()
        affected_ids = {e.target_hypothesis_id for e in evidence if e.target_hypothesis_id}
        if affected_ids:
            self.update_hypotheses(state, affected_ids)
        return evidence

    def update_hypotheses(
        self, state: DiagnosticCaseState, hypothesis_ids: set[str] | None = None
    ) -> list[DiagnosticHypothesis]:
        """Recomputes supporting/contradicting evidence links and
        confidence for the given hypotheses (or all hypotheses if
        `hypothesis_ids` is None). This is the mechanism that makes
        confidence genuinely mutable analytical state (mandate §6) rather
        than a constant from a static lookup table.

        Also enforces §17's configuration-requirement gate: a hypothesis
        with a non-empty `configuration_requirements` dict is deactivated
        (`active=False`) whenever the case's identity context is missing
        one of the required attributes — P4 does not decide what
        confidence *means* here, only that an under-specified hypothesis
        should not remain active."""
        targets = [h for h in state.hypotheses if hypothesis_ids is None or h.id in hypothesis_ids]
        available_attrs = state.identity_context.attributes if state.identity_context else {}
        for h in targets:
            relevant = [e for e in state.evidence if e.target_hypothesis_id == h.id]
            h.supporting_evidence_ids = [e.id for e in relevant if e.direction == EvidenceDirection.SUPPORTS]
            h.contradicting_evidence_ids = [e.id for e in relevant if e.direction == EvidenceDirection.CONTRADICTS]
            h.confidence = self._scorer.score(h, relevant, state)
            if h.configuration_requirements:
                missing = [k for k, required in h.configuration_requirements.items() if required and k not in available_attrs]
                h.active = not missing
        state.touch()
        return targets

    def update_uncertainties(
        self,
        state: DiagnosticCaseState,
        new_uncertainties: list[DiagnosticUncertainty] | None = None,
        resolved_ids: set[str] | None = None,
    ) -> None:
        if new_uncertainties:
            existing_ids = {u.id for u in state.uncertainties}
            state.uncertainties.extend(u for u in new_uncertainties if u.id not in existing_ids)
        if resolved_ids:
            for u in state.uncertainties:
                if u.id in resolved_ids:
                    u.resolved = True
        state.touch()

    def detect_contradictions(
        self, state: DiagnosticCaseState, contradictions: list[DiagnosticContradiction]
    ) -> None:
        """Merges domain-detected contradictions into state. Detection
        logic itself is domain-supplied (per P3's boundary: the schema is
        generic, the detection rules are automotive) — this method only
        applies the resulting deltas, per §9's requirement that a
        contradiction may persist `resolved=False` rather than the engine
        arbitrarily picking a side."""
        existing_ids = {c.id for c in state.contradictions}
        state.contradictions.extend(c for c in contradictions if c.id not in existing_ids)
        state.touch()

    def record_answer(self, state: DiagnosticCaseState, answer: DiagnosticAnswer) -> None:
        state.answers.append(answer)
        state.touch()
