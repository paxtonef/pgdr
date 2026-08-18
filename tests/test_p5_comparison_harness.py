"""P5 mandate §20 — comparison harness.

Runs the same diagnostic input through BOTH the legacy analytical path
(DiagnosticEngine, called directly and standalone — it is no longer
reachable via SessionController as of P5) and the new production path
(SessionController -> DiagnosticLoop), and checks for MAJOR regressions
only. Per the mandate: "Le but n'est pas d'exiger l'identité exacte...
mais il faut détecter les régressions majeures" — exact equality is not
the goal (P5 deliberately changes the analytical dynamic), catching
things like "emergency no longer blocks" or "identity context lost" is.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.diagnostic import DiagnosticEngine
from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
from pgdr.models import Consent, DiagnosticSession, InitialComplaint, PreGarageDiagnosticRequest, VehicleIdentityContext
from pgdr.session_controller import SessionController


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


def _run_legacy_standalone(request):
    """Exercises DiagnosticEngine directly and standalone — this is
    explicitly NOT how production code reaches it anymore post-P5; this
    harness is the one place in the codebase deliberately calling it, for
    comparison purposes only."""
    from pgdr.complaint_parser import ComplaintParser
    from pgdr.safety_engine import SafetyEngine

    session = DiagnosticSession(request=request)
    complaint_parser = ComplaintParser()
    extraction, symptoms = complaint_parser.extract(request.initial_complaint)
    session.symptoms = symptoms
    session.warning_indicators = complaint_parser.extract_warning_indicators(request.initial_complaint)

    triage = SafetyEngine().evaluate(session)
    session.safety_triage = triage

    if triage.level.value in ("emergency_stop", "do_not_drive"):
        return {"escalated": True, "triage": triage, "hypotheses": []}

    engine = DiagnosticEngine()
    engine.process_answers(session)
    engine.detect_contradictions(session)
    hypotheses = engine.generate_hypotheses(session)
    return {"escalated": False, "triage": triage, "hypotheses": hypotheses, "session": session}


def _run_v2_production(request):
    controller = SessionController()
    session = controller.start(request)
    from pgdr.models import Answer
    guard = 0
    while session.pending_questions and guard < 50:
        guard += 1
        q = session.pending_questions[0]
        val = False if q.answer_type.value == "yes_no" else "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))
    return session


_SCENARIOS = [
    "La voiture tremble au ralenti",
    "La pédale de frein est molle et la voiture ne freine plus",
    "Bruit métallique au démarrage à froid.",
    "Voyant batterie allumé en roulant.",
]


@pytest.mark.parametrize("complaint", _SCENARIOS)
def test_no_major_regression_between_legacy_and_v2(complaint):
    request_id = f"HARNESS-{abs(hash(complaint)) % 10000}"
    legacy_request = _make_request(request_id, complaint)
    v2_request = _make_request(request_id, complaint)

    legacy = _run_legacy_standalone(legacy_request)
    v2_session = _run_v2_production(v2_request)

    legacy_emergency = legacy["escalated"] or legacy["triage"].level.value in ("emergency_stop", "do_not_drive")
    v2_emergency = v2_session.state.value == "escalated"
    assert legacy_emergency == v2_emergency, (
        f"MAJOR REGRESSION for '{complaint}': legacy emergency={legacy_emergency}, v2 emergency={v2_emergency}"
    )

    if not legacy_emergency:
        assert legacy["hypotheses"], f"legacy produced no hypotheses for '{complaint}'"
        assert v2_session.result.diagnostic_hypotheses, (
            f"MAJOR REGRESSION for '{complaint}': v2 produced zero hypotheses where legacy produced some"
        )

    # identity context must not be lost in either path
    if not legacy_emergency:
        assert v2_session.result.vehicle_identity_summary.get("resolution_id") == v2_request.vehicle_identity_context.resolution_id
    else:
        assert v2_session.result.vehicle_identity_summary.get("resolution_id") == v2_request.vehicle_identity_context.resolution_id

    # complaint preserved verbatim in both
    assert v2_session.result.garage_preparation_report.customer_reported_problem == complaint


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
