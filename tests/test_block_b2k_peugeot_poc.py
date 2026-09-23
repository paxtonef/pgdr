"""Block B2-K — Vehicle-Specific Dashboard Knowledge, Peugeot 3008 II POC.

Covers the original 12 required test categories (§23 of the B2-K
mandate) plus the Knowledge Persistence mandate's own PGDR-side
requirements (§29): repository contract, adapter-uses-repository (not a
permanent fixture), stale/superseded distinguishability, and case-data
isolation.

Uses a small in-memory KnowledgeRepositoryPort test double
(_InMemoryKnowledgeRepository) so these remain pure, fast, no-database
PGDR unit tests. The real, database-backed concrete adapter and the real
full owner-attested (not independently verified) Peugeot content (all 11 entries, transcribed from document
9999_9999_326_en-GB.pdf) live and are separately tested on the PI/CPL
persistence side -- this file's own fixture data is a small
representative subset sufficient to prove the pattern, not a duplicate
copy of the full production seed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pgdr.adapters.peugeot_dashboard_knowledge import PeugeotDashboardKnowledgeAdapter
from pgdr.domain.dashboard_knowledge import (
    ApplicabilityPeriod, ApplicabilityStatus, DashboardReferenceEntry, DashboardReferenceSet, IndicatorState,
    KnowledgeLifecycleStatus, ManufacturerDocumentReference, SourceAuthority, VehicleApplicabilityContext,
)
from pgdr.ports.knowledge_repository import KnowledgeRepositoryPort
from pgdr.ports.vehicle_dashboard_knowledge import VehicleDashboardKnowledgePort


class _InMemoryKnowledgeRepository:
    """PGDR-side test double only -- proves PeugeotDashboardKnowledgeAdapter
    genuinely depends on the injected Port. Not shipped as production
    code; the real, durable implementation lives on the PI/CPL side."""

    def __init__(self):
        self._documents: list[tuple[tuple[str, str, str], ManufacturerDocumentReference]] = []
        self._entries: dict[str, list[DashboardReferenceEntry]] = {}

    def register_document(self, manufacturer: str, model: str, generation: str,
                           document: ManufacturerDocumentReference) -> None:
        self._documents.append(((manufacturer, model, generation), document))

    def register_entries(self, document_id: str, entries: list[DashboardReferenceEntry]) -> None:
        self._entries[document_id] = entries

    def find_applicable_documents(self, vehicle: VehicleApplicabilityContext) -> list[ManufacturerDocumentReference]:
        key = (vehicle.manufacturer, vehicle.model, vehicle.generation)
        return [
            d for (k, d) in self._documents
            if k == key and d.lifecycle_status == KnowledgeLifecycleStatus.ACTIVE
        ]

    def entries_for_document(self, document_id: str) -> list[DashboardReferenceEntry]:
        return self._entries.get(document_id, [])

    def get_document_by_id(self, document_id: str):
        for (_, d) in self._documents:
            if d.document_id == document_id:
                return d
        return None


_PEUGEOT_DOC = ManufacturerDocumentReference(
    manufacturer="Peugeot", document_id="9999_9999_326_en-GB",
    document_title="MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL,
    source_locator="Peugeot Service Box, document 9999_9999_326_en-GB.pdf",
)

_OIL_PRESSURE_ENTRY = DashboardReferenceEntry(
    entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
    colour="red", state=IndicatorState.FIXED,
    documented_meaning="Fault with the engine lubrication system.",
    documented_instruction="(1) Stop the vehicle as soon as it is safe to do so and switch off the "
                            "ignition. (2) Contact a PEUGEOT dealer or a qualified workshop.",
    applicability=_PEUGEOT_DOC,
)
_ENGINE_DIAG_FIXED_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-fixed", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FIXED,
    documented_meaning="Fault in the emissions control system. The warning lamp should go off when "
                        "the engine is started.",
    documented_instruction="Go to a PEUGEOT dealer or a qualified workshop without delay.",
    applicability=_PEUGEOT_DOC,
)
_ENGINE_DIAG_FLASHING_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Fault in the engine management system. Risk of catalytic-converter destruction.",
    documented_instruction="Contact a PEUGEOT dealer or a qualified workshop.",
    applicability=_PEUGEOT_DOC,
)


def _peugeot_repository() -> _InMemoryKnowledgeRepository:
    repo = _InMemoryKnowledgeRepository()
    repo.register_document("Peugeot", "3008", "II", _PEUGEOT_DOC)
    repo.register_entries(_PEUGEOT_DOC.document_id, [
        _OIL_PRESSURE_ENTRY, _ENGINE_DIAG_FIXED_ENTRY, _ENGINE_DIAG_FLASHING_ENTRY,
    ])
    return repo


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
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        assert isinstance(adapter, VehicleDashboardKnowledgePort)
        result = adapter.get_dashboard_reference_set(_test_vehicle(first_registration_date="2020-09-15"))
        assert isinstance(result, DashboardReferenceSet)
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE

    def test_from_pgdr_vehicle_identity_dict_round_trip(self):
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
        assert vehicle.trim is None


class TestB2K02ApplicabilityUsesIdentityNotManufacturerAlone:
    def test_manufacturer_and_model_and_generation_all_required(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        r = adapter.get_dashboard_reference_set(
            _test_vehicle(generation="I", first_registration_date="2020-09-15")
        )
        assert r.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE

    def test_non_peugeot_vehicle_rejected(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        r = adapter.get_dashboard_reference_set(
            _test_vehicle(manufacturer="Renault", model="Clio", generation="V")
        )
        assert r.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE


class TestB2K03UnknownFieldsNeverInvented:
    def test_trim_variant_engine_code_stay_none(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        vehicle = _test_vehicle(first_registration_date="2020-09-15")
        result = adapter.get_dashboard_reference_set(vehicle)
        assert result.vehicle_applicability.trim is None
        assert result.vehicle_applicability.variant is None
        assert result.vehicle_applicability.engine_code is None


class TestB2K04ApplicabilityUncertaintyPreserved:
    def test_single_unbounded_document_needs_no_registration_date(self):
        """VIR -> PGDR boundary correction: with one candidate and no issue
        period (today's real Peugeot data) the date discriminates nothing and
        is not required."""
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(_test_vehicle())
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert len(result.candidate_documents) == 1
        assert result.vehicle_applicability.first_registration_date is None

    def test_a_supplied_date_does_not_change_an_undiscriminated_resolution(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert len(result.candidate_documents) == 1


class TestB2K05ZeroOneManyEntries:
    def test_insufficient_case_has_zero_entries(self):
        result = PeugeotDashboardKnowledgeAdapter(repository=_period_bound_repository()).get_dashboard_reference_set(
            _synthetic_vehicle()
        )
        assert result.entries == []

    def test_resolved_case_has_many_entries(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        assert len(result.entries) > 1


class TestB2K06ProvenancePreserved:
    def test_every_entry_traces_to_its_manufacturer_document(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        for entry in result.entries:
            assert entry.applicability.manufacturer == "Peugeot"
            assert entry.applicability.document_id
            assert entry.applicability.source_locator

    def test_verified_content_is_tagged_manufacturer_official(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        for doc in result.candidate_documents:
            assert doc.source_authority == SourceAuthority.MANUFACTURER_OFFICIAL
            assert doc.document_id == "9999_9999_326_en-GB"


class TestB2K07IndicatorStateDistinction:
    def test_fixed_and_flashing_produce_distinct_documented_meanings(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        fixed = next(e for e in result.entries if e.entry_id == "engine-diag-fixed")
        flashing = next(e for e in result.entries if e.entry_id == "engine-diag-flashing")
        assert fixed.state == IndicatorState.FIXED
        assert flashing.state == IndicatorState.FLASHING
        assert fixed.documented_meaning != flashing.documented_meaning


class TestB2K09UnsupportedVehicleGetsNoPeugeotKnowledge:
    def test_bmw_gets_no_3008_entries(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(manufacturer="BMW", model="X3", generation="G01")
        )
        assert result.entries == []
        assert result.candidate_documents == []


class TestB2K10MissingDocumentationState:
    def test_unsupported_vehicle_family_is_documentation_not_available(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(manufacturer="Peugeot", model="208", generation="II")
        )
        assert result.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE
        assert result.entries == []

    def test_production_dates_never_stand_in_for_the_registration_date(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_period_bound_repository())
        result = adapter.get_dashboard_reference_set(_synthetic_vehicle(
            production_year=2019, production_start_date="2019-06-01", production_end_date="2019-12-31",
        ))
        assert result.applicability_status == ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT
        assert result.entries == []


# ---------------------------------------------------------------------------
# VIR -> PGDR identity boundary correction, owner decision 3: the first-
# registration date is required only when it materially discriminates
# between candidate documents bounded by issue periods. SYNTHETIC documents
# only -- not manufacturer data.
# ---------------------------------------------------------------------------

def _synthetic_doc(document_id: str, start: str | None, end: str | None) -> ManufacturerDocumentReference:
    return ManufacturerDocumentReference(
        manufacturer="SynthMfr", document_id=document_id, document_title=f"Synthetic handbook {document_id}",
        applicability_period=ApplicabilityPeriod(start_date=start, end_date=end) if (start or end) else None,
        source_authority=SourceAuthority.UNVERIFIED_PLACEHOLDER, source_locator=f"synthetic://{document_id}",
    )


# Distinct, overlapping issue periods: 2019-01-01..2020-12-31 and 2020-07-01..2022-12-31.
_EDITION_EARLY = _synthetic_doc("SYNTH-EARLY", "2019-01-01", "2020-12-31")
_EDITION_LATE = _synthetic_doc("SYNTH-LATE", "2020-07-01", "2022-12-31")


def _period_bound_repository(*documents: ManufacturerDocumentReference) -> _InMemoryKnowledgeRepository:
    repo = _InMemoryKnowledgeRepository()
    for doc in documents or (_EDITION_EARLY, _EDITION_LATE):
        repo.register_document("SynthMfr", "SynthModel", "I", doc)
        repo.register_entries(doc.document_id, [DashboardReferenceEntry(
            entry_id=f"{doc.document_id}-lamp", manufacturer_designation="Synthetic lamp",
            documented_meaning="Synthetic meaning.", applicability=doc,
        )])
    return repo


def _synthetic_vehicle(**overrides) -> VehicleApplicabilityContext:
    return VehicleApplicabilityContext(**{"manufacturer": "SynthMfr", "model": "SynthModel", "generation": "I",
                                          **overrides})


class TestFirstRegistrationDateOnlyWhenItDiscriminates:
    def _resolve(self, repository, **vehicle):
        return PeugeotDashboardKnowledgeAdapter(repository=repository).get_dashboard_reference_set(
            _synthetic_vehicle(**vehicle)
        )

    def test_a_period_bound_candidates_without_a_date_fail_closed_as_identity_insufficient(self):
        result = self._resolve(_period_bound_repository())
        assert result.applicability_status == ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT
        assert {d.document_id for d in result.candidate_documents} == {"SYNTH-EARLY", "SYNTH-LATE"}
        assert result.entries == []
        assert "first-registration date" in result.provenance_note

    def test_b_a_date_inside_one_period_selects_exactly_that_document(self):
        early = self._resolve(_period_bound_repository(), first_registration_date="2019-05-10")
        assert early.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert [d.document_id for d in early.candidate_documents] == ["SYNTH-EARLY"]
        assert [e.entry_id for e in early.entries] == ["SYNTH-EARLY-lamp"]

        late = self._resolve(_period_bound_repository(), first_registration_date="2022-03-01")
        assert late.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert [d.document_id for d in late.candidate_documents] == ["SYNTH-LATE"]

    def test_b_a_date_in_the_overlap_is_not_resolved_automatically(self):
        result = self._resolve(_period_bound_repository(), first_registration_date="2020-09-15")
        assert result.applicability_status == ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN
        assert result.entries == []

    def test_b_a_date_outside_every_period_finds_no_documentation(self):
        result = self._resolve(_period_bound_repository(), first_registration_date="2024-01-01")
        assert result.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE

    def test_b_an_unreadable_date_fails_closed(self):
        result = self._resolve(_period_bound_repository(), first_registration_date="not-a-date")
        assert result.applicability_status == ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN

    def test_c_a_single_document_needs_no_date_even_when_period_bound(self):
        result = self._resolve(_period_bound_repository(_EDITION_EARLY))
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert [d.document_id for d in result.candidate_documents] == ["SYNTH-EARLY"]

    def test_c_several_documents_without_periods_need_no_date_and_stay_unresolved(self):
        repo = _period_bound_repository(_synthetic_doc("SYNTH-A", None, None), _synthetic_doc("SYNTH-B", None, None))
        result = self._resolve(repo)
        # The date could not discriminate: it is not demanded, and the
        # multiple-document ambiguity is reported as such.
        assert result.applicability_status == ApplicabilityStatus.DOCUMENT_APPLICABILITY_UNCERTAIN
        assert "More than one" in result.provenance_note

    def test_c_todays_real_shaped_peugeot_data_needs_no_date(self):
        result = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository()).get_dashboard_reference_set(
            _test_vehicle()
        )
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE


class TestB2K11NoPGDREvidenceCreated:
    def test_no_evidence_construction_anywhere_in_b2k_code(self):
        import inspect
        from pgdr.adapters import peugeot_dashboard_knowledge
        from pgdr.domain import dashboard_knowledge
        from pgdr.ports import vehicle_dashboard_knowledge, knowledge_repository

        for module in (peugeot_dashboard_knowledge, dashboard_knowledge, vehicle_dashboard_knowledge, knowledge_repository):
            source = inspect.getsource(module)
            assert "Evidence(" not in source
            assert "Observation(" not in source
            assert "_apply_media_evidence_rule" not in source


class TestB2K12NoMechanicalDiagnosis:
    def test_documented_meaning_never_states_root_cause_certainty(self):
        adapter = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        result = adapter.get_dashboard_reference_set(
            _test_vehicle(first_registration_date="2020-09-15")
        )
        forbidden_phrases = ("pump failure", "replace the", "is mechanically damaged", "faulty ")
        for entry in result.entries:
            text = f"{entry.documented_meaning} {entry.documented_instruction or ''}".lower()
            for phrase in forbidden_phrases:
                assert phrase not in text

    def test_no_image_interpretation_dependency(self):
        import inspect
        from pgdr.adapters import peugeot_dashboard_knowledge
        source = inspect.getsource(peugeot_dashboard_knowledge)
        assert "DashboardInterpretationPort" not in source
        assert "MediaResolverPort" not in source
        assert "resolve(" not in source
        assert "interpret(" not in source


# ---------------------------------------------------------------------------
# Knowledge Persistence mandate's own PGDR-side requirements (§29).
# ---------------------------------------------------------------------------

class TestB2K13KnowledgeRepositoryPortContract:
    def test_in_memory_double_satisfies_the_port_structurally(self):
        repo = _peugeot_repository()
        assert isinstance(repo, KnowledgeRepositoryPort)

    def test_find_and_entries_and_get_by_id_all_present(self):
        repo = _peugeot_repository()
        docs = repo.find_applicable_documents(_test_vehicle())
        assert len(docs) == 1
        entries = repo.entries_for_document(docs[0].document_id)
        assert len(entries) == 3
        assert repo.get_document_by_id(docs[0].document_id) is not None
        assert repo.get_document_by_id("does-not-exist") is None


class TestB2K14AdapterUsesRepositoryNotFixture:
    def test_adapter_constructor_requires_a_repository(self):
        """The adapter no longer owns a permanent fixture -- confirmed
        both by this construction requirement and by source inspection
        (no module-level ManufacturerDocumentReference/DashboardReference
        Entry constants remain in the adapter file itself)."""
        import inspect
        from pgdr.adapters import peugeot_dashboard_knowledge
        source = inspect.getsource(peugeot_dashboard_knowledge)
        assert "ManufacturerDocumentReference(" not in source
        assert "DashboardReferenceEntry(" not in source
        assert "def __init__(self, repository:" in source

    def test_different_injected_repositories_yield_different_results(self):
        """Directly proves data comes from the injected Port, not from
        anything hardcoded in the adapter: an empty repository yields no
        knowledge for the exact same vehicle a populated one resolves."""
        adapter_empty = PeugeotDashboardKnowledgeAdapter(repository=_InMemoryKnowledgeRepository())
        adapter_populated = PeugeotDashboardKnowledgeAdapter(repository=_peugeot_repository())
        vehicle = _test_vehicle(first_registration_date="2020-09-15")

        result_empty = adapter_empty.get_dashboard_reference_set(vehicle)
        result_populated = adapter_populated.get_dashboard_reference_set(vehicle)

        assert result_empty.applicability_status == ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE
        assert result_populated.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE


class TestB2K15KnowledgeFreshnessIsIndependentOfApplicability:
    """PRE-INTEGRATION REPAIR §10 A-D: freshness and applicability are
    independent axes. A document can be applicable while STALE, or while
    requiring source update/unavailable -- these are never encoded into
    ApplicabilityStatus, which stays applicability/result-only."""

    def _repo_with_freshness(self, freshness) -> _InMemoryKnowledgeRepository:
        doc = ManufacturerDocumentReference(
            manufacturer="Peugeot", document_id="FRESH-TEST-DOC", document_title="Freshness test doc",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator",
            freshness_status=freshness,
        )
        repo = _InMemoryKnowledgeRepository()
        repo.register_document("Peugeot", "3008", "II", doc)
        repo.register_entries(doc.document_id, [
            DashboardReferenceEntry(
                entry_id="test-entry", manufacturer_designation="Test indicator",
                documented_meaning="Test meaning.", applicability=doc,
            ),
        ])
        return repo

    def test_a_applicable_and_verified_current(self):
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        repo = self._repo_with_freshness(KnowledgeFreshnessStatus.VERIFIED_CURRENT)
        adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
        result = adapter.get_dashboard_reference_set(_test_vehicle(first_registration_date="2020-09-15"))
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert result.candidate_documents[0].freshness_status == KnowledgeFreshnessStatus.VERIFIED_CURRENT

    def test_b_applicable_and_stale(self):
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        repo = self._repo_with_freshness(KnowledgeFreshnessStatus.STALE)
        adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
        result = adapter.get_dashboard_reference_set(_test_vehicle(first_registration_date="2020-09-15"))
        # Applicability is unaffected by staleness -- still resolves.
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert result.candidate_documents[0].freshness_status == KnowledgeFreshnessStatus.STALE

    def test_c_applicable_and_source_update_required(self):
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        repo = self._repo_with_freshness(KnowledgeFreshnessStatus.SOURCE_UPDATE_REQUIRED)
        adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
        result = adapter.get_dashboard_reference_set(_test_vehicle(first_registration_date="2020-09-15"))
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert result.candidate_documents[0].freshness_status == KnowledgeFreshnessStatus.SOURCE_UPDATE_REQUIRED

    def test_d_applicable_and_source_unavailable(self):
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        repo = self._repo_with_freshness(KnowledgeFreshnessStatus.SOURCE_UNAVAILABLE)
        adapter = PeugeotDashboardKnowledgeAdapter(repository=repo)
        result = adapter.get_dashboard_reference_set(_test_vehicle(first_registration_date="2020-09-15"))
        assert result.applicability_status == ApplicabilityStatus.REFERENCE_SET_AVAILABLE
        assert result.candidate_documents[0].freshness_status == KnowledgeFreshnessStatus.SOURCE_UNAVAILABLE

    def test_freshness_values_are_not_present_on_applicability_status(self):
        """Structural confirmation the repair actually happened: none of
        the four freshness values exist as ApplicabilityStatus members."""
        applicability_values = {m.value for m in ApplicabilityStatus}
        assert "knowledge_stale" not in applicability_values
        assert "source_update_required" not in applicability_values
        assert "source_unavailable" not in applicability_values


class TestB2K16SupersededIsNotStale:
    """§10 E/F: SUPERSEDED (lifecycle) and STALE (freshness) are
    different axes and must never be treated as equivalent."""

    def test_e_superseded_document_remains_historically_retrievable(self):
        repo = _InMemoryKnowledgeRepository()
        old_doc = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-A", document_title="Generation A",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-a",
            lifecycle_status=KnowledgeLifecycleStatus.SUPERSEDED,
        )
        new_doc = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-B", document_title="Generation B",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-b",
            lifecycle_status=KnowledgeLifecycleStatus.ACTIVE, supersedes_document_id="TEST-DOC-A",
        )
        repo.register_document("TestMfr", "TestModel", "I", old_doc)
        repo.register_document("TestMfr", "TestModel", "I", new_doc)

        historical = repo.get_document_by_id("TEST-DOC-A")
        assert historical is not None
        assert historical.lifecycle_status == KnowledgeLifecycleStatus.SUPERSEDED

    def test_f_superseded_is_not_equivalent_to_stale(self):
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        # A SUPERSEDED document can perfectly well have been
        # VERIFIED_CURRENT at the moment it was superseded -- the two
        # axes are independent, confirmed by constructing exactly that
        # combination without any validation error or forced coupling.
        superseded_but_was_current = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-A", document_title="Generation A",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-a",
            lifecycle_status=KnowledgeLifecycleStatus.SUPERSEDED,
            freshness_status=KnowledgeFreshnessStatus.VERIFIED_CURRENT,
        )
        assert superseded_but_was_current.lifecycle_status == KnowledgeLifecycleStatus.SUPERSEDED
        assert superseded_but_was_current.freshness_status == KnowledgeFreshnessStatus.VERIFIED_CURRENT
        # And the reverse: an ACTIVE (non-superseded) document can be STALE.
        active_but_stale = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-C", document_title="Generation C",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-c",
            lifecycle_status=KnowledgeLifecycleStatus.ACTIVE,
            freshness_status=KnowledgeFreshnessStatus.STALE,
        )
        assert active_but_stale.lifecycle_status == KnowledgeLifecycleStatus.ACTIVE
        assert active_but_stale.freshness_status == KnowledgeFreshnessStatus.STALE


class TestB2K17VerifiedAtDoesNotDetermineFreshness:
    def test_g_verified_at_alone_does_not_determine_freshness_state(self):
        """§10 G: verified_at is evidence of when verification occurred,
        never itself the governed freshness decision. Two documents with
        the identical verified_at timestamp can legitimately carry
        different freshness_status values -- nothing in the domain type
        derives one from the other."""
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        same_timestamp = "2020-01-01T00:00:00+00:00"
        doc_current = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-X", document_title="Doc X",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-x",
            verified_at=same_timestamp, freshness_status=KnowledgeFreshnessStatus.VERIFIED_CURRENT,
        )
        doc_stale = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-Y", document_title="Doc Y",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-y",
            verified_at=same_timestamp, freshness_status=KnowledgeFreshnessStatus.STALE,
        )
        assert doc_current.verified_at == doc_stale.verified_at
        assert doc_current.freshness_status != doc_stale.freshness_status

    def test_default_freshness_is_owner_attested_unverified_not_verified_current(self):
        """Confirms the default value is an explicit constant, not a
        computation involving verified_at (which defaults to None here)."""
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        doc = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-Z", document_title="Doc Z",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-z",
        )
        assert doc.verified_at is None
        assert doc.freshness_status == KnowledgeFreshnessStatus.OWNER_ATTESTED_UNVERIFIED
        assert doc.freshness_status != KnowledgeFreshnessStatus.VERIFIED_CURRENT


class TestB2K18SupersededKnowledgeRemainsHistoricallyAvailable:
    def test_superseded_document_is_excluded_from_new_lookups_but_reachable_by_id(self):
        """Synthetic repository lifecycle test data (per the mandate's own
        §22 instruction) -- not fabricated Peugeot production facts."""
        repo = _InMemoryKnowledgeRepository()
        old_doc = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-A", document_title="Generation A",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-a",
            lifecycle_status=KnowledgeLifecycleStatus.SUPERSEDED,
        )
        new_doc = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-B", document_title="Generation B",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-b",
            lifecycle_status=KnowledgeLifecycleStatus.ACTIVE, supersedes_document_id="TEST-DOC-A",
        )
        repo.register_document("TestMfr", "TestModel", "I", old_doc)
        repo.register_document("TestMfr", "TestModel", "I", new_doc)

        vehicle = VehicleApplicabilityContext(manufacturer="TestMfr", model="TestModel", generation="I",
                                               first_registration_date="2021-01-01")
        current = repo.find_applicable_documents(vehicle)
        assert len(current) == 1
        assert current[0].document_id == "TEST-DOC-B"

        historical = repo.get_document_by_id("TEST-DOC-A")
        assert historical is not None
        assert historical.lifecycle_status == KnowledgeLifecycleStatus.SUPERSEDED
        assert repo.get_document_by_id("TEST-DOC-B").supersedes_document_id == "TEST-DOC-A"


class TestB2K19CaseDataCannotContaminateManufacturerKnowledge:
    def test_domain_types_have_no_case_or_execution_field(self):
        """§21: manufacturer knowledge records must contain no execution_
        id/case_id/diagnostic_id/vehicle-instance ownership field."""
        from pgdr.domain.dashboard_knowledge import DashboardReferenceEntry, ManufacturerDocumentReference
        forbidden_field_names = {"execution_id", "case_id", "diagnostic_id", "vehicle_instance_id"}
        for model in (ManufacturerDocumentReference, DashboardReferenceEntry):
            assert forbidden_field_names.isdisjoint(model.model_fields.keys())


class TestSourceVeracityCorrection:
    """B2 owner decision A(b)/C: provenance truthfulness only. A document
    never claims VERIFIED_CURRENT unless a verification is recorded, and
    the correction does not touch diagnostic eligibility semantics."""

    def test_owner_attested_unverified_is_a_distinct_freshness_state(self):
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        assert KnowledgeFreshnessStatus("owner_attested_unverified") is KnowledgeFreshnessStatus.OWNER_ATTESTED_UNVERIFIED
        assert KnowledgeFreshnessStatus.OWNER_ATTESTED_UNVERIFIED != KnowledgeFreshnessStatus.VERIFIED_CURRENT

    def test_persisted_row_value_round_trips_through_the_enum(self):
        from pgdr.domain.dashboard_knowledge import KnowledgeFreshnessStatus
        assert KnowledgeFreshnessStatus("OWNER_ATTESTED_UNVERIFIED".lower()) is KnowledgeFreshnessStatus.OWNER_ATTESTED_UNVERIFIED

    def test_freshness_is_still_never_read_by_the_diagnostic_rule_gate(self):
        """Diagnostic semantics preserved: eligibility keys on
        source_authority only; freshness_status remains unread."""
        import inspect
        from pgdr.automotive import domain_adapter
        src = inspect.getsource(domain_adapter)
        assert "entry.applicability.freshness_status" not in src
        assert "OWNER_ATTESTED_UNVERIFIED" not in src
        assert "entry.applicability.source_authority != SourceAuthority.MANUFACTURER_OFFICIAL" in src
