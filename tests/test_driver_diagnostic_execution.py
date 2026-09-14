"""PGDR Driver Diagnostic Execution Mandate v0 — required tests (§16) and
acceptance journeys (§17/§18).

Tests the production path (SessionController), the same convention P5's
own integration tests use, since this mandate wires Driver Diagnostic
content through the same production reporting path
(build_from_case_state / build_result_from_case_state), unmodified.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pgdr.enums import (
    AnswerType, ClaimStatus, Confidence, Deadline, DrivingAssessment,
    ResolutionStatus, TriageLevel, VehicleLocation, VehicleState,
)
from pgdr.models import (
    Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest,
    UserContext, VehicleIdentityContext,
)
from pgdr.session_controller import SessionController

WARNING_LIGHT_COMPLAINT = (
    "Le voyant moteur s'est allumé sur le tableau de bord et je sens une perte de puissance."
)
EMERGENCY_WARNING_COMPLAINT = "Le voyant moteur est allumé et il y a de la fumée sous le capot."
PLAIN_NOISE_COMPLAINT = "J'entends un bruit bizarre quand j'accélère."
VIBRATION_COMPLAINT = "J'ai une vibration au niveau du moteur."


def _make_request(request_id: str, complaint: str) -> PreGarageDiagnosticRequest:
    return PreGarageDiagnosticRequest(
        request_id=request_id,
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=f"VIR-{request_id}", resolution_status=ResolutionStatus.PROVISIONALLY_RESOLVED,
        ),
        initial_complaint=InitialComplaint(
            free_text=complaint, current_vehicle_location=VehicleLocation.HOME,
            vehicle_current_state=VehicleState.ENGINE_OFF,
        ),
        user_context=UserContext(),
        consent=Consent(media_analysis_allowed=True, report_storage_allowed=True),
    )


def _run_to_completion(controller, request, answer_plan=None):
    """Drives a session to completion. `answer_plan` is an optional
    dict[question_id -> value]; any question not in the plan gets a safe
    generic default derived from its own shape."""
    answer_plan = answer_plan or {}
    session = controller.start(request)
    guard = 0
    while session.pending_questions and guard < 50:
        guard += 1
        q = session.pending_questions[0]
        if q.question_id in answer_plan:
            value = answer_plan[q.question_id]
        elif q.answer_type == "media_upload":
            value = "media-ref-test-001"
        elif q.answer_type == "yes_no":
            value = False
        elif q.choices:
            value = q.choices[0]
        else:
            value = "réponse de test"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))
    assert not session.pending_questions, "guard exhausted before session completed"
    return session


# ---------------------------------------------------------------------------
# §16 required tests
# ---------------------------------------------------------------------------

class TestDriverGarageSeparation:
    def test_1_user_summary_and_garage_report_remain_separate(self):
        """§16.1 / PGDR-AC-010."""
        controller = SessionController(governance_enabled=False)
        session = _run_to_completion(controller, _make_request("T1", PLAIN_NOISE_COMPLAINT))
        result = session.result
        assert result.user_summary is not None
        assert result.garage_preparation_report is not None
        assert result.user_summary is not result.garage_preparation_report
        assert type(result.user_summary).__name__ == "UserSummary"
        assert type(result.garage_preparation_report).__name__ == "GaragePreparationReport"


class TestSafetyIndependence:
    def test_2_safety_not_derived_from_diagnostic_confidence(self):
        """§16.2 / Decision D01 — same complaint (a non-preempting safety
        level, so the analytical loop actually runs), two runs that
        diverge only in Q-COND-001's answer (which shifts
        diagnostic_confidence via a real, empirically-confirmed
        discriminating rule), must produce the SAME safety_level /
        driveability / urgency_deadline despite DIFFERENT
        diagnostic_confidence."""
        controller_a = SessionController(governance_enabled=False)
        controller_b = SessionController(governance_enabled=False)

        session_a = _run_to_completion(
            controller_a, _make_request("T2A", VIBRATION_COMPLAINT),
            answer_plan={"Q-COND-001": ["au ralenti / démarrage"]},
        )
        session_b = _run_to_completion(
            controller_b, _make_request("T2B", VIBRATION_COMPLAINT),
            answer_plan={"Q-COND-001": ["je ne sais pas"]},
        )
        us_a, us_b = session_a.result.user_summary, session_b.result.user_summary

        assert us_a.diagnostic_confidence != us_b.diagnostic_confidence, (
            "the discriminating answer must actually have shifted confidence, or this test proves nothing"
        )
        assert us_a.safety_level == us_b.safety_level
        assert us_a.driveability == us_b.driveability
        assert us_a.urgency_deadline == us_b.urgency_deadline

    def test_2b_safety_engine_evaluate_runs_before_any_hypothesis_or_confidence_exists(self):
        """Structural corroboration: SafetyEngine.evaluate() is called in
        SessionController.start(), before case_state (and therefore any
        hypothesis/confidence) is even created — see session_controller.py."""
        import inspect
        from pgdr.safety_engine import SafetyEngine
        source = inspect.getsource(SafetyEngine.evaluate)
        assert "confidence" not in source.lower()
        assert "hypothes" not in source.lower()

    def test_2c_emergency_case_has_no_confidence_yet_but_full_safety_state(self):
        """The most direct proof: an EMERGENCY_STOP case is resolved
        before any question is asked, so diagnostic_confidence is
        genuinely None — yet safety_level/driveability/urgency_deadline
        are all fully, correctly populated."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T2C", EMERGENCY_WARNING_COMPLAINT))
        assert not session.pending_questions
        us = session.result.user_summary
        assert us.diagnostic_confidence is None
        assert us.safety_level == TriageLevel.EMERGENCY_STOP
        assert us.driveability == DrivingAssessment.DO_NOT_DRIVE
        assert us.urgency_deadline == Deadline.IMMEDIATE


