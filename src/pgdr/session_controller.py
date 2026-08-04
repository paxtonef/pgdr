"""Session Controller — state machine per AMD pack 14.2."""
from __future__ import annotations

from pgdr.complaint_parser import ComplaintParser
from pgdr.config_loader import load_questions
from pgdr.diagnostic import DiagnosticEngine
from pgdr.enums import AnswerType, ResolutionStatus, SessionState
from pgdr.models import Answer, DiagnosticQuestion, DiagnosticSession, PreGarageDiagnosticRequest
from pgdr.report_builder import ReportBuilder
from pgdr.safety_engine import SafetyEngine

_CATEGORY_PRIORITY = {
    "safety": 0, "vehicle_behavior": 1, "operating_condition": 2,
    "temporal": 3, "intensity": 4, "recent_event": 5, "evidence": 6,
    "clarification": 7,
}


class SessionController:
    def __init__(self) -> None:
        self.safety_engine = SafetyEngine()
        self.complaint_parser = ComplaintParser()
        self.diagnostic_engine = DiagnosticEngine()
        self.report_builder = ReportBuilder()
        self.question_bank = load_questions().get("questions", [])

    def start(self, request: PreGarageDiagnosticRequest) -> DiagnosticSession:
        session = DiagnosticSession(request=request)

        session.log_transition(SessionState.RECEIVED, SessionState.IDENTITY_RESOLUTION, "Request received")
        # PGDR-ID-001/002: the VIR context is consumed verbatim, never rebuilt.
        session.log_transition(
            SessionState.IDENTITY_RESOLUTION, SessionState.COMPLAINT_ANALYSIS, "VIR identity context consumed"
        )

        extraction, symptoms = self.complaint_parser.extract(request.initial_complaint)
        session.extracted_complaint = extraction
        session.symptoms = symptoms
        session.warning_indicators = self.complaint_parser.extract_warning_indicators(request.initial_complaint)

        session.log_transition(
            SessionState.COMPLAINT_ANALYSIS, SessionState.IMMEDIATE_SAFETY_TRIAGE, "Complaint parsed"
        )

        # PGDR-BR-002 / PGDR-INV-005: safety triage always runs before reasoning.
        triage = self.safety_engine.evaluate(session)
        session.safety_triage = triage

        if triage.level.value in ("emergency_stop", "do_not_drive"):
            session.log_transition(
                SessionState.IMMEDIATE_SAFETY_TRIAGE, SessionState.ESCALATED,
                f"Critical safety signal: {triage.level.value}",
            )
            session.result = self.report_builder.build(session)
            return session

        session.log_transition(
            SessionState.IMMEDIATE_SAFETY_TRIAGE, SessionState.SYMPTOM_COLLECTION, "No critical safety signal"
        )
        session.pending_questions = self._select_questions(session)
        return session

    def submit_answer(self, session: DiagnosticSession, answer: Answer) -> DiagnosticSession:
        session.answers.append(answer)
        matched = next((q for q in session.pending_questions if q.question_id == answer.question_id), None)
        if matched:
            session.questions_asked.append(matched)
            session.pending_questions.remove(matched)

        # Re-select in case the new answer unlocks a conditional question
        # (e.g. Q-EVT-002 after Q-EVT-001==true).
        session.pending_questions = self._select_questions(session)

        if not session.pending_questions:
            self._finalize(session)
        return session

    def _finalize(self, session: DiagnosticSession) -> None:
        session.log_transition(session.state, SessionState.EVIDENCE_COLLECTION, "Symptom questions completed")
        session.log_transition(SessionState.EVIDENCE_COLLECTION, SessionState.CONTRADICTION_CHECK, "Evidence phase complete")

        self.diagnostic_engine.process_answers(session)
        self.diagnostic_engine.detect_contradictions(session)

        # PGDR-BR-001 / PGDR-ID-003: limit vehicle-specific reasoning when
        # identity is not reliably resolved.
        identity_status = session.request.vehicle_identity_context.resolution_status
        if identity_status in (
            ResolutionStatus.AMBIGUOUS, ResolutionStatus.INSUFFICIENT_DATA, ResolutionStatus.CONTRADICTORY,
        ):
            session.limitations.append(
                "PGDR-BR-001: identité du véhicule non fiable — le raisonnement diagnostique "
                "spécifique au véhicule est limité à des hypothèses génériques par famille de symptôme."
            )

        session.log_transition(SessionState.CONTRADICTION_CHECK, SessionState.REASONING, "Contradictions checked")
        self.diagnostic_engine.generate_hypotheses(session)
        session.log_transition(SessionState.REASONING, SessionState.REPORT_GENERATION, "Hypotheses generated")

        session.result = self.report_builder.build(session)
        session.log_transition(SessionState.REPORT_GENERATION, SessionState.COMPLETED, "Report generated")

    def _select_questions(self, session: DiagnosticSession) -> list[DiagnosticQuestion]:
        answered_ids = {a.question_id for a in session.answers}
        answers_by_id = {a.question_id: a for a in session.answers}
        selected: list[DiagnosticQuestion] = []

        for raw in self.question_bank:
            qid = raw["question_id"]
            if qid in answered_ids:
                continue

            if raw.get("answer_type") == "media_upload" and not session.request.consent.media_analysis_allowed:
                continue

            ask_if = raw.get("ask_if", "")
            if ask_if == "contradiction_detected":
                if not session.contradictions:
                    continue
            elif ask_if and "==" in ask_if:
                dep_id, expected = ask_if.split("==", 1)
                dep_id = dep_id.strip()
                expected = expected.strip().strip('"').strip("'").lower()
                dep_answer = answers_by_id.get(dep_id)
                if dep_answer is None:
                    continue
                actual = str(dep_answer.value).lower()
                if actual != expected:
                    continue

            selected.append(DiagnosticQuestion(
                question_id=qid,
                target=raw["target"],
                category=raw["category"],
                prompt=raw["prompt"],
                answer_type=raw["answer_type"],
                required=raw.get("required", False),
                risk_level=raw.get("risk_level", "none"),
                selection_reason=raw.get("selection_reason", ""),
                choices=raw.get("choices"),
            ))

        selected.sort(key=lambda q: (_CATEGORY_PRIORITY.get(q.category.value, 99), not q.required))
        return selected

    def get_current_state(self, session: DiagnosticSession) -> dict:
        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "pending_questions": [q.model_dump(mode="json") for q in session.pending_questions],
            "safety_triage": session.safety_triage.model_dump(mode="json") if session.safety_triage else None,
            "symptoms": [s.model_dump(mode="json") for s in session.symptoms],
        }
