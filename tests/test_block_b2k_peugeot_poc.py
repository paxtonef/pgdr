"""Block B2-K — Vehicle-Specific Dashboard Knowledge, Peugeot 3008 II POC.

Covers the 12 required test categories (§23 of the B2-K mandate).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pgdr.adapters.peugeot_dashboard_knowledge import PeugeotDashboardKnowledgeAdapter
from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceSet, IndicatorState, VehicleApplicabilityContext,
)
from pgdr.ports.vehicle_dashboard_knowledge import VehicleDashboardKnowledgePort


def _test_vehicle(**overrides) -> VehicleApplicabilityContext:
    base = dict(
        manufacturer="Peugeot", model="3008", generation="II", production_year=2020,
        fuel_primary_type="diesel", engine_commercial_name="BlueHDi 130", engine_displacement_cc=1499,
        engine_power_kw=96, transmission_type="automatic", transmission_gears=8,
        drivetrain="front-wheel drive",
    )
    base.update(overrides)
    return VehicleApplicabilityContext(**base)


class TestB2K01PortReachable:
    def test_compatible_peugeot_3008_identity_reaches_the_port(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        assert isinstance(adapter, VehicleDashboardKnowledgePort)
        result = adapter.get_dashboard_reference_set(_test_vehicle(first_registration_date="2020-09-15"))
        assert isinstance(result, DashboardReferenceSet)
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE

    def test_from_pgdr_vehicle_identity_dict_round_trip(self):
        """Confirms the adapter's own input can be built from exactly the
        dict shape PGDR's real VehicleIdentityContext.vehicle_identity
        carries (per handoff_mapper.py::map_resolution's model_dump)."""
        raw = {
            "manufacturer": "Peugeot", "model": "3008", "generation": "II",
            "production": {"year": 2020, "start_date": None, "end_date": None},
            "fuel": {"primary_type": "diesel"},
            "engine": {"commercial_name": "BlueHDi 130", "engine_code": None,
                       "displacement_cc": 1499, "power_kw": 96},
            "transmission": {"type": "automatic", "gears": 8},
            "drivetrain": "front-wheel drive", "trim": None, "variant": None,
        }
        vehicle = VehicleApplicabilityContext.from_pgdr_vehicle_identity_dict(raw)
        assert vehicle.manufacturer == "Peugeot"
        assert vehicle.production_year == 2020
        assert vehicle.engine_commercial_name == "BlueHDi 130"
        assert vehicle.trim is None
        assert vehicle.variant is None
        assert vehicle.engine_code is None


class TestB2K02ApplicabilityUsesIdentityNotManufacturerAlone:
    def test_manufacturer_and_model_and_generation_all_required(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        # right manufacturer + model, wrong generation
        r = adapter.get_dashboard_reference_set(
            _test_vehicle(generation="I", first_registration_date="2020-09-15")
        )
        assert r.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE

    def test_non_peugeot_vehicle_rejected(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        r = adapter.get_dashboard_reference_set(
            _test_vehicle(manufacturer="Renault", model="Clio", generation="V")
        )
        assert r.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE


class TestB2K03UnknownFieldsNeverInvented:
    def test_trim_variant_engine_code_stay_none(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        vehicle = _test_vehicle(first_registration_date="2020-09-15")
        assert vehicle.trim is None
        assert vehicle.variant is None
        assert vehicle.engine_code is None
        result = adapter.get_dashboard_reference_set(vehicle)
        # the result's own echoed vehicle_applicability must not have
        # invented values either
        assert result.vehicle_applicability.trim is None
        assert result.vehicle_applicability.variant is None
        assert result.vehicle_applicability.engine_code is None


class TestB2K04ApplicabilityUncertaintyPreserved:
    def test_2020_production_year_alone_is_uncertain_not_guessed(self):
        """The exact scenario the mandate calls out by name: production
        year 2020 alone straddles both illustrative editions; no
        first-registration date is available to discriminate. Must NOT
        silently pick one."""
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(_test_vehicle())  # no first_registration_date
        assert result.applicability_status == ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN
        assert len(result.candidate_documents) == 2
        assert result.entries == []  # no entries returned while uncertain -- never guessed

    def test_first_registration_date_resolves_the_same_ambiguity(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert len(result.candidate_documents) == 1


class TestB2K05ZeroOneManyEntries:
    def test_uncertain_case_has_zero_entries(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(_test_vehicle())
        assert result.entries == []

    def test_resolved_case_has_many_entries(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        assert len(result.entries) > 1


class TestB2K06ProvenancePreserved:
    def test_every_entry_traces_to_its_manufacturer_document(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        for entry in result.entries:
            assert entry.applicability.manufacturer == "Peugeot"
            assert entry.applicability.document_id
            assert entry.applicability.source_locator

    def test_placeholder_source_authority_is_never_claimed_official(self):
        """§8/§14 of the B2-K mandate: this POC's own fixture must never
        claim to be verified manufacturer-official content, since no real
        source was actually consulted."""
        from pgdr.domain.dashboard_knowledge import SourceAuthority
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        for doc in result.candidate_documents:
            assert doc.source_authority == SourceAuthority.UNVERIFIED_PLACEHOLDER


class TestB2K07IndicatorStateDistinction:
    def test_fixed_and_flashing_produce_distinct_documented_meanings(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        fixed = next(e for e in result.entries if e.entry_id == "engine-diag-fixed")
        flashing = next(e for e in result.entries if e.entry_id == "engine-diag-flashing")
        assert fixed.state == IndicatorState.FIXED
        assert flashing.state == IndicatorState.FLASHING
        assert fixed.documented_meaning != flashing.documented_meaning
        assert fixed.documented_instruction != flashing.documented_instruction


class TestB2K08MultiSignalPattern:
    def test_scr_warning_and_range_message_reference_each_other(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        warning = next(e for e in result.entries if e.entry_id == "scr-additive-level-warning")
        message = next(e for e in result.entries if e.entry_id == "scr-range-countdown-message")
        assert message.entry_id in warning.combined_with_entry_ids
        assert warning.entry_id in message.combined_with_entry_ids


class TestB2K09UnsupportedVehicleGetsNoPeugeotKnowledge:
    def test_bmw_gets_no_3008_entries(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(manufacturer="BMW", model="X3", generation="G01")
        )
        assert result.entries == []
        assert result.candidate_documents == []


class TestB2K10MissingDocumentationState:
    def test_year_outside_all_known_windows_is_explicit(self):
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(_test_vehicle(production_year=2035))
        assert result.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE
        assert result.entries == []


class TestB2K11NoPGDREvidenceCreated:
    def test_no_evidence_construction_anywhere_in_b2k_code(self):
        import inspect
        from pgdr.adapters import peugeot_dashboard_knowledge
        from pgdr.domain import dashboard_knowledge
        from pgdr.ports import vehicle_dashboard_knowledge

        for module in (peugeot_dashboard_knowledge, dashboard_knowledge, vehicle_dashboard_knowledge):
            source = inspect.getsource(module)
            assert "Evidence(" not in source
            assert "Observation(" not in source
            assert "_apply_media_evidence_rule" not in source


class TestB2K12NoMechanicalDiagnosis:
    def test_documented_meaning_never_states_root_cause_certainty(self):
        """A weak but concrete structural proxy: the fixture's own
        documented_meaning/documented_instruction strings describe
        symptoms/warnings, never a definitive component-failure
        conclusion -- confirmed by the absence of common diagnosis-only
        phrasing this fixture was deliberately NOT written to contain."""
        adapter = PeugeotDashboardKnowledgeAdapter()
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        forbidden_phrases = ("pump failure", "replace the", "is mechanically damaged", "faulty ")
        for entry in result.entries:
            text = f"{entry.documented_meaning} {entry.documented_instruction or ''}".lower()
            for phrase in forbidden_phrases:
                assert phrase not in text

    def test_no_image_interpretation_dependency(self):
        """B2-K must not import or invoke DashboardInterpretationPort or
        MediaResolverPort -- that is B2-V's concern, not B2-K's."""
        import inspect
        from pgdr.adapters import peugeot_dashboard_knowledge
        source = inspect.getsource(peugeot_dashboard_knowledge)
        assert "DashboardInterpretationPort" not in source
        assert "MediaResolverPort" not in source
        assert "resolve(" not in source
        assert "interpret(" not in source
