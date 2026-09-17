"""Block B2-K — Knowledge Persistence, §6/§7 of the implementation
mandate. The capability boundary: applicability criteria -> persisted
manufacturer document/entry records.

PGDR domain/port code contains no SQL, no PostgreSQL, no CPL, no PI
dependency anywhere in this module -- confirmed by construction (no
import of anything outside pgdr.domain here). A concrete, storage-backed
implementation is injected by the caller (the PI/CPL persistence side),
mirroring exactly the same discipline already established for
MediaResolverPort (B1.5) and DashboardInterpretationPort (B1): PGDR
defines capability semantics only.

This Port is deliberately separate from VehicleDashboardKnowledgePort
(unchanged by this mandate, per its own §7): VehicleDashboardKnowledgePort
is "given a vehicle, decide applicability and return a
DashboardReferenceSet" (manufacturer-specific reasoning, e.g.
PeugeotDashboardKnowledgeAdapter's own knowledge of Peugeot's first-
registration rule); KnowledgeRepositoryPort is "given applicability
criteria, retrieve the stored records" (a generic, manufacturer-neutral
data-access capability). PeugeotDashboardKnowledgeAdapter now depends on
an injected KnowledgeRepositoryPort instead of owning its fixture as
module-level constants.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pgdr.domain.dashboard_knowledge import (
    DashboardReferenceEntry, ManufacturerDocumentReference, VehicleApplicabilityContext,
)


@runtime_checkable
class KnowledgeRepositoryPort(Protocol):
    """§6: find manufacturer documents applicable to a vehicle/application
    context; retrieve DashboardReferenceEntry records associated with a
    document; expose enough lifecycle/provenance information (already
    carried directly on ManufacturerDocumentReference itself --
    lifecycle_status, verified_at, supersedes_document_id -- per the §8
    domain-model extension) to determine whether stored knowledge is
    usable."""

    def find_applicable_documents(self, vehicle: VehicleApplicabilityContext) -> list[ManufacturerDocumentReference]:
        """Returns currently-ACTIVE documents whose applicability
        (manufacturer + model + generation) matches the given vehicle.
        Does NOT apply any manufacturer-specific date/edition-selection
        policy (e.g. Peugeot's own first-registration rule) -- that
        remains the calling adapter's responsibility, not this Port's.
        Returns an empty list, never a fabricated result, when nothing
        matches."""
        ...

    def entries_for_document(self, document_id: str) -> list[DashboardReferenceEntry]:
        """Returns every DashboardReferenceEntry stored under the given
        document_id. Returns an empty list, never a fabricated result,
        when the document has no stored entries."""
        ...

    def get_document_by_id(self, document_id: str) -> Optional[ManufacturerDocumentReference]:
        """Returns the document with this exact document_id regardless of
        its current lifecycle_status (ACTIVE or SUPERSEDED) -- the
        historical-lookup path (§9): a case that recorded which document_
        id it used can always re-resolve that same record later, even
        after a newer generation has superseded it for new lookups.
        Returns None, never a fabricated result, when no such document_id
        exists at all."""
        ...
