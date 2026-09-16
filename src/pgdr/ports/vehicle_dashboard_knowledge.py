"""Block B2-K — the capability boundary: vehicle identity -> Dashboard
Reference Set. Follows the existing pgdr/ports/ convention exactly
(typing.Protocol, @runtime_checkable), matching
pgdr.ports.media_resolver.MediaResolverPort and
pgdr.ports.dashboard_interpretation.DashboardInterpretationPort.

PGDR domain/session code depends on this Port only -- never on a
manufacturer-specific adapter directly (§11 of the B2-K mandate).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pgdr.domain.dashboard_knowledge import DashboardReferenceSet, VehicleApplicabilityContext


@runtime_checkable
class VehicleDashboardKnowledgePort(Protocol):
    """vehicle identity -> Dashboard Reference Set. A concrete
    implementation (e.g. a manufacturer-specific adapter) is injected by
    the caller -- PGDR domain code never imports or depends on a specific
    manufacturer source."""

    def get_dashboard_reference_set(self, vehicle: VehicleApplicabilityContext) -> DashboardReferenceSet:
        """Determine what manufacturer-documented dashboard knowledge is
        applicable to this identified vehicle. Never fabricates
        applicability when the vehicle identity or the source itself is
        insufficient -- returns a DashboardReferenceSet whose
        applicability_status honestly reflects that (see
        pgdr.domain.dashboard_knowledge.ApplicabilityStatus)."""
        ...
