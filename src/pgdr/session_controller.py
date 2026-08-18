"""Session Controller — state machine per AMD pack 14.2, migrated in P5
to delegate all analytical reasoning to the P4 engine
(DiagnosticLoop + DiagnosticCaseState) instead of the legacy
DiagnosticEngine.

P5 migration invariant (mandate §2): there is exactly one authoritative
analytical state for an active session — DiagnosticCaseState, held in
`self._case_states` keyed by session_id. SessionController orchestrates;
it does not reason. Per §3's explicit prohibition list, this class no
longer:
  - generates hypotheses itself (was: self.diagnostic_engine.generate_hypotheses)
  - calculates hypothesis confidence
  - interprets answer effects
  - maintains a parallel question-selection algorithm (was: _select_questions)
  - reconstructs analytical evidence

`DiagnosticEngine` remains importable (kept as `self.diagnostic_engine`
for backward-reference / diagnostics only — see
docs/architecture/p5_legacy_deprecation.md) but is NEVER CALLED on this
class's production path. Per P5.3 (§5), SafetyEngine is untouched and
retains sole authority over the safety verdict — DiagnosticLoop only
*consults* that verdict (via SafetyState.preempts_analysis), it never
recomputes or reinterprets it.
"""
from __future__ import annotations

from pgdr.application.case_factory import DiagnosticCaseFactory
from pgdr.application.case_state_updater import CaseStateUpdater
from pgdr.application.diagnostic_loop import DiagnosticLoop
from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
from pgdr.application.question_selector import DeterministicQuestionSelector
from pgdr.automotive.domain_adapter import AutomotiveDiagnosticDomain
from pgdr.automotive.domain_validator import validate_automotive_domain
from pgdr.automotive.evidence_mapper import AutomotiveEvidenceMapper
from pgdr.complaint_parser import ComplaintParser
from pgdr.config_loader import load_questions
from pgdr.diagnostic import DiagnosticEngine
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.enums import ResolutionStatus, SessionState
from pgdr.models import Answer, DiagnosticQuestion, DiagnosticSession, PreGarageDiagnosticRequest
from pgdr.report_builder import ReportBuilder, build_result_from_case_state
from pgdr.safety_engine import SafetyEngine


