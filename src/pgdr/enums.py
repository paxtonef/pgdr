"""Domain enums — PGDR v0.1 (see AMD packs 2, 4-14, 16-17)."""
from enum import Enum


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    PROVISIONALLY_RESOLVED = "provisionally_resolved"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_DATA = "insufficient_data"
    CONTRADICTORY = "contradictory"


class VehicleLocation(str, Enum):
    HOME = "home"
    ROADSIDE = "roadside"
    PARKING = "parking"
    WORKPLACE = "workplace"
    GARAGE = "garage"
    MOVING = "moving"
    UNKNOWN = "unknown"


class VehicleState(str, Enum):
    ENGINE_OFF = "engine_off"
    ENGINE_RUNNING = "engine_running"
    MOVING = "moving"
    UNABLE_TO_START = "unable_to_start"
    IMMOBILIZED = "immobilized"
    UNKNOWN = "unknown"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class DrivingStatus(str, Enum):
    NOT_DRIVING = "not_driving"
    PASSENGER = "passenger"
    PARKED = "parked"
    UNKNOWN = "unknown"


class TechnicalLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class SymptomFamily(str, Enum):
    STARTING = "starting"
    ENGINE_RUNNING = "engine_running"
    ACCELERATION = "acceleration"
    POWER_LOSS = "power_loss"
    BRAKING = "braking"
    STEERING = "steering"
    SUSPENSION = "suspension"
    TRANSMISSION = "transmission"
    ELECTRICAL = "electrical"
    BATTERY_OR_CHARGING = "battery_or_charging"
    TEMPERATURE_OR_OVERHEATING = "temperature_or_overheating"
    FLUID_LEAK = "fluid_leak"
    SMOKE = "smoke"
    SMELL = "smell"
    NOISE = "noise"
    VIBRATION = "vibration"
    WARNING_LIGHT = "warning_light"
    FUEL_CONSUMPTION = "fuel_consumption"
    TYRE_OR_WHEEL = "tyre_or_wheel"
    CLIMATE_CONTROL = "climate_control"
    VISIBILITY = "visibility"
    BODY_OR_STRUCTURE = "body_or_structure"
    CHARGING_SYSTEM_EV = "charging_system_ev"
    UNKNOWN = "unknown"


class Frequency(str, Enum):
    CONSTANT = "constant"
    INTERMITTENT = "intermittent"
    ONCE = "once"
    INCREASING = "increasing"
    DECREASING = "decreasing"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    SLIGHT = "slight"
    MODERATE = "moderate"
    STRONG = "strong"
    DISABLING = "disabling"
    UNKNOWN = "unknown"


class Reproducibility(str, Enum):
    ALWAYS = "always"
    OFTEN = "often"
    SOMETIMES = "sometimes"
    RARE = "rare"
    NOT_REPRODUCIBLE = "not_reproducible"
    UNKNOWN = "unknown"


class EvidenceSource(str, Enum):
    USER_STATEMENT = "user_statement"
    USER_OBSERVATION = "user_observation"
    UPLOADED_MEDIA = "uploaded_media"
    VEHICLE_DISPLAY = "vehicle_display"
    EXTERNAL_RECORD = "external_record"


class QuestionCategory(str, Enum):
    SAFETY = "safety"
    TEMPORAL = "temporal"
    OPERATING_CONDITION = "operating_condition"
    LOCALIZATION = "localization"
    INTENSITY = "intensity"
    WARNING_INDICATOR = "warning_indicator"
    RECENT_EVENT = "recent_event"
    EVIDENCE = "evidence"
    VEHICLE_BEHAVIOR = "vehicle_behavior"
    CLARIFICATION = "clarification"


class AnswerType(str, Enum):
    YES_NO = "yes_no"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    NUMERIC = "numeric"
    TEXT = "text"
    MEDIA_UPLOAD = "media_upload"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    PROHIBITED = "prohibited"


class WarningColor(str, Enum):
    RED = "red"
    AMBER = "amber"
    GREEN = "green"
    BLUE = "blue"
    WHITE = "white"
    UNKNOWN = "unknown"


class WarningBehavior(str, Enum):
    CONSTANT = "constant"
    FLASHING = "flashing"
    INTERMITTENT = "intermittent"
    APPEARED_THEN_DISAPPEARED = "appeared_then_disappeared"
    UNKNOWN = "unknown"


class TriageLevel(str, Enum):
    """Ordered from lowest to highest severity — see severity_rank() in safety_engine.py"""
    MONITOR_AND_DOCUMENT = "monitor_and_document"
    STANDARD_APPOINTMENT = "standard_appointment"
    PROMPT_INSPECTION = "prompt_inspection"
    LIMITED_MOVEMENT_ONLY = "limited_movement_only"
    DO_NOT_DRIVE = "do_not_drive"
    EMERGENCY_STOP = "emergency_stop"


class DrivingAssessment(str, Enum):
    """PGDR-INV-003 / boundary contract: 'safe_to_drive' must never exist as a value here."""
    NOT_ASSESSED = "not_assessed"
    DO_NOT_DRIVE = "do_not_drive"
    LIMITED_MOVEMENT = "limited_movement"
    PROFESSIONAL_ASSESSMENT_REQUIRED = "professional_assessment_required"


class EventRelation(str, Enum):
    BEFORE = "before"
    SIMULTANEOUS = "simultaneous"
    AFTER = "after"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SPECULATIVE = "speculative"


class ClaimStatus(str, Enum):
    POSSIBLE = "possible"
    COMPATIBLE = "compatible"
    UNLIKELY = "unlikely"
    UNRESOLVED = "unresolved"


class ContradictionSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContradictionImpact(str, Enum):
    NO_MATERIAL_IMPACT = "no_material_impact"
    HYPOTHESIS_UNCERTAINTY = "hypothesis_uncertainty"
    SAFETY_UNCERTAINTY = "safety_uncertainty"
    BLOCKS_REPORT_COMPLETION = "blocks_report_completion"


class ResolutionAction(str, Enum):
    RETAIN_BOTH = "retain_both"
    ASK_CLARIFICATION = "ask_clarification"
    REDUCE_CONFIDENCE = "reduce_confidence"
    BLOCK_CONCLUSION = "block_conclusion"


class SessionState(str, Enum):
    """Matches AMD pack 14.2 state machine."""
    RECEIVED = "received"
    IDENTITY_RESOLUTION = "identity_resolution"
    COMPLAINT_ANALYSIS = "complaint_analysis"
    IMMEDIATE_SAFETY_TRIAGE = "immediate_safety_triage"
    SYMPTOM_COLLECTION = "symptom_collection"
    EVIDENCE_COLLECTION = "evidence_collection"
    CONTRADICTION_CHECK = "contradiction_check"
    REASONING = "reasoning"
    REPORT_GENERATION = "report_generation"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"


class ReportStatus(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_LIMITATIONS = "completed_with_limitations"
    CLARIFICATION_REQUIRED = "clarification_required"
    SAFETY_ESCALATION = "safety_escalation"
    BLOCKED = "blocked"
