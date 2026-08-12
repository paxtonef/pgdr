"""P0.1 — Packaging Integrity smoke test.

Everything in test_p0_config_integrity.py and test_runner.py runs against
the source tree via `sys.path.insert(str(.../src))`. That proves the
*logic* is correct but proves nothing about the *distributed artifact* —
a wheel could theoretically omit a YAML resource, declare the wrong
package name, or have a broken console_scripts entry point, and every
other test in this suite would still pass.

This file is the missing proof:

    build wheel
        -> fresh venv (zero access to src/, zero prior state)
        -> pip install pgdr-*.whl
        -> import pgdr; load_all_configs(); SafetyEngine()
        -> the actual installed `pgdr` console-script, not `run_pgdr.py`
        -> the full P0 negative-config matrix, run against that install

It is deliberately slower than the rest of the suite (builds a wheel,
creates a real venv, installs from PyPI) — that cost is the point; a
`sys.path` trick cannot substitute for actually installing the thing.
The wheel is built and the venv is created ONCE per test session (module-
scoped fixtures) and reused across all tests in this file.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent

pytestmark = pytest.mark.packaging

REQUIRED_WHEEL_RESOURCES = {
    "pgdr/config/__init__.py",
    "pgdr/config/safety_rules.yaml",
    "pgdr/config/symptom_taxonomy.yaml",
    "pgdr/config/questions.yaml",
    "pgdr/config/business_rules.yaml",
}

_VALID_RULE = {
    "id": "T1",
    "conditions": {"keywords_any": ["x"]},
    "triage_level": "emergency_stop",
    "driving_assessment": "do_not_drive",
    "instruction": "i",
    "reason": "r",
}
_VALID_DEFAULT = {
    "triage_level": "monitor_and_document",
    "driving_assessment": "not_assessed",
    "instruction": "i",
    "reason": "r",
}


# ---------------------------------------------------------------------------
# Fixtures — build once, reuse across every test in this module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    dist_dir = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"wheel build failed (returncode={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel in {dist_dir}, found {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def fresh_venv_python(built_wheel, tmp_path_factory):
    """A brand-new venv with the built wheel (and its dependencies)
    installed — and nothing else. Never reuses the dev .venv; the whole
    point is proving the artifact carries everything it needs on its own."""
    venv_dir = tmp_path_factory.mktemp("venv")
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    py = venv_dir / "bin" / "python"
    if not py.exists():
        py = venv_dir / "Scripts" / "python.exe"  # Windows layout

    result = subprocess.run(
        [str(py), "-m", "pip", "install", "-q", str(built_wheel)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, f"pip install of built wheel failed:\n{result.stderr}"
    return py


def _isolated_cwd():
    """A scratch directory with no relationship to the project — running
    subprocess commands from here (instead of PROJECT_ROOT) makes sure
    nothing is accidentally resolving pgdr via a relative src/ path."""
    return tempfile.mkdtemp(prefix="pgdr-wheel-test-cwd-")


def _run_negative_config_case(python_exe: Path, safety_rules_content, expect_in_stderr: str):
    """Writes `safety_rules_content` (a dict, dumped to YAML, or a raw
    string for malformed/empty cases) as the only file in a fresh
    PGDR_CONFIG_DIR, then asserts load_safety_rules() fails closed against
    the INSTALLED wheel."""
    config_dir = tempfile.mkdtemp(prefix="pgdr-wheel-test-config-")
    try:
        target = Path(config_dir) / "safety_rules.yaml"
        if safety_rules_content is not None:
            if isinstance(safety_rules_content, str):
                target.write_text(safety_rules_content)
            else:
                target.write_text(yaml.safe_dump(safety_rules_content))
        # else: leave the file missing entirely

        import os
        env = dict(os.environ)
        env["PGDR_CONFIG_DIR"] = config_dir
        code = "from pgdr.config_loader import load_safety_rules; load_safety_rules()"
        result = subprocess.run(
            [str(python_exe), "-c", code],
            cwd=_isolated_cwd(), env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0, (
            f"expected failure but process succeeded. stdout={result.stdout!r}"
        )
        assert "ConfigurationError" in result.stderr
        assert expect_in_stderr.lower() in result.stderr.lower()
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# P0.1 — the wheel actually contains the packaged resources
# ---------------------------------------------------------------------------

def test_wheel_contains_all_required_config_resources(built_wheel):
    with zipfile.ZipFile(built_wheel) as zf:
        names = set(zf.namelist())
    missing = REQUIRED_WHEEL_RESOURCES - names
    assert not missing, f"wheel is missing required packaged resources: {missing}"


# ---------------------------------------------------------------------------
# Positive path — installed wheel, fresh venv, zero source-tree access
# ---------------------------------------------------------------------------

def test_wheel_installs_and_loads_all_configs_in_fresh_venv(fresh_venv_python):
    code = (
        "import pgdr\n"
        "from pgdr.config_loader import load_all_configs\n"
        "from pgdr.safety_engine import SafetyEngine\n"
        "cfgs = load_all_configs()\n"
        "assert set(cfgs) == {'safety_rules','symptom_taxonomy','questions','business_rules'}, cfgs.keys()\n"
        "assert len(cfgs['safety_rules']['rules']) > 0\n"
        "engine = SafetyEngine()\n"
        "assert len(engine.rules) > 0\n"
        "print('WHEEL_SMOKE_OK')\n"
    )
    result = subprocess.run(
        [str(fresh_venv_python), "-c", code],
        cwd=_isolated_cwd(), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "WHEEL_SMOKE_OK" in result.stdout


def test_wheel_console_script_entry_point_runs_full_emergency_scenario(fresh_venv_python):
    """Through the actual installed `pgdr` console-script — not
    `python run_pgdr.py` — proving pip's entry-point wiring itself works."""
    pgdr_bin = fresh_venv_python.parent / "pgdr"
    assert pgdr_bin.exists(), f"console_scripts entry point not found at {pgdr_bin}"

    result = subprocess.run(
        [str(pgdr_bin), "run", "--vir-id", "VIR-001",
         "--complaint", "La pédale de frein est molle et la voiture ne freine plus",
         "--non-interactive"],
        cwd=_isolated_cwd(), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    combined = (result.stdout + result.stderr).lower()
    assert "signal de sécurité" in combined
    assert "emergency_stop" in combined


def test_wheel_valid_override_config_still_succeeds(fresh_venv_python):
    """Negative-matrix sibling: proves PGDR_CONFIG_DIR override itself
    works against the installed wheel (not just that broken configs fail —
    a validator that rejects everything would trivially pass the FAIL
    cases below without this control)."""
    good = {"rules": [_VALID_RULE], "default": _VALID_DEFAULT}
    config_dir = tempfile.mkdtemp(prefix="pgdr-wheel-test-config-")
    try:
        (Path(config_dir) / "safety_rules.yaml").write_text(yaml.safe_dump(good))
        import os
        env = dict(os.environ)
        env["PGDR_CONFIG_DIR"] = config_dir
        result = subprocess.run(
            [str(fresh_venv_python), "-c",
             "from pgdr.config_loader import load_safety_rules; load_safety_rules(); print('OK')"],
            cwd=_isolated_cwd(), env=env, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Negative matrix — same 7 cases from the mandate, now proven against the
# INSTALLED WHEEL rather than the source tree.
# ---------------------------------------------------------------------------

def test_wheel_missing_safety_rules_fails_closed(fresh_venv_python):
    _run_negative_config_case(fresh_venv_python, None, "missing")


def test_wheel_empty_safety_rules_fails_closed(fresh_venv_python):
    _run_negative_config_case(fresh_venv_python, "", "empty")


def test_wheel_malformed_yaml_fails_closed(fresh_venv_python):
    _run_negative_config_case(fresh_venv_python, "rules: [\n  bad: yaml: here", "malformed")


def test_wheel_unknown_triage_level_fails_closed(fresh_venv_python):
    bad = {"rules": [dict(_VALID_RULE, triage_level="emergncy_stop")], "default": _VALID_DEFAULT}
    _run_negative_config_case(fresh_venv_python, bad, "triage_level")


def test_wheel_unknown_driving_assessment_fails_closed(fresh_venv_python):
    bad = {"rules": [dict(_VALID_RULE, driving_assessment="safe_to_drive")], "default": _VALID_DEFAULT}
    _run_negative_config_case(fresh_venv_python, bad, "driving_assessment")


def test_wheel_duplicate_rule_id_fails_closed(fresh_venv_python):
    bad = {"rules": [_VALID_RULE, dict(_VALID_RULE)], "default": _VALID_DEFAULT}
    _run_negative_config_case(fresh_venv_python, bad, "duplicate")


def test_wheel_empty_conditions_fails_closed(fresh_venv_python):
    bad = {"rules": [dict(_VALID_RULE, conditions={})], "default": _VALID_DEFAULT}
    _run_negative_config_case(fresh_venv_python, bad, "conditions")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
