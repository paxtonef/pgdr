"""Block B2-K — Peugeot 3008 II POC adapter.

Implements pgdr.ports.vehicle_dashboard_knowledge.VehicleDashboardKnowledgePort
for a single, narrow test case: Peugeot 3008, generation II.

======================================================================
PROVENANCE NOTICE (correction pass -- content now verified)
======================================================================
The five entries below (and their sub-states) were originally shipped as
UNVERIFIED_PLACEHOLDER content, disclosed as such, because this execution
environment has no web access tool and could not retrieve or verify the
authorized Peugeot source on its own.

The content below has since been supplied directly by the person running
this mandate, sourced from the official Peugeot document identified below.
It is transcribed here as closely and literally as the supplied excerpt
allows -- no meaning, instruction, state, message, or applicability
boundary beyond what was explicitly supplied has been added, generalized,
or guessed. Any field the supplied source did not specify for a given
entry is left None, not filled in with plausible-sounding text.

DOCUMENT:
  Title: MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK
  Official source: Peugeot Service Box
  Document file identifier: 9999_9999_326_en-GB.pdf
  Vehicle family: Peugeot 3008 / 5008
  Language: en-GB

APPLICABILITY RULE (as stated by Peugeot in the supplied source): handbook
issue-period applicability must correspond to the vehicle's date of first
registration. The supplied source does NOT establish an exact,
independently-verifiable first-registration date range that this specific
document edition covers. No such range is fabricated here (per the
mandate's own explicit instruction). Consequently this adapter can only
resolve applicability to REFERENCE_SET_AVAILABLE when the vehicle's own
first_registration_date is actually known -- production year alone is not
treated as sufficient, since Peugeot's own stated rule ties edition
selection to first registration, not production year.
"""
from __future__ import annotations

from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceEntry, DashboardReferenceSet,
    IndicatorState, ManufacturerDocumentReference, SourceAuthority,
    VehicleApplicabilityContext,
)

# ---------------------------------------------------------------------------
# The single authorized source document. No applicability_period is set --
# the supplied source states the general first-registration rule but does
# not give this specific document's own date boundary, so none is invented.
# ---------------------------------------------------------------------------

_PEUGEOT_HANDBOOK = ManufacturerDocumentReference(
    manufacturer="Peugeot",
    document_id="9999_9999_326_en-GB",
    document_title="MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK",
    edition=None,
    applicability_period=None,
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL,
    source_locator="Peugeot Service Box, document 9999_9999_326_en-GB.pdf",
)

# ---------------------------------------------------------------------------
# Entry 1 -- oil-pressure-warning
# ---------------------------------------------------------------------------

_OIL_PRESSURE_ENTRY = DashboardReferenceEntry(
    entry_id="oil-pressure-warning",
    manufacturer_designation="Engine oil pressure",
    symbol_descriptor=None,
    colour="red",
    state=IndicatorState.FIXED,
    displayed_message=None,
    audible_signal=None,
    documented_meaning="Fault with the engine lubrication system.",
    documented_instruction=(
        "(1) Stop the vehicle as soon as it is safe to do so and switch off the ignition. "
        "(2) Contact a PEUGEOT dealer or a qualified workshop."
    ),
    applicability=_PEUGEOT_HANDBOOK,
)

# ---------------------------------------------------------------------------
# Entries 2 & 3 -- engine self-diagnostic system, flashing vs fixed
# ---------------------------------------------------------------------------

_ENGINE_DIAG_FLASHING_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-flashing",
    manufacturer_designation="Engine self-diagnostic system",
    symbol_descriptor=None,
    colour="orange",
    state=IndicatorState.FLASHING,
    displayed_message=None,
    audible_signal=None,
    documented_meaning="Fault in the engine management system. Risk of catalytic-converter destruction.",
    documented_instruction="Contact a PEUGEOT dealer or a qualified workshop.",
    applicability=_PEUGEOT_HANDBOOK,
)

_ENGINE_DIAG_FIXED_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-fixed",
    manufacturer_designation="Engine self-diagnostic system",
    symbol_descriptor=None,
    colour="orange",
    state=IndicatorState.FIXED,
    displayed_message=None,
    audible_signal=None,
    documented_meaning="Fault in the emissions control system. The warning lamp should go off when "
                        "the engine is started.",
    documented_instruction="Go to a PEUGEOT dealer or a qualified workshop without delay.",
    applicability=_PEUGEOT_HANDBOOK,
)

