"""PGDR v2 Release Certification -- RC-01 through RC-06.

Not new test coverage for new behavior -- these compose existing,
independently-tested mechanisms (P0-P8) into named release signature
scenarios per the v2 Completion / Release Freeze mandate. Each RC-xx
corresponds 1:1 to the mandate's own numbered scenario list.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from ggm.contract.types import GovernanceResult
from ggm.model import DecisionType

from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
from pgdr.governance.adapter import GGMDiagnosticGovernanceAdapter
from pgdr.governance.reporting import govern_and_build_result
from pgdr.governance.trace import InMemoryGovernanceTraceStore
from pgdr.models import Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest, VehicleIdentityContext
from pgdr.session_controller import SessionController

PROJECT_ROOT = Path(__file__).parent.parent


def _make_request(request_id, complaint, vir_status=ResolutionStatus.PROVISIONALLY_RESOLVED):
    return PreGarageDiagnosticRequest(
        request_id=request_id,
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=f"VIR-{request_id}", resolution_status=vir_status,
        ),
        initial_complaint=InitialComplaint(
            free_text=complaint, current_vehicle_location=VehicleLocation.HOME,
            vehicle_current_state=VehicleState.ENGINE_OFF,
        ),
        consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),
    )


def _drive_to_completion(controller, session):
    guard = 0
    while session.pending_questions and guard < 30:
        guard += 1
        q = session.pending_questions[0]
        val = False if q.answer_type.value == "yes_no" else "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))
    return session


class _FixedOutcomeConsumer:
    def __init__(self, result):
        self._result = result

    def evaluate(self, request):
        return self._result


# ---------------------------------------------------------------------------
# RC-01 -- Normal diagnostic: complaint -> hypotheses -> evidence ->
# adaptive question -> governed result -> user summary.
# ---------------------------------------------------------------------------

def test_rc01_normal_diagnostic_full_chain():
    controller = SessionController()  # real governance, default config
    req = _make_request("RC-01", "La voiture tremble au ralenti")
    session = controller.start(req)

    assert session.pending_questions  # adaptive question was offered
    case_state = controller._case_states[session.session_id]
    assert case_state.hypotheses  # hypotheses exist
    assert any(h.supporting_evidence_ids for h in case_state.hypotheses)  # evidence exists

    session = _drive_to_completion(controller, session)

    assert session.result is not None
    assert session.result.user_summary is not None
    assert session.result.garage_preparation_report is not None
    assert session.result.user_summary is not session.result.garage_preparation_report


# ---------------------------------------------------------------------------
# RC-02 -- Safety preemption: dangerous complaint -> SafetyEngine ->
# preemption -> no analytical/GGM path able to weaken safety.
# ---------------------------------------------------------------------------

def test_rc02_safety_preemption_unweakenable():
    controller = SessionController()
    req = _make_request("RC-02", "La pédale de frein est molle et la voiture ne freine plus")
    session = controller.start(req)

    assert session.state.value == "escalated"
    assert session.result.status.value == "safety_escalation"
    assert session.result.safety_triage.level.value == "emergency_stop"
    assert "ne roulez pas" in session.result.safety_triage.user_instruction.lower()

    # No governance trace exists for this case at all -- governance never
    # had the opportunity to weaken (or even see) the safety verdict.
    case_state = controller._case_states[session.session_id]
    assert controller._governance_trace_store.for_case(case_state.case_id) == []
    assert case_state.hypotheses == []  # no analytical reasoning ran either


# ---------------------------------------------------------------------------
# RC-03 -- Ambiguous evidence: insufficient evidence -> uncertainty
# preserved -> no fabricated certainty -> governed presentation.
# ---------------------------------------------------------------------------

def test_rc03_ambiguous_evidence_no_fabricated_certainty():
    controller = SessionController()
    req = _make_request("RC-03", "Bruit indéterminé")
    session = controller.start(req)
    session = _drive_to_completion(controller, session)

    assert session.result is not None
    # No hypothesis is ever presented with fabricated certainty language --
    # PGDR-HYP-003's "compatible with" phrasing, never a definitive claim.
    for h in session.result.diagnostic_hypotheses:
        assert "confirmé" not in h.description.lower()
        assert "certain" not in h.description.lower()
    # Uncertainty is preserved, not silently resolved.
    assert session.result.limitations  # at least one limitation is always present


# ---------------------------------------------------------------------------
# RC-04 -- GGM BLOCK: valid analytical hypothesis -> GGM BLOCK ->
# hypothesis remains analytically present -> absent from external
# assertion.
# ---------------------------------------------------------------------------

def test_rc04_ggm_block_analytically_present_not_externally_asserted():
    controller = SessionController()
    req = _make_request("RC-04", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive_to_completion(controller, session)
    case_state = controller._case_states[session.session_id]

    assert case_state.hypotheses  # valid analytical hypothesis exists

    blocking_port = GGMDiagnosticGovernanceAdapter(
        _FixedOutcomeConsumer(GovernanceResult(request_id="rc04", outcome=DecisionType.BLOCK)),
        manifest_id="m", capability_profile_version="1.0",
        trace_store=InMemoryGovernanceTraceStore(),
    )
    result, traces = govern_and_build_result(req.request_id, case_state, blocking_port)

    # Analytically present:
    assert len(case_state.hypotheses) > 0
    assert all(h.active for h in case_state.hypotheses)  # original untouched
    # Absent from external assertion:
    assert result.garage_preparation_report.systems_to_examine == []


# ---------------------------------------------------------------------------
# RC-05 -- GGM unavailable: fail closed -> no ungoverned diagnostic
# assertion.
# ---------------------------------------------------------------------------

def test_rc05_ggm_unavailable_fails_closed(monkeypatch):
    from pgdr.governance.errors import GovernanceUnavailableError
    import pgdr.session_controller as sc_module

    def _broken_resolve(*args, **kwargs):
        raise GovernanceUnavailableError("simulated GGM unavailability")

    monkeypatch.setattr(sc_module, "resolve_pgdr_consumption_manifest_or_raise", _broken_resolve)

    with pytest.raises(GovernanceUnavailableError):
        SessionController()  # no ungoverned SessionController is ever produced

    # Readiness independently reports NOT READY.
    import pgdr.governance.consumption_profile as cp_module
    monkeypatch.setattr(cp_module, "resolve_pgdr_consumption_manifest_or_raise", _broken_resolve)
    from pgdr.readiness import check_readiness
    report = check_readiness()
    assert report.ready is False


# ---------------------------------------------------------------------------
# RC-06 -- Packaging: wheel/install -> external CLI process -> successful
# governed execution.
# ---------------------------------------------------------------------------

@pytest.mark.packaging
def test_rc06_packaging_external_cli_governed_execution():
    run_pgdr = PROJECT_ROOT / "run_pgdr.py"
    result = subprocess.run(
        [sys.executable, str(run_pgdr), "run", "--vir-id", "VIR-001",
         "--complaint", "La voiture tremble au ralenti", "--non-interactive"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Systèmes à examiner" in result.stdout

    readiness = subprocess.run(
        [sys.executable, str(run_pgdr), "readiness"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert readiness.returncode == 0
    assert "PGDR READY" in readiness.stdout
    assert "ggm_consumption" in readiness.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
