"""P4 mandate §19 — QuestionSelector v1 is deliberately simple and
substitutable; P5 may improve the strategy without touching
DiagnosticCaseState or DiagnosticLoop.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.question import DiagnosticQuestion


@runtime_checkable
class QuestionSelector(Protocol):
    def select(
        self,
        candidates: list[DiagnosticQuestion],
        state: DiagnosticCaseState,
    ) -> DiagnosticQuestion | None:
        ...