class TestDriveability:
    def test_3_driver_output_exposes_driveability(self):
        """§16.3."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T3", EMERGENCY_WARNING_COMPLAINT))
        us = session.result.user_summary
        assert isinstance(us.driveability, DrivingAssessment)
        assert us.driveability == DrivingAssessment.DO_NOT_DRIVE
        # PGDR-INV-003 boundary contract: 'safe_to_drive' must never exist.
        assert "SAFE_TO_DRIVE" not in DrivingAssessment.__members__


class TestUrgencyDeadline:
    def test_4_driver_output_exposes_explicit_urgency_deadline(self):
        """§16.4."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T4", EMERGENCY_WARNING_COMPLAINT))
        us = session.result.user_summary
        assert isinstance(us.urgency_deadline, Deadline)
        assert us.urgency_deadline == Deadline.IMMEDIATE
        # Legacy presentation field preserved (additive, not replaced).
        assert "label" in us.urgency and "explanation" in us.urgency

    def test_4b_deadline_is_categorical_not_numerical(self):
        for member in Deadline:
            assert not any(ch.isdigit() for ch in member.value)


class TestSituationExplanation:
    def test_5_situation_explanation_is_not_a_complaint_echo(self):
        """§16.5."""
        controller = SessionController(governance_enabled=False)
        session = _run_to_completion(controller, _make_request("T5", PLAIN_NOISE_COMPLAINT))
        us = session.result.user_summary
        assert us.situation_explanation
        assert us.situation_explanation != PLAIN_NOISE_COMPLAINT
        assert PLAIN_NOISE_COMPLAINT not in us.situation_explanation
        for internal_id in ("engine_running", "electrical", "tyre_or_wheel", "\"noise\""):
            assert internal_id not in us.situation_explanation


