"""P0 — Execution & Safety Configuration Integrity.

These tests prove the fail-closed contract: a broken safety configuration
must raise ConfigurationError and prevent PGDR from becoming operational —
never silently degrade to a default/empty configuration that lets the
system appear to run normally with no real safety envelope.

Two testing strategies are used:
  - File-level failures (missing / empty / malformed YAML) are tested by
    pointing PGDR_CONFIG_DIR at a purpose-built temp directory and calling
    the real loader — this exercises the actual file I/O path.
  - Schema-level failures (invalid enum, duplicate id, empty conditions,
    missing field) are tested by calling validate_safety_rules() directly
    on hand-built dicts — faster, and pinpoints exactly which validation
    rule is being exercised without needing a full YAML fixture per case.
"""
import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import yaml

from pgdr.errors import ConfigurationError

# A minimal, fully valid safety_rules document — every negative test below
# starts from a deep copy of this and breaks exactly one thing, so a
# failure can only be attributed to the thing that test changed.
_VALID_SAFETY_RULES: dict = {
    "rules": [
        {
            "id": "TEST-RULE-001",
            "conditions": {"keywords_any": ["test keyword"]},
            "triage_level": "emergency_stop",
            "driving_assessment": "do_not_drive",
            "instruction": "Test instruction.",
            "reason": "Test reason.",
            "emergency_services": False,
            "roadside_assistance": True,
        }
    ],
    "default": {
        "triage_level": "monitor_and_document",
        "driving_assessment": "not_assessed",
        "instruction": "Default instruction.",
        "reason": "Default reason.",
        "emergency_services": False,
        "roadside_assistance": False,
    },
}


def _valid_copy() -> dict:
    return copy.deepcopy(_VALID_SAFETY_RULES)


# ---------------------------------------------------------------------------
# Sanity check: the fixture itself must be valid, or every negative test
# below is meaningless (it would "pass" even if validation were a no-op).
# ---------------------------------------------------------------------------

def test_p0_baseline_fixture_is_itself_valid():
    from pgdr.config_loader import validate_safety_rules
    validate_safety_rules(_valid_copy())  # must not raise


# ---------------------------------------------------------------------------
# P0.2 — file-level failures (missing / empty / malformed)
# ---------------------------------------------------------------------------

def test_p0_missing_safety_rules_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))
    # deliberately do not create safety_rules.yaml
    from pgdr.config_loader import load_safety_rules
    with pytest.raises(ConfigurationError, match="missing"):
        load_safety_rules()


def test_p0_empty_safety_rules_file_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "safety_rules.yaml").write_text("")
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))
    from pgdr.config_loader import load_safety_rules
    with pytest.raises(ConfigurationError, match="empty"):
        load_safety_rules()


def test_p0_malformed_yaml_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "safety_rules.yaml").write_text("rules: [\n  this is not: valid: yaml: at all")
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))
    from pgdr.config_loader import load_safety_rules
    with pytest.raises(ConfigurationError, match="Malformed YAML"):
        load_safety_rules()


def test_p0_non_mapping_yaml_fails_closed(tmp_path, monkeypatch):
    """A syntactically valid YAML file that isn't a mapping (e.g. a bare
    list) must still fail closed, not crash with an unrelated TypeError
    deeper in the pipeline."""
    (tmp_path / "safety_rules.yaml").write_text("- just\n- a\n- list\n")
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))
    from pgdr.config_loader import load_safety_rules
    with pytest.raises(ConfigurationError, match="mapping"):
        load_safety_rules()


def test_p0_all_four_required_configs_fail_closed_when_missing(tmp_path, monkeypatch):
    """P0.2 applies uniformly to all 4 packaged configs at the load level
    (missing/empty/malformed), even though only safety_rules gets the
    deeper P0.3 semantic schema validation."""
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))
    from pgdr.config_loader import (
        load_business_rules, load_questions, load_safety_rules, load_taxonomy,
    )
    for loader in (load_safety_rules, load_taxonomy, load_questions, load_business_rules):
        with pytest.raises(ConfigurationError):
            loader()


# ---------------------------------------------------------------------------
# P0.3 — semantic schema validation (direct dict-level tests)
# ---------------------------------------------------------------------------

def test_p0_unknown_triage_level_fails_closed():
    """The exact bug this phase was written to close: a typo like
    'emergncy_stop' must never silently degrade to monitor_and_document."""
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    data["rules"][0]["triage_level"] = "emergncy_stop"  # typo, deliberate
    with pytest.raises(ConfigurationError, match="invalid triage_level"):
        validate_safety_rules(data)


def test_p0_unknown_driving_assessment_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    data["rules"][0]["driving_assessment"] = "safe_to_drive"  # must never be accepted, even syntactically
    with pytest.raises(ConfigurationError, match="invalid driving_assessment"):
        validate_safety_rules(data)


def test_p0_duplicate_rule_id_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    second = copy.deepcopy(data["rules"][0])
    data["rules"].append(second)  # same id as rules[0]
    with pytest.raises(ConfigurationError, match="duplicate rule id"):
        validate_safety_rules(data)


