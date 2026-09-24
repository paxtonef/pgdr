"""R-5 monotonicity (Execution Mandate v0.2 FINAL §9 R-5, D-C4, A2 — a
mandatory Completion Gate item).

R-5 may RAISE the SafetyEngine result and never lower it:
  * the triage level is at least the SafetyEngine level;
  * driving_assessment is never moved away from DO_NOT_DRIVE;
  * roadside_assistance is never changed from true to false;
  * emergency_services always equals the SafetyEngine value.
Checked exhaustively over every SafetyEngine output shape × every finding
shape R-5 can see, and on real SafetyEngine results.
"""
from __future__ import annotations

import itertools

import pytest

import photo_first_support as sup
from pgdr.application import part1_first_finding as p1
from pgdr.enums import DrivingAssessment, TriageLevel
from pgdr.models import (
    Consent, DiagnosticSession, FindingItem, InitialComplaint, ManufacturerFirstFinding, PreGarageDiagnosticRequest,
    SafetyTriage, VehicleIdentityContext,
)
from pgdr.application.photo_first import warning_indicator_from_entry
from pgdr.safety_engine import SafetyEngine

MAPPING = p1.load_part1_mapping()
_REQ = FindingItem(value="required", basis="documented", source_field="documented_instruction", source_phrase="x")
_WITHOUT_DELAY = FindingItem(value="without delay", basis="documented", source_field="documented_instruction",
                             source_phrase="without delay")
_PROMPTLY = FindingItem(value="Promptly", basis="documented", source_field="documented_instruction", source_phrase="Promptly")
_DNT = FindingItem(value="do_not_drive", basis="derived", rule_id="R-1", source_field="documented_instruction",
                   source_phrase="x")
_NE = FindingItem.not_established()


def _base():
    return p1.build_entry_finding(sup.REAL_ENTRIES["service-warning-lamp-fixed"],
                                  identification_origin="visual_provider_match", mapping=MAPPING)


def _shape(sveo=False, dnt=False, professional=False, urgency=None):
    return _base().model_copy(update={
        "stop_vehicle_engine_off": _REQ if sveo else _NE,
        "operability": _DNT if dnt else _NE,
        "professional_attention": _REQ if professional else _NE,
        "urgency_phrase": {"without delay": _WITHOUT_DELAY, "Promptly": _PROMPTLY}.get(urgency, _NE),
    })


# Every combination of the fields R-5 reads, per entry, plus multi-entry findings.
_ENTRY_SHAPES = [
    _shape(sveo, dnt, prof, urg)
    for sveo, dnt, prof, urg in itertools.product([False, True], [False, True], [False, True], [None, "without delay", "Promptly"])
]
FINDING_SHAPES = [ManufacturerFirstFinding(entries=[])] + [
    ManufacturerFirstFinding(entries=[e]) for e in _ENTRY_SHAPES
] + [
    ManufacturerFirstFinding(entries=[a, b]) for a, b in itertools.combinations(_ENTRY_SHAPES[::5], 2)
]
ENGINE_SHAPES = [
    SafetyTriage(level=level, driving_assessment=da, roadside_assistance_recommended=rs,
                 emergency_services_required=es, user_instruction="engine", triggered_rules=["X"], reasons=["r"])
    for level, da, rs, es in itertools.product(list(TriageLevel), list(DrivingAssessment), [False, True], [False, True])
]


def _assert_never_lowers(engine: SafetyTriage, composed: SafetyTriage) -> None:
    assert p1.severity_rank(composed.level) >= p1.severity_rank(engine.level)
    if engine.driving_assessment == DrivingAssessment.DO_NOT_DRIVE:
        assert composed.driving_assessment == DrivingAssessment.DO_NOT_DRIVE
    elif composed.driving_assessment != engine.driving_assessment:
        assert composed.driving_assessment == DrivingAssessment.DO_NOT_DRIVE      # R-5 only ever writes DO_NOT_DRIVE
    if engine.roadside_assistance_recommended:
        assert composed.roadside_assistance_recommended is True
    assert composed.emergency_services_required == engine.emergency_services_required
    assert composed.triggered_rules[: len(engine.triggered_rules)] == engine.triggered_rules
    assert composed.reasons[: len(engine.reasons)] == engine.reasons


def test_r5_never_lowers_any_safety_engine_result_exhaustively():
    checked = 0
    for engine, finding in itertools.product(ENGINE_SHAPES, FINDING_SHAPES):
        composed, _ = p1.compose_triage(engine, finding, raised_instruction=p1.raised_instructions(finding))
        _assert_never_lowers(engine, composed)
        checked += 1
    assert checked == len(ENGINE_SHAPES) * len(FINDING_SHAPES) >= 3000


