"""P5 — PGDR v2 Integration & Automotive Domain Enrichment tests.

Tests the PRODUCTION path (SessionController) explicitly, not the
isolated DiagnosticLoop the way P4's tests did — that distinction is the
whole point of P5-T21, the signature test for this phase.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.domain.enums import EvidenceDirection
from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
from pgdr.errors import ConfigurationError
from pgdr.models import Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest, VehicleIdentityContext
from pgdr.session_controller import SessionController


def _make_request(request_id, complaint, vir_status=ResolutionStatus.PROVISIONALLY_RESOLVED, vir_id=None):
    return PreGarageDiagnosticRequest(
        request_id=request_id,
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=vir_id or f"VIR-{request_id}", resolution_status=vir_status,
        ),
        initial_complaint=InitialComplaint(
            free_text=complaint, current_vehicle_location=VehicleLocation.HOME,
            vehicle_current_state=VehicleState.ENGINE_OFF,
        ),
        consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),
    )


def _answer_all(controller, session, value_fn=None):
    guard = 0
    while session.pending_questions:
        guard += 1
        assert guard < 50, "question loop did not terminate"
        q = session.pending_questions[0]
        if value_fn:
            val = value_fn(q)
        elif q.answer_type.value == "yes_no":
            val = False
        elif q.answer_type.value == "multiple_choice":
            val = ["je ne sais pas"]
        else:
            val = "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))
    return session


@pytest.fixture
def controller():
    return SessionController()


# ---------------------------------------------------------------------------
# P5-T01 — SessionController initializes DiagnosticCaseState
# ---------------------------------------------------------------------------

def test_p5_t01_session_controller_initializes_case_state(controller):
    req = _make_request("P5-T01", "La voiture tremble au ralenti")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]
    assert case_state is not None
    assert case_state.observations


# ---------------------------------------------------------------------------
# P5-T02 — SessionController uses DiagnosticLoop
# ---------------------------------------------------------------------------

def test_p5_t02_session_controller_uses_diagnostic_loop(controller):
    req = _make_request("P5-T02", "La voiture tremble au ralenti")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]
    assert case_state.iteration >= 1


# ---------------------------------------------------------------------------
# P5-T03 — Legacy DiagnosticEngine is not authoritative
# ---------------------------------------------------------------------------

def test_p5_t03_legacy_diagnostic_engine_not_authoritative(controller, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("legacy DiagnosticEngine method was called on the production path")

    monkeypatch.setattr(controller.diagnostic_engine, "generate_hypotheses", _boom)
    monkeypatch.setattr(controller.diagnostic_engine, "process_answers", _boom)

    req = _make_request("P5-T03", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _answer_all(controller, session)
    assert session.result is not None


# ---------------------------------------------------------------------------
# P5-T04 — Critical safety preempts DiagnosticLoop
# ---------------------------------------------------------------------------

def test_p5_t04_critical_safety_preempts_diagnostic_loop(controller):
    req = _make_request("P5-T04", "La pédale de frein est molle et la voiture ne freine plus")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]

    assert session.safety_triage.level.value == "emergency_stop"
    assert case_state.stop_reason.value == "SAFETY_PREEMPTED"
    assert case_state.hypotheses == []
    assert session.pending_questions == []


# ---------------------------------------------------------------------------
# P5-T05 — Initial complaint produces canonical observations
# ---------------------------------------------------------------------------

def test_p5_t05_initial_complaint_produces_canonical_observations(controller):
    req = _make_request("P5-T05", "Bruit métallique au démarrage à froid.")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]

    kinds = {o.kind for o in case_state.observations}
    assert "raw_complaint" in kinds
    assert "symptom" in kinds


# ---------------------------------------------------------------------------
# P5-T06 — VIR context is preserved in CaseState
# ---------------------------------------------------------------------------

def test_p5_t06_vir_context_preserved_in_case_state(controller):
    req = _make_request("P5-T06", "Voyant batterie allumé", vir_id="VIR-SPECIFIC-123")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]

    assert case_state.identity_context is not None
    assert case_state.identity_context.identity_ref == "VIR-SPECIFIC-123"


# ---------------------------------------------------------------------------
# P5-T07 — Question selected by v2 selector reaches user interaction
# ---------------------------------------------------------------------------

def test_p5_t07_v2_selected_question_reaches_user(controller):
    req = _make_request("P5-T07", "La voiture tremble au ralenti")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]

    assert len(session.pending_questions) == 1
    presented_id = session.pending_questions[0].question_id
    assert any(q.id == presented_id for q in case_state.questions)


# ---------------------------------------------------------------------------
# P5-T08 / T09 — Answer is recorded in state / creates an observation
# ---------------------------------------------------------------------------

def test_p5_t08_t09_answer_recorded_and_creates_observation(controller):
    req = _make_request("P5-T08", "La voiture tremble au ralenti")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]
    obs_before = len(case_state.observations)
    answers_before = len(case_state.answers)

    q = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q.question_id, value="je ne sais pas"))
    case_state = controller._case_states[session.session_id]

    assert len(case_state.answers) == answers_before + 1
    assert len(case_state.observations) > obs_before


# ---------------------------------------------------------------------------
# P5-T10 / T11 — Observation creates evidence / evidence updates hypothesis score
# ---------------------------------------------------------------------------

def test_p5_t10_t11_observation_creates_evidence_that_updates_hypothesis(controller):
    req = _make_request("P5-T10", "La voiture tremble au ralenti")
    session = controller.start(req)

    guard = 0
    while session.pending_questions and session.pending_questions[0].question_id != "Q-COND-001" and guard < 20:
        guard += 1
        q = session.pending_questions[0]
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value="je ne sais pas"))

    assert session.pending_questions and session.pending_questions[0].question_id == "Q-COND-001"
    case_state = controller._case_states[session.session_id]
    before = {h.id: h.confidence for h in case_state.hypotheses}
    evidence_before = len(case_state.evidence)

    q = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q.question_id, value=["vitesse stabilisée"]))
    case_state = controller._case_states[session.session_id]

    assert len(case_state.evidence) > evidence_before
    after = {h.id: h.confidence for h in case_state.hypotheses}
    assert before != after


# ---------------------------------------------------------------------------
# P5-T12 — Updated hypothesis affects next question
# ---------------------------------------------------------------------------

def test_p5_t12_updated_hypothesis_affects_next_question(controller):
    req = _make_request("P5-T12", "La voiture tremble au ralenti")
    session = controller.start(req)

    seen_ids = []
    guard = 0
    while session.pending_questions and guard < 20:
        guard += 1
        q = session.pending_questions[0]
        seen_ids.append(q.question_id)
        val = ["vitesse stabilisée"] if q.question_id == "Q-COND-001" else "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))

    assert seen_ids.count("Q-COND-001") == 1


# ---------------------------------------------------------------------------
# P5-T13 — Resolved uncertainty is not targeted again
#
# AutomotiveDiagnosticDomain does not yet GENERATE DiagnosticUncertainty
# objects (a documented, honest gap — see p5_findings.md) so this is
# tested at the mechanism level, directly against CaseStateUpdater, the
# same way P4 tested configuration_requirements gating.
# ---------------------------------------------------------------------------

def test_p5_t13_resolved_uncertainty_not_targeted_again():
    from pgdr.application.case_state_updater import CaseStateUpdater
    from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
    from pgdr.domain.analytical_state import DiagnosticCaseState
    from pgdr.domain.enums import UncertaintyKind
    from pgdr.domain.uncertainty import DiagnosticUncertainty

    updater = CaseStateUpdater(DeterministicHypothesisScorer())
    state = DiagnosticCaseState()
    u = DiagnosticUncertainty(kind=UncertaintyKind.SYMPTOM, description="test uncertainty")
    updater.update_uncertainties(state, new_uncertainties=[u])
    assert state.unresolved_uncertainties() == [u]

    updater.update_uncertainties(state, resolved_ids={u.id})
    assert state.unresolved_uncertainties() == []
    assert u.resolved is True


# ---------------------------------------------------------------------------
# P5-T14 — Unresolved contradiction persists
# ---------------------------------------------------------------------------

def test_p5_t14_unresolved_contradiction_persists(controller):
    req = _make_request(
        "P5-T14",
        "La voiture ne démarre jamais le matin mais j'ai réussi à rouler 50km hier.",
        vir_status=ResolutionStatus.CONTRADICTORY,
    )
    session = controller.start(req)
    session = _answer_all(controller, session)

    assert len(session.result.contradictions) >= 1
    case_state = controller._case_states[session.session_id]
    assert case_state.unresolved_contradictions()


# ---------------------------------------------------------------------------
# P5-T15 — No state progress terminates cleanly
# ---------------------------------------------------------------------------

def test_p5_t15_no_state_progress_terminates_cleanly(controller):
    req = _make_request("P5-T15", "Bruit indéterminé")
    session = controller.start(req)
    session = _answer_all(controller, session)
    assert session.result is not None


# ---------------------------------------------------------------------------
# P5-T16 — Answered non-repeatable question is not re-asked
# ---------------------------------------------------------------------------

def test_p5_t16_answered_question_not_reasked(controller):
    req = _make_request("P5-T16", "La voiture tremble au ralenti")
    session = controller.start(req)

    seen = []
    guard = 0
    while session.pending_questions and guard < 20:
        guard += 1
        q = session.pending_questions[0]
        seen.append(q.question_id)
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value="je ne sais pas"))

    assert len(seen) == len(set(seen))


# ---------------------------------------------------------------------------
# P5-T17 / T18 / T19 — ReportBuilder reads CaseState; UserSummary and
# GarageReport both generated from the same canonical state
# ---------------------------------------------------------------------------

def test_p5_t17_t18_t19_reports_generated_from_same_canonical_state(controller):
    req = _make_request("P5-T17", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _answer_all(controller, session)

    assert session.result.garage_preparation_report is not None
    assert session.result.user_summary is not None
    assert session.result.garage_preparation_report is not session.result.user_summary
    assert (
        session.result.garage_preparation_report.customer_reported_problem
        == req.initial_complaint.free_text
    )
    assert session.result.user_summary.main_observations == [req.initial_complaint.free_text]


# ---------------------------------------------------------------------------
# P5-T20 — Existing emergency behavior unchanged
# ---------------------------------------------------------------------------

def test_p5_t20_existing_emergency_behavior_unchanged(controller):
    req = _make_request("P5-T20", "La pédale de frein est molle et la voiture ne freine plus")
    session = controller.start(req)

    assert session.state.value == "escalated"
    assert session.result.status.value == "safety_escalation"
    assert session.result.safety_triage.driving_assessment.value == "do_not_drive"
    assert "ne roulez pas" in session.result.safety_triage.user_instruction.lower()


# ---------------------------------------------------------------------------
# P5-T21 — THE SIGNATURE TEST: the PRODUCT itself is adaptive, not just
# the isolated P4 engine.
# ---------------------------------------------------------------------------

def test_p5_t21_signature_adaptive_product_path(controller):
    req = _make_request("P5-T21", "La voiture tremble au ralenti")
    session = controller.start(req)

    guard = 0
    while session.pending_questions and session.pending_questions[0].question_id != "Q-COND-001" and guard < 20:
        guard += 1
        q = session.pending_questions[0]
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value="je ne sais pas"))

    assert session.pending_questions and session.pending_questions[0].question_id == "Q-COND-001"
    q1 = session.pending_questions[0]

    case_state = controller._case_states[session.session_id]
    h1 = next(h for h in case_state.hypotheses if h.hypothesis_type == "engine_running")
    h2 = next(h for h in case_state.hypotheses if h.hypothesis_type == "tyre_or_wheel")
    before = (h1.confidence, h2.confidence)

    session = controller.submit_answer(session, Answer(question_id=q1.question_id, value=["vitesse stabilisée"]))
    case_state = controller._case_states[session.session_id]

    h1_after = next(h for h in case_state.hypotheses if h.id == h1.id)
    h2_after = next(h for h in case_state.hypotheses if h.id == h2.id)
    after = (h1_after.confidence, h2_after.confidence)

    assert before != after
    assert h1_after.confidence < before[0]
    assert h2_after.confidence > before[1]

    session = _answer_all(controller, session)
    assert session.result is not None


# ---------------------------------------------------------------------------
# Domain enrichment tests (§25) — test the DECLARED semantics of the one
# MAPPED question, not merely "an Evidence object exists"
# ---------------------------------------------------------------------------

def test_domain_enrichment_q_cond_001_semantics_are_correct():
    from pgdr.automotive.evidence_mapper import _DISCRIMINATING_RULES

    rule = _DISCRIMINATING_RULES["Q-COND-001"]
    assert rule["au ralenti / démarrage"]["engine_running"] == EvidenceDirection.SUPPORTS
    assert rule["au ralenti / démarrage"]["tyre_or_wheel"] == EvidenceDirection.CONTRADICTS
    assert rule["vitesse stabilisée"]["tyre_or_wheel"] == EvidenceDirection.SUPPORTS
    assert rule["vitesse stabilisée"]["engine_running"] == EvidenceDirection.CONTRADICTS


# ---------------------------------------------------------------------------
# Neutral question behavior (§26)
# ---------------------------------------------------------------------------

def test_neutral_question_stores_observation_without_fabricating_hypothesis_impact(controller):
    from pgdr.automotive.question_classification import QuestionMigrationStatus, classify_questions

    classification = classify_questions()
    assert classification["Q-STATE-001"] == QuestionMigrationStatus.NEUTRAL

    req = _make_request("P5-NEUTRAL", "La voiture tremble au ralenti")
    session = controller.start(req)
    assert session.pending_questions[0].question_id == "Q-STATE-001"

    case_state = controller._case_states[session.session_id]
    before = {h.id: h.confidence for h in case_state.hypotheses}

    q = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q.question_id, value="atelier"))
    case_state = controller._case_states[session.session_id]
    after = {h.id: h.confidence for h in case_state.hypotheses}

    assert any(o.source_ref == "Q-STATE-001" for o in case_state.observations)
    assert before == after

    q_state_001_obs_ids = {o.id for o in case_state.observations if o.source_ref == "Q-STATE-001"}
    q_state_001_evidence = [
        e for e in case_state.evidence if set(e.observation_ids) & q_state_001_obs_ids
    ]
    assert all(e.direction == EvidenceDirection.NEUTRAL for e in q_state_001_evidence)


# ---------------------------------------------------------------------------
# Question classification coverage (§10) — 100% explicitly classified,
# not 100% MAPPED
# ---------------------------------------------------------------------------

def test_all_questions_are_explicitly_classified():
    from pgdr.automotive.question_classification import classify_questions
    from pgdr.config_loader import load_questions

    classification = classify_questions()
    all_ids = {q["question_id"] for q in load_questions().get("questions", [])}
    assert set(classification.keys()) == all_ids
    assert all(v is not None for v in classification.values())


# ---------------------------------------------------------------------------
# Configuration validation (§28/§29) — dangling domain reference caught
# at startup, not mid-session
# ---------------------------------------------------------------------------

def test_domain_validator_catches_dangling_hypothesis_reference(monkeypatch):
    import pgdr.automotive.evidence_mapper as evidence_mapper_module
    from pgdr.automotive.domain_validator import validate_automotive_domain

    bad_rules = {
        "Q-COND-001": {
            "au ralenti / démarrage": {"nonexistent_hypothesis_type": EvidenceDirection.SUPPORTS},
        },
    }
    monkeypatch.setattr(evidence_mapper_module, "_DISCRIMINATING_RULES", bad_rules)

    with pytest.raises(ConfigurationError, match="dangling domain reference"):
        validate_automotive_domain()


def test_domain_validator_catches_reference_to_unknown_question_id(monkeypatch):
    import pgdr.automotive.evidence_mapper as evidence_mapper_module
    from pgdr.automotive.domain_validator import validate_automotive_domain

    bad_rules = {
        "Q-DOES-NOT-EXIST": {"yes": {"engine_running": EvidenceDirection.SUPPORTS}},
    }
    monkeypatch.setattr(evidence_mapper_module, "_DISCRIMINATING_RULES", bad_rules)

    with pytest.raises(ConfigurationError, match="unknown question_id"):
        validate_automotive_domain()


def test_domain_validator_passes_on_real_configuration():
    from pgdr.automotive.domain_validator import validate_automotive_domain
    validate_automotive_domain()


def test_session_controller_construction_fails_closed_on_broken_domain_config(monkeypatch):
    import pgdr.automotive.evidence_mapper as evidence_mapper_module

    bad_rules = {"Q-COND-001": {"x": {"nonexistent": EvidenceDirection.SUPPORTS}}}
    monkeypatch.setattr(evidence_mapper_module, "_DISCRIMINATING_RULES", bad_rules)

    with pytest.raises(ConfigurationError):
        SessionController()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
