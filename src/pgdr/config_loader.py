"""Loads the deterministic governance YAML files (taxonomy, safety rules,
questions, business rules). Keeping these in YAML instead of Python keeps
the domain-knowledge layer editable without touching code, per AMD pack
15.2 (deterministic vs AI-assisted capability split)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml


def _config_dir() -> Path:
    env_dir = os.environ.get("PGDR_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).parent / "config"


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    path = _config_dir() / f"{name}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_taxonomy() -> dict:
    return load_yaml("symptom_taxonomy")


def load_safety_rules() -> dict:
    return load_yaml("safety_rules")


def load_questions() -> dict:
    return load_yaml("questions")


def load_business_rules() -> dict:
    return load_yaml("business_rules")
