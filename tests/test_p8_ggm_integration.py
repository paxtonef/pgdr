"""P8 — PGDR x GGM Governed Consumption Integration tests.

Every test here runs against the REAL pinned GGM package (never a mock
of GGM's own internals) — the only fixtures below fake are PGDR-side
GGMConsumer *injections* (mandate's own sanctioned pattern, §30: "For
tests/development, dependency injection may use DefaultGGMConsumer or a
deterministic test consumer").
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from ggm.contract.errors import ConsumptionError, ErrorType
from ggm.contract.interface import DefaultGGMConsumer
from ggm.contract.types import GovernanceRequest, GovernanceResult, Operation, ProfileTrace
from ggm.model import DecisionType

from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
from pgdr.governance.adapter import GGMDiagnosticGovernanceAdapter
from pgdr.governance.consumption_profile import resolve_pgdr_consumption_manifest_or_raise
from pgdr.governance.errors import GovernanceUnavailableError
from pgdr.governance.object_mapper import PGDRGGMObjectMapper
from pgdr.governance.port import DiagnosticGovernanceCandidate
from pgdr.governance.reporting import govern_and_build_result
from pgdr.governance.trace import InMemoryGovernanceTraceStore
from pgdr.models import Answer, Consent, InitialComplaint, PreGarageDiagnosticRequest, VehicleIdentityContext
from pgdr.session_controller import SessionController

PROJECT_ROOT = Path(__file__).parent.parent
GOVERNANCE_PACKAGE = PROJECT_ROOT / "src" / "pgdr" / "governance"

# Symbols P8 must never import directly (mandate §4/§39).
_FORBIDDEN_GGM_SYMBOLS = {
    "InvariantEngine", "TransitionEngine", "GovernanceDecisionEngine",
    "EscalationDetector", "ProfileResolver", "build_default_profiles",
}
_FORBIDDEN_SCRIPT_MODULES = {
    "semantic_provider", "semantic_mapper", "openai_semantic_provider",
    "sgri_validator", "mock_semantic_provider", "semantic_evaluator", "semantic_types",
}


def _make_request(request_id, complaint, vir_status=ResolutionStatus.PROVISIONALLY_RESOLVED):
    return PreGarageDiagnosticRequest(
        request_id=request_id,
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=f"VIR-{request_id}", resolution_status=vir_status,
        ),
        initial_complaint=InitialComplaint(
            free_text=complaint, current_vehicle_location=VehicleLocation.HOME,
            vehicle_current_state=VehicleState.ENGINE_OFF,
        ),
        consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),
    )


class _FixedOutcomeConsumer:
    """A deterministic test consumer (mandate §30's sanctioned pattern) —
    always returns the same GovernanceResult or ConsumptionError,
    regardless of the request. Used for BLOCK/REPAIR/ESCALATE/error-path
    tests where triggering the real ggm.base policy rules deterministically
    would require reverse-engineering its transition-policy internals
    (out of scope — this fixture tests PGDR's HANDLING of each outcome,
    not GGM's decision to produce it)."""

    def __init__(self, result):
        self._result = result
        self.last_request: GovernanceRequest | None = None

    def evaluate(self, request: GovernanceRequest):
        self.last_request = request
        return self._result


def _adapter_with(result_or_error) -> GGMDiagnosticGovernanceAdapter:
    consumer = _FixedOutcomeConsumer(result_or_error)
    return GGMDiagnosticGovernanceAdapter(
        consumer, manifest_id="test-manifest", capability_profile_version="1.0",
        trace_store=InMemoryGovernanceTraceStore(),
    )


def _candidate(**overrides) -> DiagnosticGovernanceCandidate:
    defaults = dict(
        case_id="CASE-1", hypothesis_id="DHYP-1", statement="Compatible avec un problème de roue.",
        analytical_score=0.6, supporting_evidence_ids=["EVD-1"], contradicting_evidence_ids=[],
        source_observation_ids=["OBS-1"], presentation_target="garage_report",
    )
    defaults.update(overrides)
    return DiagnosticGovernanceCandidate(**defaults)


@pytest.fixture
def controller():
    return SessionController()


def _drive_to_completion(controller, session):
    guard = 0
    while session.pending_questions and guard < 30:
        guard += 1
        q = session.pending_questions[0]
        val = False if q.answer_type.value == "yes_no" else "je ne sais pas"
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value=val))
    return session


# ---------------------------------------------------------------------------
# P8-T01 — PGDR imports only the GGM consumer contract / public consumption
# surface (never internal GGM engines, never P2.2 lab code).
# ---------------------------------------------------------------------------

