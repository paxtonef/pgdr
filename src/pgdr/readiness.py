"""P1 — Runner Execution Contract: readiness check mechanism.

LIVENESS ("is the process alive?") and READINESS ("can PGDR safely accept
diagnostic work right now?") are different questions. A PGDR process can
be LIVE (the Python interpreter started, `import pgdr` succeeded) while
being NOT READY (its safety configuration is invalid). This module only
answers the READINESS question — liveness is trivially true if this code
is executing at all, and is not separately modeled here (see
runner_execution_contract.yaml `liveness` section).

This module does not invent capabilities PGDR doesn't have. As of P1,
PGDR has exactly 3 required internal checks (packaged configuration,
safety engine, full session controller construction) and zero optional
capabilities — see runner_execution_contract.yaml for the authoritative,
explicit inventory. `check_readiness(extra_checks=...)` accepts
synthetic checks so the *mechanism itself* (in particular: "an optional
check failing must never block readiness") can be exercised by tests
without fabricating a PGDR capability that doesn't exist in production.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pgdr.errors import ConfigurationError


class CheckStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"


class FailureReason(str, Enum):
    """Maps to the `failure_semantics` section of
    runner_execution_contract.yaml. Computed from the readiness report,
    not hand-assigned per check, so it always reflects what actually
    failed rather than a guess made at check-authoring time."""
    NONE = "none"
    CONFIGURATION_ERROR = "configuration_error"
    SAFETY_ENGINE_UNAVAILABLE = "safety_engine_unavailable"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"


@dataclass
class CapabilityCheck:
    name: str
    required: bool
    status: CheckStatus
    detail: str = ""
    # Only meaningful when status == FAILED. Distinguishes "this failed
    # because safety_rules.yaml didn't validate" (CONFIGURATION_ERROR)
    # from "this failed for some other reason entirely" (CAPABILITY_UNAVAILABLE)
    # — see _classify_exception below.
    failure_reason: FailureReason = FailureReason.NONE


@dataclass
class ReadinessReport:
    ready: bool
    checks: list[CapabilityCheck] = field(default_factory=list)

    @property
    def reason(self) -> FailureReason:
        if self.ready:
            return FailureReason.NONE
        failed_required = [c for c in self.checks if c.required and c.status == CheckStatus.FAILED]
        if not failed_required:
            return FailureReason.NONE
        # safety_engine failures take priority in reporting — a broken
        # safety envelope is the most operationally significant reason to
        # be NOT_READY, even if other checks also failed.
        for c in failed_required:
            if c.name == "safety_engine":
                return c.failure_reason
        return failed_required[0].failure_reason

    def as_dict(self) -> dict:
        return {
            "ready": self.ready,
            "reason": self.reason.value,
            "checks": [
                {
                    "name": c.name,
                    "required": c.required,
                    "status": c.status.value,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


def _classify_exception(exc: Exception) -> FailureReason:
    if isinstance(exc, ConfigurationError):
        return FailureReason.CONFIGURATION_ERROR
    return FailureReason.CAPABILITY_UNAVAILABLE


def _check_packaged_resources_and_configuration() -> CapabilityCheck:
    """Required. All 4 governance YAML files must be present and load
    without error (P0.2); safety_rules.yaml must additionally pass full
    semantic validation (P0.3)."""
    from pgdr.config_loader import load_all_configs
    try:
        load_all_configs()
        return CapabilityCheck("packaged_resources_and_configuration", True, CheckStatus.OK)
    except Exception as exc:
        return CapabilityCheck(
            "packaged_resources_and_configuration", True, CheckStatus.FAILED,
            detail=str(exc), failure_reason=_classify_exception(exc),
        )


def _check_safety_engine() -> CapabilityCheck:
    """Required. The deterministic safety engine must construct
    successfully and load at least one rule. This is intentionally
    checked separately from the generic config check above, even though
    today both are driven by the same safety_rules.yaml — the Runner
    Execution Contract tracks 'safety engine operational' as its own
    readiness axis (see runner_execution_contract.yaml `safety`)."""
    from pgdr.safety_engine import SafetyEngine
    try:
        engine = SafetyEngine()
        if not engine.rules:
            return CapabilityCheck(
                "safety_engine", True, CheckStatus.FAILED,
                detail="SafetyEngine constructed with zero rules loaded",
                failure_reason=FailureReason.SAFETY_ENGINE_UNAVAILABLE,
            )
        return CapabilityCheck(
            "safety_engine", True, CheckStatus.OK,
            detail=f"{len(engine.rules)} safety rules loaded",
        )
    except Exception as exc:
        return CapabilityCheck(
            "safety_engine", True, CheckStatus.FAILED,
            detail=str(exc), failure_reason=FailureReason.SAFETY_ENGINE_UNAVAILABLE,
        )


def _check_session_controller() -> CapabilityCheck:
    """Required. Constructing a full SessionController exercises every
    required capability at once: ComplaintParser (symptom_taxonomy.yaml),
    the automotive Domain Pack (business_rules.yaml, questions.yaml,
    domain evidence-mapping validation), and SafetyEngine. This is PGDR's
    complete set of required internal capabilities as of P7 — there are
    no optional capabilities to check today (see
    runner_execution_contract.yaml `capabilities.optional`)."""
    from pgdr.session_controller import SessionController
    try:
        SessionController()
        return CapabilityCheck("session_controller", True, CheckStatus.OK)
    except Exception as exc:
        return CapabilityCheck(
            "session_controller", True, CheckStatus.FAILED,
            detail=str(exc), failure_reason=_classify_exception(exc),
        )


def check_readiness(extra_checks: list[CapabilityCheck] | None = None) -> ReadinessReport:
    """Runs every required PGDR readiness check, plus any `extra_checks`
    supplied by a caller (used by tests to exercise the optional-check
    path — see module docstring). READY iff every REQUIRED check passed;
    an OPTIONAL check failing never blocks readiness."""
    checks = [
        _check_packaged_resources_and_configuration(),
        _check_safety_engine(),
        _check_session_controller(),
    ]
    if extra_checks:
        checks.extend(extra_checks)

    ready = all(c.status == CheckStatus.OK for c in checks if c.required)
    return ReadinessReport(ready=ready, checks=checks)
