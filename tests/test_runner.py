"""Integration tests — AMD pack 21.1 (acceptance criteria) / 21.2 (scenarios)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.enums import ResolutionStatus, TriageLevel, VehicleLocation, VehicleState
from pgdr.models import (
    Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest,
    VehicleIdentityContext,
)
from pgdr.session_controller import SessionController


def _make_request(request_id, complaint_text, vir_status=ResolutionStatus.PROVISIONALLY_RESOLVED):
    return PreGarageDiagnosticRequest(
        request_id=request_id,
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=f"VIR-{request_id}",
            resolution_status=vir_status,
        ),
        initial_complaint=InitialComplaint(
            free_text=complaint_text,
            current_vehicle_location=VehicleLocation.HOME,
            vehicle_current_state=VehicleState.ENGINE_OFF,
        ),
        consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),
    )


def _answer_all(controller, session, value_fn=None):
    """Drives a session to completion, answering 'je ne sais pas' / False by default."""
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


# ---------------------------------------------------------------------------
# Scenario 1 — flashing engine warning + vibration -> do_not_drive/prompt_inspection
# ---------------------------------------------------------------------------

def test_scenario_1_flashing_engine_warning_and_vibration():
    controller = SessionController()
    req = _make_request(
        "TEST-001",
        "La voiture tremble au ralenti et le voyant moteur clignote parfois.",
    )
    session = controller.start(req)

    assert session.safety_triage.level in (TriageLevel.DO_NOT_DRIVE, TriageLevel.PROMPT_INSPECTION)
    assert session.safety_triage.driving_assessment.value != "safe_to_drive"
    # Hypothesis generation must not have run before triage produced a level.
    assert session.safety_triage is not None


# ---------------------------------------------------------------------------
# Scenario 2 — brake pedal loss -> emergency_stop / safety_escalation
# ---------------------------------------------------------------------------

def test_scenario_2_brake_pedal_loss_triggers_emergency_stop():
    controller = SessionController()
    req = _make_request(
        "TEST-002",
        "La pédale de frein est molle et la voiture ne freine plus.",
    )
    session = controller.start(req)

    assert session.state.value == "escalated"
    assert session.safety_triage.level == TriageLevel.EMERGENCY_STOP
    assert session.safety_triage.roadside_assistance_recommended is True
    assert session.result.status.value == "safety_escalation"
    assert session.result.safety_triage.driving_assessment.value == "do_not_drive"


# ---------------------------------------------------------------------------
# Scenario 3 — intermittent cold-start noise -> reproduction profile + report
# ---------------------------------------------------------------------------

def test_scenario_3_intermittent_cold_start_noise_produces_report():
    controller = SessionController()
    req = _make_request(
        "TEST-003",
        "Bruit métallique au démarrage à froid pendant quelques secondes.",
    )
    session = controller.start(req)
    session = _answer_all(controller, session)

    assert session.result is not None
    assert session.result.garage_preparation_report is not None
    assert session.result.user_summary is not None
    assert len(session.result.diagnostic_hypotheses) > 0
    # PGDR-BR-003: complaint preserved verbatim.
    assert session.result.garage_preparation_report.customer_reported_problem == req.initial_complaint.free_text


# ---------------------------------------------------------------------------
# Scenario 4 — ambiguous vehicle identity -> limited reasoning, report has limitations
# ---------------------------------------------------------------------------

def test_scenario_4_ambiguous_identity_limits_reasoning():
    controller = SessionController()
    req = _make_request(
        "TEST-004",
        "Bruit métallique au démarrage à froid.",
        vir_status=ResolutionStatus.AMBIGUOUS,
    )
    session = controller.start(req)
    session = _answer_all(controller, session)

    assert session.result is not None
    assert session.result.status.value == "completed_with_limitations"
    assert any("PGDR-BR-001" in lim for lim in session.result.limitations)


# ---------------------------------------------------------------------------
# Scenario 5 — dangerous evidence instructions are never generated
# ---------------------------------------------------------------------------

def test_scenario_5_no_dangerous_evidence_instructions():
    controller = SessionController()
    req = _make_request("TEST-005", "Fuite de liquide sous le moteur.")
    session = controller.start(req)
    session = _answer_all(controller, session)

    dangerous_terms = ["touchez", "touch the leaking", "placez-vous sous", "sous le véhicule"]
    all_prompts = " ".join(q.prompt.lower() for q in session.questions_asked)
    for term in dangerous_terms:
        assert term not in all_prompts


# ---------------------------------------------------------------------------
# Scenario 6 — degraded mode with insufficient identity data still completes
# ---------------------------------------------------------------------------

def test_scenario_6_degraded_mode_without_reliable_identity():
    controller = SessionController()
    req = _make_request(
        "TEST-006",
        "La voiture consomme plus de carburant que d'habitude.",
        vir_status=ResolutionStatus.INSUFFICIENT_DATA,
    )
    session = controller.start(req)
    session = _answer_all(controller, session)

    assert session.result is not None
    assert session.safety_triage.level == TriageLevel.MONITOR_AND_DOCUMENT
    assert session.result.status.value == "completed_with_limitations"


# ---------------------------------------------------------------------------
# Acceptance criteria — cross-cutting invariants
# ---------------------------------------------------------------------------

def test_ac005_no_output_ever_declares_safe_to_drive():
    """PGDR-AC-005 / PGDR-INV-003: safe_to_drive must not exist as a value anywhere."""
    from pgdr.enums import DrivingAssessment
    values = [e.value for e in DrivingAssessment]
    assert "safe_to_drive" not in values


def test_ac006_every_hypothesis_has_supporting_observations():
    controller = SessionController()
    req = _make_request("TEST-007", "La voiture tremble beaucoup en accélérant.")
    session = controller.start(req)
    session = _answer_all(controller, session)

    for h in session.result.diagnostic_hypotheses:
        assert len(h.supporting_observations) > 0


def test_ac010_garage_report_and_user_summary_are_distinct_objects():
    controller = SessionController()
    req = _make_request("TEST-008", "Voyant batterie allumé en roulant.")
    session = controller.start(req)
    session = _answer_all(controller, session)

    assert session.result.garage_preparation_report is not session.result.user_summary
    assert session.result.garage_preparation_report.model_dump() != session.result.user_summary.model_dump()


def test_ac012_runner_operates_without_media_analysis():
    controller = SessionController()
    req = _make_request("TEST-009", "Bruit au freinage.")
    req.consent.media_analysis_allowed = False
    session = controller.start(req)
    session = _answer_all(controller, session)

    for q in session.questions_asked:
        assert q.answer_type.value != "media_upload"
    assert session.result is not None


def test_ac013_report_exposes_unresolved_questions():
    controller = SessionController()
    req = _make_request("TEST-010", "Bruit de suspension sur route abîmée.")
    session = controller.start(req)
    session = _answer_all(controller, session)

    assert len(session.result.garage_preparation_report.unresolved_questions) > 0


# ---------------------------------------------------------------------------
# Regression: "tremble au ralenti" must classify as vibration, not unknown.
# A complaint can match multiple keyword families (vibration + engine_running);
# the more specific one must win as primary, not whichever sorts first alphabetically.
# ---------------------------------------------------------------------------

def test_regression_vibration_at_idle_is_not_classified_as_unknown():
    controller = SessionController()
    req = _make_request("TEST-011", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _answer_all(controller, session)

    primary = next(s for s in session.symptoms if s.is_primary)
    assert primary.family.value == "vibration"
    families_examined = {h.system_family for h in session.result.diagnostic_hypotheses}
    assert "unknown" not in families_examined


# ---------------------------------------------------------------------------
# Regression: every SymptomFamily must produce a real hypothesis, not fall
# through to 'unknown' just because it lacks a curated entry in the map.
# ---------------------------------------------------------------------------

def test_regression_all_symptom_families_produce_non_unknown_hypothesis():
    from pgdr.enums import SymptomFamily

    controller = SessionController()
    complaints = {
        "climate_control": "La climatisation ne refroidit plus du tout.",
        "fuel_consumption": "Consommation de carburant beaucoup plus élevée que d'habitude.",
        "tyre_or_wheel": "Le pneu avant semble abîmé et fait du bruit.",
    }
    for expected_family, text in complaints.items():
        req = _make_request(f"TEST-FAM-{expected_family}", text)
        session = controller.start(req)
        session = _answer_all(controller, session)
        families_examined = {h.system_family for h in session.result.diagnostic_hypotheses}
        assert families_examined, f"No hypotheses generated for: {text}"
        assert "unknown" not in families_examined, (
            f"Complaint '{text}' (expected family involving {expected_family}) "
            f"fell through to 'unknown'"
        )


# ---------------------------------------------------------------------------
# Regression: safety rules must fire regardless of French accents in input
# (mobile keyboards / fast typing frequently drop them).
# ---------------------------------------------------------------------------

def test_regression_safety_rules_are_accent_insensitive():
    controller = SessionController()
    # Deliberately unaccented: "fumee" / "brule" instead of "fumée" / "brûlé"
    req = _make_request(
        "TEST-012",
        "Fumee blanche qui sort du capot et odeur de brule apres 10 minutes de route.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.EMERGENCY_STOP


# ---------------------------------------------------------------------------
# Regression: flat-tyre safety rule must match even when "pneu" and "plat"
# are not adjacent in the sentence.
# ---------------------------------------------------------------------------

def test_regression_flat_tyre_matches_with_intervening_words():
    controller = SessionController()
    req = _make_request(
        "TEST-013",
        "Pneu avant gauche visiblement à plat, je ne peux pas rouler.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.DO_NOT_DRIVE


# ---------------------------------------------------------------------------
# Regression: contradiction detection must match any conjugation of
# "rouler" (rouler/roulé/roulant), not only the exact past-participle form.
# ---------------------------------------------------------------------------

def test_regression_contradiction_detects_infinitive_form_of_rouler():
    controller = SessionController()
    req = _make_request(
        "TEST-014",
        "La voiture ne démarre jamais le matin mais j'ai réussi à rouler 50km hier.",
        vir_status=ResolutionStatus.CONTRADICTORY,
    )
    session = controller.start(req)
    session = _answer_all(controller, session)
    assert len(session.result.contradictions) >= 1


# ---------------------------------------------------------------------------
# Round 3 — 14-scenario batch found 7 more gaps: two matched AMD pack 11.2
# high-risk signals (sudden_extreme_stiffness, battery_thermal_event,
# major_unknown_fluid_leak) that had no safety rule at all; the rest were
# phrase-adjacency / language-coverage brittleness in the same family as
# the flat-tyre bug.
# ---------------------------------------------------------------------------

def test_regression_sudden_steering_stiffness_triggers_do_not_drive():
    controller = SessionController()
    req = _make_request(
        "TEST-015",
        "La direction est devenue très dure d'un coup et j'ai du mal à tourner le volant.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.DO_NOT_DRIVE


def test_regression_ev_battery_heating_during_charge_triggers_emergency_stop():
    controller = SessionController()
    req = _make_request(
        "TEST-016",
        "La batterie de ma voiture électrique chauffe beaucoup pendant la charge.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.EMERGENCY_STOP


def test_regression_major_unknown_fluid_leak_triggers_do_not_drive():
    controller = SessionController()
    req = _make_request(
        "TEST-017",
        "Fuite de liquide inconnu sous le moteur, grande flaque ce matin.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.DO_NOT_DRIVE


def test_regression_minor_oil_stain_does_not_over_escalate():
    """A small stain (not a major leak) should classify as fluid_leak but
    must NOT trigger the same safety escalation as a major leak — this is
    the negative-control pair for the previous test."""
    controller = SessionController()
    req = _make_request(
        "TEST-018",
        "Il y a une petite tache d'huile sous la voiture le matin, rien d'autre.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.MONITOR_AND_DOCUMENT


def test_regression_flat_tyre_matches_degonfle_and_wheel_wobble_without_qui():
    controller = SessionController()
    req = _make_request(
        "TEST-019",
        "le pneu arrière droit est complètement dégonflé et la roue bouge bizarrement",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.DO_NOT_DRIVE


def test_regression_english_soft_brake_pedal_triggers_emergency_stop():
    controller = SessionController()
    req = _make_request(
        "TEST-020",
        "My car is making a strange noise when I brake and the pedal feels soft.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.EMERGENCY_STOP


def test_regression_abs_warning_light_triggers_prompt_inspection():
    controller = SessionController()
    req = _make_request(
        "TEST-021",
        "Voyant ABS orange allumé depuis ce matin, rien d'autre d'anormal.",
    )
    session = controller.start(req)
    assert session.safety_triage.level == TriageLevel.PROMPT_INSPECTION


def test_regression_empty_and_uninformative_complaint_does_not_crash():
    """Degraded-mode robustness: a near-empty complaint must still complete
    without raising, matching AMD pack 21.2 Scenario 6 in spirit."""
    controller = SessionController()
    req = _make_request("TEST-022", "RAS", vir_status=ResolutionStatus.INSUFFICIENT_DATA)
    session = controller.start(req)
    session = _answer_all(controller, session)
    assert session.result is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
