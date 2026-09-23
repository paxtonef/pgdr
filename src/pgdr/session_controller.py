"""Session Controller — state machine per AMD pack 14.2, migrated in P5
to delegate all analytical reasoning to the P4 engine
(DiagnosticLoop + DiagnosticCaseState), with the legacy analytical engine
fully retired in P7 (see docs/architecture/p7_retirement_result.md), and
diagnostic output now governed by GGM before presentation as of P8 (see
docs/architecture/p8_ggm_integration.md).

P5 migration invariant (mandate §2): there is exactly one authoritative
analytical state for an active session — DiagnosticCaseState, held in
`self._case_states` keyed by session_id. SessionController orchestrates;
it does not reason.

P7 update: `DiagnosticEngine` and `ReportBuilder` (the legacy classes
this docstring used to describe as "kept but unauthoritative") no longer
exist — P7's reachability audit found them genuinely unreachable from any
direction (not merely unauthoritative) and removed them. The one
production-reachable fragment of `DiagnosticEngine`
(`_generic_entries`, the no-curated-hypothesis fallback) was relocated to
`automotive/domain_adapter.py`, its sole caller, rather than deleted.
Per P5.3, `SafetyEngine` remains untouched and retains sole authority
over the safety verdict — `DiagnosticLoop` only *consults* that verdict
(via `SafetyState.preempts_analysis`), it never recomputes or
reinterprets it.

P8 update: the analytical-path report (the non-safety-escalated case,
`_finalize()`) now goes through `govern_and_build_result()` instead of
calling `build_result_from_case_state()` directly — every active
hypothesis is governed by GGM before it can appear in the final report.
Per mandate §28, the SAFETY-ESCALATED path (`start()`'s early return) is
explicitly NOT routed through governance — SafetyEngine's verdict remains
independent of and unreachable by GGM, unchanged since P0.
"""
from __future__ import annotations

from ggm.contract.interface import GGMConsumer

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
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.enums import ResolutionStatus, SessionState
from pgdr.governance.adapter import GGMDiagnosticGovernanceAdapter
from pgdr.governance.consumption_profile import (
    materialize_pgdr_runtime_or_raise,
    resolve_pgdr_consumption_manifest_or_raise,
)
from pgdr.governance.errors import GovernanceUnavailableError
from pgdr.governance.reporting import govern_and_build_result
from pgdr.governance.trace import InMemoryGovernanceTraceStore
from pgdr.models import Answer, DiagnosticQuestion, DiagnosticSession, PreGarageDiagnosticRequest
from pgdr.application.diagnostic_intake_from_interpretation import DiagnosticIntakeResult
from pgdr.application.diagnostic_intake_ingestion import ingest_dashboard_interpretation
from pgdr.application.photo_first import (
    FallbackOffer, PhotoCaseState, PhotoPhase, PhotoStep, build_user_selection_intake, fallback_offer,
    fallback_trigger, warning_indicator_from_entry,
)
from pgdr.domain.dashboard_knowledge import DashboardReferenceSet
from pgdr.domain.photo_provenance import LOCATION_QUESTION_ID, MAX_RETAKES
from pgdr.domain.safety_state import SafetyState
from pgdr.enums import TriageLevel
from pgdr.ports.dashboard_interpretation import DashboardInterpretationPort, MatchStatus
from pgdr.ports.media_resolver import MediaResolverPort
from pgdr.report_builder import build_result_from_case_state
from pgdr.safety_engine import SafetyEngine