class TestPlausibleCauses:
    def test_6_plausible_hypotheses_without_certainty(self):
        """§16.6."""
        controller = SessionController(governance_enabled=False)
        session = _run_to_completion(controller, _make_request("T6", PLAIN_NOISE_COMPLAINT))
        us = session.result.user_summary
        assert us.plausible_causes
        for cause in us.plausible_causes:
            assert cause.claim_status in (ClaimStatus.POSSIBLE, ClaimStatus.COMPATIBLE, ClaimStatus.UNRESOLVED)
            assert isinstance(cause.confidence, Confidence)
            assert "certain" not in cause.description.lower()
            assert "confirmé" not in cause.description.lower()
        assert all(cause.label != "engine_running" for cause in us.plausible_causes)


class TestRemainingUncertainty:
    def test_7_case_specific_uncertainty_exposed(self):
        """§16.7."""
        controller = SessionController(governance_enabled=False)
        session = _run_to_completion(controller, _make_request("T7", PLAIN_NOISE_COMPLAINT))
        us = session.result.user_summary
        assert us.remaining_uncertainty
        assert isinstance(us.remaining_uncertainty, list)
        assert all(isinstance(item, str) and item for item in us.remaining_uncertainty)


class TestNextActionsVary:
    def test_8_next_actions_vary_by_case_state(self):
        """§16.8."""
        controller_emergency = SessionController(governance_enabled=False)
        controller_monitor = SessionController(governance_enabled=False)

        session_emergency = controller_emergency.start(_make_request("T8A", EMERGENCY_WARNING_COMPLAINT))
        session_monitor = _run_to_completion(
            controller_monitor, _make_request("T8B", "Ma voiture consomme un peu plus d'essence que d'habitude.")
        )

        actions_emergency = session_emergency.result.user_summary.next_actions
        actions_monitor = session_monitor.result.user_summary.next_actions

        assert actions_emergency != actions_monitor
        assert any("secours" in a.lower() for a in actions_emergency)


class TestEvidenceFirstOrdering:
    def test_9_warning_light_context_prioritizes_evidence_before_generic_questions(self):
        """§16.9 / Journey A core assertion."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T9", WARNING_LIGHT_COMPLAINT))
        assert session.pending_questions, "expected at least one pending question after start()"
        first_question = session.pending_questions[0]
        assert first_question.question_id == "Q-EVI-001"

        session = controller.submit_answer(session, Answer(question_id="Q-EVI-001", value=True))
        assert session.pending_questions
        second_question = session.pending_questions[0]
        assert second_question.question_id == "Q-EVI-002"
        assert second_question.answer_type == AnswerType.MEDIA_UPLOAD.value

    def test_10_no_useful_photo_case_does_not_get_unnecessary_media_priority(self):
        """§16.10 / Journey B core assertion — no warning-indicator
        context means the evidence-acquisition tier is never artificially
        promoted; generic symptom questions come first."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T10", PLAIN_NOISE_COMPLAINT))
        assert session.pending_questions
        first_question = session.pending_questions[0]
        assert first_question.question_id not in ("Q-EVI-001", "Q-EVI-002")


