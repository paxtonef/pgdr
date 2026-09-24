"""Pydantic domain models — PGDR v0.1."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pgdr.domain.media import PrimaryDiagnosticMedia
from pgdr.enums import (
    AnswerType, ClaimStatus, Confidence, ContradictionImpact,
    ContradictionSeverity, Deadline, DrivingAssessment, DrivingStatus,
    EventRelation, EvidenceSource, FindingBasis, Frequency, ImmediateRequirement,
    ManufacturerOperability, PracticalProviderStatus, PracticalRequirement, QuestionCategory,
    ReportStatus, ResolutionAction, ResolutionStatus, Reproducibility,
    RiskLevel, SessionState, Severity, SymptomFamily, TechnicalLevel,
    TriageLevel, Urgency, VehicleLocation, VehicleState, WarningBehavior,
    WarningColor,
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
    dashboard_identifications: list[dict[str, Any]] = Field(default_factory=list)
    """B2 photo-first: dashboard symbols established from the driver's photo,
    each with an explicit `origin` -- 'visual_provider_match' (machine
    visual interpretation, validated against the manufacturer reference
    set) or 'user_selection' (the driver's own choice from the
    manufacturer symbol list, machine_verified=False). The two are never
    merged or phrased alike. Empty for cases without a photo."""
    systems_to_examine: list[dict[str, Any]] = Field(default_factory=list)
    suggested_professional_checks: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    contradictions: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_now)
    manufacturer_first_finding: Optional[dict[str, Any]] = None
    """PGDR Part 1 (Execution Mandate v0.2 FINAL, §1 C7): the Manufacturer
    First Finding, additive key. None for cases without a photo. Every
    pre-existing key above is unchanged (D-C5: the legacy urgency content
    is not authoritative for Part 1 and never overrides this finding)."""


# ---------------------------------------------------------------------------
# Pack 19 — User summary (extended by PGDR Driver Diagnostic Execution
# Mandate v0 — see D01/§9. All new fields are additive; the four
# pre-existing fields keep their exact original shape, so no existing
# PreGarageDiagnosticResult consumer breaks (mandate §19).
# ---------------------------------------------------------------------------

class PlausibleCause(BaseModel):
    """A single driver-facing entry in the plausible-cause space (mandate
    §9.E / §11). Reuses the existing hypothesis's own description and
    epistemic status verbatim — no new claim is invented here, only
    translated to a human-facing label at the presentation boundary."""
    label: str
    description: str
    confidence: Confidence
    claim_status: ClaimStatus


class UserSummary(BaseModel):
    urgency: dict[str, str] = Field(default_factory=dict)
    main_observations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    disclaimer: list[str] = Field(default_factory=list)

    # -- Driver Diagnostic extension (mandate D01/§9) --------------------
    situation_explanation: str = ""
    safety_level: TriageLevel = TriageLevel.MONITOR_AND_DOCUMENT
    driveability: DrivingAssessment = DrivingAssessment.NOT_ASSESSED
    urgency_deadline: Deadline = Deadline.MONITORING
    diagnostic_confidence: Optional[Confidence] = None
    plausible_causes: list[PlausibleCause] = Field(default_factory=list)
    remaining_uncertainty: list[str] = Field(default_factory=list)


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
    primary_diagnostic_media: Optional[PrimaryDiagnosticMedia] = None
    """Block B1 (VIR_PHOTO_PGDR_BUILD_DECOMPOSITION_v1, PGDR_BLOCK_B1_
    PRIMARY_DIAGNOSTIC_MEDIA_CONTRACT_v0 §5): the canonical, explicit
    diagnostic-input surface for raw dashboard media, deliberately
    distinct from `evidence` above (Evidence is a scored, targeted,
    already-formal concept -- this field carries only raw, uninterpreted
    input, exactly matching the frozen semantics: media_reference ->
    Evidence(...) and media_reference -> InitialComplaint(...) are both
    forbidden). Chosen as the smallest existing canonical request surface
    that already represents diagnostic input, per §5's own instruction to
    inspect existing models before adding a new one -- no new request
    model was created."""
    consent: Consent


# ---------------------------------------------------------------------------
# PGDR Part 1 — Manufacturer First Finding (Execution Mandate v0.2 FINAL, §3)
#
# Additive output representation. Every structured item is DOCUMENTED
# (verbatim source phrase), DERIVED (named §9 rule + the phrase it applies
# to) or NOT_ESTABLISHED. The manufacturer text carried here is read at
# runtime from the manufacturer knowledge record (the DashboardReferenceEntry
# supplied through PI) -- never from PGDR's derivation layer (§4).
# ---------------------------------------------------------------------------

FINDING_SOURCE_FIELDS = ("documented_meaning", "documented_instruction", "displayed_message")
NOT_ESTABLISHED_VALUE = "not_established"


class FindingItem(BaseModel):
    """§3 item shape, with the loader invariants enforced structurally."""
    model_config = ConfigDict(frozen=True)

    value: str
    basis: FindingBasis
    rule_id: Optional[str] = None
    source_field: Optional[str] = None
    source_phrase: Optional[str] = None

    @model_validator(mode="after")
    def _invariants(self) -> "FindingItem":
        if (self.value == NOT_ESTABLISHED_VALUE) != (self.basis == FindingBasis.NOT_ESTABLISHED):
            raise ValueError("value = not_established <=> basis = not_established")
        if (self.rule_id is not None) != (self.basis == FindingBasis.DERIVED):
            raise ValueError("rule_id is required iff basis = derived")
        established = self.basis != FindingBasis.NOT_ESTABLISHED
        if established != (self.source_field is not None) or established != (self.source_phrase is not None):
            raise ValueError("source_field/source_phrase are required iff basis != not_established")
        if self.source_field is not None and self.source_field not in FINDING_SOURCE_FIELDS:
            raise ValueError(f"unknown source_field {self.source_field!r}")
        return self

    @classmethod
    def not_established(cls) -> "FindingItem":
        return cls(value=NOT_ESTABLISHED_VALUE, basis=FindingBasis.NOT_ESTABLISHED)


class DocumentedPhrase(BaseModel):
    """A verbatim phrase of the manufacturer record (e.g. a stop condition)."""
    model_config = ConfigDict(frozen=True)

    source_field: str
    source_phrase: str


class DocumentedFigure(BaseModel):
    """§3.4 / R-4: a documented range, countdown or quantity. Never an
    operability limit and never permission to drive. `caution` = the
    mandatory T6 caution applies (a distance/range figure)."""
    model_config = ConfigDict(frozen=True)

    source_field: str
    source_phrase: str
    meaning: str
    caution: bool


class PracticalAssistanceRequirement(BaseModel):
    """§3.5 handoff interface to a later Practical Assistance capability.
    Nothing is acquired or called: provider_status is always NOT_INTEGRATED
    and its absence never blocks the finding."""
    model_config = ConfigDict(frozen=True)

    requirement: FindingItem
    documented_suitability: FindingItem
    urgency_phrase: FindingItem
    precise_location_needed: bool
    provider_status: PracticalProviderStatus = PracticalProviderStatus.NOT_INTEGRATED


class FindingProvenance(BaseModel):
    """§3.8."""
    model_config = ConfigDict(frozen=True)

    document_id: str
    document_title: str
    source_authority: str
    freshness_status: str
    entry_id: str
    manufacturer_designation: str
    colour: Optional[str] = None
    state: Optional[str] = None
    identification_origin: str
    mapping_fingerprint_match: bool
    language: str = "en (source representation, untranslated)"


_ITEM_VALUE_SETS: dict[str, set[str]] = {
    "stop_vehicle_engine_off": {v.value for v in ImmediateRequirement},
    "vehicle_immobilization": {v.value for v in ImmediateRequirement},
    "exit_vehicle": {v.value for v in ImmediateRequirement},
    "move_away_from_vehicle": {v.value for v in ImmediateRequirement},
    "environment_dependent_requirement": {v.value for v in ImmediateRequirement},
    "operability": {v.value for v in ManufacturerOperability},
    "professional_attention": {v.value for v in ImmediateRequirement},
}
_MAY_DRIVE_VALUES = {ManufacturerOperability.MAY_DRIVE.value, ManufacturerOperability.MAY_DRIVE_WITH_RESTRICTIONS.value}


class EntryFinding(BaseModel):
    """The Manufacturer First Finding for ONE identified manufacturer entry.

    `stop_vehicle_engine_off` (the immediate action, §3.1 / A1) and
    `operability` (subsequent use of the vehicle, §3.3) are two distinct
    fields: neither is ever computed from the other's value."""
    model_config = ConfigDict(frozen=True)

    provenance: FindingProvenance
    # Manufacturer text, verbatim, from the live manufacturer record.
    manufacturer_designation: str
    documented_meaning: str
    documented_instruction: Optional[str] = None
    displayed_message: Optional[str] = None
    combined_with_entry_ids: list[str] = Field(default_factory=list)

    stop_vehicle_engine_off: FindingItem
    vehicle_immobilization: FindingItem
    exit_vehicle: FindingItem
    move_away_from_vehicle: FindingItem
    environment_dependent_requirement: FindingItem
    operability: FindingItem
    max_speed: FindingItem
    max_distance: FindingItem
    max_duration: FindingItem
    stop_conditions: list[DocumentedPhrase] = Field(default_factory=list)
    documented_figures: list[DocumentedFigure] = Field(default_factory=list)
    professional_attention: FindingItem
    urgency_phrase: FindingItem
    documented_suitability: FindingItem
    practical_assistance: PracticalAssistanceRequirement
    audit_flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _value_sets(self) -> "EntryFinding":
        for name, allowed in _ITEM_VALUE_SETS.items():
            if getattr(self, name).value not in allowed:
                raise ValueError(f"{name}: invalid value {getattr(self, name).value!r}")
        if self.practical_assistance.requirement.value not in {v.value for v in PracticalRequirement}:
            raise ValueError("practical_assistance.requirement: invalid value")
        # Decision 1 / PGDR-INV-003 / D-C1: permission is never inferred.
        if self.operability.value in _MAY_DRIVE_VALUES and self.operability.basis != FindingBasis.DOCUMENTED:
            raise ValueError("MAY_DRIVE* may only be DOCUMENTED")
        # R-4: a documented figure never becomes a distance/duration limit.
        figure_phrases = {f.source_phrase for f in self.documented_figures}
        for limit in (self.max_distance, self.max_duration):
            if limit.source_phrase is not None and limit.source_phrase in figure_phrases:
                raise ValueError("R-4: a documented figure cannot populate max_distance/max_duration")
        return self


class ManufacturerFirstFinding(BaseModel):
    """PGDR Part 1 terminal artifact: one EntryFinding per identified
    manufacturer entry (possibly none, e.g. when the driver indicated that
    no offered symbol matched), plus the R-5 composition record."""
    model_config = ConfigDict(frozen=True)

    entries: list[EntryFinding] = Field(default_factory=list)
    triage_composition: list[str] = Field(default_factory=list)
    """R-5 rows that applied (e.g. 'R-5:stop_vehicle_engine_off:oil-pressure-warning'),
    for traceability. Empty when R-5 applied no row."""


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
    manufacturer_first_finding: Optional[ManufacturerFirstFinding] = None
    """PGDR Part 1 (§1 C7): present on both terminal paths of a photo-origin
    case; None for every other case."""


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
