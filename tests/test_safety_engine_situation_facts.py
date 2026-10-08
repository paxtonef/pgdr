"""SafetyEngine: rule exclusion from a structured situation fact (PGDR-SAF-012).
Generic, no notice content: indicators are built by hand."""
from __future__ import annotations

import copy

import pytest

from pgdr.config_loader import load_safety_rules, validate_safety_rules
from pgdr.errors import ConfigurationError
from pgdr.models import (Consent, DiagnosticSession, InitialComplaint, PreGarageDiagnosticRequest,
                         VehicleIdentityContext, WarningIndicator)
from pgdr.enums import WarningColor
from pgdr.safety_engine import SafetyEngine


def session(*indicators, text=""):
    s = DiagnosticSession(request=PreGarageDiagnosticRequest(
        request_id="T", vehicle_identity_context=VehicleIdentityContext(resolution_id="T", resolution_status="resolved",
                                                                          vehicle_identity={}),
        initial_complaint=InitialComplaint(free_text=text), consent=Consent(media_analysis_allowed=False, report_storage_allowed=False)))
    s.warning_indicators = list(indicators)
    return s


def red(label, fact=None):
    return WarningIndicator(label=label, observed_color=WarningColor.RED, situation_fact=fact)


NORMAL = {"entry_id": "x", "nature": "fonctionnement_normal", "provenance": "classement des situations validé", "variant": "selected"}


@pytest.mark.parametrize("fact, fires", [
    (None, True),                                             # no fact: unchanged
    (NORMAL, False),                                          # established ordinary indication
    ({**NORMAL, "provenance": None}, True),                   # no provenance: never excluded
    ({**NORMAL, "variant": "possible"}, True),                # undetermined variant: never excluded
    ({**NORMAL, "nature": "alerte_consigne_immediate"}, True),
])
def test_saf012_exclusion_requires_established_fact(fact, fires):
    t = SafetyEngine().evaluate(session(red("PARKING BRAKE APPLIED", fact)))
    assert ("PGDR-SAF-012" in t.triggered_rules) is fires
    assert bool(t.rule_exclusions) is (not fires)


def test_other_red_brake_indicator_still_triggers():
    t = SafetyEngine().evaluate(session(red("PARKING BRAKE APPLIED", NORMAL), red("BRAKE FLUID")))
    assert "PGDR-SAF-012" in t.triggered_rules and t.rule_exclusions == []


def test_free_text_still_triggers():
    t = SafetyEngine().evaluate(session(red("PARKING BRAKE APPLIED", NORMAL), text="mon frein ne répond plus"))
    assert "PGDR-SAF-012" in t.triggered_rules


def test_exclusion_key_validated():
    data = copy.deepcopy(load_safety_rules())
    rule = next(r for r in data["rules"] if r["id"] == "PGDR-SAF-012")
    rule["conditions"]["exclude_established_situations"] = []
    with pytest.raises(ConfigurationError):
        validate_safety_rules(data)
