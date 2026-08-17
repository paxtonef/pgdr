"""P4 mandate §14-16, 20-21 — DiagnosticLoop: runs one analytical
iteration independent of the CLI or any future web layer, per §14's
required contract. Per §16, the safety-preemption invariant is unchanged
— DiagnosticLoop consults SafetyState.preempts_analysis (itself a thin
wrapper over the existing, unmodified SafetyEngine's output) and refuses
to proceed, exactly as SessionController already does for the v0.1
pipeline. P4 changes zero automotive safety rules.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.enums import AnalyticalStatus, DiagnosticStopReason, ObservationSource
from pgdr.domain.identity import MachineIdentityContext
from pgdr.domain.observation import Observation
from pgdr.domain.question import DiagnosticAnswer, DiagnosticQuestion
from pgdr.domain.safety_state import SafetyState
from pgdr.ports.diagnostic_domain import DiagnosticDomain
from pgdr.ports.evidence_mapper import EvidenceMapper
from pgdr.ports.question_selector import QuestionSelector

from pgdr.application.case_state_updater import CaseStateUpdater

DEFAULT_MAX_ITERATIONS = 25


class DiagnosticIterationResult(BaseModel):
    state: DiagnosticCaseState
    next_question: DiagnosticQuestion | None = None
    stop_reason: DiagnosticStopReason | None = None


class DiagnosticLoop:
    def __init__(
        self,
        domain: DiagnosticDomain,
        evidence_mapper: EvidenceMapper,
        selector: QuestionSelector,
        updater: CaseStateUpdater,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self._domain = domain
        self._evidence_mapper = evidence_mapper
        self._selector = selector
        self._updater = updater
        self._max_iterations = max_iterations
        # Anti-loop bookkeeping (§21): per case_id, remembers the last
        # question offered and a content fingerprint of the state at that
        # moment. If run_iteration would return the identical question
        # again with no CONTENT change in between (not just a timestamp
        # touch — run_iteration itself always calls state.touch() when it
        # advances `iteration`, so updated_at alone is not a reliable
        # "did anything change" signal), it stops instead. This is an
        # execution-engine safeguard, not a cognitive rule (explicitly not
        # a substitute for future CGM question-relevance governance).
        self._last_seen: dict[str, tuple[str, tuple[int, int, int, int]]] = {}

    # -- lifecycle ------------------------------------------------------

    def start(
        self,
        raw_complaint: str,
        identity_context: MachineIdentityContext | None = None,
        safety_state: SafetyState | None = None,
    ) -> DiagnosticCaseState:
        """P4-T01: builds a DiagnosticCaseState from an initial complaint.
        Mirrors the mandate's diagram: Complaint -> observations ->
        evidence(none yet) -> hypotheses -> uncertainty -> ready for
        run_iteration()."""
        state = DiagnosticCaseState(identity_context=identity_context, safety_state=safety_state)

        raw_obs = Observation(kind="raw_complaint", value=raw_complaint, source_type=ObservationSource.USER)
        self._updater.add_observations(state, [raw_obs])

        derived = self._domain.interpret_observations(state)
        if derived:
            self._updater.add_observations(state, derived)

        if state.safety_state is not None and state.safety_state.preempts_analysis:
            state.analytical_status = AnalyticalStatus.STOPPED
            state.stop_reason = DiagnosticStopReason.SAFETY_PREEMPTED
            return state

        self._generate_hypotheses_and_evidence(state)
        return state

    # -- iteration --------------------------------------------------------

    def run_iteration(self, state: DiagnosticCaseState) -> DiagnosticIterationResult:
        """One analytical iteration per mandate §14's 9-step contract.
        Steps 2-6 (process observations / create evidence / update
        hypotheses & contradictions & uncertainties) happen as a side
        effect of `submit_answer()` being called between iterations —
        this method's job is step 1 (safety), and steps 7-9 (continue?
        which question next?)."""
        # 1. validate safety state
        if state.safety_state is not None and state.safety_state.preempts_analysis:
            return self._stop(state, DiagnosticStopReason.SAFETY_PREEMPTED)

        if state.iteration >= self._max_iterations:
            return self._stop(state, DiagnosticStopReason.MAX_ITERATIONS_REACHED)

        state.iteration += 1
        state.touch()

        # Domain may propose new hypotheses / evidence as observations
        # accumulate (steps 2-4 of §14 for anything not already handled
        # by submit_answer()).
        self._generate_hypotheses_and_evidence(state)

        # 7. decide whether analysis continues
        if not state.active_hypotheses():
            return self._stop(state, DiagnosticStopReason.NO_ACTIVE_HYPOTHESES)

        # 8/9. select next question
        available = self._domain.available_questions(state)
        existing_question_ids = {q.id for q in state.questions}
        for q in available:
            if q.id not in existing_question_ids:
                state.questions.append(q)
                existing_question_ids.add(q.id)

        answered_ids = state.answered_question_ids()
        candidates = [q for q in available if q.active and (q.id not in answered_ids or q.repeatable)]

        next_question = self._selector.select(candidates, state)
        if next_question is None:
            return self._stop(state, DiagnosticStopReason.NO_AVAILABLE_QUESTION)

        # Anti-loop guard (§21): identical candidate + no CONTENT change
        # since it was last offered for this case -> stop rather than
        # cycle. Fingerprint is (observations, evidence, answers,
        # hypotheses) counts — NOT updated_at, which this method itself
        # always advances via state.touch() above regardless of whether
        # anything substantive changed.
        fingerprint = (len(state.observations), len(state.evidence), len(state.answers), len(state.hypotheses))
        last = self._last_seen.get(state.case_id)
        if last is not None and last == (next_question.id, fingerprint):
            return self._stop(state, DiagnosticStopReason.NO_STATE_CHANGE)
        self._last_seen[state.case_id] = (next_question.id, fingerprint)

        return DiagnosticIterationResult(state=state, next_question=next_question, stop_reason=None)

    def submit_answer(
        self, state: DiagnosticCaseState, question: DiagnosticQuestion, value: Any
    ) -> DiagnosticCaseState:
        """P4-T05/T06/T07: Answer -> Observation -> Evidence -> Hypothesis
        update. Never just 'append to report' (mandate §11)."""
        observation = Observation(
            kind=f"answer:{question.id}",
            value=value,
            source_type=ObservationSource.USER,
            source_ref=question.id,
        )
        self._updater.add_observations(state, [observation])

        answer = DiagnosticAnswer(
            question_id=question.id,
            value=value,
            observation_ids_created=[observation.id],
        )
        self._updater.record_answer(state, answer)

        new_evidence = self._evidence_mapper.from_answer(question, answer, state)
        if new_evidence:
            self._updater.add_evidence(state, new_evidence)

        return state

    # -- internals --------------------------------------------------------

    def _generate_hypotheses_and_evidence(self, state: DiagnosticCaseState) -> None:
        """Steps 3-4 of §14: ask the domain for any new hypotheses given
        current observations, then for evidence linking observations to
        (new or existing) hypotheses. Wired as one step because
        map_evidence's initial-support rule (see AutomotiveDiagnosticDomain)
        depends on the hypotheses it's evaluating already existing on
        `state`."""
        new_hypotheses = self._domain.generate_hypotheses(state)
        if new_hypotheses:
            existing_ids = {h.id for h in state.hypotheses}
            truly_new = [h for h in new_hypotheses if h.id not in existing_ids]
            if truly_new:
                state.hypotheses.extend(truly_new)
                state.touch()

        new_evidence = self._domain.map_evidence(state)
        if new_evidence:
            self._updater.add_evidence(state, new_evidence)
        elif state.hypotheses:
            # No new evidence, but confidence still needs computing for
            # brand-new hypotheses that haven't been scored yet.
            unscored_ids = {h.id for h in state.hypotheses if h.confidence is None}
            if unscored_ids:
                self._updater.update_hypotheses(state, unscored_ids)

    def _stop(self, state: DiagnosticCaseState, reason: DiagnosticStopReason) -> DiagnosticIterationResult:
        state.analytical_status = AnalyticalStatus.STOPPED
        state.stop_reason = reason
        return DiagnosticIterationResult(state=state, next_question=None, stop_reason=reason)
