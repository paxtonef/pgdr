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
from pgdr.domain.identity import MachineIdentityContext, from_vehicle_identity_context
from pgdr.domain.safety_state import SafetyState
from pgdr.models import PreGarageDiagnosticRequest, SafetyTriage


class DiagnosticCaseFactory:
    def __init__(self, loop: DiagnosticLoop) -> None:
        self._loop = loop

    def _case_context(
        self, request: PreGarageDiagnosticRequest, safety_triage: SafetyTriage
    ) -> tuple[MachineIdentityContext, SafetyState]:
        """The single request -> case-context mapping, shared by both entries
        so a text-first case and a photo-first case can never end up carrying
        identity or safety context built by two different rules. Pure
        transport: the VIR context is mapped verbatim and the SafetyTriage is
        wrapped as computed — nothing is evaluated or reinterpreted here (§5,
        P5.3: SafetyEngine remains the sole authority)."""
        return (
            from_vehicle_identity_context(request.vehicle_identity_context),
            SafetyState(triage=safety_triage),
        )

    def create(
        self, request: PreGarageDiagnosticRequest, safety_triage: SafetyTriage
    ) -> DiagnosticCaseState:
        identity_context, safety_state = self._case_context(request, safety_triage)
        return self._loop.start(
            raw_complaint=request.initial_complaint.free_text,
            identity_context=identity_context,
            safety_state=safety_state,
        )

    def create_for_photo(
        self, request: PreGarageDiagnosticRequest, safety_triage: SafetyTriage
    ) -> DiagnosticCaseState:
        """PHOTO-FIRST: as create(), but without a complaint (none exists).
        Same case context, same DiagnosticLoop, same lifecycle — the only
        difference is that no complaint is submitted, because there is none."""
        identity_context, safety_state = self._case_context(request, safety_triage)
        return self._loop.start_without_complaint(
            identity_context=identity_context,
            safety_state=safety_state,
        )