def test_p0_empty_conditions_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    data["rules"][0]["conditions"] = {}
    with pytest.raises(ConfigurationError, match="conditions"):
        validate_safety_rules(data)


def test_p0_missing_conditions_key_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    del data["rules"][0]["conditions"]
    with pytest.raises(ConfigurationError, match="conditions"):
        validate_safety_rules(data)


def test_p0_missing_rule_id_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    del data["rules"][0]["id"]
    with pytest.raises(ConfigurationError, match="id"):
        validate_safety_rules(data)


def test_p0_missing_instruction_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    del data["rules"][0]["instruction"]
    with pytest.raises(ConfigurationError, match="instruction"):
        validate_safety_rules(data)


def test_p0_missing_reason_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    del data["rules"][0]["reason"]
    with pytest.raises(ConfigurationError, match="reason"):
        validate_safety_rules(data)


def test_p0_missing_rules_key_entirely_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    del data["rules"]
    with pytest.raises(ConfigurationError, match="rules"):
        validate_safety_rules(data)


def test_p0_empty_rules_list_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    data["rules"] = []
    with pytest.raises(ConfigurationError, match="non-empty"):
        validate_safety_rules(data)


def test_p0_missing_default_block_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    del data["default"]
    with pytest.raises(ConfigurationError, match="default"):
        validate_safety_rules(data)


def test_p0_invalid_triage_level_in_default_block_fails_closed():
    """The default block gets the same scrutiny as a rule — it's not a
    lesser-validated fallback path."""
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    data["default"]["triage_level"] = "not_a_real_level"
    with pytest.raises(ConfigurationError, match="invalid triage_level"):
        validate_safety_rules(data)


def test_p0_non_boolean_emergency_services_fails_closed():
    """YAML footgun: emergency_services: "false" (a string) is truthy in
    Python and would silently always request emergency services."""
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    data["rules"][0]["emergency_services"] = "false"  # string, not bool — deliberate
    with pytest.raises(ConfigurationError, match="must be a boolean"):
        validate_safety_rules(data)


def test_p0_non_dict_rule_fails_closed():
    from pgdr.config_loader import validate_safety_rules
    data = _valid_copy()
    data["rules"].append("not a mapping")
    with pytest.raises(ConfigurationError, match="mapping"):
        validate_safety_rules(data)


# ---------------------------------------------------------------------------
# Fail-closed BEHAVIOR contract: a config failure must block execution, not
# fabricate a safety verdict. Confirms SafetyEngine construction itself
# raises (rather than, say, catching internally and returning a default
# SafetyTriage instance that looks like a real result).
# ---------------------------------------------------------------------------

def test_p0_safety_engine_construction_raises_on_invalid_config(tmp_path, monkeypatch):
    bad = _valid_copy()
    bad["rules"][0]["triage_level"] = "emergncy_stop"
    (tmp_path / "safety_rules.yaml").write_text(yaml.safe_dump(bad))
    # SafetyEngine only reads safety_rules.yaml directly, so no need to
    # populate the other 3 configs in this fixture directory.
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))
    from pgdr.safety_engine import SafetyEngine
    with pytest.raises(ConfigurationError):
        SafetyEngine()


def test_p0_cli_refuses_to_run_on_broken_safety_config_without_fabricating_verdict(tmp_path, monkeypatch):
    """End-to-end: broken config must produce a technical failure message,
    never a driving/safety instruction, and must exit non-zero."""
    import shutil
    import subprocess

    src_config_dir = Path(__file__).parent.parent / "src" / "pgdr" / "config"
    for name in ("symptom_taxonomy.yaml", "questions.yaml", "business_rules.yaml"):
        shutil.copy(src_config_dir / name, tmp_path / name)

    bad = _valid_copy()
    bad["rules"][0]["triage_level"] = "emergncy_stop"
    (tmp_path / "safety_rules.yaml").write_text(yaml.safe_dump(bad))

    env = dict(os.environ)
    env["PGDR_CONFIG_DIR"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path(__file__).parent.parent / "src")
    run_pgdr = Path(__file__).parent.parent / "run_pgdr.py"

    result = subprocess.run(
        [sys.executable, str(run_pgdr), "run", "--vir-id", "VIR-001",
         "--complaint", "brake pedal loss", "--non-interactive"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "unavailable" in combined or "configuration invalid" in combined

    # The critical negative assertion: no fabricated safety VERDICT was
    # printed. Note this deliberately does NOT ban the substring
    # "emergency_stop" outright — the error message legitimately lists it
    # as one of the *valid* enum options ("must be one of [...]"), which is
    # helpful diagnostics, not a fabricated conclusion. What must never
    # appear is the actual triage-result UI: the escalation panel or a
    # "Niveau : <level>" verdict line, which only render on a real
    # (successfully constructed) SafetyTriage.
    assert "signal de sécurité détecté" not in combined
    assert "niveau :" not in combined
    assert "ne roulez pas" not in combined


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
