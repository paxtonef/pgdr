"""P5 mandate §4 (P5.2) — DiagnosticCaseFactory: the canonical path from
(initial complaint + VIR context + a pre-computed safety verdict) to a
DiagnosticCaseState.

Deliberately does NOT run safety evaluation itself — per §5 (P5.3),
SafetyEngine remains the sole, unmodified authority for that, and its
result is supplied here as an already-computed SafetyTriage, never
recomputed or reinterpreted by this factory or by DiagnosticLoop.
"""
from __future__ import annotations

from pgdr.application.diagnostic_loop import DiagnosticLoop
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.identity import from_vehicle_identity_context
from pgdr.domain.safety_state import SafetyState
from pgdr.models import PreGarageDiagnosticRequest, SafetyTriage


class DiagnosticCaseFactory:
    def __init__(self, loop: DiagnosticLoop) -> None:
        self._loop = loop

    def create(
        self, request: PreGarageDiagnosticRequest, safety_triage: SafetyTriage
    ) -> DiagnosticCaseState:
        identity_context = from_vehicle_identity_context(request.vehicle_identity_context)
        safety_state = SafetyState(triage=safety_triage)
        return self._loop.start(
            raw_complaint=request.initial_complaint.free_text,
            identity_context=identity_context,
            safety_state=safety_state,
        )
