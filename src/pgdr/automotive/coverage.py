"""P6 mandate §3 — AutomotiveDomainCoverage: computes the canonical
coverage matrix for both questions and hypotheses, entirely from the
actual loaded configuration and rule tables. Nothing here is hand-typed —
per the mandate's own principle (§5: "no invented automotive knowledge")
applied equally to documentation ABOUT the domain, not just the domain
rules themselves.

Question coverage uses a 4-status scheme distinct from P5's
QuestionMigrationStatus (kept untouched for P5 test compatibility — see
question_classification.py). The mandate's own vocabulary for P6
(MAPPED/NEUTRAL/UNMAPPED/INVALID) is a genuine refinement, not a
duplicate: it distinguishes "no evidentiary role identified" (NEUTRAL)
from "a plausible role exists but has no validated source yet"
(UNMAPPED) — P5's scheme collapsed both into NEUTRAL.
"""
from __future__ import annotations

from collections import defaultdict
from enum import Enum

from pydantic import BaseModel

from pgdr.automotive.evidence_mapper import (
    _DISCRIMINATING_RULES, _PROVISIONAL_KEYWORD_RULES,
)
from pgdr.config_loader import load_questions
from pgdr.diagnostic import _HYPOTHESIS_MAP
from pgdr.domain.enums import EvidenceDirection


class QuestionCoverageStatus(str, Enum):
    MAPPED = "MAPPED"
    NEUTRAL = "NEUTRAL"
    UNMAPPED = "UNMAPPED"
    INVALID = "INVALID"


class HypothesisCoverageStatus(str, Enum):
    EVIDENCE_LINKED = "EVIDENCE_LINKED"
    PARTIALLY_LINKED = "PARTIALLY_LINKED"
    TRIGGER_ONLY = "TRIGGER_ONLY"
    UNMAPPED = "UNMAPPED"


class QuestionCoverage(BaseModel):
    question_id: str
    status: QuestionCoverageStatus
    reason: str


class HypothesisCoverage(BaseModel):
    hypothesis_type: str
    status: HypothesisCoverageStatus
    directions: list[str]


class CoverageReport(BaseModel):
    questions: list[QuestionCoverage]
    hypotheses: list[HypothesisCoverage]

    @property
    def question_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for q in self.questions:
            counts[q.status.value] += 1
        return dict(counts)

    @property
    def hypothesis_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for h in self.hypotheses:
            counts[h.status.value] += 1
        return dict(counts)


# Questions with an identified PLAUSIBLE future mapping but no validated
# source yet — distinct from questions with genuinely no evidentiary role.
# Each entry needs its own justification; this is not a place to list
# "things that seem interesting" — see p6_findings.md for how
# Q-STATE-002 was decided and Q-EVI-002 was decided differently.
_UNMAPPED_CANDIDATES: dict[str, str] = {
    "Q-STATE-002": (
        "Cold/hot engine state is a plausible future MAPPED candidate — the "
        "engine_running hypothesis's own description text already references "
        "'comportement à chaud/froid' — but that text does not discriminate "
        "FOR or AGAINST engine_running based on which state is reported (both "
        "are described as consistent with it), so no directional SUPPORTS/"
        "CONTRADICTS source exists yet. Flagged UNMAPPED rather than forced "
        "into a fabricated MAPPED rule."
    ),
    "Q-EVI-002": (
        "Excluded entirely from the v2 question flow (media_upload — the "
        "Evidence/photo pipeline is dormant end-to-end, P2 Finding #7). Not "
        "evaluated for mapping because it is never offered; distinct from a "
        "question that was evaluated and found to have no evidentiary role."
    ),
}


def _all_hypothesis_types() -> set[str]:
    types: set[str] = set()
    for entries in _HYPOTHESIS_MAP.values():
        for system_family, _description, _confidence, _tags in entries:
            types.add(system_family)
    return types


def _rule_target_directions() -> dict[str, set[EvidenceDirection]]:
    targets: dict[str, set[EvidenceDirection]] = defaultdict(set)
    for value_rules in _DISCRIMINATING_RULES.values():
        for per_hypothesis in value_rules.values():
            for hypothesis_type, direction in per_hypothesis.items():
                targets[hypothesis_type].add(direction)
    for rules in _PROVISIONAL_KEYWORD_RULES.values():
        for _keywords, hypothesis_type, direction, _rationale in rules:
            targets[hypothesis_type].add(direction)
    return targets


def _mapped_question_ids() -> set[str]:
    return set(_DISCRIMINATING_RULES.keys()) | set(_PROVISIONAL_KEYWORD_RULES.keys())


def compute_coverage() -> CoverageReport:
    mapped_ids = _mapped_question_ids()
    questions: list[QuestionCoverage] = []
    for q in load_questions().get("questions", []):
        qid = q["question_id"]
        if qid in mapped_ids:
            status = QuestionCoverageStatus.MAPPED
            reason = "Has an explicit evidence rule in AutomotiveEvidenceMapper (discriminating or provisional)."
        elif qid in _UNMAPPED_CANDIDATES:
            status = QuestionCoverageStatus.UNMAPPED
            reason = _UNMAPPED_CANDIDATES[qid]
        else:
            status = QuestionCoverageStatus.NEUTRAL
            reason = "Answer stored as an observation; no evidentiary role identified for this question."
        questions.append(QuestionCoverage(question_id=qid, status=status, reason=reason))

    # INVALID is never populated by a live report — validate_automotive_domain()
    # is a fail-closed startup gate (P0/P5 lineage), so a running instance
    # can never have a dangling reference to report here. See
    # p6_automotive_domain_coverage.md for why this category exists anyway.

    target_directions = _rule_target_directions()
    hypotheses: list[HypothesisCoverage] = []
    for hypothesis_type in sorted(_all_hypothesis_types()):
        directions = target_directions.get(hypothesis_type, set())
        if {EvidenceDirection.SUPPORTS, EvidenceDirection.CONTRADICTS} <= directions:
            status = HypothesisCoverageStatus.EVIDENCE_LINKED
        elif directions:
            status = HypothesisCoverageStatus.PARTIALLY_LINKED
        else:
            # Every hypothesis gets automatic initial SUPPORTS evidence
            # from its triggering symptom observation (see
            # AutomotiveDiagnosticDomain.map_evidence()) — so "no rule
            # ever targets it" means TRIGGER_ONLY, not UNMAPPED. A truly
            # UNMAPPED hypothesis (no mechanism links it to any evidence,
            # not even the initial trigger) does not currently exist in
            # this codebase — recorded here as an empty category, not
            # removed, since "0 today" is itself informative.
            status = HypothesisCoverageStatus.TRIGGER_ONLY
        hypotheses.append(HypothesisCoverage(
            hypothesis_type=hypothesis_type, status=status,
            directions=sorted(d.value for d in directions),
        ))

    return CoverageReport(questions=questions, hypotheses=hypotheses)
