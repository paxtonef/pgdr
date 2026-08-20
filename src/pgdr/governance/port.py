"""P8 mandate §8-9 — DiagnosticGovernancePort: the PGDR-side abstraction
diagnostic reporting calls. Does not redefine GGM semantics — its
implementation (adapter.py::GGMDiagnosticGovernanceAdapter) uses
GGMConsumer internally, but nothing here imports a GGM type by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class DiagnosticGovernanceCandidate:
    """Mandate §9. Neutral PGDR integration DTO — carries no GGM
    vocabulary. `analytical_score` is metadata only; per mandate §9/§11 it
    MUST NOT be automatically mapped to VERIFIED/CONFIRMED/HIGH authority
    by anything that constructs one of these (see object_mapper.py)."""
    case_id: str
    hypothesis_id: str
    statement: str
    analytical_score: float | None
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    source_observation_ids: list[str]
    presentation_target: str  # "user_summary" | "garage_report"
    context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiagnosticGovernanceOutcome:
    """PGDR-side result of governing one candidate. `presentable` is the
    single field report assembly actually needs to act on — everything
    else is audit/trace detail. Deliberately does NOT re-expose the raw
    GGM DecisionType/ErrorType enums here (those stay inside adapter.py /
    trace.py, which DO import from ggm.* — this dataclass is part of the
    neutral PGDR-side port, so it uses plain strings, matching
    DiagnosticGovernanceCandidate's own style)."""
    presentable: bool
    result_channel: str  # "GOVERNANCE_RESULT" | "CONSUMPTION_ERROR"
    outcome: str | None  # "ALLOW" | "BLOCK" | "REPAIR" | "ESCALATE" | "LABEL" | None (if error channel)
    error_type: str | None  # set only when result_channel == "CONSUMPTION_ERROR"
    escalated: bool
    reasons: list[str]
    trace: "DiagnosticGovernanceTrace"


@runtime_checkable
class DiagnosticGovernancePort(Protocol):
    """Mandate §8. The only interface diagnostic reporting code depends
    on. Its implementation talks to GGM; callers of this Protocol never
    need to."""

    def govern_candidate(self, candidate: DiagnosticGovernanceCandidate) -> DiagnosticGovernanceOutcome:
        ...


# Imported here only for the type-checker-visible forward reference above;
# avoids a circular import at module load time since trace.py does not
# import from this module.
from pgdr.governance.trace import DiagnosticGovernanceTrace  # noqa: E402
