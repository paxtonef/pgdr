"""P4 mandate §7 — DeterministicHypothesisScorer: the first, simple,
substitutable implementation of the HypothesisScorer contract. The
formula is intentionally unremarkable — the contract is what matters, not
this specific scoring strategy. A rule-based, LLM-assisted, Bayesian, or
case-based scorer can replace this later without any other P4 component
changing (mandate §7).
"""
from __future__ import annotations

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.enums import EvidenceDirection
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis

_BASELINE = 0.3
_DEFAULT_EVIDENCE_WEIGHT = 0.2


class DeterministicHypothesisScorer:
    def score(
        self,
        hypothesis: DiagnosticHypothesis,
        evidence: list[Evidence],
        case_state: DiagnosticCaseState,
    ) -> float:
        support = sum(
            e.weight if e.weight is not None else _DEFAULT_EVIDENCE_WEIGHT
            for e in evidence if e.direction == EvidenceDirection.SUPPORTS
        )
        contradict = sum(
            e.weight if e.weight is not None else _DEFAULT_EVIDENCE_WEIGHT
            for e in evidence if e.direction == EvidenceDirection.CONTRADICTS
        )
        raw = _BASELINE + support - contradict
        return max(0.0, min(1.0, raw))
