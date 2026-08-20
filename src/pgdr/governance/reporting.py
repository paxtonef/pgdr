"""P8 mandate §27/§29 — governance runs before candidate diagnostic
assertions become externally visible, but never mutates
DiagnosticCaseState. The P7-frozen report input boundary
(build_from_case_state / build_result_from_case_state) is NOT modified —
this module wraps it, per the freeze doc's own instruction ("P8 must
consume these contracts or pass through adapters — it must not redefine
them arbitrarily").

Mechanism: govern each active hypothesis against a DEEP COPY of the case
state; only the copy's hypotheses get deactivated for non-presentable
outcomes, then the existing (unmodified) build_result_from_case_state()
is called on the copy. The original `state` passed in is never written
to — this is what test_p8_t23/t24/t25/t29 verify (byte/structurally
equivalent DiagnosticCaseState before and after governance).
"""
from __future__ import annotations

from pgdr.governance.port import DiagnosticGovernanceCandidate, DiagnosticGovernancePort
from pgdr.governance.trace import DiagnosticGovernanceTrace
from pgdr.report_builder import build_result_from_case_state

_GOVERNANCE_LIMITATION_BLOCKED = (
    "Une ou plusieurs hypothèses diagnostiques n'ont pas pu être présentées "
    "sous gouvernance (conclusion diagnostique indisponible sous gouvernance)."
)
_GOVERNANCE_LIMITATION_ESCALATED = (
    "Une ou plusieurs hypothèses diagnostiques nécessitent une vérification "
    "supplémentaire avant confirmation et ne sont pas présentées comme établies."
)
_GOVERNANCE_LIMITATION_UNAVAILABLE = (
    "La gouvernance n'a pas pu être délivrée pour une ou plusieurs hypothèses "
    "diagnostiques (GOUVERNANCE INDISPONIBLE) ; ces hypothèses ne sont pas "
    "présentées, par défaut de refus."
)


def govern_and_build_result(
    request_id: str,
    state,
    governance_port: DiagnosticGovernancePort,
    presentation_target: str = "garage_report",
):
    """Returns (PreGarageDiagnosticResult, list[DiagnosticGovernanceTrace]).
    `state` is read-only from this function's perspective — see module
    docstring."""
    state_copy = state.model_copy(deep=True)
    traces: list[DiagnosticGovernanceTrace] = []

    any_blocked = False
    any_escalated = False
    any_unavailable = False

    for h in state_copy.hypotheses:
        if not h.active:
            continue

        evidence_by_id = {e.id: e for e in state_copy.evidence}
        source_observation_ids = sorted({
            oid
            for eid in (h.supporting_evidence_ids + h.contradicting_evidence_ids)
            if eid in evidence_by_id
            for oid in evidence_by_id[eid].observation_ids
        })

        candidate = DiagnosticGovernanceCandidate(
            case_id=state_copy.case_id,
            hypothesis_id=h.id,
            statement=h.description,
            analytical_score=h.confidence,
            supporting_evidence_ids=list(h.supporting_evidence_ids),
            contradicting_evidence_ids=list(h.contradicting_evidence_ids),
            source_observation_ids=source_observation_ids,
            presentation_target=presentation_target,
        )
        outcome = governance_port.govern_candidate(candidate)
        traces.append(outcome.trace)

        if not outcome.presentable:
            h.active = False
            if outcome.result_channel == "CONSUMPTION_ERROR":
                any_unavailable = True
            elif outcome.escalated:
                any_escalated = True
            else:
                any_blocked = True

    result = build_result_from_case_state(request_id, state_copy)

    extra_limitations = []
    if any_blocked:
        extra_limitations.append(_GOVERNANCE_LIMITATION_BLOCKED)
    if any_escalated:
        extra_limitations.append(_GOVERNANCE_LIMITATION_ESCALATED)
    if any_unavailable:
        extra_limitations.append(_GOVERNANCE_LIMITATION_UNAVAILABLE)

    if extra_limitations:
        # Presentation-level post-processing of the RETURNED report object
        # (not the frozen DiagnosticCaseState, and not a mutation of
        # build_result_from_case_state's internals) — squarely within
        # ReportBuilder's "format/group" permitted scope (P7 freeze doc).
        result.limitations = list(result.limitations) + extra_limitations
        result.garage_preparation_report.limitations = (
            list(result.garage_preparation_report.limitations) + extra_limitations
        )

    return result, traces