def test_r5_only_changes_the_level_through_the_approved_table():
    for engine, finding in itertools.product(ENGINE_SHAPES, FINDING_SHAPES):
        composed, rows = p1.compose_triage(engine, finding)
        expected = engine.level
        for e in finding.entries:
            if e.stop_vehicle_engine_off.value == "required":
                row = TriageLevel.EMERGENCY_STOP
            elif e.operability.value == "do_not_drive":
                row = TriageLevel.DO_NOT_DRIVE
            elif e.professional_attention.value == "required" and e.urgency_phrase.value == "without delay":
                row = TriageLevel.PROMPT_INSPECTION
            else:
                continue
            expected = max(expected, row, key=p1.severity_rank)
        assert composed.level == expected
        if not rows:
            assert composed == engine                     # "anything else" row: no change at all


def test_r5_does_not_mutate_the_safety_engine_object():
    engine = SafetyTriage(level=TriageLevel.MONITOR_AND_DOCUMENT, user_instruction="engine")
    snapshot = engine.model_copy(deep=True)
    p1.compose_triage(engine, ManufacturerFirstFinding(entries=[_shape(sveo=True)]))
    assert engine == snapshot


def test_instruction_is_replaced_only_when_the_level_is_raised():
    finding = ManufacturerFirstFinding(entries=[_shape(sveo=True, dnt=True)])
    low = SafetyTriage(level=TriageLevel.MONITOR_AND_DOCUMENT, user_instruction="Aucun signal critique n'a été identifié")
    raised, _ = p1.compose_triage(low, finding, raised_instruction=p1.raised_instructions(finding))
    assert raised.user_instruction == p1.APPROVED_LABELS["stop_vehicle_engine_off = REQUIRED"]
    high = SafetyTriage(level=TriageLevel.EMERGENCY_STOP, user_instruction="engine wording")
    kept, _ = p1.compose_triage(high, finding, raised_instruction=p1.raised_instructions(finding))
    assert kept.level == TriageLevel.EMERGENCY_STOP and kept.user_instruction == "engine wording"


# ---- real SafetyEngine results --------------------------------------------

def _text_session(complaint: str) -> DiagnosticSession:
    request = PreGarageDiagnosticRequest(
        request_id="R5", initial_complaint=InitialComplaint(free_text=complaint), consent=Consent(),
        vehicle_identity_context=VehicleIdentityContext.model_validate(sup.vir_identity()),
    )
    return DiagnosticSession(request=request)


def _real_finding(entry_id: str) -> ManufacturerFirstFinding:
    return p1.build_manufacturer_first_finding(
        [(sup.REAL_ENTRIES[entry_id], "visual_provider_match")], mapping=MAPPING)


def test_saf_004_emergency_with_emergency_services_is_kept_with_a_non_raising_entry():
    engine = SafetyEngine().evaluate(_text_session("fumée noire sortant du moteur"))
    assert engine.level == TriageLevel.EMERGENCY_STOP and engine.emergency_services_required is True
    finding = _real_finding("adblue-level-state-a")
    composed, rows = p1.compose_triage(engine, finding, raised_instruction=p1.raised_instructions(finding))
    assert rows == [] and composed == engine
    assert composed.level == TriageLevel.EMERGENCY_STOP and composed.emergency_services_required is True


def test_saf_012_do_not_drive_is_kept_with_a_prompt_inspection_entry():
    session = _text_session("")
    session.warning_indicators.append(warning_indicator_from_entry(sup.BRAKE, photo_evidence_id="obs"))
    engine = SafetyEngine().evaluate(session)
    assert engine.level == TriageLevel.DO_NOT_DRIVE
    finding = _real_finding("engine-diag-fixed")
    composed, rows = p1.compose_triage(engine, finding, raised_instruction=p1.raised_instructions(finding))
    assert rows == ["R-5:professional_without_delay:engine-diag-fixed"]
    _assert_never_lowers(engine, composed)
    assert composed.level == TriageLevel.DO_NOT_DRIVE
    assert composed.driving_assessment == engine.driving_assessment == DrivingAssessment.DO_NOT_DRIVE
    assert composed.user_instruction == engine.user_instruction      # not raised -> engine wording kept


@pytest.mark.parametrize("entry_id", sup.REAL_ENTRY_IDS)
def test_real_entries_on_the_real_photo_default_never_lower(entry_id):
    session = _text_session("")
    session.warning_indicators.append(warning_indicator_from_entry(sup.REAL_ENTRIES[entry_id], photo_evidence_id="o"))
    engine = SafetyEngine().evaluate(session)
    finding = _real_finding(entry_id)
    composed, _ = p1.compose_triage(engine, finding, raised_instruction=p1.raised_instructions(finding))
    _assert_never_lowers(engine, composed)
