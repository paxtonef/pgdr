"""P6 — Automotive Evidence & Capability Enrichment tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.automotive.coverage import compute_coverage
from pgdr.domain.enums import EvidenceDirection
from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
from pgdr.errors import ConfigurationError
from pgdr.models import Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest, VehicleIdentityContext
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


@pytest.fixture
def controller():
    return SessionController()


def _drive(controller, session, until_question_id, answer_overrides=None):
    """Answers everything with sensible defaults, applying
    `answer_overrides` (question_id -> value) when reached, until
    `until_question_id` is presented (not yet answered)."""
    answer_overrides = answer_overrides or {}
    guard = 0
    while session.pending_questions and session.pending_questions[0].question_id != until_question_id and guard < 30:
        guard += 1
        q = session.pending_questions[0]
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
# P6-T01 — Every automotive question has explicit classification
# ---------------------------------------------------------------------------

def test_p6_t01_every_question_has_explicit_classification():
    from pgdr.config_loader import load_questions

    report = compute_coverage()
    all_ids = {q["question_id"] for q in load_questions().get("questions", [])}
    covered_ids = {q.question_id for q in report.questions}
    assert covered_ids == all_ids
    assert all(q.status is not None for q in report.questions)


# ---------------------------------------------------------------------------
# P6-T02 — Every automotive hypothesis has explicit coverage status
# ---------------------------------------------------------------------------

def test_p6_t02_every_hypothesis_has_explicit_coverage_status():
    from pgdr.diagnostic import _HYPOTHESIS_MAP

    report = compute_coverage()
    all_types = {sf for entries in _HYPOTHESIS_MAP.values() for sf, *_ in entries}
    covered_types = {h.hypothesis_type for h in report.hypotheses}
    assert covered_types == all_types


# ---------------------------------------------------------------------------
# P6-T03 / T04 — MAPPED SUPPORTS / CONTRADICTS relations produce evidence
# ---------------------------------------------------------------------------

def test_p6_t03_t04_mapped_supports_and_contradicts_produce_evidence(controller):
    req = _make_request("P6-T03", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive(controller, session, "Q-COND-001")

    q = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q.question_id, value=["vitesse stabilisée"]))
    case_state = controller._case_states[session.session_id]

    supports = [e for e in case_state.evidence if e.direction == EvidenceDirection.SUPPORTS]
    contradicts = [e for e in case_state.evidence if e.direction == EvidenceDirection.CONTRADICTS]
    assert supports and contradicts


# ---------------------------------------------------------------------------
# P6-T05 — Neutral question never changes hypothesis
# ---------------------------------------------------------------------------

def test_p6_t05_neutral_question_never_changes_hypothesis(controller):
    req = _make_request("P6-T05", "La voiture tremble au ralenti")
    session = controller.start(req)
    assert session.pending_questions[0].question_id == "Q-STATE-001"  # NEUTRAL

    case_state = controller._case_states[session.session_id]
    before = {h.id: h.confidence for h in case_state.hypotheses}
    q = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q.question_id, value="atelier"))
    case_state = controller._case_states[session.session_id]
    after = {h.id: h.confidence for h in case_state.hypotheses}
    assert before == after


# ---------------------------------------------------------------------------
# P6-T06 / T07 — Invalid question/hypothesis reference fails validation
# ---------------------------------------------------------------------------

def test_p6_t06_invalid_question_reference_fails_validation(monkeypatch):
    import pgdr.automotive.evidence_mapper as em
    from pgdr.automotive.domain_validator import validate_automotive_domain

    monkeypatch.setattr(em, "_PROVISIONAL_KEYWORD_RULES", {
        "Q-DOES-NOT-EXIST": [(["pneu"], "tyre_or_wheel", EvidenceDirection.SUPPORTS, "PROVISIONAL - test")],
    })
    with pytest.raises(ConfigurationError, match="unknown question_id"):
        validate_automotive_domain()


def test_p6_t07_invalid_hypothesis_reference_fails_validation(monkeypatch):
    import pgdr.automotive.evidence_mapper as em
    from pgdr.automotive.domain_validator import validate_automotive_domain

    monkeypatch.setattr(em, "_PROVISIONAL_KEYWORD_RULES", {
        "Q-EVT-002": [(["pneu"], "nonexistent_type", EvidenceDirection.SUPPORTS, "PROVISIONAL - test")],
    })
    with pytest.raises(ConfigurationError, match="dangling domain reference"):
        validate_automotive_domain()


# ---------------------------------------------------------------------------
# P6-T08 / T17 — mapping without rationale/PROVISIONAL marker fails validation
# ---------------------------------------------------------------------------

def test_p6_t08_t17_mapping_without_provisional_marker_fails_validation(monkeypatch):
    import pgdr.automotive.evidence_mapper as em
    from pgdr.automotive.domain_validator import validate_automotive_domain

    monkeypatch.setattr(em, "_PROVISIONAL_KEYWORD_RULES", {
        "Q-EVT-002": [(["pneu"], "tyre_or_wheel", EvidenceDirection.SUPPORTS, "just a guess, no rationale")],
    })
    with pytest.raises(ConfigurationError, match="PROVISIONAL"):
        validate_automotive_domain()


# ---------------------------------------------------------------------------
# P6-T09 — Invalid evidence weight fails validation
# ---------------------------------------------------------------------------

def test_p6_t09_invalid_evidence_weight_fails_validation(monkeypatch):
    import pgdr.automotive.evidence_mapper as em
    from pgdr.automotive.domain_validator import validate_automotive_domain

    monkeypatch.setattr(em, "_PROVISIONAL_WEIGHT", 1.5)
    with pytest.raises(ConfigurationError, match="out of bounds"):
        validate_automotive_domain()


# ---------------------------------------------------------------------------
# P6-T10 — Configuration-dependent hypothesis inactive when required
# identity attribute absent (mechanism-level, same pattern as P4-T12)
# ---------------------------------------------------------------------------

def test_p6_t10_configuration_dependent_hypothesis_inactive_without_attribute():
    from pgdr.application.case_state_updater import CaseStateUpdater
    from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
    from pgdr.domain.analytical_state import DiagnosticCaseState
    from pgdr.domain.hypothesis import DiagnosticHypothesis
    from pgdr.domain.identity import MachineIdentityContext

    updater = CaseStateUpdater(DeterministicHypothesisScorer())
    state = DiagnosticCaseState(identity_context=MachineIdentityContext(attributes={}))
    h = DiagnosticHypothesis(
        hypothesis_type="turbo_specific", description="d",
        configuration_requirements={"turbocharged": True},
    )
    state.hypotheses.append(h)
    updater.update_hypotheses(state, {h.id})
    assert h.active is False


# ---------------------------------------------------------------------------
# P6-T11 — Multi-hypothesis discriminating answer updates hypotheses in
# opposite directions (same evidence as P5-T21, re-asserted here as P6
# domain-enrichment coverage)
# ---------------------------------------------------------------------------

def test_p6_t11_multi_hypothesis_discriminating_answer_opposite_directions(controller):
    req = _make_request("P6-T11", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive(controller, session, "Q-COND-001")

    case_state = controller._case_states[session.session_id]
    h1 = next(h for h in case_state.hypotheses if h.hypothesis_type == "engine_running")
    h2 = next(h for h in case_state.hypotheses if h.hypothesis_type == "tyre_or_wheel")
    before = (h1.confidence, h2.confidence)

    q = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q.question_id, value=["vitesse stabilisée"]))
    case_state = controller._case_states[session.session_id]
    h1_after = next(h for h in case_state.hypotheses if h.id == h1.id)
    h2_after = next(h for h in case_state.hypotheses if h.id == h2.id)

    assert h1_after.confidence < before[0]
    assert h2_after.confidence > before[1]


# ---------------------------------------------------------------------------
# P6-T12 — Contradictory observations remain represented (re-uses P5
# scenario; asserted here as domain-enrichment coverage)
# ---------------------------------------------------------------------------

def test_p6_t12_contradictory_observations_remain_represented(controller):
    req = _make_request(
        "P6-T12",
        "La voiture ne démarre jamais le matin mais j'ai réussi à rouler 50km hier.",
        vir_status=ResolutionStatus.CONTRADICTORY,
    )
    session = controller.start(req)
    session = _drive(controller, session, "___never___")
    assert len(session.result.contradictions) >= 1


# ---------------------------------------------------------------------------
# P6-T13 — Safety state remains independent from causal hypothesis scoring
# ---------------------------------------------------------------------------

def test_p6_t13_safety_independent_from_causal_scoring(controller):
    """A soft-brake-pedal complaint triggers emergency_stop (deterministic
    safety) — this must NOT translate into any 'confirmed master cylinder
    failure' hypothesis; the loop halts before any hypothesis is even
    generated, per the mandate's own §20 boundary."""
    req = _make_request("P6-T13", "La pédale de frein est molle et la voiture ne freine plus")
    session = controller.start(req)
    case_state = controller._case_states[session.session_id]

    assert session.safety_triage.level.value == "emergency_stop"
    assert case_state.hypotheses == []  # no causal hypothesis fabricated from the safety signal


