"""P4 mandate §17 — MachineIdentityContext: the generic identity
abstraction. P4 does NOT decide what a given confidence value permits
("confidence 0.63 -> which claim is allowed?") — that's GGM/CGM's job.
P4 only lets the analytical engine know identity is incomplete, and lets
a hypothesis declare `configuration_requirements` so the engine can
detect "this hypothesis needs identity data the case doesn't have" (see
DiagnosticHypothesis.configuration_requirements).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MachineIdentityContext(BaseModel):
    identity_ref: str | None = None
    confidence: float | None = None
    ambiguity: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


def from_vehicle_identity_context(vic) -> MachineIdentityContext:
    """Automotive adapter: maps pgdr.models.VehicleIdentityContext (the
    VIR input contract) into the generic MachineIdentityContext. This is
    the automotive Domain Pack's IdentityContextPort implementation
    referenced in P3's generic_domain_contracts.md — kept as a plain
    function rather than a class since it's a pure, stateless mapping.
    """
    ambiguous_statuses = {"ambiguous", "insufficient_data", "contradictory"}
    confidence = vic.confidence.score if vic.confidence else None
    return MachineIdentityContext(
        identity_ref=vic.resolution_id,
        confidence=confidence,
        ambiguity=vic.resolution_status.value in ambiguous_statuses,
        attributes={
            "resolution_status": vic.resolution_status.value,
            "unresolved_fields": list(vic.unresolved_fields),
            "contradictions": list(vic.contradictions),
            **(vic.vehicle_identity or {}),
        },
    )
