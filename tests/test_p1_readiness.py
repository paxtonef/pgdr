"""P1 — Runner Execution Contract: readiness mechanism tests.

Covers the exact minimum test matrix from the P1 mandate:

    valid installation                  -> READY
    missing safety config                -> NOT_READY
    invalid safety config                -> NOT_READY
    SafetyEngine initialization failure  -> NOT_READY
    optional capability unavailable      -> READY (if genuinely optional)
    required capability unavailable      -> NOT_READY

Plus: the REC YAML itself parses and has the mandated top-level sections,
and the `pgdr readiness` CLI command exercises the same contract end-to-end.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
import yaml

from pgdr.errors import ConfigurationError
from pgdr.readiness import (
    CapabilityCheck, CheckStatus, FailureReason, check_readiness,
)

PROJECT_ROOT = Path(__file__).parent.parent
REAL_CONFIG_DIR = PROJECT_ROOT / "src" / "pgdr" / "config"


# ---------------------------------------------------------------------------
# 1. valid installation -> READY
# ---------------------------------------------------------------------------

def test_valid_installation_is_ready():
    report = check_readiness()
    assert report.ready is True
    assert report.reason == FailureReason.NONE
    assert all(c.status == CheckStatus.OK for c in report.checks)


# ---------------------------------------------------------------------------
# 2. missing safety config -> NOT_READY
# ---------------------------------------------------------------------------

def test_missing_safety_config_is_not_ready(tmp_path, monkeypatch):
    for name in ("symptom_taxonomy.yaml", "questions.yaml", "business_rules.yaml"):
        (tmp_path / name).write_text((REAL_CONFIG_DIR / name).read_text())
    # deliberately do NOT write safety_rules.yaml
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))

    report = check_readiness()
    assert report.ready is False
    # Note: report.reason prioritizes the safety_engine check's reason
    # whenever it's among the failed checks (see ReadinessReport.reason
    # docstring) — "the safety envelope is down" is more operationally
    # urgent to surface than the generic config-error framing, even
    # though both are true here simultaneously.
    assert report.reason == FailureReason.SAFETY_ENGINE_UNAVAILABLE
    safety_check = next(c for c in report.checks if c.name == "safety_engine")
    assert safety_check.status == CheckStatus.FAILED
    config_check = next(c for c in report.checks if c.name == "packaged_resources_and_configuration")
    assert config_check.status == CheckStatus.FAILED
    assert config_check.failure_reason == FailureReason.CONFIGURATION_ERROR


# ---------------------------------------------------------------------------
# 3. invalid safety config -> NOT_READY
# ---------------------------------------------------------------------------

def test_invalid_safety_config_is_not_ready(tmp_path, monkeypatch):
    for name in ("symptom_taxonomy.yaml", "questions.yaml", "business_rules.yaml"):
        (tmp_path / name).write_text((REAL_CONFIG_DIR / name).read_text())
    bad = {
        "rules": [{
            "id": "T1", "conditions": {"keywords_any": ["x"]},
            "triage_level": "emergncy_stop",  # typo, deliberate
            "driving_assessment": "do_not_drive", "instruction": "i", "reason": "r",
        }],
        "default": {
            "triage_level": "monitor_and_document", "driving_assessment": "not_assessed",
            "instruction": "i", "reason": "r",
        },
    }
    (tmp_path / "safety_rules.yaml").write_text(yaml.safe_dump(bad))
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))

    report = check_readiness()
    assert report.ready is False
    # Same priority note as the missing-config test above.
    assert report.reason == FailureReason.SAFETY_ENGINE_UNAVAILABLE
    config_check = next(c for c in report.checks if c.name == "packaged_resources_and_configuration")
    assert config_check.failure_reason == FailureReason.CONFIGURATION_ERROR


# ---------------------------------------------------------------------------
# 4. SafetyEngine initialization failure -> NOT_READY
#
# Deliberately distinct from case 3: forces a failure that is NOT a
# ConfigurationError (an arbitrary RuntimeError during construction), to
# prove the readiness mechanism correctly reports NOT_READY /
# CAPABILITY_UNAVAILABLE-shaped behavior for failure modes PGDR doesn't
# currently have a concrete production example of, rather than only
# handling the one failure mode (bad YAML) it happens to exercise today.
# ---------------------------------------------------------------------------

def test_safety_engine_initialization_failure_that_is_not_a_configuration_error(monkeypatch):
    """Patches SafetyEngine itself (not the check function) to raise a
    plain RuntimeError — something that is NOT a ConfigurationError —
    proving _check_safety_engine's real exception handling correctly
    reports SAFETY_ENGINE_UNAVAILABLE for ANY construction failure, not
    only the one failure mode (bad YAML) PGDR happens to exercise today."""
    import pgdr.safety_engine as safety_engine_module

    class _ExplodingSafetyEngine:
        def __init__(self):
            raise RuntimeError("simulated non-configuration failure during SafetyEngine construction")

    monkeypatch.setattr(safety_engine_module, "SafetyEngine", _ExplodingSafetyEngine)

    report = check_readiness()
    assert report.ready is False
    safety_check = next(c for c in report.checks if c.name == "safety_engine")
    assert safety_check.status == CheckStatus.FAILED
    assert safety_check.failure_reason == FailureReason.SAFETY_ENGINE_UNAVAILABLE
    assert "simulated non-configuration failure" in safety_check.detail
    assert report.reason == FailureReason.SAFETY_ENGINE_UNAVAILABLE


# ---------------------------------------------------------------------------
# 5. optional capability unavailable -> READY (if genuinely optional)
#
# PGDR v0.1 has zero real optional capabilities (see
# runner_execution_contract.yaml `capabilities.optional: []`). This test
# exercises the MECHANISM's handling of an optional check via
# check_readiness(extra_checks=...) rather than claiming PGDR currently
# has an optional capability it doesn't have.
# ---------------------------------------------------------------------------

def test_optional_capability_failure_does_not_block_readiness():
    fake_optional_failure = CapabilityCheck(
        name="hypothetical_optional_capability",
        required=False,
        status=CheckStatus.FAILED,
        detail="synthetic failure injected for this test only — not a real PGDR capability",
    )
    report = check_readiness(extra_checks=[fake_optional_failure])
    assert report.ready is True, "an optional check failing must never block readiness"
    assert any(c.name == "hypothetical_optional_capability" for c in report.checks)


def test_optional_capability_success_also_keeps_readiness_true():
    fake_optional_ok = CapabilityCheck(
        name="hypothetical_optional_capability", required=False, status=CheckStatus.OK,
    )
    report = check_readiness(extra_checks=[fake_optional_ok])
    assert report.ready is True


# ---------------------------------------------------------------------------
# 6. required capability unavailable -> NOT_READY
#
# safety_rules.yaml is VALID here — only symptom_taxonomy.yaml is missing.
# This proves session_controller (which needs all 4 configs) fails
# independently of the safety_engine check, i.e. readiness genuinely
# checks every required capability rather than only the safety config.
# ---------------------------------------------------------------------------

def test_missing_non_safety_required_config_is_not_ready(tmp_path, monkeypatch):
    (tmp_path / "safety_rules.yaml").write_text((REAL_CONFIG_DIR / "safety_rules.yaml").read_text())
    (tmp_path / "questions.yaml").write_text((REAL_CONFIG_DIR / "questions.yaml").read_text())
    (tmp_path / "business_rules.yaml").write_text((REAL_CONFIG_DIR / "business_rules.yaml").read_text())
    # symptom_taxonomy.yaml deliberately missing
    monkeypatch.setenv("PGDR_CONFIG_DIR", str(tmp_path))

    report = check_readiness()
    assert report.ready is False
    # safety_engine only needs safety_rules.yaml, which IS present and valid here.
    safety_check = next(c for c in report.checks if c.name == "safety_engine")
    assert safety_check.status == CheckStatus.OK
    # but session_controller needs all 4, so it must fail.
    sc_check = next(c for c in report.checks if c.name == "session_controller")
    assert sc_check.status == CheckStatus.FAILED
    assert report.reason == FailureReason.CONFIGURATION_ERROR


# ---------------------------------------------------------------------------
# ReadinessReport / as_dict shape
# ---------------------------------------------------------------------------

def test_as_dict_shape_is_json_serializable():
    import json
    report = check_readiness()
    d = report.as_dict()
    json.dumps(d)  # must not raise
    assert set(d.keys()) == {"ready", "reason", "checks"}
    for c in d["checks"]:
        assert set(c.keys()) == {"name", "required", "status", "detail"}


# ---------------------------------------------------------------------------
# The Runner Execution Contract YAML itself
# ---------------------------------------------------------------------------

_REQUIRED_REC_SECTIONS = {
    "identity", "runtime", "packaged_resources", "startup", "configuration",
    "safety", "capabilities", "network", "persistence", "interfaces",
    "liveness", "readiness", "failure_semantics", "verification",
    "supported_execution_environments",
}


def test_rec_yaml_parses_and_has_all_mandated_sections():
    rec_path = PROJECT_ROOT / "runner_execution_contract.yaml"
    assert rec_path.exists(), "runner_execution_contract.yaml must exist at project root"
    with open(rec_path) as f:
        data = yaml.safe_load(f)
    missing = _REQUIRED_REC_SECTIONS - set(data.keys())
    assert not missing, f"REC is missing mandated sections: {missing}"


def test_rec_does_not_claim_unimplemented_capabilities_are_available():
    """Guards the 'do not invent' constraint: the REC must not claim an
    API, database, or optional capability exists when the codebase has
    none. This is a living check — if these ever DO become true, this
    test (and the REC) must be updated deliberately, not silently."""
    rec_path = PROJECT_ROOT / "runner_execution_contract.yaml"
    with open(rec_path) as f:
        data = yaml.safe_load(f)
    assert data["interfaces"]["api"]["available"] is False
    assert data["capabilities"]["optional"] == []
    assert data["persistence"]["required"] is False
    assert data["network"]["required_at_runtime"] is False


# ---------------------------------------------------------------------------
# CLI end-to-end — `pgdr readiness`
# ---------------------------------------------------------------------------

def test_cli_readiness_command_exits_zero_on_healthy_install():
    run_pgdr = PROJECT_ROOT / "run_pgdr.py"
    result = subprocess.run(
        [sys.executable, str(run_pgdr), "readiness"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "PGDR READY" in result.stdout


def test_cli_readiness_command_json_output_is_valid_json():
    import json
    run_pgdr = PROJECT_ROOT / "run_pgdr.py"
    result = subprocess.run(
        [sys.executable, str(run_pgdr), "readiness", "--json-output"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed["ready"] is True


def test_cli_readiness_command_exits_one_on_broken_config(tmp_path):
    import os
    for name in ("symptom_taxonomy.yaml", "questions.yaml", "business_rules.yaml"):
        (tmp_path / name).write_text((REAL_CONFIG_DIR / name).read_text())
    bad = {
        "rules": [{
            "id": "T1", "conditions": {"keywords_any": ["x"]},
            "triage_level": "emergncy_stop",
            "driving_assessment": "do_not_drive", "instruction": "i", "reason": "r",
        }],
        "default": {
            "triage_level": "monitor_and_document", "driving_assessment": "not_assessed",
            "instruction": "i", "reason": "r",
        },
    }
    (tmp_path / "safety_rules.yaml").write_text(yaml.safe_dump(bad))

    env = dict(os.environ)
    env["PGDR_CONFIG_DIR"] = str(tmp_path)
    run_pgdr = PROJECT_ROOT / "run_pgdr.py"
    result = subprocess.run(
        [sys.executable, str(run_pgdr), "readiness"],
        cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "PGDR NOT READY" in result.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
