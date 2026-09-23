"""VIR identity artifact -> manufacturer document applicability.

The only path from a consumed vehicle identity to a Dashboard Reference Set:

    VehicleIdentityContext (VIR, via PI map_resolution())
      -> VehicleApplicabilityContext.from_pgdr_vehicle_identity_dict()
      -> VehicleDashboardKnowledgePort
      -> DashboardReferenceSet

PGDR does not resolve vehicle identity (PGDR-ID-001). When the VIR artifact
lacks a fact that applicability genuinely depends on, this fails closed with
VEHICLE_IDENTITY_INSUFFICIENT; it never asks the driver to supply it.
"""
from __future__ import annotations

from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceSet, VehicleApplicabilityContext,
)
from pgdr.models import VehicleIdentityContext
from pgdr.ports.vehicle_dashboard_knowledge import VehicleDashboardKnowledgePort

# The identity keys manufacturer documents are resolved on (see
# KnowledgeRepositoryPort.find_applicable_documents).
APPLICABILITY_IDENTITY_FIELDS = ("manufacturer", "model", "generation")


def applicability_identity_gaps(identity: VehicleIdentityContext) -> list[str]:
    """The applicability keys VIR did not establish: absent, or reported by
    VIR itself as unresolved or contradictory."""
    vehicle = identity.vehicle_identity or {}
    doubtful = set(identity.unresolved_fields) | set(identity.contradictions)
    return [f for f in APPLICABILITY_IDENTITY_FIELDS if not vehicle.get(f) or f in doubtful]


def resolve_dashboard_reference(
    identity: VehicleIdentityContext, knowledge: VehicleDashboardKnowledgePort,
) -> DashboardReferenceSet:
    vehicle = VehicleApplicabilityContext.from_pgdr_vehicle_identity_dict(identity.vehicle_identity)
    gaps = applicability_identity_gaps(identity)
    if gaps:
        return DashboardReferenceSet(
            vehicle_applicability=vehicle,
            applicability_status=ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT,
            provenance_note=f"VIR identity artifact {identity.resolution_id} does not establish: "
                            f"{', '.join(gaps)}. No document applicability decision is made.",
        )
    return knowledge.get_dashboard_reference_set(vehicle)
