"""PGDR error types.

ConfigurationError is the single signal used across config_loader and
safety_engine for "this instance is not safe to operate" (P0). Catching it
must never produce a fabricated safety verdict — only an explicit refusal
to run. See safety_engine.py and cli.py for how it's handled at the
boundary.
"""
from __future__ import annotations


class ConfigurationError(Exception):
    """Raised when a required PGDR configuration file is missing, empty,
    malformed, or semantically invalid (e.g. an unknown enum value in a
    safety rule).

    Fail-closed contract (P0): raising this must always result in PGDR
    refusing to execute — never in a degraded-but-apparently-normal
    triage result, and never in a fabricated safety instruction (e.g.
    "do not drive") synthesized from the failure itself.
    """