def test_p8_t01_no_forbidden_ggm_imports_in_governance_package():
    for py_file in GOVERNANCE_PACKAGE.rglob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_names = {alias.name for alias in node.names}
                bad = imported_names & _FORBIDDEN_GGM_SYMBOLS
                assert not bad, f"{py_file}: forbidden GGM engine import: {bad}"
                module = node.module or ""
                assert not any(m in module for m in _FORBIDDEN_SCRIPT_MODULES), (
                    f"{py_file}: forbidden P2.2 lab module import: {module}"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in _FORBIDDEN_SCRIPT_MODULES


def test_p8_t01b_only_contract_and_consumption_ggm_modules_imported():
    allowed_prefixes = ("ggm.contract", "ggm.consumption", "ggm.model")
    for py_file in GOVERNANCE_PACKAGE.rglob("*.py"):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ggm"):
                assert node.module.startswith(allowed_prefixes), (
                    f"{py_file}: imports from disallowed ggm submodule: {node.module}"
                )


# ---------------------------------------------------------------------------
# P8-T02/T03/T04 — consumption resolves, manifest has mandatory kernel,
# required operations enabled.
# ---------------------------------------------------------------------------

def test_p8_t02_t03_t04_consumption_resolves_with_kernel_and_operations():
    manifest = resolve_pgdr_consumption_manifest_or_raise()
    assert manifest.manifest_id
    assert manifest.mandatory_kernel.kernel_version
    assert manifest.mandatory_kernel.mandatory_invariants
    assert set(manifest.operations_enabled) == {"DECIDE", "TRANSITION", "CHECK_ESCALATION"}
    assert manifest.contract_version == "1.2"


# ---------------------------------------------------------------------------
# P8-T05 — DiagnosticHypothesis (via candidate) maps to a valid serialized
# GGM object (round-trips through GGM's own deserializer).
# ---------------------------------------------------------------------------

def test_p8_t05_candidate_maps_to_valid_serialized_ggm_object():
    from ggm.contract.serialization import deserialize_governed_object

    mapper = PGDRGGMObjectMapper()
    serialized = mapper.to_governed_claim_dict(_candidate())
    obj = deserialize_governed_object(serialized)  # raises ValueError if malformed
    assert obj.id == "DHYP-1"
    assert obj.object_type == "claim"


# ---------------------------------------------------------------------------
# P8-T06/T07/T08 — Evidence maps to EvidenceRef; SUPPORTS/CONTRADICTS
# survive unchanged.
# ---------------------------------------------------------------------------

def test_p8_t06_t07_t08_evidence_direction_preserved():
    mapper = PGDRGGMObjectMapper()
    refs = mapper.to_evidence_refs([
        ("EVD-1", "SUPPORTS", "r1"),
        ("EVD-2", "CONTRADICTS", "r2"),
    ])
    directions = {r.ref: r.details["direction"] for r in refs}
    assert directions["EVD-1"] == "SUPPORTS"
    assert directions["EVD-2"] == "CONTRADICTS"
    # never silently converted to a GGM RelationType value like "causes"
    assert "causes" not in directions.values()
    assert "CAUSES" not in directions.values()


# ---------------------------------------------------------------------------
# P8-T09 — analytical_score does not create VERIFIED/CONFIRMED authority.
# ---------------------------------------------------------------------------

def test_p8_t09_analytical_score_does_not_create_authority():
    mapper = PGDRGGMObjectMapper()
    high_score_candidate = _candidate(analytical_score=0.99)
    serialized = mapper.to_governed_claim_dict(high_score_candidate)
    assert serialized["epistemic"]["status"] == "UNKNOWN"
    assert serialized["authority"]["level"] == "NONE"
    assert serialized["classification"]["confidence"] == 0.99  # score preserved as metadata only


# ---------------------------------------------------------------------------
# P8-T10 — DECIDE ALLOW permits presentation.
# ---------------------------------------------------------------------------

def test_p8_t10_decide_allow_permits_presentation():
    adapter = _adapter_with(GovernanceResult(request_id="r1", outcome=DecisionType.ALLOW))
    outcome = adapter.govern_candidate(_candidate())
    assert outcome.presentable is True
    assert outcome.result_channel == "GOVERNANCE_RESULT"
    assert outcome.outcome == "ALLOW"


# ---------------------------------------------------------------------------
# P8-T11/T12 — DECIDE BLOCK prevents presentation; does not leak through
# another field.
# ---------------------------------------------------------------------------

def test_p8_t11_t12_decide_block_prevents_presentation_and_does_not_leak(controller):
    blocking_consumer = _FixedOutcomeConsumer(
        GovernanceResult(request_id="r1", outcome=DecisionType.BLOCK, reasons=["forbidden"])
    )
    port = GGMDiagnosticGovernanceAdapter(
        blocking_consumer, manifest_id="m", capability_profile_version="1.0",
        trace_store=InMemoryGovernanceTraceStore(),
    )
    req = _make_request("P8-T11", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive_to_completion(controller, session)

    case_state = controller._case_states[session.session_id]
    blocked_statement_fragments = [h.description for h in case_state.hypotheses if h.active]

    result, traces = govern_and_build_result(req.request_id, case_state, port)

    assert result.garage_preparation_report.systems_to_examine == []
    result_text_surfaces = str(result.model_dump())
    for fragment in blocked_statement_fragments:
        assert fragment not in result_text_surfaces

    # The analytical hypothesis is still fully present in the ORIGINAL
    # DiagnosticCaseState, unchanged — "not presentable" != "not
    # analytically present" (mandate §36).
    assert len(case_state.hypotheses) > 0
    assert all(h.active for h in case_state.hypotheses)  # original untouched


# ---------------------------------------------------------------------------
# P8-T13 — REPAIR does not mutate DiagnosticCaseState.
# ---------------------------------------------------------------------------

def test_p8_t13_repair_does_not_mutate_case_state(controller):
    repair_consumer = _FixedOutcomeConsumer(
        GovernanceResult(request_id="r1", outcome=DecisionType.REPAIR, repair_instruction="soften claim")
    )
    port = GGMDiagnosticGovernanceAdapter(
        repair_consumer, manifest_id="m", capability_profile_version="1.0",
        trace_store=InMemoryGovernanceTraceStore(),
    )
    req = _make_request("P8-T13", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive_to_completion(controller, session)

    case_state = controller._case_states[session.session_id]
    before = [(h.id, h.confidence, h.active, tuple(h.supporting_evidence_ids)) for h in case_state.hypotheses]
    evidence_before = len(case_state.evidence)

    result, traces = govern_and_build_result(req.request_id, case_state, port)

    after = [(h.id, h.confidence, h.active, tuple(h.supporting_evidence_ids)) for h in case_state.hypotheses]
    assert before == after
    assert len(case_state.evidence) == evidence_before
    # REPAIR is treated as not-presentable in P8 v1 (mandate §18 — no
    # invented repair execution).
    assert result.garage_preparation_report.systems_to_examine == []


# ---------------------------------------------------------------------------
# P8-T14 — ESCALATE does not present candidate as approved.
# ---------------------------------------------------------------------------

def test_p8_t14_escalate_not_presented_as_approved(controller):
    escalate_consumer = _FixedOutcomeConsumer(
        GovernanceResult(request_id="r1", outcome=DecisionType.ESCALATE, escalation_target="human_review")
    )
    port = GGMDiagnosticGovernanceAdapter(
        escalate_consumer, manifest_id="m", capability_profile_version="1.0",
        trace_store=InMemoryGovernanceTraceStore(),
    )
    req = _make_request("P8-T14", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive_to_completion(controller, session)
    case_state = controller._case_states[session.session_id]

    result, traces = govern_and_build_result(req.request_id, case_state, port)

    assert result.garage_preparation_report.systems_to_examine == []
    all_limitations = list(result.limitations) + list(result.garage_preparation_report.limitations)
    assert any("vérification" in lim.lower() for lim in all_limitations)
    assert all(t.outcome == "ESCALATE" for t in traces)


# ---------------------------------------------------------------------------
# P8-T15/T16/T17/T18/T19 — ConsumptionError handled on a separate channel,
# with the correct error_type per scenario, all default-deny.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("error_type", [
    ErrorType.CAPABILITY_NOT_AVAILABLE, ErrorType.CONTRACT_MISMATCH,
    ErrorType.RUNTIME_INTEGRITY_FAILURE, ErrorType.MALFORMED_REQUEST,
])
def test_p8_t15_to_t19_consumption_error_default_denies_and_is_not_block(error_type):
    error = ConsumptionError(error_type=error_type, request_id="r1", details="test")
    adapter = _adapter_with(error)
    outcome = adapter.govern_candidate(_candidate())

    assert outcome.presentable is False
    assert outcome.result_channel == "CONSUMPTION_ERROR"
    assert outcome.outcome is None  # never a GovernanceResult outcome value
    assert outcome.error_type == error_type.value
    assert "GOVERNANCE UNAVAILABLE" in outcome.reasons[0]
    assert "BLOCK" not in outcome.reasons[0]


def test_p8_t16_capability_not_available_via_real_default_ggm_consumer():
    """Uses DefaultGGMConsumer's own real capability_check hook (mandate
    §21) rather than a fixture pretending to be GGM — this is the real
    consumer, real ConsumptionError construction path."""
    def _reject_transition(request: GovernanceRequest):
        if request.operation == Operation.TRANSITION:
            return "TRANSITION not enabled for this test consumer"
        return None

    consumer = DefaultGGMConsumer(capability_check=_reject_transition)
    from ggm.contract.types import TransitionAsk
    request = GovernanceRequest(
        object=PGDRGGMObjectMapper().to_governed_claim_dict(_candidate()),
        operation=Operation.TRANSITION,
        requested_transitions=[TransitionAsk(dimension="epistemic", to_state="VERIFIED")],
    )
    result = consumer.evaluate(request)
    assert isinstance(result, ConsumptionError)
    assert result.error_type == ErrorType.CAPABILITY_NOT_AVAILABLE
    assert not isinstance(result, GovernanceResult)


# ---------------------------------------------------------------------------
# P8-T20/T21/T22 — audit trace fields recorded and correlated.
# ---------------------------------------------------------------------------

def test_p8_t20_t21_t22_trace_records_profile_runtime_and_correlation():
    fixed_result = GovernanceResult(
        request_id="r1", outcome=DecisionType.ALLOW,
        rules_applied=["rule-x"],
        profile_trace=ProfileTrace(profiles_applied=["ggm.base"], resolution_id="res-1"),
    )
    adapter = _adapter_with(fixed_result)
    outcome = adapter.govern_candidate(_candidate(case_id="CASE-CORR"))
    trace = outcome.trace
    assert trace.profiles_applied == ["ggm.base"]
    assert trace.runtime_version
    assert trace.case_id == "CASE-CORR"
    assert trace.request_id


# ---------------------------------------------------------------------------
# P8-T23/T24/T25 — GGM governance does not alter hypothesis scores,
# evidence, or question selection (DiagnosticCaseState untouched).
# ---------------------------------------------------------------------------

def test_p8_t23_t24_t25_governance_does_not_alter_case_state(controller):
    req = _make_request("P8-T23", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive_to_completion(controller, session)

    case_state = controller._case_states[session.session_id]
    before = case_state.model_dump(mode="json")

    for fixed_result in (
        GovernanceResult(request_id="x", outcome=DecisionType.ALLOW),
        GovernanceResult(request_id="x", outcome=DecisionType.BLOCK),
        ConsumptionError(error_type=ErrorType.RUNTIME_INTEGRITY_FAILURE),
    ):
        port = _adapter_with(fixed_result)
        govern_and_build_result(req.request_id, case_state, port)
        after = case_state.model_dump(mode="json")
        assert before == after, "DiagnosticCaseState was mutated by governance"


# ---------------------------------------------------------------------------
# P8-T26 — Safety preemption unchanged.
# ---------------------------------------------------------------------------

def test_p8_t26_safety_preemption_unchanged(controller):
    req = _make_request("P8-T26", "La pédale de frein est molle et la voiture ne freine plus")
    session = controller.start(req)
    assert session.state.value == "escalated"
    assert session.result.status.value == "safety_escalation"
    assert session.result.safety_triage.level.value == "emergency_stop"
    # Safety-escalated results bypass governance entirely (mandate §28) —
    # no governance trace should exist for this session's case at all.
    assert controller._governance_trace_store.for_case(
        controller._case_states[session.session_id].case_id
    ) == []


# ---------------------------------------------------------------------------
# P8-T27/T28 — no silent ungoverned fallback; readiness false when
# required GGM unavailable.
# ---------------------------------------------------------------------------

def test_p8_t27_t28_readiness_false_and_fail_closed_when_ggm_unavailable(monkeypatch):
    import pgdr.session_controller as sc_module
    import pgdr.governance.consumption_profile as cp_module

    def _broken_resolve(*args, **kwargs):
        raise GovernanceUnavailableError("simulated GGM unavailability")

    # session_controller.py does `from ... import resolve_pgdr_consumption_manifest_or_raise`
    # at module load time (a direct name binding), so the patch target for
    # SessionController construction must be the name as bound in
    # session_controller's own namespace.
    monkeypatch.setattr(sc_module, "resolve_pgdr_consumption_manifest_or_raise", _broken_resolve)
    with pytest.raises(GovernanceUnavailableError):
        SessionController()

    # readiness.py's _check_ggm_consumption() does the equivalent import
    # LOCALLY, inside the function body, evaluated fresh on every call —
    # so patching the source module itself is sufficient here.
    monkeypatch.setattr(cp_module, "resolve_pgdr_consumption_manifest_or_raise", _broken_resolve)

    from pgdr.readiness import check_readiness
    report = check_readiness()
    assert report.ready is False
    ggm_check = next(c for c in report.checks if c.name == "ggm_consumption")
    assert ggm_check.status.value == "failed"


def test_p8_t27b_governance_disabled_is_explicit_not_silent_activation():
    """governance_enabled=False must remain available for
    tests/development (mandate §33) but is never the silent result of a
    failure — confirmed here by it being an explicit constructor
    parameter, not something a caught exception can flip."""
    disabled_controller = SessionController(governance_enabled=False)
    assert disabled_controller.governance_enabled is False
    assert disabled_controller._governance_port is None


# ---------------------------------------------------------------------------
# P8-T29 — P6/P7 signature scenario still holds with governance live by
# default.
# ---------------------------------------------------------------------------

def test_p8_t29_p6_two_step_scenario_still_holds_with_governance_live():
    controller = SessionController()  # governance_enabled=True (default)
    req = _make_request("P8-T29", "La voiture tremble au ralenti")
    session = controller.start(req)

    guard = 0
    while session.pending_questions and session.pending_questions[0].question_id != "Q-COND-001" and guard < 20:
        guard += 1
        q = session.pending_questions[0]
        session = controller.submit_answer(session, Answer(question_id=q.question_id, value="je ne sais pas"))
    q1 = session.pending_questions[0]
    session = controller.submit_answer(session, Answer(question_id=q1.question_id, value=["vitesse stabilisée"]))
    session = _drive_to_completion(controller, session)
    assert session.result is not None


# ---------------------------------------------------------------------------
# P8-T30 — wheel/install/CLI regression (packaging-marked, slower).
# ---------------------------------------------------------------------------

@pytest.mark.packaging
def test_p8_t30_cli_regression_with_governance_enabled():
    import subprocess
    run_pgdr = PROJECT_ROOT / "run_pgdr.py"
    result = subprocess.run(
        [sys.executable, str(run_pgdr), "run", "--vir-id", "VIR-001",
         "--complaint", "La voiture tremble au ralenti", "--non-interactive"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Systèmes à examiner" in result.stdout

    readiness = subprocess.run(
        [sys.executable, str(run_pgdr), "readiness"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert readiness.returncode == 0
    assert "PGDR READY" in readiness.stdout


# ---------------------------------------------------------------------------
# P8 SIGNATURE TEST (mandate §35)
# ---------------------------------------------------------------------------

def test_p8_signature_full_governance_boundary(controller):
    req = _make_request("P8-SIG", "La voiture tremble au ralenti")
    session = controller.start(req)
    session = _drive_to_completion(controller, session)

    case_state = controller._case_states[session.session_id]
    before = case_state.model_dump(mode="json")

    assert case_state.hypotheses  # H1 exists with an analytical score
    h1 = case_state.hypotheses[0]
    assert h1.confidence is not None

    port = controller._governance_port
    assert port is not None  # governance is live (real GGMConsumer, not a fixture)

    result, traces = govern_and_build_result(req.request_id, case_state, port)

    # 1/2. GGM received the request and determined presentability — proven
    # by a real, non-empty trace existing per governed hypothesis.
    assert traces
    for t in traces:
        assert t.request_id
        assert t.runtime_version

    # 3. DiagnosticCaseState structurally equivalent before/after.
    after = case_state.model_dump(mode="json")
    assert before == after

    # 4. Governance trace records request_id/rules_applied/profile_trace/runtime_version.
    for t in traces:
        assert t.runtime_version == "ggm/1.1"
        assert isinstance(t.rules_applied, list)
        assert isinstance(t.profiles_applied, list)

    # 5. The final report reflects the governance outcome (ALLOW under
    # ggm.base's default policy for a static, non-transition-requesting
    # claim -> presentable).
    assert result.garage_preparation_report is not None
    if all(t.outcome == "ALLOW" for t in traces):
        assert result.garage_preparation_report.systems_to_examine != [] or not case_state.active_hypotheses()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