# ---------------------------------------------------------------------------
# P6-T16 — Coverage metrics match real Domain Pack (i.e. are genuinely computed)
# ---------------------------------------------------------------------------

def test_p6_t16_coverage_metrics_match_real_domain_pack():
    report = compute_coverage()
    assert report.question_counts.get("MAPPED", 0) == 2  # Q-COND-001, Q-EVT-002
    assert report.hypothesis_counts.get("EVIDENCE_LINKED", 0) == 2  # engine_running, tyre_or_wheel
    assert report.question_counts.get("INVALID", 0) == 0


# ---------------------------------------------------------------------------
# P6 signature test (§24) — TWO evidence-driven discrimination steps in
# one session, not just Q-COND-001 alone.
# ---------------------------------------------------------------------------

def test_p6_signature_two_step_adaptive_discrimination(controller):
    req = _make_request("P6-SIG", "La voiture tremble au ralenti")
    session = controller.start(req)

    session = _drive(controller, session, "Q-COND-001")
    q1 = session.pending_questions[0]
    case_state = controller._case_states[session.session_id]
    h1 = next(h for h in case_state.hypotheses if h.hypothesis_type == "engine_running")
    h2 = next(h for h in case_state.hypotheses if h.hypothesis_type == "tyre_or_wheel")
    step1_before = (h1.confidence, h2.confidence)

    session = controller.submit_answer(session, Answer(question_id=q1.question_id, value=["vitesse stabilisée"]))
    case_state = controller._case_states[session.session_id]
    h1_mid = next(h for h in case_state.hypotheses if h.id == h1.id).confidence
    h2_mid = next(h for h in case_state.hypotheses if h.id == h2.id).confidence
    assert (h1_mid, h2_mid) != step1_before

    session = _drive(controller, session, "Q-EVT-002", answer_overrides={"Q-EVT-001": True})
    assert session.pending_questions and session.pending_questions[0].question_id == "Q-EVT-002"
    q2 = session.pending_questions[0]

    session = controller.submit_answer(
        session, Answer(question_id=q2.question_id, value="Changement de pneu avant gauche récemment")
    )
    case_state = controller._case_states[session.session_id]
    h2_final = next(h for h in case_state.hypotheses if h.id == h2.id).confidence

    assert h2_final > h2_mid
    assert h2_final != step1_before[1]

    session = _drive(controller, session, "___never___")
    assert session.result is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