class SessionController:
    def __init__(self) -> None:
        # P5.29 / P5.28 — validate the domain's declarative relations
        # (evidence-mapping rules referencing real hypothesis types and
        # real question ids) at startup, fail-closed, before any session
        # can begin. Reuses the same ConfigurationError signal P0
        # established for the safety envelope — a broken domain
        # configuration should never be discovered mid-session.
        validate_automotive_domain()

        self.safety_engine = SafetyEngine()
        self.complaint_parser = ComplaintParser()
        # DEPRECATED — retained only as a documented legacy reference.
        # NOT called anywhere in this class's production path as of P5.
        # See docs/architecture/p5_legacy_deprecation.md.
        self.diagnostic_engine = DiagnosticEngine()
        # DEPRECATED for the multi-object DiagnosticSession-driven
        # ReportBuilder.build() path — retained for its _URGENCY_COPY /
        # formatting helpers, not invoked directly by this class anymore.
        self.report_builder = ReportBuilder()

        # P5 production path
        self._domain = AutomotiveDiagnosticDomain()
        self._updater = CaseStateUpdater(DeterministicHypothesisScorer())
        self._loop = DiagnosticLoop(
            self._domain, AutomotiveEvidenceMapper(), DeterministicQuestionSelector(), self._updater,
        )
        self._case_factory = DiagnosticCaseFactory(self._loop)
        self._case_states: dict[str, DiagnosticCaseState] = {}

        # Only used to recover a question's original QuestionCategory for
        # the legacy pgdr.models.DiagnosticQuestion shape (session.pending_questions) —
        # not used for selection logic, which is entirely the v2
        # DeterministicQuestionSelector's responsibility now.
        self._category_by_question_id = {
            q["question_id"]: q["category"] for q in load_questions().get("questions", [])
        }

    def start(self, request: PreGarageDiagnosticRequest) -> DiagnosticSession:
        session = DiagnosticSession(request=request)

        session.log_transition(SessionState.RECEIVED, SessionState.IDENTITY_RESOLUTION, "Request received")
        # PGDR-ID-001/002: the VIR context is consumed verbatim, never rebuilt.
        session.log_transition(
            SessionState.IDENTITY_RESOLUTION, SessionState.COMPLAINT_ANALYSIS, "VIR identity context consumed"
        )

        # session.symptoms / .warning_indicators / .extracted_complaint
        # are still populated directly here (not via the v2 engine) for
        # two reasons: (1) SafetyEngine.evaluate() below requires them in
        # this exact legacy shape and is explicitly NOT modified by P5
        # (§5); (2) some callers/tests still read these fields directly.
        # AutomotiveDiagnosticDomain.interpret_observations() performs the
        # equivalent extraction a second time, independently, when
        # DiagnosticCaseFactory.create() calls DiagnosticLoop.start() below
        # — a known, documented duplication, not a hidden one (see
        # docs/architecture/p5_findings.md).
        extraction, symptoms = self.complaint_parser.extract(request.initial_complaint)
        session.extracted_complaint = extraction
        session.symptoms = symptoms
        session.warning_indicators = self.complaint_parser.extract_warning_indicators(request.initial_complaint)

        session.log_transition(
            SessionState.COMPLAINT_ANALYSIS, SessionState.IMMEDIATE_SAFETY_TRIAGE, "Complaint parsed"
        )

        # PGDR-BR-002 / PGDR-INV-005 / P5.3: safety triage always runs
        # first, via the unmodified SafetyEngine, and DiagnosticLoop only
        # ever consults its result — never recomputes or overrides it.
        triage = self.safety_engine.evaluate(session)
        session.safety_triage = triage

        case_state = self._case_factory.create(request, triage)
        self._case_states[session.session_id] = case_state

        if triage.level.value in ("emergency_stop", "do_not_drive"):
            session.log_transition(
                SessionState.IMMEDIATE_SAFETY_TRIAGE, SessionState.ESCALATED,
                f"Critical safety signal: {triage.level.value}",
            )
            session.result = build_result_from_case_state(request.request_id, case_state)
            return session

        session.log_transition(
            SessionState.IMMEDIATE_SAFETY_TRIAGE, SessionState.SYMPTOM_COLLECTION, "No critical safety signal"
        )
        session.pending_questions = self._advance(session, case_state)
        return session

    def submit_answer(self, session: DiagnosticSession, answer: Answer) -> DiagnosticSession:
        case_state = self._case_states[session.session_id]

        session.answers.append(answer)
        matched = next((q for q in session.pending_questions if q.question_id == answer.question_id), None)
        if matched:
            session.questions_asked.append(matched)
            session.pending_questions.remove(matched)

        # Record the answer against the authoritative v2 state — this is
        # what turns Answer -> Observation -> Evidence -> Hypothesis
        # update (mandate §11/§8), never just "append to report".
        new_question = next((q for q in case_state.questions if q.id == answer.question_id), None)
        if new_question is not None:
            case_state = self._loop.submit_answer(case_state, new_question, answer.value)
            self._case_states[session.session_id] = case_state

        session.pending_questions = self._advance(session, case_state)

        if not session.pending_questions:
            self._finalize(session, case_state)
        return session

    def _advance(self, session: DiagnosticSession, case_state: DiagnosticCaseState) -> list[DiagnosticQuestion]:
        """Runs one DiagnosticLoop iteration and translates the resulting
        `next_question` (if any) into the legacy DiagnosticQuestion shape
        for `session.pending_questions`. Always returns 0 or 1 question —
        a deliberate, documented behavioral difference from the v0.1
        `_select_questions()`, which returned every eligible question at
        once (mandate §20 explicitly permits this: "P5 change
        volontairement la dynamique analytique")."""
        result = self._loop.run_iteration(case_state)
        self._case_states[session.session_id] = result.state

        if result.next_question is None:
            return []

        nq = result.next_question
        category = self._category_by_question_id.get(nq.domain_ref or "", None) or "clarification"
        reason = (
            f"Cible {len(nq.target_hypothesis_ids)} hypothèse(s) active(s)."
            if nq.target_hypothesis_ids else ""
        )
        return [DiagnosticQuestion(
            question_id=nq.id,
            target=nq.domain_ref or "",
            category=category,
            prompt=nq.text,
            answer_type=nq.answer_type,
            required=False,
            risk_level=nq.risk_level or "none",
            selection_reason=reason,
            choices=nq.choices,
        )]

    def _finalize(self, session: DiagnosticSession, case_state: DiagnosticCaseState) -> None:
        session.log_transition(session.state, SessionState.EVIDENCE_COLLECTION, "Symptom questions completed")
        session.log_transition(
            SessionState.EVIDENCE_COLLECTION, SessionState.CONTRADICTION_CHECK, "Evidence phase complete"
        )

        # Contradiction detection is not part of the DiagnosticDomain
        # Protocol's 4-method contract (P4 §18) — called explicitly here,
        # once, at finalization, mirroring where the legacy
        # DiagnosticEngine.detect_contradictions() used to run.
        contradictions = self._domain.detect_contradictions(case_state)
        if contradictions:
            self._updater.detect_contradictions(case_state, contradictions)

        session.log_transition(SessionState.CONTRADICTION_CHECK, SessionState.REASONING, "Contradictions checked")
        session.log_transition(SessionState.REASONING, SessionState.REPORT_GENERATION, "Hypotheses generated")

        session.result = build_result_from_case_state(session.request.request_id, case_state)
        session.log_transition(SessionState.REPORT_GENERATION, SessionState.COMPLETED, "Report generated")

    def get_current_state(self, session: DiagnosticSession) -> dict:
        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "pending_questions": [q.model_dump(mode="json") for q in session.pending_questions],
            "safety_triage": session.safety_triage.model_dump(mode="json") if session.safety_triage else None,
            "symptoms": [s.model_dump(mode="json") for s in session.symptoms],
        }
