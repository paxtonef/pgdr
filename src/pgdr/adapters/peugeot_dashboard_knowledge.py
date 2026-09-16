"""Block B2-K — Peugeot 3008 II POC adapter.

Implements pgdr.ports.vehicle_dashboard_knowledge.VehicleDashboardKnowledgePort
for a single, narrow test case: Peugeot 3008, generation II.

======================================================================
HONESTY / PROVENANCE NOTICE -- READ BEFORE USING ANY DATA IN THIS FILE
======================================================================
This execution environment had no web access tool (no web_search, no
web_fetch) when this adapter was written, and therefore could not
retrieve or verify the actual authorized Peugeot 3008/5008 handbook or
Service Box content the B2-K mandate names as the authorized source.

Every ManufacturerDocumentReference and DashboardReferenceEntry below is
therefore tagged SourceAuthority.UNVERIFIED_PLACEHOLDER, not
SourceAuthority.MANUFACTURER_OFFICIAL. The document identifiers, edition
labels, applicability windows, and all documented_meaning/documented_
instruction text are illustrative constructs written to exercise the
domain model's real structural requirements (colour+state+message
combinations, multi-signal patterns, edition-applicability ambiguity) --
they are NOT transcriptions or paraphrases of real Peugeot text, and MUST
NOT be treated as accurate dashboard guidance for a real vehicle.

Replacing this module's fixture with genuine, source-attributed Peugeot
content (with real document identifiers, real edition dates, and real
section/page locators) is a prerequisite for any real acceptance of B2-K
beyond this POC's own structural/architectural proof.
"""
from __future__ import annotations

from datetime import date

from pgdr.domain.dashboard_knowledge import (
    ApplicabilityPeriod, ApplicabilityStatus, DashboardReferenceEntry,
    DashboardReferenceSet, IndicatorState, ManufacturerDocumentReference,
    SourceAuthority, VehicleApplicabilityContext,
)

# ---------------------------------------------------------------------------
# §9/§13: two illustrative, overlapping-in-2020 handbook editions -- exactly
# the scenario the mandate asks B2-K to handle honestly. Both
# UNVERIFIED_PLACEHOLDER (see module docstring).
# ---------------------------------------------------------------------------

_EDITION_EARLY = ManufacturerDocumentReference(
    manufacturer="Peugeot",
    document_id="3008-II-HB-EARLY-PLACEHOLDER",
    document_title="Peugeot 3008 (Generation II) Owner's Handbook -- illustrative early edition",
    edition="illustrative-A",
    applicability_period=ApplicabilityPeriod(
        start_date="2018-08-01", end_date="2020-06-30",
        note="Illustrative placeholder window only -- not a real Peugeot edition boundary.",
    ),
    source_authority=SourceAuthority.UNVERIFIED_PLACEHOLDER,
    source_locator="UNVERIFIED -- no real source consulted (see module docstring)",
)

_EDITION_LATE = ManufacturerDocumentReference(
    manufacturer="Peugeot",
    document_id="3008-II-HB-LATE-PLACEHOLDER",
    document_title="Peugeot 3008 (Generation II) Owner's Handbook -- illustrative later edition",
    edition="illustrative-B",
    applicability_period=ApplicabilityPeriod(
        start_date="2020-07-01", end_date="2023-12-31",
        note="Illustrative placeholder window only -- not a real Peugeot edition boundary.",
    ),
    source_authority=SourceAuthority.UNVERIFIED_PLACEHOLDER,
    source_locator="UNVERIFIED -- no real source consulted (see module docstring)",
)

_ALL_EDITIONS = [_EDITION_EARLY, _EDITION_LATE]

# ---------------------------------------------------------------------------
# §15: three illustrative entries attached to the LATE edition only --
# proving the model can represent (A) a single-state warning, (B) an
# indicator whose documented meaning depends on fixed vs flashing state,
# and (C) a multi-signal/message combination pattern. All
# UNVERIFIED_PLACEHOLDER.
# ---------------------------------------------------------------------------

_OIL_PRESSURE_ENTRY = DashboardReferenceEntry(
    entry_id="oil-pressure-warning",
    manufacturer_designation="Engine oil pressure warning lamp (illustrative)",
    symbol_descriptor="Oil-can-shaped symbol",
    colour="red",
    state=None,  # single documented state for this illustrative entry
    displayed_message=None,
    audible_signal=None,
    documented_meaning="[PLACEHOLDER] Indicates insufficient engine oil pressure.",
    documented_instruction="[PLACEHOLDER] Stop the vehicle safely and check oil level before continuing.",
    applicability=_EDITION_LATE,
)

_ENGINE_DIAG_FIXED_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-fixed",
    manufacturer_designation="Engine management (self-diagnostic) indicator -- fixed (illustrative)",
    symbol_descriptor="Engine-block-shaped symbol",
    colour="amber",
    state=IndicatorState.FIXED,
    displayed_message=None,
    audible_signal=None,
    documented_meaning="[PLACEHOLDER] A fault has been detected in the engine management system; "
                        "driving may continue with caution.",
    documented_instruction="[PLACEHOLDER] Have the vehicle checked at the earliest opportunity.",
    applicability=_EDITION_LATE,
)

_ENGINE_DIAG_FLASHING_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-flashing",
    manufacturer_designation="Engine management (self-diagnostic) indicator -- flashing (illustrative)",
    symbol_descriptor="Engine-block-shaped symbol",
    colour="amber",
    state=IndicatorState.FLASHING,
    displayed_message=None,
    audible_signal=None,
    documented_meaning="[PLACEHOLDER] A more severe fault has been detected; continued driving risks "
                        "damage to the catalytic converter/engine.",
    documented_instruction="[PLACEHOLDER] Reduce speed/load immediately and seek assessment without delay.",
    applicability=_EDITION_LATE,
)

