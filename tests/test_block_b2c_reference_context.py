"""Block B2-C — Exact Manufacturer Reference Context Transport.

Covers C01-C22 of the B2-C mandate: proving that
DiagnosticIntakeResult.matched_reference_entries carries the EXACT
(same-instance, frozen) DashboardReferenceEntry used by B2-V/B2-D for
every MATCH result, with no repository re-query, no reconstruction, and
no new semantic representation -- while every prior B2-D/B2-I/B2-V
guarantee remains untouched.

Reuses the same test-only fixture shape as
test_block_b2d_diagnostic_intake.py (_REFERENCE_SET, _RESOLVED_MEDIA,
_ScriptedVisualProvider, _provenance, _match_result), defined locally.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.application import diagnostic_intake_from_interpretation as b2d_module
from pgdr.application.diagnostic_intake_from_interpretation import (
    DiagnosticIntakeResult, build_diagnostic_intake,
)
from pgdr.application.interpretation_validation import InterpretationValidationError
from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceEntry, DashboardReferenceSet, IndicatorState,
    KnowledgeFreshnessStatus, KnowledgeLifecycleStatus, ManufacturerDocumentReference, SourceAuthority,
    VehicleApplicabilityContext,
)
from pgdr.domain.media import MediaType
from pgdr.enums import Confidence
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationResult, InterpretationProvenance, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia

# ---------------------------------------------------------------------------
# Test-only fixtures (same shape as test_block_b2d_diagnostic_intake.py),
# with explicit lifecycle/freshness/source_authority values so C07-C09 can
# assert on something other than defaults.
# ---------------------------------------------------------------------------

_TEST_DOC = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-B2C-DOC", document_title="Test handbook",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator",
    lifecycle_status=KnowledgeLifecycleStatus.ACTIVE,
    freshness_status=KnowledgeFreshnessStatus.VERIFIED_CURRENT,
)

_OIL_ENTRY = DashboardReferenceEntry(
    entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
    colour="red", state=IndicatorState.FIXED,
    documented_meaning="Fault with the engine lubrication system.",
    documented_instruction="Stop the vehicle safely and check the oil level.",
    applicability=_TEST_DOC,
)
_ENGINE_DIAG_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Fault in the engine management system.",
    documented_instruction="Have the vehicle checked as soon as possible.",
    applicability=_TEST_DOC,
)
_SERVICE_ENTRY = DashboardReferenceEntry(
    entry_id="service-warning-lamp-fixed", manufacturer_designation="Service warning lamp",
    state=IndicatorState.FIXED, documented_meaning="Combined-pattern lamp.", applicability=_TEST_DOC,
)

_REFERENCE_SET = DashboardReferenceSet(
    vehicle_applicability=VehicleApplicabilityContext(manufacturer="TestMfr", model="TestModel", generation="I"),
    candidate_documents=[_TEST_DOC],
    entries=[_OIL_ENTRY, _ENGINE_DIAG_ENTRY, _SERVICE_ENTRY],
    applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
)

_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-ref-b2c-001")


class _ScriptedVisualProvider:
    """Test-only deterministic fake -- not a production provider."""

    def __init__(self, planned_results=None, raise_on_call=None):
        self._planned_results = planned_results if planned_results is not None else []
        self._raise_on_call = raise_on_call
        self.calls = []

    def interpret(self, media: ResolvedMedia, reference_set: DashboardReferenceSet) -> list[DashboardInterpretationResult]:
        self.calls.append((media, reference_set))
        if self._raise_on_call is not None:
            raise self._raise_on_call
        return self._planned_results


def _provenance() -> InterpretationProvenance:
    return InterpretationProvenance(adapter_id="scripted-test-provider", media_reference=_RESOLVED_MEDIA.reference)


def _match_result(entry_id: str = "engine-diag-flashing") -> DashboardInterpretationResult:
    return DashboardInterpretationResult(
        observation="Amber engine-shaped warning symbol, flashing",
        observation_confidence=Confidence.HIGH,
        match_status=MatchStatus.MATCH,
        matched_reference_entry_id=entry_id,
        match_confidence=Confidence.HIGH,
        provenance=_provenance(),
    )


class TestC01ExactEntryRetainedForMatch:
    def test_matched_reference_entries_has_one_entry_for_a_match(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(result.matched_reference_entries) == 1

    def test_entry_is_reachable_by_the_observations_own_id(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert obs_id in result.matched_reference_entries
        assert result.matched_reference_entries[obs_id].entry_id == "engine-diag-flashing"


class TestC02NotReconstructedFromFields:
    def test_transported_entry_is_the_identical_object_from_the_reference_set(self):
        """Identity (is), not merely equality (==) -- proves no
        reconstruction, no copy, the exact same frozen instance from
        _REFERENCE_SET.entries flows through."""
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        transported = result.matched_reference_entries[obs_id]
        assert transported is _ENGINE_DIAG_ENTRY


class TestC03DocumentedMeaningAvailable:
    def test_documented_meaning_readable_from_the_transported_entry(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert result.matched_reference_entries[obs_id].documented_meaning == (
            "Fault in the engine management system."
        )


class TestC04DocumentedInstructionAvailable:
    def test_documented_instruction_readable_from_the_transported_entry(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert result.matched_reference_entries[obs_id].documented_instruction == (
            "Have the vehicle checked as soon as possible."
        )


class TestC05ManufacturerDocumentReferenceAvailable:
    def test_applicability_is_the_identical_document_object(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert result.matched_reference_entries[obs_id].applicability is _TEST_DOC


class TestC06DocumentIdStructured:
    def test_document_id_readable_structurally_not_via_rationale_text(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert result.matched_reference_entries[obs_id].applicability.document_id == "TEST-B2C-DOC"


class TestC07SourceAuthorityPreserved:
    def test_source_authority_readable_from_transported_document(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert result.matched_reference_entries[obs_id].applicability.source_authority == (
            SourceAuthority.MANUFACTURER_OFFICIAL
        )


class TestC08LifecyclePreserved:
    def test_lifecycle_status_readable_from_transported_document(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert result.matched_reference_entries[obs_id].applicability.lifecycle_status == (
            KnowledgeLifecycleStatus.ACTIVE
        )


class TestC09FreshnessPreserved:
    def test_freshness_status_readable_from_transported_document(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert result.matched_reference_entries[obs_id].applicability.freshness_status == (
            KnowledgeFreshnessStatus.VERIFIED_CURRENT
        )


class TestC10NoRepositoryRequery:
    def test_b2d_module_imports_neither_knowledge_port(self):
        import inspect
        source = inspect.getsource(b2d_module)
        assert "KnowledgeRepositoryPort" not in source
        assert "VehicleDashboardKnowledgePort" not in source

    def test_lookup_helper_only_reads_the_supplied_reference_set_object(self):
        """Static confirmation that _matched_entry_for_result's only data
        source is the reference_set parameter already passed in -- no
        repository, no port, no I/O. Scans only the executable body, not
        the docstring, which legitimately names 'repository' to explain
        what is deliberately NOT done (same discipline as C17 below)."""
        import inspect
        source = inspect.getsource(b2d_module._matched_entry_for_result)
        body = source.split('"""', 2)[-1]  # drop the def line + docstring
        assert "repository" not in body.lower()
        assert "port" not in body.lower()
        assert "reference_set.entries" in body


