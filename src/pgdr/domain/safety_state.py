"""P4 mandate §16 — Safety interaction. P4 changes ZERO automotive safety
rules. This module only wraps the existing, unmodified
pgdr.models.SafetyTriage (produced by the existing, unmodified
SafetyEngine) with a `preempts_analysis` computation — the exact same
condition session_controller.py already uses
(`triage.level.value in ("emergency_stop", "do_not_drive")`), extracted
here as a single named predicate so DiagnosticLoop and
session_controller.py provably agree on it rather than each hardcoding
the same tuple independently.
"""
from __future__ import annotations

from pydantic import BaseModel

from pgdr.models import SafetyTriage

_PREEMPTING_LEVELS = frozenset({"emergency_stop", "do_not_drive"})


class SafetyState(BaseModel):
    triage: SafetyTriage

    @property
    def preempts_analysis(self) -> bool:
        return self.triage.level.value in _PREEMPTING_LEVELS
