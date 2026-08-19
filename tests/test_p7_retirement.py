"""P7 — Legacy Analytical Path Retirement & Architecture Freeze tests.

Covers the mandate's P7-T01..T10 matrix. Written AFTER retirement
(P7.3-P7.5), proving the post-retirement codebase — not a prediction of
what retirement would do.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.domain.enums import EvidenceDirection
from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
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


@pytest.fixture
def controller():
    return SessionController()


def _drive(controller, session, until_question_id=None, answer_overrides=None):
    answer_overrides = answer_overrides or {}
    guard = 0
    while session.pending_questions and guard < 30:
        q = session.pending_questions[0]
        if until_question_id is not None and q.question_id == until_question_id:
            break
        guard += 1
        if q.question_id in answer_overrides:
            val = answer_overrides[q.question_id]
        elif q.answer_type.value == "yes_no":
            val = False
        elif q.answer_type.value == "multiple_choice":
            val = ["je ne sais pas"]
        else:
            val = "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))
    return session


# ---------------------------------------------------------------------------
# P7-T01 — No-Legacy Reachability Test
# ---------------------------------------------------------------------------

def test_p7_t01_no_reachable_legacy_analytical_component():
    import pgdr.diagnostic as diagnostic_module
    import pgdr.report_builder as report_builder_module

    assert not hasattr(diagnostic_module, "DiagnosticEngine")
    assert not hasattr(report_builder_module, "ReportBuilder")

    controller = SessionController()
    assert not hasattr(controller, "diagnostic_engine")
    assert not hasattr(controller, "report_builder")

    # And the scenario still runs to completion end-to-end.
    req = _make_request("P7-T01", "La voiture tremble au ralenti")
    session = controller.start(req)
    guard = 0
    while session.pending_questions and guard < 30:
        guard += 1
        q = session.pending_questions[0]
        val = False if q.answer_type.value == "yes_no" else "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))
    assert session.result is not None


# ---------------------------------------------------------------------------
# P7-T02 — Single State Test
# ---------------------------------------------------------------------------

def test_p7_t02_one_session_has_one_authoritative_case_state(controller):
    req = _make_request("P7-T02", "La voiture tremble au ralenti")
    session = controller.start(req)
    case_id_initial = controller._case_states[session.session_id].case_id

    q1 = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q1.question_id, value="je ne sais pas"))
    case_id_after_a1 = controller._case_states[session.session_id].case_id
    assert case_id_after_a1 == case_id_initial

    if session.pending_questions:
        q2 = session.pending_questions[0]
        session = controller.submit_answer(session, Answer(question_id=q2.question_id, value="je ne sais pas"))
        case_id_after_a2 = controller._case_states[session.session_id].case_id
        assert case_id_after_a2 == case_id_initial

    # Exactly one DiagnosticCaseState is ever tracked for this session_id.
    assert len(controller._case_states) == 1


# ---------------------------------------------------------------------------
# P7-T03 — No Silent Fallback Test
# ---------------------------------------------------------------------------

def test_p7_t03_diagnostic_loop_failure_never_falls_back_silently(controller, monkeypatch):
    req = _make_request("P7-T03", "La voiture tremble au ralenti")
    session = controller.start(req)

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DiagnosticLoop failure")

    monkeypatch.setattr(controller._loop, "run_iteration", _boom)

    q = session.pending_questions[0]
    with pytest.raises(RuntimeError, match="simulated DiagnosticLoop failure"):
        controller.submit_answer(session, Answer(question_id=q.question_id, value="je ne sais pas"))
    # The failure propagated explicitly — it was not caught and silently
    # routed to any alternate reasoning path (none exists to route to).


# ---------------------------------------------------------------------------
# P7-T04 — Question Authority Test
# ---------------------------------------------------------------------------

def test_p7_t04_every_question_originates_from_diagnostic_loop(controller):
    req = _make_request("P7-T04", "La voiture tremble au ralenti")
    session = controller.start(req)

    seen = 0
    guard = 0
    while session.pending_questions and guard < 30:
        guard += 1
        presented = session.pending_questions[0]
        case_state = controller._case_states[session.session_id]
        assert any(q.id == presented.question_id for q in case_state.questions), (
            "a presented question did not originate from DiagnosticLoop/case_state.questions"
        )
        seen += 1
        val = False if presented.answer_type.value == "yes_no" else "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=presented.question_id, value=val))
    assert seen > 0


# ---------------------------------------------------------------------------
# P7-T05 — Evidence Authority Test
# ---------------------------------------------------------------------------

def test_p7_t05_every_score_change_has_corresponding_evidence(controller):
    req = _make_request("P7-T05", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive(controller, session, until_question_id="Q-COND-001")

    case_state = controller._case_states[session.session_id]
    before = {h.id: h.confidence for h in case_state.hypotheses}

    q = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q.question_id, value=["vitesse stabilisée"]))
    case_state = controller._case_states[session.session_id]
    after = {h.id: h.confidence for h in case_state.hypotheses}

    changed_ids = {hid for hid in before if before[hid] != after[hid]}
    assert changed_ids, "expected at least one hypothesis score to change"
    for hid in changed_ids:
        h = next(h for h in case_state.hypotheses if h.id == hid)
        assert h.supporting_evidence_ids or h.contradicting_evidence_ids, (
            f"hypothesis {hid} changed score with no corresponding evidence recorded"
        )


# ---------------------------------------------------------------------------
# P7-T06 — Reporting Purity Test
# ---------------------------------------------------------------------------

def test_p7_t06_reporting_does_not_mutate_analytical_state(controller):
    from pgdr.report_builder import build_result_from_case_state

    req = _make_request("P7-T06", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive(controller, session)
    case_state = controller._case_states[session.session_id]

    before = {
        "hypotheses": [(h.id, h.confidence, h.active) for h in case_state.hypotheses],
        "evidence_count": len(case_state.evidence),
        "uncertainties": [(u.id, u.resolved) for u in case_state.uncertainties],
        "contradictions": [(c.id, c.resolved) for c in case_state.contradictions],
    }

    build_result_from_case_state(req.request_id, case_state)
    build_result_from_case_state(req.request_id, case_state)  # called twice, deliberately

    after = {
        "hypotheses": [(h.id, h.confidence, h.active) for h in case_state.hypotheses],
        "evidence_count": len(case_state.evidence),
        "uncertainties": [(u.id, u.resolved) for u in case_state.uncertainties],
        "contradictions": [(c.id, c.resolved) for c in case_state.contradictions],
    }
    assert before == after


# ---------------------------------------------------------------------------
# P7-T07 — Safety Regression (anchor test; the full matrix lives in
# test_runner.py's 24 tests, all still green post-retirement)
# ---------------------------------------------------------------------------

def test_p7_t07_safety_scenarios_unchanged_post_retirement(controller):
    req = _make_request("P7-T07", "La pédale de frein est molle et la voiture ne freine plus")
    session = controller.start(req)
    assert session.state.value == "escalated"
    assert session.result.status.value == "safety_escalation"
    assert session.result.safety_triage.level.value == "emergency_stop"


# ---------------------------------------------------------------------------
# P7-T08 — P6 Regression: two-step adaptive discrimination still passes
# after legacy removal
# ---------------------------------------------------------------------------

def test_p7_t08_p6_two_step_discrimination_survives_retirement(controller):
    req = _make_request("P7-T08", "La voiture tremble au ralenti")
    session = controller.start(req)

    session = _drive(controller, session, until_question_id="Q-COND-001")
    q1 = session.pending_questions[0]
    case_state = controller._case_states[session.session_id]
    h2 = next(h for h in case_state.hypotheses if h.hypothesis_type == "tyre_or_wheel")
    step1_before = h2.confidence

    session = controller.submit_answer(session, Answer(question_id=q1.question_id, value=["vitesse stabilisée"]))
    case_state = controller._case_states[session.session_id]
    h2_mid = next(h for h in case_state.hypotheses if h.id == h2.id).confidence
    assert h2_mid != step1_before

    session = _drive(controller, session, until_question_id="Q-EVT-002", answer_overrides={"Q-EVT-001": True})
    assert session.pending_questions and session.pending_questions[0].question_id == "Q-EVT-002"
    q2 = session.pending_questions[0]
    session = controller.submit_answer(
        session, Answer(question_id=q2.question_id, value="Changement de pneu avant gauche récemment")
    )
    case_state = controller._case_states[session.session_id]
    h2_final = next(h for h in case_state.hypotheses if h.id == h2.id).confidence
    assert h2_final > h2_mid


# ---------------------------------------------------------------------------
# P7-T09 — Packaging Regression
# ---------------------------------------------------------------------------

pytestmark_packaging = pytest.mark.packaging


@pytest.mark.packaging
def test_p7_t09_wheel_build_install_scenario_after_retirement(tmp_path_factory):
    import venv

    dist_dir = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr
    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1

    venv_dir = tmp_path_factory.mktemp("venv")
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    py = venv_dir / "bin" / "python"
    install = subprocess.run(
        [str(py), "-m", "pip", "install", "-q", str(wheels[0])],
        capture_output=True, text=True, timeout=300,
    )
    assert install.returncode == 0, install.stderr

    code = (
        "from pgdr.session_controller import SessionController\n"
        "from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState\n"
        "from pgdr.models import Consent, InitialComplaint, PreGarageDiagnosticRequest, VehicleIdentityContext, Answer\n"
        "req = PreGarageDiagnosticRequest(\n"
        "    request_id='P7-WHEEL', \n"
        "    vehicle_identity_context=VehicleIdentityContext(resolution_id='V1', resolution_status=ResolutionStatus.PROVISIONALLY_RESOLVED),\n"
        "    initial_complaint=InitialComplaint(free_text='La voiture tremble au ralenti', current_vehicle_location=VehicleLocation.HOME, vehicle_current_state=VehicleState.ENGINE_OFF),\n"
        "    consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),\n"
        ")\n"
        "c = SessionController()\n"
        "s = c.start(req)\n"
        "guard = 0\n"
        "while s.pending_questions and guard < 30:\n"
        "    guard += 1\n"
        "    q = s.pending_questions[0]\n"
        "    val = False if q.answer_type.value == 'yes_no' else 'je ne sais pas'\n"
        "    s = c.submit_answer(s, Answer(question_id=q.question_id, value=val))\n"
        "assert s.result is not None\n"
        "print('WHEEL_POST_RETIREMENT_OK')\n"
    )
    run_result = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=30)
    assert run_result.returncode == 0, run_result.stderr
    assert "WHEEL_POST_RETIREMENT_OK" in run_result.stdout


# ---------------------------------------------------------------------------
# P7-T10 — CLI/API Regression
# ---------------------------------------------------------------------------

def test_p7_t10_cli_entry_point_unchanged(tmp_path):
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
