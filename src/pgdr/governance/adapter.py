"""P8 mandate §8 (suggested impl), §14-20 — GGMDiagnosticGovernanceAdapter:
the only place in PGDR that constructs a GovernanceRequest and calls
GGMConsumer.evaluate(). Implements DiagnosticGovernancePort; nothing
outside this module needs to import from ggm.contract directly.

Outcome handling (mandate §15-20), explicit, no default `else: allow`:

    ALLOW      -> presentable=True, subject to effective_permissions
                  (mandate §16 — checked but not yet enforced field-by-
                  field in P8 v1; presentation-level permission
                  enforcement beyond "is it presentable at all" is left
                  for a future phase, documented in p8_findings.md)
    BLOCK      -> presentable=False
    REPAIR     -> presentable=False (P8 v1 does not attempt to execute
                  repair_instruction — mandate §18 explicitly permits
                  this: "if repair cannot be safely executed
                  deterministically: do not invent repair -> treat as
                  not presentable")
    ESCALATE   -> presentable=False, escalated=True (mandate §19 — must
                  not be presented as approved)
    LABEL      -> presentable=False (declared DecisionType, never
                  currently emitted by the pinned GGM engine — verified
                  by reading ggm/governance and ggm/model directly, see
                  p8_findings.md. No presentation semantics are defined
                  for it anywhere in the mandate, so it is handled via
                  the same explicit fail-closed path as a genuinely
                  unknown outcome, rather than inventing one.)
    <unknown>  -> presentable=False (fail closed, mandate §15)

ConsumptionError -> presentable=False, result_channel="CONSUMPTION_ERROR",
                  never conflated with a BLOCK GovernanceResult (mandate
                  §20 — this distinction is load-bearing and tested).
"""
from __future__ import annotations

from ggm.contract.errors import ConsumptionError
from ggm.contract.interface import GGMConsumer
from ggm.contract.types import GovernanceRequest, GovernanceResult, Operation

from pgdr.governance.object_mapper import PGDRGGMObjectMapper
from pgdr.governance.port import DiagnosticGovernanceCandidate, DiagnosticGovernanceOutcome
from pgdr.governance.trace import DiagnosticGovernanceTrace, InMemoryGovernanceTraceStore

_PRESENTABLE_OUTCOMES = {"ALLOW"}
_NON_PRESENTABLE_OUTCOMES = {"BLOCK", "REPAIR", "ESCALATE", "LABEL"}


