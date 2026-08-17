"""P4 domain enums. Reuses pgdr.enums.AnswerType for
DiagnosticQuestion.answer_type rather than inventing a parallel
QuestionAnswerType — the existing enum already covers yes_no /
single_choice / multiple_choice / numeric / text / media_upload and there
is no reason for the analytical layer to duplicate it.
"""
from __future__ import annotations

from enum import Enum


class ObservationSource(str, Enum):
    """Where a piece of case data came from. Per P4 mandate §4: this says
    only WHERE the data originated, never whether it's true — epistemic
    status (verified/confirmed/etc.) is explicitly out of scope for P4."""
    USER = "USER"
    VIR = "VIR"
    MACHINE = "MACHINE"
    DOCUMENT = "DOCUMENT"
    PROVIDER = "PROVIDER"
    SYSTEM = "SYSTEM"


class EvidenceDirection(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"


class UncertaintyKind(str, Enum):
    IDENTITY = "IDENTITY"
    SYMPTOM = "SYMPTOM"
    CONTEXT = "CONTEXT"
    EVIDENCE = "EVIDENCE"
    CAUSAL = "CAUSAL"


class AnalyticalStatus(str, Enum):
    """Status of the case's analytical process itself (is the loop still
    running, why did it stop) — NOT a diagnostic conclusion status. See
    DiagnosticStopReason for the specific stop reason when not ACTIVE."""
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"


class DiagnosticStopReason(str, Enum):
    """Technical reasons the analytical loop stopped. Deliberately does
    NOT include a 'CONFIRMED_DIAGNOSIS' member — per P4 mandate §15, that
    would encroach on the future epistemic contract with GGM/CGM."""
    SAFETY_PREEMPTED = "SAFETY_PREEMPTED"
    NO_ACTIVE_HYPOTHESES = "NO_ACTIVE_HYPOTHESES"
    NO_AVAILABLE_QUESTION = "NO_AVAILABLE_QUESTION"
    REQUIRED_INPUT_UNAVAILABLE = "REQUIRED_INPUT_UNAVAILABLE"
    USER_STOPPED = "USER_STOPPED"
    ANALYTICAL_LOOP_COMPLETE = "ANALYTICAL_LOOP_COMPLETE"
    MAX_ITERATIONS_REACHED = "MAX_ITERATIONS_REACHED"
    NO_STATE_CHANGE = "NO_STATE_CHANGE"