class TestC11MultipleMatchesRetainOwnEntries:
    def test_two_matches_map_to_two_distinct_correct_entries(self):
        provider = _ScriptedVisualProvider(planned_results=[
            _match_result("oil-pressure-warning"),
            _match_result("service-warning-lamp-fixed"),
        ])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(result.matched_reference_entries) == 2
        by_entry_id = {e.entry_id: obs_id for obs_id, e in result.matched_reference_entries.items()}
        assert set(by_entry_id) == {"oil-pressure-warning", "service-warning-lamp-fixed"}
        # Each is the identical fixture object, not a mix-up or a copy.
        oil_obs_id = next(oid for oid, e in result.matched_reference_entries.items() if e.entry_id == "oil-pressure-warning")
        service_obs_id = next(oid for oid, e in result.matched_reference_entries.items() if e.entry_id == "service-warning-lamp-fixed")
        assert result.matched_reference_entries[oil_obs_id] is _OIL_ENTRY
        assert result.matched_reference_entries[service_obs_id] is _SERVICE_ENTRY

    def test_no_collapsing_into_one_global_reference(self):
        """§9: result 1 -> entry A, result 2 -> entry B must both survive
        distinctly, keyed by their own observation, not merged."""
        provider = _ScriptedVisualProvider(planned_results=[
            _match_result("oil-pressure-warning"),
            _match_result("engine-diag-flashing"),
        ])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(result.observations) == 2
        assert len(result.matched_reference_entries) == 2
        assert len({id(e) for e in result.matched_reference_entries.values()}) == 2


