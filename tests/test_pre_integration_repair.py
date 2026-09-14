"""PGDR Driver Diagnostic — Pre-Integration Repair (R1, R2) regression
tests.

Both repairs correct pre-existing defects discovered and documented (not
fixed) during the Driver Diagnostic Execution Mandate v0's implementation
(commit 720b4f0). Neither repair touches Driver Diagnostic architecture,
Evidence-First architecture, SafetyEngine, safety_rules.yaml, or any
non-authorized area.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pgdr.config_loader import load_questions
from pgdr.domain.enums import EvidenceDirection
from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
from pgdr.models import (
    Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest,
    UserContext, VehicleIdentityContext,
)
from pgdr.session_controller import SessionController


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


# ---------------------------------------------------------------------------
# R1 — question category lookup
# ---------------------------------------------------------------------------

class TestR1QuestionCategoryLookup:
    def test_r1_configured_categories_are_exposed_correctly_not_defaulted(self):
        """Drives a real session far enough to encounter questions from
        several distinct configured categories (per questions.yaml:
        evidence, vehicle_behavior, operating_condition, temporal,
        intensity, recent_event) and asserts each pending question's
        `.category` matches its real configured value — not the old
        silent 'clarification' default that fired for every question
        regardless of its true category."""
        configured_categories = {
            q["question_id"]: q["category"] for q in load_questions()["questions"]
        }
        # Sanity: the fixture itself must contain more than one distinct
        # category, or this test would not be able to detect the bug.
        assert len(set(configured_categories.values())) > 1

        controller = SessionController(governance_enabled=False)
        session = controller.start(
            _make_request("R1", "Le voyant moteur s'est allumé et je sens une perte de puissance.")
        )
        observed: dict[str, str] = {}
        guard = 0
        while session.pending_questions and guard < 50:
            guard += 1
            q = session.pending_questions[0]
            observed[q.question_id] = q.category
            value = (
                "media-ref" if q.answer_type == "media_upload"
                else True if q.question_id == "Q-EVI-001"
                else (q.choices[0] if q.choices else False)
            )
            session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))

        assert len(observed) >= 4, "expected to observe several distinct questions in this journey"
        for question_id, observed_category in observed.items():
            assert observed_category == configured_categories[question_id], (
                f"{question_id}: expected configured category "
                f"{configured_categories[question_id]!r}, got {observed_category!r}"
            )
        # The specific regression this repairs: not every category is
        # silently "clarification".
        assert len(set(observed.values())) > 1

    def test_r1_specific_known_categories(self):
        """Explicit, named assertions for the categories most likely to
        matter to a future consumer grouping questions by category."""
        configured_categories = {
            q["question_id"]: q["category"] for q in load_questions()["questions"]
        }
        assert configured_categories["Q-EVI-001"] == "evidence"
        assert configured_categories["Q-STATE-001"] == "vehicle_behavior"
        assert configured_categories["Q-SYM-001"] == "temporal"
        assert configured_categories["Q-SYM-002"] == "intensity"

        controller = SessionController(governance_enabled=False)
        session = controller.start(
            _make_request("R1B", "Le voyant moteur s'est allumé et je sens une perte de puissance.")
        )
        by_id: dict[str, str] = {}
        guard = 0
        while session.pending_questions and guard < 50:
            guard += 1
            q = session.pending_questions[0]
            by_id[q.question_id] = q.category
            value = (
                "media-ref" if q.answer_type == "media_upload"
                else True if q.question_id == "Q-EVI-001"
                else (q.choices[0] if q.choices else False)
            )
            session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))

        assert by_id.get("Q-EVI-001") == "evidence"
        assert by_id.get("Q-STATE-001") == "vehicle_behavior"
        assert by_id.get("Q-SYM-001") == "temporal"
        assert by_id.get("Q-SYM-002") == "intensity"


# ---------------------------------------------------------------------------
# R2 — Q-COND-001 discriminating rule, real configured choice value
# ---------------------------------------------------------------------------

class TestR2DiscriminatingRuleRealValue:
    def test_r2_actual_configured_choice_triggers_discrimination_not_neutral_fallback(self):
        """Uses the REAL choice text from questions.yaml (not the
        previously-mismatched key) and confirms it produces the intended
        tyre_or_wheel-supporting / engine_running-contradicting evidence,
        not the generic NEUTRAL fallback."""
        raw_questions = {q["question_id"]: q for q in load_questions()["questions"]}
        real_choice = raw_questions["Q-COND-001"]["choices"][2]
        assert real_choice == "à vitesse stabilisée", (
            "questions.yaml's own configured choice text changed -- update this test's assumption"
        )

        controller = SessionController(governance_enabled=False)
        session = controller.start(_make_request("R2", "J'ai une vibration au niveau du moteur."))
        guard = 0
        while session.pending_questions and guard < 50:
            guard += 1
            q = session.pending_questions[0]
            if q.question_id == "Q-COND-001":
                value = [real_choice]
            elif q.answer_type == "media_upload":
                value = "media-ref"
            elif q.answer_type == "yes_no":
                value = False
            elif q.choices:
                value = q.choices[0]
            else:
                value = "réponse"
            session = controller.submit_answer(session, Answer(question_id=q.question_id, value=value))

        case_state = controller._case_states[session.session_id]
        cond_evidence = [
            e for e in case_state.evidence
            if e.source_rule_id == "automotive.q_cond_001_discriminator"
        ]
        assert cond_evidence, (
            "no discriminating evidence was produced for the real configured Q-COND-001 choice -- "
            "the rule key still does not match the real choice text"
        )
        directions_by_hypothesis_type = {}
        for e in cond_evidence:
            h = next(h for h in case_state.hypotheses if h.id == e.target_hypothesis_id)
            directions_by_hypothesis_type[h.hypothesis_type] = e.direction

        assert directions_by_hypothesis_type.get("tyre_or_wheel") == EvidenceDirection.SUPPORTS
        assert directions_by_hypothesis_type.get("engine_running") == EvidenceDirection.CONTRADICTS

    def test_r2_rule_dict_key_matches_real_configured_choice_exactly(self):
        """Direct, minimal proof the rule dict itself now uses the real
        string, not a near-miss."""
        from pgdr.automotive.evidence_mapper import _DISCRIMINATING_RULES

        raw_questions = {q["question_id"]: q for q in load_questions()["questions"]}
        real_choices = set(raw_questions["Q-COND-001"]["choices"])
        rule = _DISCRIMINATING_RULES["Q-COND-001"]
        for configured_key in rule:
            assert configured_key in real_choices, (
                f"_DISCRIMINATING_RULES['Q-COND-001'] has key {configured_key!r}, which does not match "
                f"any of questions.yaml's real configured choices {sorted(real_choices)}"
            )
