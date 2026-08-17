"""P4 mandate §7 — the contract matters more than the formula. This
Protocol lets DeterministicHypothesisScorer (application/hypothesis_scorer.py)
be swapped later for a rule-based, LLM-assisted, Bayesian, or case-based
scorer without DiagnosticCaseState or anything else changing.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis


@runtime_checkable
class HypothesisScorer(Protocol):
    def score(
        self,
        hypothesis: DiagnosticHypothesis,
        evidence: list[Evidence],
        case_state: DiagnosticCaseState,
    ) -> float:
        ...
