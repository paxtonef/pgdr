"""P4 mandate §19 — a first, simple, substitutable QuestionSelector.
Priority order, exactly as specified:
  1. questions targeting unresolved contradictions
  2. questions targeting multiple active hypotheses
  3. questions targeting high-severity uncertainty
  4. remaining relevant questions
P5 may improve this strategy without DiagnosticLoop or DiagnosticCaseState
changing.
"""
from __future__ import annotations

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.question import DiagnosticQuestion

_HIGH_SEVERITY_THRESHOLD = 0.66


class DeterministicQuestionSelector:
    def select(
        self,
        candidates: list[DiagnosticQuestion],
        state: DiagnosticCaseState,
    ) -> DiagnosticQuestion | None:
        if not candidates:
            return None

        contradiction_hypothesis_ids = {
            hid for c in state.unresolved_contradictions() for hid in c.hypothesis_ids
        }
        active_hypothesis_ids = {h.id for h in state.active_hypotheses()}
        high_severity_uncertainty_ids = {
            u.id for u in state.unresolved_uncertainties()
            if (u.severity or 0.0) >= _HIGH_SEVERITY_THRESHOLD
        }

        def targets_contradiction(q: DiagnosticQuestion) -> bool:
            return bool(set(q.target_hypothesis_ids) & contradiction_hypothesis_ids)

        def targets_multiple_active_hypotheses(q: DiagnosticQuestion) -> bool:
            return len(set(q.target_hypothesis_ids) & active_hypothesis_ids) >= 2

        def targets_high_severity_uncertainty(q: DiagnosticQuestion) -> bool:
            return bool(set(q.target_uncertainty_ids) & high_severity_uncertainty_ids)

        tiers = [
            [q for q in candidates if targets_contradiction(q)],
            [q for q in candidates if targets_multiple_active_hypotheses(q)],
            [q for q in candidates if targets_high_severity_uncertainty(q)],
            candidates,
        ]
        for tier in tiers:
            if tier:
                return tier[0]
        return None