class TestMediaEvidenceRetention:
    def test_11_submitted_media_evidence_is_retained_and_associated_with_case(self):
        """§16.11."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T11", WARNING_LIGHT_COMPLAINT))
        session = controller.submit_answer(session, Answer(question_id="Q-EVI-001", value=True))
        assert session.pending_questions[0].question_id == "Q-EVI-002"

        case_state = controller._case_states[session.session_id]
        evidence_before = len(case_state.evidence)

        session = controller.submit_answer(
            session, Answer(question_id="Q-EVI-002", value="media-ref-dashboard-warning-001")
        )
        case_state = controller._case_states[session.session_id]
        media_evidence = [
            e for e in case_state.evidence if e.source_rule_id == "automotive.media_evidence_acquired"
        ]
        assert media_evidence, "media answer produced no retained Evidence"
        assert len(case_state.evidence) > evidence_before
        for e in media_evidence:
            assert e.direction.value == "NEUTRAL"  # no content interpretation claimed
            assert "media-ref-dashboard-warning-001" in e.rationale  # reference preserved
            assert e.observation_ids  # linked to a real Observation (case association)
            assert e.id  # evidence identifier/reference present

    def test_11b_one_evidence_record_per_targeted_hypothesis(self):
        """A media answer must not be dropped — every hypothesis the
        question targeted receives its own Evidence record."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T11B", WARNING_LIGHT_COMPLAINT))
        session = controller.submit_answer(session, Answer(question_id="Q-EVI-001", value=True))
        legacy_q = session.pending_questions[0]
        case_state = controller._case_states[session.session_id]
        domain_q = next(q for q in case_state.questions if q.id == legacy_q.question_id)
        target_count = len(domain_q.target_hypothesis_ids)
        assert target_count > 0
        session = controller.submit_answer(session, Answer(question_id="Q-EVI-002", value="ref-002"))
        case_state = controller._case_states[session.session_id]
        media_evidence = [
            e for e in case_state.evidence if e.source_rule_id == "automotive.media_evidence_acquired"
        ]
        assert len(media_evidence) == target_count


class TestNoDuplicateEvidenceRequests:
    def test_12_evidence_not_repeatedly_requested_once_present(self):
        """§16.12."""
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("T12", WARNING_LIGHT_COMPLAINT))
        session = controller.submit_answer(session, Answer(question_id="Q-EVI-001", value=True))
        session = controller.submit_answer(session, Answer(question_id="Q-EVI-002", value="ref-003"))
        remaining_ids = [q.question_id for q in session.pending_questions]
        assert "Q-EVI-001" not in remaining_ids
        assert "Q-EVI-002" not in remaining_ids
        guard = 0
        while session.pending_questions and guard < 50:
            guard += 1
            q = session.pending_questions[0]
            assert q.question_id not in ("Q-EVI-001", "Q-EVI-002")
            value = q.choices[0] if q.choices else ("réponse" if q.answer_type == "text" else False)
            session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))


class TestSelectorDeterminism:
    def test_13_question_selection_is_deterministic(self):
        """§16.13."""
        results = []
        for i in range(3):
            controller = SessionController(governance_enabled=False)
            session = controller.start(_make_request(f"T13-{i}", WARNING_LIGHT_COMPLAINT))
            order = []
            guard = 0
            while session.pending_questions and guard < 50:
                guard += 1
                q = session.pending_questions[0]
                order.append(q.question_id)
                value = (
                    "media-ref" if q.answer_type == "media_upload"
                    else True if q.question_id == "Q-EVI-001"
                    else (q.choices[0] if q.choices else False)
                )
                session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))
            results.append(order)
        assert results[0] == results[1] == results[2]


class TestGarageHandoffPreserved:
    def test_14_garage_report_preserves_existing_technical_information(self):
        """§16.14 / §13."""
        controller = SessionController(governance_enabled=False)
        session = _run_to_completion(controller, _make_request("T14", PLAIN_NOISE_COMPLAINT))
        report = session.result.garage_preparation_report
        assert report.customer_reported_problem == PLAIN_NOISE_COMPLAINT
        assert report.systems_to_examine
        assert report.safety_information
        assert "triage_level" in report.safety_information
        assert "driving_assessment" in report.safety_information
        assert report.suggested_professional_checks
        if len(report.systems_to_examine) > 1:
            assert any("discrimin" in c for c in report.suggested_professional_checks)