class SessionController:
    def __init__(
        self, *, governance_enabled: bool = True, governance_consumer: GGMConsumer | None = None,
        dashboard_interpretation_port: DashboardInterpretationPort | None = None,
    ) -> None:
        # P5.29 / P5.28 — validate the domain's declarative relations
        # (evidence-mapping rules referencing real hypothesis types and
        # real question ids) at startup, fail-closed, before any session
        # can begin. Reuses the same ConfigurationError signal P0
        # established for the safety envelope — a broken domain
        # configuration should never be discovered mid-session.
        validate_automotive_domain()

        self.safety_engine = SafetyEngine()
        self.complaint_parser = ComplaintParser()

        # P5 production path
        self._domain = AutomotiveDiagnosticDomain()
        self._updater = CaseStateUpdater(DeterministicHypothesisScorer())
        self._loop = DiagnosticLoop(
            self._domain, AutomotiveEvidenceMapper(), DeterministicQuestionSelector(), self._updater,
        )
        self._case_factory = DiagnosticCaseFactory(self._loop)
        self._case_states: dict[str, DiagnosticCaseState] = {}

        # Block B1 (§11): the minimum wiring necessary to establish the
        # Port boundary cleanly. Stored, and ONLY stored -- never invoked
        # anywhere in this class for B1. start() does not call
        # self._dashboard_interpretation_port.interpret(...); the
        # diagnostic reasoning loop is not modified to consume
        # interpretation results. That wiring belongs to a later B slice.
        self._dashboard_interpretation_port = dashboard_interpretation_port

        # PHOTO-FIRST (B2 completion): per-session photo acquisition state.
        # Keyed by session id, so concurrent sessions cannot share it.
        self._photo_state: dict[str, PhotoCaseState] = {}

        # Only used to recover a question's original QuestionCategory for
        # the legacy pgdr.models.DiagnosticQuestion shape (session.pending_questions) —
        # not used for selection logic, which is entirely the v2
        # DeterministicQuestionSelector's responsibility now.
        self._category_by_question_id = {
            q["question_id"]: q["category"] for q in load_questions().get("questions", [])
        }

        # P8 — governance. Mandate §32/§33: production default is
        # enabled=True, no ungoverned fallback. If governance is required
        # and either the PGDR consumption declaration fails to resolve
        # against GGM, or the runtime cannot be materialized / the
        # injected GGMConsumer cannot be constructed, this raises
        # GovernanceUnavailableError (a ConfigurationError subclass) —
        # caught by the exact same fail-closed CLI boundary P0 already
        # established, no new catch site needed.
        #
        # P2.2 migration (evidence note §12/§13): production now
        # materializes a bounded GGM runtime via
        # materialize_pgdr_runtime_or_raise() and consumes
        # runtime.consumer, instead of constructing DefaultGGMConsumer()
        # directly — DefaultGGMConsumer instantiates GGM's full engine
        # set regardless of which operations PGDR actually enabled, while
        # RuntimeMaterializer builds only the machinery DECIDE requires
        # (structural minimality). governance_consumer remains the
        # explicit injection seam for tests/development (mandate §30) —
        # when supplied, it is used as-is and no runtime is materialized.
        self.governance_enabled = governance_enabled
        self._governance_trace_store = InMemoryGovernanceTraceStore()
        self._governance_manifest = None
        self._governance_port = None
        if governance_enabled:
            try:
                if governance_consumer is not None:
                    manifest = resolve_pgdr_consumption_manifest_or_raise()
                    consumer = governance_consumer
                else:
                    runtime = materialize_pgdr_runtime_or_raise()
                    manifest = runtime.manifest
                    consumer = runtime.consumer
            except GovernanceUnavailableError:
                raise
            except Exception as exc:  # fail closed (mandate §32) — never a silent ungoverned start
                raise GovernanceUnavailableError(
                    f"GGM consumer could not be constructed: {type(exc).__name__}: {exc}"
                ) from exc
            self._governance_manifest = manifest
            self._governance_port = GGMDiagnosticGovernanceAdapter(
                consumer,
                manifest_id=manifest.manifest_id,
                capability_profile_version=manifest.capability_profile_version,
                trace_store=self._governance_trace_store,
            )

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


    # ------------------------------------------------------------------
    # PHOTO-FIRST (B2 completion, E3/E4/E5).
    #
    # The dashboard photograph is the mandatory initial input. These
    # methods wire the ALREADY-BUILT B2 chain (B1.5 resolution -> B2-V
    # governed validation -> B2-D intake -> B2-I ingestion -> B2-R
    # relevance) into the existing case state, then re-evaluate safety
    # through the UNMODIFIED SafetyEngine. Nothing here interprets an
    # image, decides a safety state from provider output, or changes
    # Evidence/scorer/confidence semantics.
    # ------------------------------------------------------------------

    def start_photo_case(
        self, request: PreGarageDiagnosticRequest, *, session_id: str | None = None,
    ) -> DiagnosticSession:
        """Creates the session/case for a photo-first entry. Consent is a
        precondition of the CALLER's flow (no case exists without it); this
        method additionally refuses to start when media analysis was not
        authorized on the request. No complaint is required."""
        if not request.consent.media_analysis_allowed:
            raise PermissionError("media_analysis_allowed is False: a photo-first case cannot start")
        session = (
            DiagnosticSession(request=request, session_id=session_id) if session_id else DiagnosticSession(request=request)
        )
        session.log_transition(SessionState.RECEIVED, SessionState.IDENTITY_RESOLUTION, "Request received")
        session.log_transition(
            SessionState.IDENTITY_RESOLUTION, SessionState.COMPLAINT_ANALYSIS,
            f"VIR identity artifact consumed: {request.vehicle_identity_context.resolution_id}",
        )
        session.log_transition(
            SessionState.COMPLAINT_ANALYSIS, SessionState.IMMEDIATE_SAFETY_TRIAGE, "Photo-first: awaiting photo"
        )
        triage = self.safety_engine.evaluate(session)
        session.safety_triage = triage
        case_state = self._case_factory.create_for_photo(request, triage)
        self._case_states[session.session_id] = case_state
        session.log_transition(
            SessionState.IMMEDIATE_SAFETY_TRIAGE, SessionState.SYMPTOM_COLLECTION, "No critical safety signal"
        )
        self._photo_state[session.session_id] = PhotoCaseState()
        return session

    def photo_case_state(self, session: DiagnosticSession) -> PhotoCaseState:
        return self._photo_state[session.session_id]

    def acquire_photo(
        self, session: DiagnosticSession, *, media_reference: str, resolver: MediaResolverPort,
        reference_set: DashboardReferenceSet,
    ) -> PhotoStep:
        """One photo attempt through the real B2 chain."""
        ps = self._photo_state[session.session_id]
        if ps.phase not in (PhotoPhase.AWAITING_PHOTO, PhotoPhase.RETAKE_REQUESTED):
            raise RuntimeError(f"photo cannot be submitted in phase {ps.phase.value}")
        if self._dashboard_interpretation_port is None:
            raise RuntimeError("no DashboardInterpretationPort is configured")
        case_state = self._case_states[session.session_id]

        media = resolver.resolve(media_reference)          # B1.5: real bytes
        ps.media_reference = media_reference
        ps.reference_set = reference_set
        # B2-I -> B2-D -> B2-V (mandatory validation); provider failures
        # propagate unchanged and leave case state untouched.
        intake = ingest_dashboard_interpretation(
            self._dashboard_interpretation_port, media, reference_set, self._updater, case_state,
        )
        ps.last_intake = intake

        trigger = fallback_trigger(intake)
        if trigger is None:
            self._complete_photo_acquisition(session, intake)
            return PhotoStep(phase=PhotoPhase.COMPLETED)

        if trigger == MatchStatus.INSUFFICIENT_VISUAL_QUALITY and ps.retakes_used < MAX_RETAKES:
            ps.retakes_used += 1
            ps.phase = PhotoPhase.RETAKE_REQUESTED
            ps.trigger = trigger
            return PhotoStep(
                phase=PhotoPhase.RETAKE_REQUESTED, trigger=trigger, retakes_used=ps.retakes_used,
                retakes_remaining=MAX_RETAKES - ps.retakes_used,
            )
        return self._open_fallback(ps, trigger, intake, reference_set)

    def decline_retake(self, session: DiagnosticSession) -> PhotoStep:
        """The driver cannot / will not retake: move to the fallback."""
        ps = self._photo_state[session.session_id]
        if ps.phase != PhotoPhase.RETAKE_REQUESTED or ps.last_intake is None or ps.reference_set is None:
            raise RuntimeError("no retake is currently requested")
        return self._open_fallback(ps, MatchStatus.INSUFFICIENT_VISUAL_QUALITY, ps.last_intake, ps.reference_set)

    def _open_fallback(
        self, ps: PhotoCaseState, trigger: MatchStatus, intake: DiagnosticIntakeResult,
        reference_set: DashboardReferenceSet,
    ) -> PhotoStep:
        ps.trigger = trigger
        ps.offer = fallback_offer(trigger, intake, reference_set)
        ps.phase = PhotoPhase.SELECTION_REQUIRED
        return PhotoStep(
            phase=PhotoPhase.SELECTION_REQUIRED, trigger=trigger, offer=ps.offer,
            retakes_used=ps.retakes_used, retakes_remaining=max(0, MAX_RETAKES - ps.retakes_used),
        )

    def record_user_symbol_selection(
        self, session: DiagnosticSession, *, entry_id: str | None,
    ) -> PhotoStep:
        """E5: the driver's own selection (or 'none of these'). Recorded
        with USER provenance -- never as a machine-verified visual match."""
        ps = self._photo_state[session.session_id]
        if ps.phase != PhotoPhase.SELECTION_REQUIRED or ps.offer is None or ps.media_reference is None:
            raise RuntimeError("no symbol selection is currently requested")
        case_state = self._case_states[session.session_id]
        intake = build_user_selection_intake(
            ps.offer, media_reference=ps.media_reference, selected_entry_id=entry_id,
        )
        self._updater.add_observations(case_state, list(intake.observations))
        if intake.evidence:
            self._updater.add_evidence(case_state, list(intake.evidence))
        self._complete_photo_acquisition(session, intake)
        return PhotoStep(phase=PhotoPhase.COMPLETED)

    def _complete_photo_acquisition(self, session: DiagnosticSession, intake: DiagnosticIntakeResult) -> None:
        """B2-R relevance -> safety re-evaluation -> existing flow.

        Order matters: safety is re-evaluated (unmodified SafetyEngine, on
        the governed entries only) BEFORE any ordinary question is
        selected. The provider's raw output never reaches this point: only
        a governed DiagnosticIntakeResult does."""
        ps = self._photo_state[session.session_id]
        case_state = self._case_states[session.session_id]
        ps.phase = PhotoPhase.COMPLETED

        # B2-R1/R2/R5: existing dashboard relevance, unmodified.
        new_hypotheses, new_evidence = self._domain.apply_dashboard_diagnostic_relevance(intake, case_state)
        if new_hypotheses:
            case_state.hypotheses.extend(new_hypotheses)
            case_state.touch()
        if new_evidence:
            self._updater.add_evidence(case_state, new_evidence)

        # E4: safety re-evaluation from GOVERNED reference entries.
        previous = session.safety_triage
        for obs_id, entry in intake.matched_reference_entries.items():
            session.warning_indicators.append(warning_indicator_from_entry(entry, photo_evidence_id=obs_id))
        triage = self.safety_engine.evaluate(session)
        session.safety_triage = triage
        case_state.safety_state = SafetyState(triage=triage)

        elevated = _severity_index(triage.level) > _severity_index(previous.level if previous else None)
        needs_location = (
            elevated
            and _severity_index(triage.level) >= _severity_index(TriageLevel.PROMPT_INSPECTION)
            and not ps.location_clarification_asked
        )
        if needs_location:
            # ONE safety-gated location question, before any ordinary question.
            question = self._domain.safety_clarification_question(case_state)
            case_state.questions.append(question)
            ps.location_clarification_asked = True
            session.pending_questions = [self._legacy_question(question)]
            if triage.level.value in ("emergency_stop", "do_not_drive"):
                session.log_transition(
                    session.state, SessionState.ESCALATED, f"Critical safety signal: {triage.level.value}",
                )
                session.result = build_result_from_case_state(session.request.request_id, case_state)
            return

        if triage.level.value in ("emergency_stop", "do_not_drive"):
            session.log_transition(
                session.state, SessionState.ESCALATED, f"Critical safety signal: {triage.level.value}",
            )
            session.result = build_result_from_case_state(session.request.request_id, case_state)
            session.pending_questions = []
            return

        session.pending_questions = self._advance(session, case_state)
        if not session.pending_questions:
            self._finalize(session, case_state)

    def _legacy_question(self, nq) -> DiagnosticQuestion:
        category = self._category_by_question_id.get(nq.id, None) or "clarification"
        return DiagnosticQuestion(
            question_id=nq.id, target=nq.domain_ref or "", category=category, prompt=nq.text,
            answer_type=nq.answer_type, required=False, risk_level=nq.risk_level or "none",
            selection_reason="Précision nécessaire suite à l'analyse de sécurité.", choices=nq.choices,
        )

    def submit_answer(self, session: DiagnosticSession, answer: Answer) -> DiagnosticSession:
        case_state = self._case_states[session.session_id]

        # PHOTO-FIRST: a safety-gated clarification asked on an ESCALATED
        # case is recorded but never restarts ordinary questioning (the
        # existing terminal-escalation semantics are unchanged).
        if session.state == SessionState.ESCALATED and any(
            q.question_id == answer.question_id for q in session.pending_questions
        ):
            session.answers.append(answer)
            new_question = next((q for q in case_state.questions if q.id == answer.question_id), None)
            if new_question is not None:
                self._case_states[session.session_id] = self._loop.submit_answer(
                    case_state, new_question, answer.value,
                )
            session.pending_questions = []
            return session

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
        # Repair (post-mandate review): _category_by_question_id is keyed
        # by question_id (e.g. "Q-EVI-001") -- the lookup must use nq.id
        # (the same value, per automotive/domain_adapter.py's
        # `id=raw["question_id"]`), not nq.domain_ref (e.g.
        # "evidence_availability"), which never matches any key. The old
        # code silently defaulted every question's category to
        # "clarification" regardless of its real category.
        category = self._category_by_question_id.get(nq.id, None) or "clarification"
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

        # P8 — governance gate. Every active hypothesis is governed by GGM
        # before it can appear in this report; the ORIGINAL case_state is
        # never mutated by governance (see governance/reporting.py). The
        # safety-escalated path in start() deliberately bypasses this
        # entirely (mandate §28) and is untouched.
        if self.governance_enabled and self._governance_port is not None:
            result, _traces = govern_and_build_result(
                session.request.request_id, case_state, self._governance_port,
            )
            session.result = result
        else:
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


_SEVERITY_ORDER = [
    TriageLevel.MONITOR_AND_DOCUMENT, TriageLevel.STANDARD_APPOINTMENT, TriageLevel.PROMPT_INSPECTION,
    TriageLevel.LIMITED_MOVEMENT_ONLY, TriageLevel.DO_NOT_DRIVE, TriageLevel.EMERGENCY_STOP,
]


def _severity_index(level: TriageLevel | None) -> int:
    return -1 if level is None else _SEVERITY_ORDER.index(level)
