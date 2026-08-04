"""Pydantic domain models — PGDR v0.1."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from pgdr.enums import (
    AnswerType, ClaimStatus, Confidence, ContradictionImpact,
    ContradictionSeverity, DrivingAssessment, DrivingStatus, EventRelation,
    EvidenceSource, Frequency, QuestionCategory, ReportStatus,
    ResolutionAction, ResolutionStatus, Reproducibility, RiskLevel,
    SessionState, Severity, SymptomFamily, TechnicalLevel, TriageLevel,
    Urgency, VehicleLocation, VehicleState, WarningBehavior, WarningColor,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Pack 2 — Vehicle Identity (consumed from the Vehicle Identity Resolver)
# ---------------------------------------------------------------------------

class ConfidenceScore(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    level: str


class VehicleIdentityContext(BaseModel):
    """Input contract only — the PGDR never reconstructs VIR logic (PGDR-ID-001)."""
    resolution_id: str
    resolution_status: ResolutionStatus
    confidence: Optional[ConfidenceScore] = None
    vehicle_identity: Optional[dict[str, Any]] = None
    unresolved_fields: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pack 4 — Initial complaint
# ---------------------------------------------------------------------------

class InitialComplaint(BaseModel):
    free_text: str
    first_observed_at: Optional[datetime] = None
    current_vehicle_location: VehicleLocation = VehicleLocation.UNKNOWN
    vehicle_current_state: VehicleState = VehicleState.UNKNOWN
    perceived_urgency: Urgency = Urgency.UNKNOWN


class ComplaintExtraction(BaseModel):
    symptom_categories: list[str] = Field(default_factory=list)
    affected_functions: list[str] = Field(default_factory=list)
    temporal_markers: list[str] = Field(default_factory=list)
    operating_conditions: list[str] = Field(default_factory=list)
    user_emotions: list[str] = Field(default_factory=list)
    explicit_safety_signals: list[str] = Field(default_factory=list)
    uncertain_terms: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pack 5 — Symptom taxonomy
# ---------------------------------------------------------------------------

class Symptom(BaseModel):
    symptom_id: str = Field(default_factory=lambda: f"SYM-{uuid4().hex[:8].upper()}")
    family: SymptomFamily
    user_description: str
    normalized_description: str = ""
    first_occurrence: Optional[datetime] = None
    frequency: Frequency = Frequency.UNKNOWN
    severity: Severity = Severity.UNKNOWN
    reproducibility: Reproducibility = Reproducibility.UNKNOWN
    evidence_ids: list[str] = Field(default_factory=list)
    source: EvidenceSource = EvidenceSource.USER_STATEMENT
    is_primary: bool = False


# ---------------------------------------------------------------------------
# Pack 6 — Adaptive questioning
# ---------------------------------------------------------------------------

class DiagnosticQuestion(BaseModel):
    question_id: str = Field(default_factory=lambda: f"Q-{uuid4().hex[:8].upper()}")
    target: str
    category: QuestionCategory
    prompt: str
    answer_type: AnswerType
    required: bool = False
    risk_level: RiskLevel = RiskLevel.NONE
    selection_reason: str = ""
    choices: Optional[list[str]] = None


class Answer(BaseModel):
    question_id: str
    value: Union[str, int, float, bool, list[str], None]
    answered_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Pack 7 — Operating conditions
# ---------------------------------------------------------------------------

class OperatingConditions(BaseModel):
    engine_state: str = "unknown"
    vehicle_state: str = "unknown"
    speed_range: Optional[str] = None
    engine_speed_range: Optional[str] = None
    road_condition: str = "unknown"
    weather: str = "unknown"
    load: str = "unknown"
    accessories: dict[str, Any] = Field(default_factory=dict)


class ReproductionProfile(BaseModel):
    reproducible: bool = False
    sequence: list[str] = Field(default_factory=list)
    expected_delay_seconds: Optional[int] = None
    symptom_duration_seconds: Optional[int] = None
    recurrence: str = "unknown"


# ---------------------------------------------------------------------------
# Pack 8 — Warning indicators
# ---------------------------------------------------------------------------

class WarningIndicator(BaseModel):
    indicator_id: str = Field(default_factory=lambda: f"WI-{uuid4().hex[:8].upper()}")
    label: str
    observed_color: WarningColor = WarningColor.UNKNOWN
    behavior: WarningBehavior = WarningBehavior.UNKNOWN
    first_observed_at: Optional[datetime] = None
    associated_message: Optional[str] = None
    photo_evidence_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Pack 9 — Evidence
# ---------------------------------------------------------------------------

class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"EV-{uuid4().hex[:8].upper()}")
    evidence_type: str
    captured_at: Optional[datetime] = None
    captured_condition: Optional[str] = None
    user_description: Optional[str] = None
    file_reference: str = ""
    integrity_hash: Optional[str] = None
    automated_observations: list[str] = Field(default_factory=list)
    user_confirmed_observations: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pack 10 — Recent events
# ---------------------------------------------------------------------------

class VehicleEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"EVT-{uuid4().hex[:8].upper()}")
    event_type: str
    occurred_at: Optional[datetime] = None
    description: str = ""
    relation_to_symptom: EventRelation = EventRelation.UNKNOWN
    evidence_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pack 11 — Safety triage
# ---------------------------------------------------------------------------

class SafetyTriage(BaseModel):
    level: TriageLevel = TriageLevel.MONITOR_AND_DOCUMENT
    triggered_rules: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    user_instruction: str = ""
    driving_assessment: DrivingAssessment = DrivingAssessment.NOT_ASSESSED
    emergency_services_required: bool = False
    roadside_assistance_recommended: bool = False


# ---------------------------------------------------------------------------
# Pack 12 — Diagnostic reasoning
# ---------------------------------------------------------------------------

class DiagnosticHypothesis(BaseModel):
    hypothesis_id: str = Field(default_factory=lambda: f"HYP-{uuid4().hex[:8].upper()}")
    system_family: str
    description: str
    confidence: Confidence = Confidence.LOW
    supporting_observations: list[str] = Field(default_factory=list)
    contradicting_observations: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    recommended_professional_checks: list[str] = Field(default_factory=list)
    safety_relevance: str = "unknown"
    claim_status: ClaimStatus = ClaimStatus.POSSIBLE


# ---------------------------------------------------------------------------
# Pack 13 — Contradictions & uncertainty
# ---------------------------------------------------------------------------

class DiagnosticContradiction(BaseModel):
    contradiction_id: str = Field(default_factory=lambda: f"CTR-{uuid4().hex[:8].upper()}")
    fields: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)
    severity: ContradictionSeverity = ContradictionSeverity.LOW
    impact: ContradictionImpact = ContradictionImpact.NO_MATERIAL_IMPACT
    resolution_action: ResolutionAction = ResolutionAction.RETAIN_BOTH


class Uncertainty(BaseModel):
    identity_uncertainty: str = ""
    symptom_uncertainty: str = ""
    evidence_uncertainty: str = ""
    safety_uncertainty: str = ""
    reasoning_uncertainty: str = ""


# ---------------------------------------------------------------------------
# Pack 18 — Garage Preparation Report
# ---------------------------------------------------------------------------

class GaragePreparationReport(BaseModel):
    report_id: str = Field(
        default_factory=lambda: f"PGDR-REPORT-{_now().strftime('%Y')}-{uuid4().hex[:6].upper()}"
    )
    vehicle: dict[str, Any] = Field(default_factory=dict)
    customer_reported_problem: str = ""
    symptom_summary: list[dict[str, Any]] = Field(default_factory=list)
    onset_and_evolution: dict[str, Any] = Field(default_factory=dict)
    reproduction_conditions: Optional[dict[str, Any]] = None
    warning_indicators: list[dict[str, Any]] = Field(default_factory=list)
    safety_information: dict[str, Any] = Field(default_factory=dict)
    recent_vehicle_events: list[dict[str, Any]] = Field(default_factory=list)
    evidence_index: list[dict[str, Any]] = Field(default_factory=list)
    systems_to_examine: list[dict[str, Any]] = Field(default_factory=list)
    suggested_professional_checks: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Pack 19 — User summary
# ---------------------------------------------------------------------------

class UserSummary(BaseModel):
    urgency: dict[str, str] = Field(default_factory=dict)
    main_observations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    disclaimer: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pack 16 — Input contract
# ---------------------------------------------------------------------------

class UserContext(BaseModel):
    driving_status: DrivingStatus = DrivingStatus.UNKNOWN
    technical_level: TechnicalLevel = TechnicalLevel.UNKNOWN


class Consent(BaseModel):
    media_analysis_allowed: bool = False
    report_storage_allowed: bool = False


class PreGarageDiagnosticRequest(BaseModel):
    request_id: str
    locale: str = "fr-FR"
    vehicle_identity_context: VehicleIdentityContext
    initial_complaint: InitialComplaint
    user_context: UserContext = Field(default_factory=UserContext)
    evidence: list[Evidence] = Field(default_factory=list)
    consent: Consent


# ---------------------------------------------------------------------------
# Pack 17 — Output contract
# ---------------------------------------------------------------------------

class PreGarageDiagnosticResult(BaseModel):
    request_id: str
    diagnostic_session_id: str = Field(
        default_factory=lambda: f"SESS-{uuid4().hex[:12].upper()}"
    )
    created_at: datetime = Field(default_factory=_now)
    status: ReportStatus = ReportStatus.COMPLETED
    vehicle_identity_summary: dict[str, Any] = Field(default_factory=dict)
    user_complaint: dict[str, str] = Field(default_factory=dict)
    symptoms: list[Symptom] = Field(default_factory=list)
    operating_conditions: Optional[OperatingConditions] = None
    recent_events: list[VehicleEvent] = Field(default_factory=list)
    warning_indicators: list[WarningIndicator] = Field(default_factory=list)
    evidence_summary: list[Evidence] = Field(default_factory=list)
    safety_triage: SafetyTriage = Field(default_factory=SafetyTriage)
    diagnostic_hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list)
    contradictions: list[DiagnosticContradiction] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    garage_preparation_report: Optional[GaragePreparationReport] = None
    user_summary: Optional[UserSummary] = None
    limitations: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session (working state machine object — Pack 14.2)
# ---------------------------------------------------------------------------

class DiagnosticSession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"SESS-{uuid4().hex[:12].upper()}")
    state: SessionState = SessionState.RECEIVED
    request: PreGarageDiagnosticRequest

    extracted_complaint: Optional[ComplaintExtraction] = None
    symptoms: list[Symptom] = Field(default_factory=list)
    answers: list[Answer] = Field(default_factory=list)
    questions_asked: list[DiagnosticQuestion] = Field(default_factory=list)
    pending_questions: list[DiagnosticQuestion] = Field(default_factory=list)

    operating_conditions: Optional[OperatingConditions] = None
    reproduction_profile: Optional[ReproductionProfile] = None
    warning_indicators: list[WarningIndicator] = Field(default_factory=list)
    events: list[VehicleEvent] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    safety_triage: Optional[SafetyTriage] = None
    hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list)
    contradictions: list[DiagnosticContradiction] = Field(default_factory=list)

    result: Optional[PreGarageDiagnosticResult] = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    def log_transition(self, from_state: SessionState, to_state: SessionState, reason: str = "") -> None:
        self.trace.append({
            "timestamp": _now().isoformat(),
            "from": from_state.value,
            "to": to_state.value,
            "reason": reason,
        })
        self.state = to_state
