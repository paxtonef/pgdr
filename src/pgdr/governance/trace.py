"""P8 mandate §25-26 — audit correlation. In-memory only (no database
requirement in P8), but serializable for later persistence. No GGM
semantic reimplementation here — this is a flat record of what a
GovernanceRequest/GovernanceResult/ConsumptionError already contained,
not a new evaluation of anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DiagnosticGovernanceTrace:
    case_id: str
    hypothesis_id: str | None

    request_id: str
    operation: str

    result_channel: str  # "GOVERNANCE_RESULT" | "CONSUMPTION_ERROR"

    outcome: str | None
    error_type: str | None

    rules_applied: list[str]
    profiles_applied: list[str]

    runtime_version: str
    capability_profile_version: str
    manifest_id: str

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "hypothesis_id": self.hypothesis_id,
            "request_id": self.request_id,
            "operation": self.operation,
            "result_channel": self.result_channel,
            "outcome": self.outcome,
            "error_type": self.error_type,
            "rules_applied": list(self.rules_applied),
            "profiles_applied": list(self.profiles_applied),
            "runtime_version": self.runtime_version,
            "capability_profile_version": self.capability_profile_version,
            "manifest_id": self.manifest_id,
            "timestamp": self.timestamp.isoformat(),
        }


class InMemoryGovernanceTraceStore:
    """Session-level trace store — no persistence requirement in P8
    (mandate §25). Keyed by case_id so a case's full governance history
    can be retrieved for its report/audit."""

    def __init__(self) -> None:
        self._traces: dict[str, list[DiagnosticGovernanceTrace]] = {}

    def record(self, trace: DiagnosticGovernanceTrace) -> None:
        self._traces.setdefault(trace.case_id, []).append(trace)

    def for_case(self, case_id: str) -> list[DiagnosticGovernanceTrace]:
        return list(self._traces.get(case_id, []))

    def all_traces(self) -> list[DiagnosticGovernanceTrace]:
        return [t for traces in self._traces.values() for t in traces]