class TestC12AmbiguousMatchNotResolved:
    def test_ambiguous_match_has_no_entry_in_matched_reference_entries(self):
        ambiguous = DashboardInterpretationResult(
            observation="Amber symbol, partially obscured", observation_confidence=Confidence.MEDIUM,
            match_status=MatchStatus.AMBIGUOUS_MATCH,
            candidate_reference_entry_ids=["engine-diag-flashing", "service-warning-lamp-fixed"],
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[ambiguous])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.matched_reference_entries == {}
        # Candidate identity is still preserved, exactly as before B2-C --
        # just not as a resolved DashboardReferenceEntry.
        assert set(result.observations[0].context["candidate_reference_entry_ids"]) == {
            "engine-diag-flashing", "service-warning-lamp-fixed",
        }


class TestC13NoMatchHasNoEntry:
    def test_no_match_has_no_entry_in_matched_reference_entries(self):
        no_match = DashboardInterpretationResult(
            observation="An indicator not present in the supplied reference set",
            observation_confidence=Confidence.HIGH, match_status=MatchStatus.NO_MATCH,
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[no_match])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.matched_reference_entries == {}


class TestC14InsufficientQualityHasNoEntry:
    def test_insufficient_visual_quality_has_no_entry_in_matched_reference_entries(self):
        insufficient = DashboardInterpretationResult(
            observation="Image too dark/blurred to resolve dashboard content",
            observation_confidence=Confidence.SPECULATIVE,
            match_status=MatchStatus.INSUFFICIENT_VISUAL_QUALITY, provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[insufficient])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.matched_reference_entries == {}


class TestC15EvidenceRemainsNeutralUnlinkedUnweighted:
    def test_match_evidence_semantics_unchanged_by_b2c(self):
        from pgdr.domain.enums import EvidenceDirection

        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.evidence[0].direction == EvidenceDirection.NEUTRAL
        assert result.evidence[0].target_hypothesis_id is None
        assert result.evidence[0].weight is None


class TestC16NoHypothesisCreated:
    def test_no_hypothesis_construction_anywhere_in_b2d_code(self):
        import inspect
        source = inspect.getsource(b2d_module)
        assert "DiagnosticHypothesis(" not in source
        assert "Hypothesis(" not in source


class TestC17NoDiagnosticRelevanceDecisionMade:
    def test_lookup_helper_does_not_read_documented_meaning_or_instruction(self):
        """B2-D/B2-C transport the entry; they must not themselves read
        documented_meaning/documented_instruction to make any decision --
        confirmed by scanning the actual conversion logic (not the
        module's own explanatory docstrings, which legitimately name
        these fields when describing what is deliberately NOT
        interpreted)."""
        import inspect

        def body_only(obj) -> str:
            source = inspect.getsource(obj)
            lines = source.split("\n")
            out, in_docstring = [], False
            for line in lines:
                stripped = line.strip()
                if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
                    if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                        continue
                    in_docstring = True
                    continue
                if in_docstring:
                    if '"""' in line or "'''" in line:
                        in_docstring = False
                    continue
                out.append(line)
            return "\n".join(out)

        for obj in (
            b2d_module._matched_entry_for_result,
            b2d_module._diagnostic_intake_from_validated_results,
            b2d_module.build_diagnostic_intake,
        ):
            code = body_only(obj)
            assert "documented_meaning" not in code
            assert "documented_instruction" not in code