class TestNoCostField:
    def test_15_no_repair_cost_field_or_estimate_anywhere(self):
        """§16.15 / Decision D03 / PGDR-BR-012.

        The word "coût" legitimately appears exactly once, in the
        deliberate disclaimer stating that NO cost is estimated. This
        test asserts that is the ONLY occurrence, no field is cost-shaped,
        and no currency-amount pattern exists anywhere in the output.
        """
        import re

        controller = SessionController(governance_enabled=False)
        session = _run_to_completion(controller, _make_request("T15", PLAIN_NOISE_COMPLAINT))
        result = session.result

        for obj in (result.user_summary, result.garage_preparation_report, result):
            for field_name in type(obj).model_fields:
                lowered = field_name.lower()
                assert "cost" not in lowered and "price" not in lowered and "coût" not in lowered

        serialized = str(result.model_dump())
        assert serialized.count("coût") <= 1
        if "coût" in serialized:
            assert "aucun coût n'est estimé" in serialized
        assert "cost" not in serialized.lower()
        assert "price" not in serialized.lower()
        assert not re.search(r"\d+\s*(€|\$|eur\b|usd\b)", serialized.lower())

    def test_15b_business_rule_still_declared_fatal(self):
        from pgdr.config_loader import load_business_rules

        rules = load_business_rules()["rules"]
        br012 = next(r for r in rules if r["id"] == "PGDR-BR-012")
        assert br012["enforcement"] == "fatal"
        assert "cost" in br012["rule"].lower()


class TestSafetyInvariantsGreen:
    def test_16_driving_assessment_never_contains_safe_to_drive(self):
        """§16.16 / PGDR-INV-003."""
        assert "SAFE_TO_DRIVE" not in DrivingAssessment.__members__
        for member in DrivingAssessment:
            assert "safe_to_drive" not in member.value.lower()


# ---------------------------------------------------------------------------
# §17 — Acceptance Journey A: warning light
# ---------------------------------------------------------------------------

class TestAcceptanceJourneyA:
    def test_journey_a_warning_light_full_flow(self):
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("JOURNEY-A", WARNING_LIGHT_COMPLAINT))

        assert session.pending_questions[0].question_id == "Q-EVI-001"
        session = controller.submit_answer(session, Answer(question_id="Q-EVI-001", value=True))
        assert session.pending_questions[0].question_id == "Q-EVI-002"
        assert session.pending_questions[0].answer_type == AnswerType.MEDIA_UPLOAD.value

        session = controller.submit_answer(session, Answer(question_id="Q-EVI-002", value="media-ref-journeyA"))
        case_state = controller._case_states[session.session_id]
        assert any(e.source_rule_id == "automotive.media_evidence_acquired" for e in case_state.evidence)

        guard = 0
        while session.pending_questions and guard < 50:
            guard += 1
            q = session.pending_questions[0]
            assert q.question_id not in ("Q-EVI-001", "Q-EVI-002")
            value = q.choices[0] if q.choices else ("réponse" if q.answer_type == "text" else False)
            session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))

        result = session.result
        us = result.user_summary
        assert us.situation_explanation
        assert isinstance(us.safety_level, TriageLevel)
        assert isinstance(us.driveability, DrivingAssessment)
        assert isinstance(us.urgency_deadline, Deadline)
        assert us.plausible_causes
        assert us.next_actions
        assert us.remaining_uncertainty
        assert result.garage_preparation_report is not None

        serialized = str(result.model_dump()).lower()
        assert "cost" not in serialized


# ---------------------------------------------------------------------------
# §18 — Acceptance Journey B: no useful photo
# ---------------------------------------------------------------------------

class TestAcceptanceJourneyB:
    def test_journey_b_no_useful_photo_full_flow(self):
        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("JOURNEY-B", PLAIN_NOISE_COMPLAINT))
        assert session.pending_questions[0].question_id not in ("Q-EVI-001", "Q-EVI-002")

        guard = 0
        while session.pending_questions and guard < 50:
            guard += 1
            q = session.pending_questions[0]
            value = (
                "media-ref" if q.answer_type == "media_upload"
                else False if q.question_id == "Q-EVI-001"
                else (q.choices[0] if q.choices else "réponse")
            )
            session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))

        result = session.result
        assert result.user_summary is not None
        assert result.garage_preparation_report is not None
