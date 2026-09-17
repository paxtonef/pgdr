"""Block B2-K — Peugeot 3008 II POC adapter.

Implements pgdr.ports.vehicle_dashboard_knowledge.VehicleDashboardKnowledgePort.

======================================================================
KNOWLEDGE PERSISTENCE REFACTOR (this pass)
======================================================================
Per the B2-K Knowledge Persistence Investigation's own finding, this
adapter previously mixed two responsibilities: (1) Peugeot-specific
applicability DECISION logic, and (2) the entire verified knowledge
fixture as hardcoded module-level constants (the permanent "source of
record"). This pass separates them: the fixture data now lives in
durable, non-execution-scoped persistence (PI/CPL side, injected here as
a pgdr.ports.knowledge_repository.KnowledgeRepositoryPort), and this
adapter keeps only what is genuinely Peugeot-specific reasoning --
Peugeot's own documented rule that handbook-edition applicability
requires knowing the vehicle's first-registration date, never production
year alone.

pgdr.ports.vehicle_dashboard_knowledge.VehicleDashboardKnowledgePort's own
external contract (vehicle identity in, DashboardReferenceSet out) is
UNCHANGED by this refactor -- persistence is entirely behind this
boundary, exactly as media storage became an implementation detail
behind PGDR's own session/adapter boundary in Block B1.5 without altering
Block B1's PrimaryDiagnosticMedia contract.

The verified content itself (the corrected Peugeot 3008/5008 handbook
transcription, document 9999_9999_326_en-GB.pdf) is unchanged in
substance -- it no longer lives in this file; it lives in the persisted
store this adapter now queries through the injected repository. See
the Knowledge Persistence Implementation Report's own SOURCE PROVENANCE
notes for the seeding mechanism that installs it.
"""
from __future__ import annotations

from pgdr.domain.dashboard_knowledge import ApplicabilityStatus, DashboardReferenceSet, VehicleApplicabilityContext
from pgdr.ports.knowledge_repository import KnowledgeRepositoryPort


class PeugeotDashboardKnowledgeAdapter:
    """Implements VehicleDashboardKnowledgePort structurally (confirmed via
    isinstance() against the real Port in the B2-K test suite -- no
    inheritance required). Depends on an injected KnowledgeRepositoryPort
    for all actual document/entry data -- owns no fixture of its own."""

    def __init__(self, repository: KnowledgeRepositoryPort):
        self._repository = repository

    def get_dashboard_reference_set(self, vehicle: VehicleApplicabilityContext) -> DashboardReferenceSet:
        if vehicle.production_year is None and vehicle.first_registration_date is None:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                applicability_status=ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT,
                provenance_note="Neither production year nor first-registration date is known; "
                                "no document applicability decision can be made.",
            )

        # §6: the repository does the generic manufacturer+model+generation
        # match; a vehicle outside this adapter's POC scope (or any
        # unsupported vehicle) simply yields no candidates here, without
        # this adapter needing its own hardcoded manufacturer/model check.
        candidates = self._repository.find_applicable_documents(vehicle)

        if not candidates:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                applicability_status=ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE,
                provenance_note="No persisted manufacturer document matches this vehicle's "
                                "manufacturer/model/generation.",
            )

        # Peugeot's own stated rule (verified, per the corrected B2-K
        # content): handbook issue-period applicability corresponds to
        # first registration, not production year. Production year alone
        # is never treated as sufficient to confirm applicability.
        if vehicle.first_registration_date is None:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                candidate_documents=candidates,
                applicability_status=ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN,
                provenance_note="Peugeot's own documentation states that handbook issue-period "
                                "applicability corresponds to the vehicle's first-registration date. "
                                "That date is not known for this vehicle -- production year alone is "
                                "not sufficient to confirm applicability. Not resolved automatically.",
            )

        if len(candidates) > 1:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                candidate_documents=candidates,
                applicability_status=ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN,
                provenance_note="More than one persisted document matches this vehicle's applicability "
                                "criteria; not resolved automatically.",
            )

        document = candidates[0]
        entries = self._repository.entries_for_document(document.document_id)
        if not entries:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                candidate_documents=[document],
                applicability_status=ApplicabilityStatus.DASHBOARD_REFERENCE_NOT_FOUND,
                provenance_note=f"Document {document.document_id} is applicable, but the repository "
                                f"has no dashboard entries stored for it.",
            )

        return DashboardReferenceSet(
            vehicle_applicability=vehicle,
            candidate_documents=[document],
            entries=entries,
            applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
            provenance_note=f"Resolved to the single applicable persisted document: "
                             f"{document.document_id}, based on the supplied first-registration date.",
        )