# ---------------------------------------------------------------------------
# Entry 4 -- AdBlue (BlueHDi): four distinct documented states, deliberately
# NOT collapsed into one entry.
# ---------------------------------------------------------------------------

_ADBLUE_STATE_A_ENTRY = DashboardReferenceEntry(
    entry_id="adblue-level-state-a",
    manufacturer_designation="AdBlue\u00ae (BlueHDi)",
    symbol_descriptor="Illuminates for approximately 30 seconds when starting",
    colour="orange",
    state=None,
    displayed_message="Driving-range message: 1,500\u2013500 miles (2,400\u2013800 km) remaining",
    audible_signal=None,
    documented_meaning="AdBlue\u00ae driving-range warning: 1,500\u2013500 miles (2,400\u2013800 km) of range remaining.",
    documented_instruction="Top up AdBlue\u00ae.",
    applicability=_PEUGEOT_HANDBOOK,
)

_ADBLUE_STATE_B_ENTRY = DashboardReferenceEntry(
    entry_id="adblue-level-state-b",
    manufacturer_designation="AdBlue\u00ae (BlueHDi)",
    symbol_descriptor=None,
    colour="orange",
    state=IndicatorState.FIXED,
    displayed_message="Driving-range message: 500\u201362 miles (800\u2013100 km) remaining",
    audible_signal="Yes (further detail not specified in the supplied source)",
    documented_meaning="AdBlue\u00ae driving-range warning: 500\u201362 miles (800\u2013100 km) of range remaining.",
    documented_instruction="Promptly top up AdBlue\u00ae, or go to a PEUGEOT dealer or a qualified workshop.",
    applicability=_PEUGEOT_HANDBOOK,
)

_ADBLUE_STATE_C_ENTRY = DashboardReferenceEntry(
    entry_id="adblue-level-state-c",
    manufacturer_designation="AdBlue\u00ae (BlueHDi)",
    symbol_descriptor=None,
    colour="orange",
    state=IndicatorState.FLASHING,
    displayed_message="Driving-range message: less than 62 miles (100 km) remaining",
    audible_signal="Yes (further detail not specified in the supplied source)",
    documented_meaning="Risk that engine starting will be prevented.",
    documented_instruction="Top up AdBlue\u00ae to avoid engine starting being prevented, or go to a "
                            "PEUGEOT dealer or a qualified workshop.",
    applicability=_PEUGEOT_HANDBOOK,
)

_ADBLUE_STATE_D_ENTRY = DashboardReferenceEntry(
    entry_id="adblue-level-state-d",
    manufacturer_designation="AdBlue\u00ae (BlueHDi)",
    symbol_descriptor=None,
    colour="orange",
    state=IndicatorState.FLASHING,
    displayed_message="Message indicating that starting is prevented (exact wording not specified in "
                       "the supplied source for this state)",
    audible_signal="Yes (further detail not specified in the supplied source)",
    documented_meaning="AdBlue\u00ae tank empty. The legally required engine immobiliser prevents "
                        "engine starting.",
    documented_instruction="Top up AdBlue\u00ae (at least 5 litres) or contact a PEUGEOT dealer or a "
                            "qualified workshop.",
    applicability=_PEUGEOT_HANDBOOK,
)

_ALL_ADBLUE_ENTRIES = [_ADBLUE_STATE_A_ENTRY, _ADBLUE_STATE_B_ENTRY, _ADBLUE_STATE_C_ENTRY, _ADBLUE_STATE_D_ENTRY]

# ---------------------------------------------------------------------------
# Entry 5 -- SCR emissions-control-system malfunction: composite pattern
# across three escalating phases plus a standalone "Service" lamp.
# ---------------------------------------------------------------------------

_SERVICE_WARNING_LAMP_ENTRY = DashboardReferenceEntry(
    entry_id="service-warning-lamp-fixed",
    manufacturer_designation="Service warning lamp",
    symbol_descriptor=None,
    colour=None,
    state=IndicatorState.FIXED,
    displayed_message=None,
    audible_signal=None,
    documented_meaning="Documented only as part of the confirmed SCR emissions-control-system "
                        "malfunction combination (see combined_with_entry_ids); the supplied source "
                        "gives this lamp no independent standalone meaning.",
    documented_instruction=None,
    applicability=_PEUGEOT_HANDBOOK,
    combined_with_entry_ids=["scr-malfunction-confirmed-countdown"],
)

