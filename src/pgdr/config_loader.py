"""Configuration loading — P0 Execution & Safety Configuration Integrity.

Two things changed from the pre-P0 version:

1. Config is loaded via `importlib.resources` against the `pgdr.config`
   package, not via a path relative to `__file__`. This is what makes the
   4 YAML files behave identically whether PGDR runs from a source
   checkout or from an installed wheel — a `pip install`d copy has no
   `src/` layout to walk. `PGDR_CONFIG_DIR` remains available as an
   explicit override (used by tests to inject broken configs).

2. Every load is fail-closed (P0.2 / P0.3): a missing file, an empty file,
   malformed YAML, or (for safety_rules specifically) a semantically
   invalid safety rule all raise ConfigurationError instead of degrading
   to `{}` / `[]` and letting the rest of the system limp along on empty
   defaults. There is deliberately no `try/except -> return {}` anywhere
   in this module.

Caching: intentionally NOT cached (no functools.lru_cache). These are a
few KB of YAML parsed at most once per CLI invocation or once per test —
correctness and testability (being able to point PGDR_CONFIG_DIR at a
different fixture per test and get a fresh read) matter far more here
than shaving a few milliseconds.
"""
from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

import yaml

from pgdr.enums import DrivingAssessment, TriageLevel
from pgdr.errors import ConfigurationError


def _read_config_text(name: str) -> str:
    """Returns the raw YAML text for `name`, or raises ConfigurationError.

    Resolution order: PGDR_CONFIG_DIR env var (explicit override, used by
    tests and by operators who want to supply their own governance data)
    takes precedence over the packaged resource.
    """
    env_dir = os.environ.get("PGDR_CONFIG_DIR")
    if env_dir:
        path = Path(env_dir) / f"{name}.yaml"
        if not path.exists():
            raise ConfigurationError(
                f"Required configuration file missing: {path} "
                f"(PGDR_CONFIG_DIR={env_dir})"
            )
        text = path.read_text(encoding="utf-8")
    else:
        try:
            ref = resources.files("pgdr.config").joinpath(f"{name}.yaml")
            if not ref.is_file():
                raise ConfigurationError(
                    f"Required configuration resource missing from package: pgdr/config/{name}.yaml"
                )
            text = ref.read_text(encoding="utf-8")
        except ModuleNotFoundError as exc:
            raise ConfigurationError(
                f"pgdr.config is not importable — the installed package appears incomplete "
                f"(cannot locate {name}.yaml)"
            ) from exc

    if not text.strip():
        raise ConfigurationError(f"Required configuration file is empty: {name}.yaml")
    return text


def load_yaml(name: str) -> dict:
    """Loads and parses `{name}.yaml`. Raises ConfigurationError on any
    failure — missing, empty, malformed YAML, or a YAML document that
    doesn't parse to a mapping."""
    text = _read_config_text(name)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Malformed YAML in {name}.yaml: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigurationError(
            f"{name}.yaml must parse to a mapping at the top level, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# P0.3 — Safety schema validation
# ---------------------------------------------------------------------------

_VALID_TRIAGE_LEVELS = {e.value for e in TriageLevel}
_VALID_DRIVING_ASSESSMENTS = {e.value for e in DrivingAssessment}
_SAFETY_ACTION_FIELDS = ("triage_level", "driving_assessment", "instruction", "reason")


def _validate_safety_action_fields(block: dict, where: str) -> None:
    """Shared validation for a single rule OR the `default` block — both
    carry the same 4 action fields and must be held to the same standard.
    No silent conversion: an invalid enum value here is a hard failure,
    never a fallback to a lower/default severity (P0.3)."""
    for field in _SAFETY_ACTION_FIELDS:
        if field not in block or block[field] in (None, ""):
            raise ConfigurationError(f"{where}: missing required field '{field}'")

    level = block["triage_level"]
    if level not in _VALID_TRIAGE_LEVELS:
        raise ConfigurationError(
            f"{where}: invalid triage_level '{level}' — must be one of {sorted(_VALID_TRIAGE_LEVELS)}"
        )

    assessment = block["driving_assessment"]
    if assessment not in _VALID_DRIVING_ASSESSMENTS:
        raise ConfigurationError(
            f"{where}: invalid driving_assessment '{assessment}' — "
            f"must be one of {sorted(_VALID_DRIVING_ASSESSMENTS)}"
        )

    for bool_field in ("emergency_services", "roadside_assistance"):
        if bool_field in block and not isinstance(block[bool_field], bool):
            # Catches the classic YAML footgun: `emergency_services: "false"`
            # (a non-empty string) is truthy in Python and would silently
            # always request emergency services.
            raise ConfigurationError(
                f"{where}: field '{bool_field}' must be a boolean, "
                f"got {type(block[bool_field]).__name__} ({block[bool_field]!r})"
            )


def validate_safety_rules(data: dict) -> None:
    """Full semantic validation of a parsed safety_rules.yaml document.
    Raises ConfigurationError on the first violation found. Exposed as a
    standalone function (rather than folded into load_safety_rules) so
    tests can validate hand-built dicts without touching the filesystem.
    """
    if "rules" not in data:
        raise ConfigurationError("safety_rules.yaml: missing required top-level key 'rules'")
    rules = data["rules"]
    if not isinstance(rules, list) or len(rules) == 0:
        raise ConfigurationError("safety_rules.yaml: 'rules' must be a non-empty list")

    if "default" not in data:
        raise ConfigurationError("safety_rules.yaml: missing required top-level key 'default'")
    default = data["default"]
    if not isinstance(default, dict):
        raise ConfigurationError("safety_rules.yaml: 'default' must be a mapping")
    _validate_safety_action_fields(default, "safety_rules.yaml default block")

    seen_ids: set[str] = set()
    for i, rule in enumerate(rules):
        where = f"safety_rules.yaml rule #{i}"
        if not isinstance(rule, dict):
            raise ConfigurationError(f"{where}: must be a mapping, got {type(rule).__name__}")

        rule_id = rule.get("id")
        if not rule_id or not isinstance(rule_id, str):
            raise ConfigurationError(f"{where}: missing or invalid required field 'id'")
        where = f"safety_rules.yaml rule '{rule_id}'"
        if rule_id in seen_ids:
            raise ConfigurationError(f"{where}: duplicate rule id — ids must be unique")
        seen_ids.add(rule_id)

        conditions = rule.get("conditions")
        if not isinstance(conditions, dict) or len(conditions) == 0:
            raise ConfigurationError(f"{where}: 'conditions' is required and must be a non-empty mapping")

        _validate_safety_action_fields(rule, where)


def load_safety_rules() -> dict:
    """SAFETY-critical config (P0). Missing, empty, malformed, or
    semantically invalid data all raise ConfigurationError — there is no
    fallback path that lets PGDR construct a SafetyEngine on bad data."""
    data = load_yaml("safety_rules")
    validate_safety_rules(data)
    return data


def load_taxonomy() -> dict:
    return load_yaml("symptom_taxonomy")


def load_questions() -> dict:
    return load_yaml("questions")


def load_business_rules() -> dict:
    return load_yaml("business_rules")


def load_all_configs() -> dict[str, dict]:
    """Loads and validates every packaged config. Used by the P0 smoke
    test (and, from P1 onward, by the runner readiness check) to prove
    the whole configuration surface is sound before anything else runs."""
    loaders = {
        "safety_rules": load_safety_rules,
        "symptom_taxonomy": load_taxonomy,
        "questions": load_questions,
        "business_rules": load_business_rules,
    }
    return {name: loader() for name, loader in loaders.items()}
