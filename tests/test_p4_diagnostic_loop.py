"""P4 — Analytical State Model & Diagnostic Loop tests.

Covers the mandate's full P4-T01..T17 matrix (§24), with P4-T17 as the
signature test: proving Q&A genuinely changes analytical state, not just
report text (closing P2 Finding #4 — pre-P4, hypothesis confidence was
fixed at complaint-parse time regardless of any subsequent answer).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.application.case_state_updater import CaseStateUpdater
from pgdr.application.diagnostic_loop import DiagnosticIterationResult, DiagnosticLoop
from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
from pgdr.application.question_selector import DeterministicQuestionSelector
from pgdr.automotive.domain_adapter import AutomotiveDiagnosticDomain
from pgdr.automotive.evidence_mapper import AutomotiveEvidenceMapper
from pgdr.domain.contradiction import DiagnosticContradiction
from pgdr.domain.enums import AnalyticalStatus, DiagnosticStopReason, EvidenceDirection, ObservationSource
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis
from pgdr.domain.identity import MachineIdentityContext
from pgdr.domain.observation import Observation
from pgdr.domain.question import DiagnosticAnswer, DiagnosticQuestion
from pgdr.domain.safety_state import SafetyState
from pgdr.enums import AnswerType
from pgdr.models import SafetyTriage


@pytest.fixture
def loop() -> DiagnosticLoop:
    domain = AutomotiveDiagnosticDomain()
    updater = CaseStateUpdater(DeterministicHypothesisScorer())
    return DiagnosticLoop(domain, AutomotiveEvidenceMapper(), DeterministicQuestionSelector(), updater)


def _drive_to_question(loop: DiagnosticLoop, state, target_question_id: str, max_steps: int = 20):
    """Answers 'je ne sais pas' / False to every question until
    `target_question_id` is offered, or gives up after `max_steps`."""
    result = loop.run_iteration(state)
    steps = 0
    while result.next_question is not None and result.next_question.id != target_question_id and steps < max_steps:
        steps += 1
        q = result.next_question
        default = False if q.answer_type.value == "yes_no" else "je ne sais pas"
        state = loop.submit_answer(state, q, default)
        result = loop.run_iteration(state)
    return state, result


# ---------------------------------------------------------------------------
# P4-T01 — Create DiagnosticCaseState from initial complaint
# ---------------------------------------------------------------------------

def test_p4_t01_create_case_state_from_initial_complaint(loop):
    state = loop.start("La voiture tremble au ralenti")
    assert state.case_id
    raw = next(o for o in state.observations if o.kind == "raw_complaint")
    assert raw.value == "La voiture tremble au ralenti"
    assert raw.source_type == ObservationSource.USER


# ---------------------------------------------------------------------------
# P4-T02 — Initial observation generates evidence
# ---------------------------------------------------------------------------

def test_p4_t02_initial_observation_generates_evidence(loop):
    state = loop.start("La voiture tremble au ralenti")
    assert len(state.evidence) > 0


# ---------------------------------------------------------------------------
# P4-T03 — Evidence supports hypothesis
# ---------------------------------------------------------------------------

def test_p4_t03_evidence_supports_hypothesis(loop):
    state = loop.start("La voiture tremble au ralenti")
    supporting = [e for e in state.evidence if e.direction == EvidenceDirection.SUPPORTS]
    assert supporting
    hypothesis_ids = {h.id for h in state.hypotheses}
    assert all(e.target_hypothesis_id in hypothesis_ids for e in supporting)


# ---------------------------------------------------------------------------
# P4-T04 — Contradicting evidence remains attached
# ---------------------------------------------------------------------------

def test_p4_t04_contradicting_evidence_remains_attached(loop):
    state = loop.start("La voiture tremble au ralenti")
    state, result = _drive_to_question(loop, state, "Q-COND-001")
    assert result.next_question is not None and result.next_question.id == "Q-COND-001"
    state = loop.submit_answer(state, result.next_question, ["vitesse stabilisée"])

    contradicting = [e for e in state.evidence if e.direction == EvidenceDirection.CONTRADICTS]
    assert contradicting
    engine_hyp = next(h for h in state.hypotheses if h.hypothesis_type == "engine_running")
    assert engine_hyp.contradicting_evidence_ids
    assert all(eid in {e.id for e in state.evidence} for eid in engine_hyp.contradicting_evidence_ids)


# ---------------------------------------------------------------------------
# P4-T05 / T06 — Answer to a question generates an observation, which
# generates evidence
# ---------------------------------------------------------------------------

def test_p4_t05_t06_answer_generates_observation_and_evidence(loop):
    state = loop.start("La voiture tremble au ralenti")
    state, result = _drive_to_question(loop, state, "Q-COND-001")
    q = result.next_question
    obs_count_before = len(state.observations)
    evd_count_before = len(state.evidence)

    state = loop.submit_answer(state, q, ["vitesse stabilisée"])

    assert len(state.observations) == obs_count_before + 1
    new_obs = state.observations[-1]
    assert new_obs.source_ref == q.id
    assert len(state.evidence) > evd_count_before
    last_answer = state.answers[-1]
    assert last_answer.observation_ids_created == [new_obs.id]


# ---------------------------------------------------------------------------
# P4-T07 — New evidence changes hypothesis analytical state
# ---------------------------------------------------------------------------

def test_p4_t07_new_evidence_changes_hypothesis_confidence(loop):
    state = loop.start("La voiture tremble au ralenti")
    state, result = _drive_to_question(loop, state, "Q-COND-001")
    before = {h.id: h.confidence for h in state.hypotheses}

    state = loop.submit_answer(state, result.next_question, ["vitesse stabilisée"])

    after = {h.id: h.confidence for h in state.hypotheses}
    assert before != after


# ---------------------------------------------------------------------------
# P4-T08 — Question targets explicit uncertainty/hypothesis
# ---------------------------------------------------------------------------

def test_p4_t08_question_targets_explicit_hypotheses(loop):
    state = loop.start("La voiture tremble au ralenti")
    result = loop.run_iteration(state)
    assert result.next_question is not None
    assert result.next_question.target_hypothesis_ids
    assert set(result.next_question.target_hypothesis_ids) <= {h.id for h in state.hypotheses}


# ---------------------------------------------------------------------------
# P4-T09 — Answered question not asked again
# ---------------------------------------------------------------------------

def test_p4_t09_answered_question_not_asked_again(loop):
    state = loop.start("La voiture tremble au ralenti")
    result = loop.run_iteration(state)
    first_id = result.next_question.id
    state = loop.submit_answer(state, result.next_question, "je ne sais pas")

    for _ in range(10):
        result = loop.run_iteration(state)
        if result.next_question is None:
            break
        assert result.next_question.id != first_id
        state = loop.submit_answer(state, result.next_question, "je ne sais pas")


# ---------------------------------------------------------------------------
# P4-T10 — Contradiction remains unresolved unless explicitly resolved
# ---------------------------------------------------------------------------

def test_p4_t10_contradiction_remains_unresolved_unless_explicitly_resolved():
    updater = CaseStateUpdater(DeterministicHypothesisScorer())
    domain = AutomotiveDiagnosticDomain()
    loop_ = DiagnosticLoop(domain, AutomotiveEvidenceMapper(), DeterministicQuestionSelector(), updater)
    state = loop_.start("Bruit au démarrage")

    contradiction = DiagnosticContradiction(
        evidence_ids=[], hypothesis_ids=[h.id for h in state.hypotheses],
        description="Symptôme décrit comme constant puis comme rare.",
    )
    updater.detect_contradictions(state, [contradiction])

    assert len(state.unresolved_contradictions()) == 1
    assert state.contradictions[0].resolved is False
    state, result = _drive_to_question(loop_, state, "___no_such_question___", max_steps=15)
    assert state.contradictions[0].resolved is False


# ---------------------------------------------------------------------------
# P4-T11 — Critical safety state stops the loop before analytical iteration
# ---------------------------------------------------------------------------

def test_p4_t11_critical_safety_state_stops_before_iteration(loop):
    triage = SafetyTriage(level="emergency_stop", driving_assessment="do_not_drive",
                           user_instruction="Ne roulez pas.")
    state = loop.start("La pédale de frein est molle", safety_state=SafetyState(triage=triage))

    assert state.analytical_status == AnalyticalStatus.STOPPED
    assert state.stop_reason == DiagnosticStopReason.SAFETY_PREEMPTED
    assert state.hypotheses == []
    assert state.evidence == []

    result = loop.run_iteration(state)
    assert result.stop_reason == DiagnosticStopReason.SAFETY_PREEMPTED
    assert result.next_question is None


# ---------------------------------------------------------------------------
# P4-T12 — Missing identity attribute prevents configuration-dependent
# hypothesis activation
# ---------------------------------------------------------------------------

def test_p4_t12_missing_identity_attribute_deactivates_hypothesis():
    updater = CaseStateUpdater(DeterministicHypothesisScorer())
    domain = AutomotiveDiagnosticDomain()
    loop_ = DiagnosticLoop(domain, AutomotiveEvidenceMapper(), DeterministicQuestionSelector(), updater)

    identity = MachineIdentityContext(identity_ref="VIR-1", confidence=0.9, attributes={})
    state = loop_.start("Bruit moteur", identity_context=identity)

    config_dependent = DiagnosticHypothesis(
        hypothesis_type="engine_variant_specific",
        description="Nécessite le code moteur exact.",
        configuration_requirements={"engine_code": True},
    )
    state.hypotheses.append(config_dependent)
    updater.update_hypotheses(state, {config_dependent.id})

    assert config_dependent.active is False

    state.identity_context = MachineIdentityContext(
        identity_ref="VIR-1", confidence=0.9, attributes={"engine_code": "K9K"}
    )
    updater.update_hypotheses(state, {config_dependent.id})
    assert config_dependent.active is True


# ---------------------------------------------------------------------------
# P4-T13 — No useful question -> clean stop
# ---------------------------------------------------------------------------

def test_p4_t13_no_useful_question_clean_stop():
    updater = CaseStateUpdater(DeterministicHypothesisScorer())

    class _EmptyDomain:
        def interpret_observations(self, state):
            return []

        def generate_hypotheses(self, state):
            if state.hypotheses:
                return []
            return [DiagnosticHypothesis(hypothesis_type="x", description="d")]

        def map_evidence(self, state):
            return []

        def available_questions(self, state):
            return []

    class _NeverMapper:
        def from_answer(self, question, answer, state):
            return []

    loop_ = DiagnosticLoop(_EmptyDomain(), _NeverMapper(), DeterministicQuestionSelector(), updater)
    state = loop_.start("Bruit indéterminé")
    result = loop_.run_iteration(state)

    assert result.next_question is None
    assert result.stop_reason == DiagnosticStopReason.NO_AVAILABLE_QUESTION
    assert state.analytical_status == AnalyticalStatus.STOPPED


# ---------------------------------------------------------------------------
# P4-T14 — No state change prevents infinite questioning loop
# ---------------------------------------------------------------------------

def test_p4_t14_no_state_change_prevents_infinite_loop():
    updater = CaseStateUpdater(DeterministicHypothesisScorer())
    fixed_question = DiagnosticQuestion(
        id="Q-STUCK", text="?", answer_type=AnswerType.YES_NO, target_hypothesis_ids=[],
    )

    class _StuckDomain:
        def interpret_observations(self, state):
            return []

        def generate_hypotheses(self, state):
            if state.hypotheses:
                return []
            return [DiagnosticHypothesis(hypothesis_type="x", description="d")]

        def map_evidence(self, state):
            return []

        def available_questions(self, state):
            return [fixed_question]

    loop_ = DiagnosticLoop(_StuckDomain(), None, DeterministicQuestionSelector(), updater)
    state = loop_.start("Bruit indéterminé")

    first = loop_.run_iteration(state)
    assert first.next_question is not None and first.next_question.id == "Q-STUCK"

    second = loop_.run_iteration(state)
    assert second.next_question is None
    assert second.stop_reason == DiagnosticStopReason.NO_STATE_CHANGE


# ---------------------------------------------------------------------------
# P4-T15 — ReportBuilder consumes DiagnosticCaseState
# ---------------------------------------------------------------------------

def test_p4_t15_report_builder_consumes_case_state(loop):
    from pgdr.report_builder import build_from_case_state

    state = loop.start("La voiture tremble au ralenti")
    user_summary, garage_report = build_from_case_state(state)

    assert garage_report.customer_reported_problem == "La voiture tremble au ralenti"
    assert garage_report is not user_summary
    assert len(garage_report.systems_to_examine) == len(state.active_hypotheses())
    assert user_summary.urgency.get("label")


# ---------------------------------------------------------------------------
# P4-T16 — Existing PGDR (v0.1) behavior remains compatible
# ---------------------------------------------------------------------------

def test_p4_t16_existing_v01_pipeline_unaffected():
    """The pre-P4 pipeline (SessionController / SafetyEngine / DiagnosticEngine)
    must keep producing identical results — proven directly here, and by
    the full pre-existing 70-test suite still passing (verified in
    LOG_DEPLOY.md)."""
    from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
    from pgdr.models import Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest, VehicleIdentityContext
    from pgdr.session_controller import SessionController

    req = PreGarageDiagnosticRequest(
        request_id="P4-COMPAT-001",
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id="VIR-1", resolution_status=ResolutionStatus.PROVISIONALLY_RESOLVED,
        ),
        initial_complaint=InitialComplaint(
            free_text="La voiture tremble au ralenti",
            current_vehicle_location=VehicleLocation.HOME,
            vehicle_current_state=VehicleState.ENGINE_OFF,
        ),
        consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),
    )
    controller = SessionController()
    session = controller.start(req)
    guard = 0
    while session.pending_questions and guard < 50:
        guard += 1
        q = session.pending_questions[0]
        val = False if q.answer_type.value == "yes_no" else "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))

    assert session.result is not None
    assert session.result.garage_preparation_report.customer_reported_problem == req.initial_complaint.free_text


# ---------------------------------------------------------------------------
# P4-T17 — THE SIGNATURE TEST
#
# "The diagnostic state after answering a question is analytically
# different from the diagnostic state before answering it" — and,
# critically, DIFFERENTLY for different hypotheses, not a uniform bump.
# Proves P2 Finding #4 (hypothesis confidence fixed regardless of Q&A) is
# closed.
# ---------------------------------------------------------------------------

def test_p4_t17_signature_qa_changes_reasoning_not_only_report(loop):
    state = loop.start("La voiture tremble au ralenti")
    assert len(state.hypotheses) >= 2, "need at least 2 active hypotheses for this test to be meaningful"

    h1 = next(h for h in state.hypotheses if h.hypothesis_type == "engine_running")
    h2 = next(h for h in state.hypotheses if h.hypothesis_type == "tyre_or_wheel")
    confidence_h1_before = h1.confidence
    confidence_h2_before = h2.confidence

    state, result = _drive_to_question(loop, state, "Q-COND-001")
    assert result.next_question is not None and result.next_question.id == "Q-COND-001"

    state = loop.submit_answer(state, result.next_question, ["vitesse stabilisée"])
    h1_after = next(h for h in state.hypotheses if h.id == h1.id)
    h2_after = next(h for h in state.hypotheses if h.id == h2.id)

    # H1 (engine_running) is contradicted by this answer -> confidence decreases
    assert h1_after.confidence < confidence_h1_before
    # H2 (tyre_or_wheel) is supported by this answer -> confidence increases
    assert h2_after.confidence > confidence_h2_before
    # The two hypotheses move in OPPOSITE directions — proving the answer
    # discriminated between them rather than uniformly nudging every
    # active hypothesis the way a non-analytical "acknowledgment" would.
    assert (h1_after.confidence - confidence_h1_before) * (h2_after.confidence - confidence_h2_before) < 0

    from pgdr.report_builder import build_from_case_state
    _, garage_report = build_from_case_state(state)
    by_family = {s["system_family"]: s["confidence"] for s in garage_report.systems_to_examine}
    assert by_family["tyre_or_wheel"] > by_family["engine_running"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