class TestC18NoDiagnosticDirectionOrWeightAssigned:
    def test_evidence_weight_and_direction_not_derived_from_matched_entry(self):
        """Same evidence as C15, named for this specific property: the
        Evidence's direction/weight are hardcoded constants in
        _evidence_from_match, never computed from matched_entry's
        content."""
        import inspect
        source = inspect.getsource(b2d_module._evidence_from_match)
        assert "direction=EvidenceDirection.NEUTRAL" in source
        assert "weight=None" in source


class TestC19NoNewManufacturerSemanticRepresentation:
    def test_no_forbidden_duplicate_carrier_type_exists(self):
        import inspect
        source = inspect.getsource(b2d_module)
        for forbidden in ("ManufacturerSemanticSnapshot", "DashboardMeaning", "DiagnosticDashboardReference"):
            assert forbidden not in source

    def test_matched_reference_entries_values_are_the_real_domain_type(self):
        """The dict's value type is the actual, unmodified
        DashboardReferenceEntry -- not a new class wrapping it."""
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        obs_id = result.observations[0].id
        assert type(result.matched_reference_entries[obs_id]) is DashboardReferenceEntry


class TestC20B2VValidationRemainsUnavoidable:
    def test_unknown_matched_entry_id_still_raises_through_b2d(self):
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Some symbol", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH,
                matched_reference_entry_id="entry-id-not-in-the-supplied-set",
                match_confidence=Confidence.HIGH, provenance=_provenance(),
            ),
        ])
        with pytest.raises(InterpretationValidationError, match="not present in the supplied"):
            build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)


class TestC21B2DBoundaryRemainsUnavoidable:
    def test_build_diagnostic_intake_signature_unchanged(self):
        """Static confirmation: B2-C did not widen B2-D's own public
        entrypoint signature -- still (provider, media, reference_set),
        no new parameter through which a caller could inject a
        pre-built matched_reference_entries dict directly."""
        import inspect
        params = list(inspect.signature(build_diagnostic_intake).parameters)
        assert params == ["provider", "media", "reference_set"]


class TestC22QEvi002Unchanged:
    def test_media_evidence_source_rule_id_unchanged(self):
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID
        assert MEDIA_EVIDENCE_SOURCE_RULE_ID == "automotive.media_evidence_acquired"

    def test_b2d_module_still_never_references_the_q_evi_002_media_rule(self):
        import inspect
        source = inspect.getsource(b2d_module)
        assert "_apply_media_evidence_rule" not in source


class TestB2IAlreadyCarriesTheNewFieldWithNoCodeChange:
    """Not a numbered C-test, but directly supports B2-C's own §11 claim
    that B2-I needs no code change: confirms the field survives all the
    way through ingest_dashboard_interpretation() into what the caller
    receives back."""

    def test_ingest_returns_intake_with_matched_reference_entries_populated(self):
        from pgdr.application.case_state_updater import CaseStateUpdater
        from pgdr.application.diagnostic_intake_ingestion import ingest_dashboard_interpretation
        from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
        from pgdr.domain.analytical_state import DiagnosticCaseState

        updater = CaseStateUpdater(DeterministicHypothesisScorer())
        state = DiagnosticCaseState()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert isinstance(intake, DiagnosticIntakeResult)
        obs_id = intake.observations[0].id
        assert intake.matched_reference_entries[obs_id] is _ENGINE_DIAG_ENTRY