_SCR_LEVEL_WARNING_ENTRY = DashboardReferenceEntry(
    entry_id="scr-additive-level-warning",
    manufacturer_designation="SCR/AdBlue additive level warning (illustrative)",
    symbol_descriptor="AdBlue reservoir symbol",
    colour="amber",
    state=None,
    displayed_message=None,
    audible_signal=None,
    documented_meaning="[PLACEHOLDER] The SCR additive (AdBlue) level is low.",
    documented_instruction="[PLACEHOLDER] Refill the additive tank soon; the vehicle will refuse to "
                            "restart once the level is fully depleted.",
    applicability=_EDITION_LATE,
    combined_with_entry_ids=["scr-range-countdown-message"],
)

_SCR_RANGE_COUNTDOWN_ENTRY = DashboardReferenceEntry(
    entry_id="scr-range-countdown-message",
    manufacturer_designation="SCR/AdBlue range countdown display message (illustrative)",
    symbol_descriptor=None,
    colour=None,
    state=None,
    displayed_message="[PLACEHOLDER] 'AdBlue: XXX km before restart no longer possible'",
    audible_signal=None,
    documented_meaning="[PLACEHOLDER] Displayed alongside the additive-level warning; the number "
                        "communicates the remaining distance before the engine will not restart.",
    documented_instruction=None,
    applicability=_EDITION_LATE,
    combined_with_entry_ids=["scr-additive-level-warning"],
)

_ALL_ENTRIES = [
    _OIL_PRESSURE_ENTRY, _ENGINE_DIAG_FIXED_ENTRY, _ENGINE_DIAG_FLASHING_ENTRY,
    _SCR_LEVEL_WARNING_ENTRY, _SCR_RANGE_COUNTDOWN_ENTRY,
]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _applicable_editions(vehicle: VehicleApplicabilityContext) -> list[ManufacturerDocumentReference]:
    """§8/§9: uses first_registration_date when available (never
    fabricated -- VehicleApplicabilityContext.first_registration_date is
    always None today, since nothing in the VIR->PI->PGDR chain currently
    supplies it), falling back to production_year only for a coarse
    year-level overlap check. A vehicle whose production year overlaps
    more than one edition's window, with no finer-grained date available
    to discriminate, is genuinely ambiguous -- not silently resolved."""
    reference_date = _parse_date(vehicle.first_registration_date)
    if reference_date is not None:
        return [
            edition for edition in _ALL_EDITIONS
            if edition.applicability_period
            and _parse_date(edition.applicability_period.start_date) <= reference_date
            and reference_date <= _parse_date(edition.applicability_period.end_date)
        ]

    if vehicle.production_year is None:
        return []

    matches = []
    for edition in _ALL_EDITIONS:
        period = edition.applicability_period
        if period is None:
            continue
        start = _parse_date(period.start_date)
        end = _parse_date(period.end_date)
        if start is None or end is None:
            continue
        if start.year <= vehicle.production_year <= end.year:
            matches.append(edition)
    return matches


class PeugeotDashboardKnowledgeAdapter:
    """Implements VehicleDashboardKnowledgePort structurally (confirmed via
    isinstance() against the real Port in the B2-K test suite -- no
    inheritance required)."""

    def get_dashboard_reference_set(self, vehicle: VehicleApplicabilityContext) -> DashboardReferenceSet:
        # §8: applicability is never reduced to manufacturer==Peugeot or
        # model==3008 alone -- generation is required too.
        if (vehicle.manufacturer or "").strip().lower() != "peugeot" \
                or (vehicle.model or "").strip() != "3008" \
                or (vehicle.generation or "").strip().upper() != "II":
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                applicability_status=ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE,
                provenance_note="This adapter's only authorized POC scope is Peugeot 3008, generation II; "
                                "no document exists here for any other vehicle.",
            )

        if vehicle.production_year is None and vehicle.first_registration_date is None:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                applicability_status=ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT,
                provenance_note="Neither production year nor first-registration date is known; "
                                "no document applicability decision can be made.",
            )

        candidates = _applicable_editions(vehicle)

        if not candidates:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                applicability_status=ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE,
                provenance_note="Vehicle identity is a Peugeot 3008 II, but no known edition window "
                                "(illustrative placeholders only -- see module docstring) covers it.",
            )

        if len(candidates) > 1:
            # §9: exactly the scenario named by the user -- production
            # year 2020 alone straddles both illustrative editions, and
            # no first-registration date is available to discriminate.
            # Entries genuinely differ by edition in this fixture, so
            # this is uncertainty, not harmless multiplicity.
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                candidate_documents=candidates,
                applicability_status=ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN,
                provenance_note="More than one illustrative handbook edition's applicability window covers "
                                "this vehicle's known production year, and no first-registration date is "
                                "available to discriminate between them. Not resolved automatically.",
            )

        edition = candidates[0]
        entries = [e for e in _ALL_ENTRIES if e.applicability.document_id == edition.document_id]
        if not entries:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                candidate_documents=[edition],
                applicability_status=ApplicabilityStatus.DASHBOARD_REFERENCE_NOT_FOUND,
                provenance_note=f"Edition {edition.document_id} is applicable, but this POC ships no "
                                f"dashboard entries for it.",
            )

        return DashboardReferenceSet(
            vehicle_applicability=vehicle,
            candidate_documents=[edition],
            entries=entries,
            applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
            provenance_note=f"Resolved to a single applicable illustrative edition: {edition.document_id}.",
        )