_SCR_MALFUNCTION_DETECTED_ENTRY = DashboardReferenceEntry(
    entry_id="scr-malfunction-detected",
    manufacturer_designation="SCR emissions control system (BlueHDi)",
    symbol_descriptor=None,
    colour=None,
    state=IndicatorState.FIXED,
    displayed_message=None,
    audible_signal="Yes (further detail not specified in the supplied source)",
    documented_meaning="SCR emissions-control-system malfunction detected. An audible signal and a "
                        "display message are documented for this state; the supplied source does not "
                        "include the exact message wording for this initial phase. The alert disappears "
                        "if exhaust emissions return to normal.",
    documented_instruction=None,
    applicability=_PEUGEOT_HANDBOOK,
    combined_with_entry_ids=["scr-malfunction-confirmed-countdown"],
)

_SCR_MALFUNCTION_CONFIRMED_COUNTDOWN_ENTRY = DashboardReferenceEntry(
    entry_id="scr-malfunction-confirmed-countdown",
    manufacturer_designation="SCR emissions control system (BlueHDi) -- confirmed malfunction",
    symbol_descriptor="Combination: AdBlue\u00ae warning lamp flashing, together with the Service warning "
                       "lamp and Engine self-diagnostics warning lamp both fixed",
    colour=None,
    state=None,
    displayed_message="Emissions control fault: starting prevented in X miles (kms)",
    audible_signal="Yes",
    documented_meaning=(
        "Confirmed SCR emissions-control-system malfunction, reached after the initial fault "
        "indication has remained permanently displayed for 31 miles / 50 km of driving. Up to "
        "685 miles / 1,100 km may remain before engine immobilisation, counting down from that point."
    ),
    documented_instruction="Have the vehicle checked by a PEUGEOT dealer or qualified workshop without "
                            "delay to avoid starting being prevented.",
    applicability=_PEUGEOT_HANDBOOK,
    combined_with_entry_ids=["service-warning-lamp-fixed", "engine-diag-fixed",
                              "scr-malfunction-detected", "scr-starting-prevented"],
)

_SCR_STARTING_PREVENTED_ENTRY = DashboardReferenceEntry(
    entry_id="scr-starting-prevented",
    manufacturer_designation="SCR emissions control system (BlueHDi) -- starting prevented",
    symbol_descriptor=None,
    colour=None,
    state=None,
    displayed_message="Emissions control fault: Starting prevented",
    audible_signal=None,
    documented_meaning="Starting prevention has been activated.",
    documented_instruction="Contact a PEUGEOT dealer or a qualified workshop.",
    applicability=_PEUGEOT_HANDBOOK,
    combined_with_entry_ids=["scr-malfunction-confirmed-countdown"],
)

_ALL_SCR_ENTRIES = [
    _SERVICE_WARNING_LAMP_ENTRY, _SCR_MALFUNCTION_DETECTED_ENTRY,
    _SCR_MALFUNCTION_CONFIRMED_COUNTDOWN_ENTRY, _SCR_STARTING_PREVENTED_ENTRY,
]

_ALL_ENTRIES = [
    _OIL_PRESSURE_ENTRY, _ENGINE_DIAG_FIXED_ENTRY, _ENGINE_DIAG_FLASHING_ENTRY,
    *_ALL_ADBLUE_ENTRIES, *_ALL_SCR_ENTRIES,
]


class PeugeotDashboardKnowledgeAdapter:
    """Implements VehicleDashboardKnowledgePort structurally (confirmed via
    isinstance() against the real Port in the B2-K test suite -- no
    inheritance required)."""

    def get_dashboard_reference_set(self, vehicle: VehicleApplicabilityContext) -> DashboardReferenceSet:
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

        if vehicle.first_registration_date is None:
            return DashboardReferenceSet(
                vehicle_applicability=vehicle,
                candidate_documents=[_PEUGEOT_HANDBOOK],
                applicability_status=ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN,
                provenance_note="Peugeot's own documentation states that handbook issue-period "
                                "applicability corresponds to the vehicle's first-registration date. "
                                "That date is not known for this vehicle, and the supplied source does "
                                "not establish this document's own applicability boundary independently "
                                "of it -- production year alone is not sufficient to confirm "
                                "applicability. Not resolved automatically.",
            )

        return DashboardReferenceSet(
            vehicle_applicability=vehicle,
            candidate_documents=[_PEUGEOT_HANDBOOK],
            entries=_ALL_ENTRIES,
            applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
            provenance_note=f"Resolved to the single known applicable document: "
                             f"{_PEUGEOT_HANDBOOK.document_id}, based on the supplied "
                             f"first-registration date.",
        )
