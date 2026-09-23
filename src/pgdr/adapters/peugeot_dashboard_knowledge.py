"""Block B2-K — Peugeot 3008 II POC adapter.

Implements pgdr.ports.vehicle_dashboard_knowledge.VehicleDashboardKnowledgePort.

======================================================================
KNOWLEDGE PERSISTENCE REFACTOR (this pass)
======================================================================
Per the B2-K Knowledge Persistence Investigation's own finding, this
adapter previously mixed two responsibilities: (1) Peugeot-specific
applicability DECISION logic, and (2) the entire knowledge
fixture as hardcoded module-level constants (the permanent "source of
record"). This pass separates them: the fixture data now lives in
durable, non-execution-scoped persistence (PI/CPL side, injected here as
a pgdr.ports.knowledge_repository.KnowledgeRepositoryPort), and this
adapter keeps only what is genuinely Peugeot-specific reasoning --
Peugeot's own documented rule that handbook-edition applicability
follows the vehicle's first-registration date, never production year.
The date is required only where it materially discriminates between
candidate documents bounded by issue periods (VIR -> PGDR identity
boundary correction); it is never fabricated or derived from production
dates.

pgdr.ports.vehicle_dashboard_knowledge.VehicleDashboardKnowledgePort's own
external contract (vehicle identity in, DashboardReferenceSet out) is
UNCHANGED by this refactor -- persistence is entirely behind this
boundary, exactly as media storage became an implementation detail
behind PGDR's own session/adapter boundary in Block B1.5 without altering
Block B1's PrimaryDiagnosticMedia contract.

The owner-attested (not independently verified) content itself (the
corrected Peugeot 3008/5008 handbook transcription, document 9999_9999_326_en-GB.pdf) is unchanged in
substance -- it no longer lives in this file; it lives in the persisted
store this adapter now queries through the injected repository. See
the Knowledge Persistence Implementation Report's own SOURCE PROVENANCE
notes for the seeding mechanism that installs it.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceSet, ManufacturerDocumentReference, VehicleApplicabilityContext,
)
from pgdr.ports.knowledge_repository import KnowledgeRepositoryPort


def _has_period(document: ManufacturerDocumentReference) -> bool:
    period = document.applicability_period
    return period is not None and (period.start_date is not None or period.end_date is not None)


def _period_contains(document: ManufacturerDocumentReference, registration: date) -> Optional[bool]:
    """True/False when the document's period bounds decide it; None when a
    bound cannot be read (never guessed -- the caller fails closed)."""
    period = document.applicability_period
    try:
        start = date.fromisoformat(period.start_date) if period.start_date else None
        end = date.fromisoformat(period.end_date) if period.end_date else None
    except ValueError:
        return None
    return (start is None or start <= registration) and (end is None or registration <= end)


class PeugeotDashboardKnowledgeAdapter:
    """Implements VehicleDashboardKnowledgePort structurally (confirmed via
    isinstance() against the real Port in the B2-K test suite -- no
    inheritance required). Depends on an injected KnowledgeRepositoryPort
    for all actual document/entry data -- owns no fixture of its own."""

    def __init__(self, repository: KnowledgeRepositoryPort):
        self._repository = repository

    def get_dashboard_reference_set(self, vehicle: VehicleApplicabilityContext) -> DashboardReferenceSet:
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

        # Peugeot's own stated rule (owner-attested, per the transcribed B2-K
        # content): handbook issue-period applicability corresponds to first
        # registration, never production year. The date is therefore required
        # exactly when it materially discriminates: several candidates, at
        # least one bounded by an issue period. It is never fabricated, and
        # production dates never stand in for it.
        date_discriminates = len(candidates) > 1 and any(_has_period(d) for d in candidates)
        if vehicle.first_registration_date is None:
            if date_discriminates:
                return DashboardReferenceSet(
                    vehicle_applicability=vehicle,
                    candidate_documents=candidates,
                    applicability_status=ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT,
                    provenance_note="Several candidate documents are bounded by handbook issue periods, "
                                    "which Peugeot ties to the first-registration date. That date is not "
                                    "part of the vehicle identity, so the applicable document cannot be "
                                    "determined. Not resolved automatically.",
                )
        else:
            try:
                registration = date.fromisoformat(vehicle.first_registration_date)
            except ValueError:
                registration = None
            decisions = [
                (d, (_period_contains(d, registration) if registration else None) if _has_period(d) else True)
                for d in candidates
            ]
            if any(inside is None for _, inside in decisions):
                return DashboardReferenceSet(
                    vehicle_applicability=vehicle,
                    candidate_documents=candidates,
                    applicability_status=ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN,
                    provenance_note="The first-registration date or a candidate document's issue period "
                                    "cannot be read; not resolved automatically.",
                )
            candidates = [d for d, inside in decisions if inside]
            if not candidates:
                return DashboardReferenceSet(
                    vehicle_applicability=vehicle,
                    applicability_status=ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE,
                    provenance_note="No persisted document's issue period covers this vehicle's "
                                    "first-registration date.",
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
            provenance_note=f"Resolved to the single applicable persisted document: {document.document_id}"
                            + (", selected by the first-registration date." if date_discriminates else "."),
        )
