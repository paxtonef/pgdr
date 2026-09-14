"""P4 mandate §19 — a first, simple, substitutable QuestionSelector.
Priority order, exactly as specified:
  0. high-information evidence acquisition (PGDR Driver Diagnostic
     Execution Mandate v0 §5/§6/§8, Decision D02 — Option C)
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

# Kept in sync with automotive/evidence_mapper.py's MEDIA_EVIDENCE_SOURCE_RULE_ID
# (not imported directly, to avoid a structural dependency from this
# domain-agnostic P4 selector onto the automotive Domain Pack — the
# selector only needs to know a plain string tag, not the automotive
# module's implementation).
_MEDIA_EVIDENCE_SOURCE_RULE_ID = "automotive.media_evidence_acquired"


def _high_information_evidence_useful(state: DiagnosticCaseState) -> bool:
    """Mandate §6: 'AVAILABLE HIGH-INFORMATION EVIDENCE FIRST, not ALWAYS
    ASK FOR A PHOTO FIRST.' For this release, the one concrete signal of
    high-information evidence is a warning_indicator observation already
    present (the same signal SafetyEngine itself consults) — a complaint
    that already established a dashboard-warning context. If no such
    context exists, or media evidence has already been acquired for this
    case, evidence acquisition is NOT prioritized (§16.10 / Journey B)."""
    has_warning_context = any(o.kind == "warning_indicator" for o in state.observations)
    if not has_warning_context:
        return False
    already_acquired = any(
        e.source_rule_id == _MEDIA_EVIDENCE_SOURCE_RULE_ID for e in state.evidence
    )
    return not already_acquired


class DeterministicQuestionSelector:
    def select(
        self,
        candidates: list[DiagnosticQuestion],
        state: DiagnosticCaseState,
    ) -> DiagnosticQuestion | None:
        if not candidates:
            return None

        if _high_information_evidence_useful(state):
            evidence_candidates = [q for q in candidates if q.is_evidence_acquisition]
            if evidence_candidates:
                return evidence_candidates[0]

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