class GGMDiagnosticGovernanceAdapter:
    """Implements DiagnosticGovernancePort using an injected GGMConsumer.
    Constructor takes the consumer (any GGMConsumer implementation —
    DefaultGGMConsumer today, a future BoundedEmbeddedGGMConsumer once
    GGM delivers one, per mandate §30) plus the manifest identity fields
    every trace records (mandate §26)."""

    def __init__(
        self,
        consumer: GGMConsumer,
        *,
        manifest_id: str,
        capability_profile_version: str,
        trace_store: InMemoryGovernanceTraceStore,
    ) -> None:
        self._consumer = consumer
        self._manifest_id = manifest_id
        self._capability_profile_version = capability_profile_version
        self._trace_store = trace_store
        self._mapper = PGDRGGMObjectMapper()

    def govern_candidate(self, candidate: DiagnosticGovernanceCandidate) -> DiagnosticGovernanceOutcome:
        serialized_claim = self._mapper.to_governed_claim_dict(candidate)
        evidence_items = [
            (eid, "SUPPORTS", "") for eid in candidate.supporting_evidence_ids
        ] + [
            (eid, "CONTRADICTS", "") for eid in candidate.contradicting_evidence_ids
        ]
        evidence_refs = self._mapper.to_evidence_refs(evidence_items) if evidence_items else None

        request = GovernanceRequest(
            object=serialized_claim,
            operation=Operation.DECIDE,
            context={
                "consumer": "pgdr",
                "domain": "diagnostic",
                "case_id": candidate.case_id,
                "presentation_target": candidate.presentation_target,
            },
            evidence=evidence_refs,
        )

        result = self._consumer.evaluate(request)

        if isinstance(result, ConsumptionError):
            outcome = self._handle_consumption_error(candidate, request, result)
        elif isinstance(result, GovernanceResult):
            outcome = self._handle_governance_result(candidate, request, result)
        else:
            # No third result path (mandate §14) — an implementation that
            # returns anything else is itself a runtime-integrity problem,
            # not something PGDR should try to interpret.
            outcome = self._fail_closed_unrecognized(candidate, request, result)

        self._trace_store.record(outcome.trace)
        return outcome

    # -- outcome handling -------------------------------------------------

    def _handle_governance_result(
        self, candidate: DiagnosticGovernanceCandidate, request: GovernanceRequest, result: GovernanceResult,
    ) -> DiagnosticGovernanceOutcome:
        outcome_value = result.outcome.value
        presentable = outcome_value in _PRESENTABLE_OUTCOMES
        escalated = outcome_value == "ESCALATE"

        trace = DiagnosticGovernanceTrace(
            case_id=candidate.case_id,
            hypothesis_id=candidate.hypothesis_id,
            request_id=result.request_id or request.request_id,
            operation=request.operation.value,
            result_channel="GOVERNANCE_RESULT",
            outcome=outcome_value,
            error_type=None,
            rules_applied=list(result.rules_applied),
            profiles_applied=list(result.profile_trace.profiles_applied),
            runtime_version=result.runtime_version,
            capability_profile_version=self._capability_profile_version,
            manifest_id=self._manifest_id,
        )
        return DiagnosticGovernanceOutcome(
            presentable=presentable,
            result_channel="GOVERNANCE_RESULT",
            outcome=outcome_value,
            error_type=None,
            escalated=escalated,
            reasons=list(result.reasons),
            trace=trace,
        )

    def _handle_consumption_error(
        self, candidate: DiagnosticGovernanceCandidate, request: GovernanceRequest, error: ConsumptionError,
    ) -> DiagnosticGovernanceOutcome:
        # Default deny (mandate §20), but the trace/status vocabulary
        # stays "GOVERNANCE UNAVAILABLE", never "GOVERNANCE BLOCKED" —
        # result_channel is the field that carries this distinction.
        trace = DiagnosticGovernanceTrace(
            case_id=candidate.case_id,
            hypothesis_id=candidate.hypothesis_id,
            request_id=error.request_id or request.request_id,
            operation=request.operation.value if request.operation else "",
            result_channel="CONSUMPTION_ERROR",
            outcome=None,
            error_type=error.error_type.value,
            rules_applied=[],
            profiles_applied=[],
            runtime_version=error.runtime_version,
            capability_profile_version=self._capability_profile_version,
            manifest_id=self._manifest_id,
        )
        return DiagnosticGovernanceOutcome(
            presentable=False,
            result_channel="CONSUMPTION_ERROR",
            outcome=None,
            error_type=error.error_type.value,
            escalated=False,
            reasons=[f"GOVERNANCE UNAVAILABLE: {error.error_type.value} — {error.details}"],
            trace=trace,
        )

    def _fail_closed_unrecognized(self, candidate, request, result) -> DiagnosticGovernanceOutcome:
        trace = DiagnosticGovernanceTrace(
            case_id=candidate.case_id,
            hypothesis_id=candidate.hypothesis_id,
            request_id=request.request_id,
            operation=request.operation.value if request.operation else "",
            result_channel="CONSUMPTION_ERROR",
            outcome=None,
            error_type="UnrecognizedResultType",
            rules_applied=[],
            profiles_applied=[],
            runtime_version="",
            capability_profile_version=self._capability_profile_version,
            manifest_id=self._manifest_id,
        )
        return DiagnosticGovernanceOutcome(
            presentable=False,
            result_channel="CONSUMPTION_ERROR",
            outcome=None,
            error_type="UnrecognizedResultType",
            escalated=False,
            reasons=[f"GGMConsumer.evaluate() returned an unrecognized type: {type(result)!r}"],
            trace=trace,
        )
