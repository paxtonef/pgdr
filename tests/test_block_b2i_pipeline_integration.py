"""Block B2-I — Diagnostic Pipeline Integration.

Covers I01-I18 of the B2-I mandate, plus the additional required tests
in §16 (atomicity, duplicate-invocation behaviour, source-object
immutability, fail-closed provider failure, no fabricated Hypothesis).

Reuses the same test-only fixture shape as
test_block_b2d_diagnostic_intake.py (_REFERENCE_SET, _RESOLVED_MEDIA,
_ScriptedVisualProvider, _provenance, _match_result), defined locally.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.application import diagnostic_intake_ingestion as b2i_module
from pgdr.application.case_state_updater import CaseStateUpdater
from pgdr.application.diagnostic_intake_ingestion import ingest_dashboard_interpretation
from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
from pgdr.application.interpretation_validation import InterpretationValidationError
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceEntry, DashboardReferenceSet, IndicatorState,
    ManufacturerDocumentReference, SourceAuthority, VehicleApplicabilityContext,
)
from pgdr.domain.enums import EvidenceDirection
from pgdr.domain.media import MediaType
from pgdr.enums import Confidence
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationResult, InterpretationProvenance, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia

# ---------------------------------------------------------------------------
# Test-only fixtures (same shape as test_block_b2d_diagnostic_intake.py)
# ---------------------------------------------------------------------------

_TEST_DOC = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-B2I-DOC", document_title="Test handbook",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator",
)

_OIL_ENTRY = DashboardReferenceEntry(
    entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
    colour="red", state=IndicatorState.FIXED,
    documented_meaning="Fault with the engine lubrication system.", applicability=_TEST_DOC,
)
_ENGINE_DIAG_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Fault in the engine management system.", applicability=_TEST_DOC,
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

_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-ref-b2i-001")


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


def _fresh_updater_and_state() -> tuple[CaseStateUpdater, DiagnosticCaseState]:
    return CaseStateUpdater(DeterministicHypothesisScorer()), DiagnosticCaseState()


class TestI01GovernedMatchTravelsIntoCaseState:
    def test_match_result_reaches_case_state(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.observations) == 1
        assert len(state.evidence) == 1


class TestI02ObservationStoredExactlyOnce:
    def test_single_match_yields_exactly_one_observation(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.observations) == 1


class TestI03EvidenceStoredExactlyOnce:
    def test_single_match_yields_exactly_one_evidence(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.evidence) == 1


class TestI04ObservationEvidenceRelationshipPreserved:
    def test_evidence_observation_ids_points_at_the_stored_observation(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.evidence[0].observation_ids == [state.observations[0].id]


class TestI05NeutralDirectionPreserved:
    def test_evidence_direction_is_neutral_in_case_state(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.evidence[0].direction == EvidenceDirection.NEUTRAL


class TestI06NoneTargetHypothesisPreserved:
    def test_target_hypothesis_id_stays_none_in_case_state(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.evidence[0].target_hypothesis_id is None


class TestI07NoneWeightPreserved:
    def test_weight_stays_none_in_case_state(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.evidence[0].weight is None


class TestI08MediaProvenanceSurvivesIngestion:
    def test_source_ref_and_context_media_reference_survive(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        obs = state.observations[0]
        assert obs.source_ref == _RESOLVED_MEDIA.reference
        assert obs.context["media_reference"] == _RESOLVED_MEDIA.reference


class TestI09B2KProvenanceSurvivesIngestion:
    def test_manufacturer_document_reference_survives_in_evidence_rationale(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        rationale = state.evidence[0].rationale
        assert _TEST_DOC.manufacturer in rationale
        assert _TEST_DOC.document_id in rationale

    def test_vehicle_applicability_survives_in_observation_context(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.observations[0].context["vehicle_applicability"]["manufacturer"] == "TestMfr"


class TestI10MultiplicityPreserved:
    def test_two_matches_remain_two_observations_and_two_evidence_in_case_state(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[
            _match_result("oil-pressure-warning"),
            _match_result("service-warning-lamp-fixed"),
        ])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.observations) == 2
        assert len(state.evidence) == 2


class TestI11AmbiguousMatchRemainsUnresolved:
    def test_ambiguous_match_stored_as_observation_only_no_evidence(self):
        updater, state = _fresh_updater_and_state()
        ambiguous = DashboardInterpretationResult(
            observation="Amber symbol, partially obscured", observation_confidence=Confidence.MEDIUM,
            match_status=MatchStatus.AMBIGUOUS_MATCH,
            candidate_reference_entry_ids=["engine-diag-flashing", "service-warning-lamp-fixed"],
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[ambiguous])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.observations) == 1
        assert len(state.evidence) == 0
        assert state.observations[0].context["match_status"] == MatchStatus.AMBIGUOUS_MATCH.value


class TestI12NoMatchAcquiresNoEvidence:
    def test_no_match_stored_without_evidence_in_case_state(self):
        updater, state = _fresh_updater_and_state()
        no_match = DashboardInterpretationResult(
            observation="An indicator not present in the supplied reference set",
            observation_confidence=Confidence.HIGH, match_status=MatchStatus.NO_MATCH,
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[no_match])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.observations) == 1
        assert len(state.evidence) == 0


class TestI13InsufficientQualityAcquiresNoEvidence:
    def test_insufficient_visual_quality_stored_without_evidence_in_case_state(self):
        updater, state = _fresh_updater_and_state()
        insufficient = DashboardInterpretationResult(
            observation="Image too dark/blurred to resolve dashboard content",
            observation_confidence=Confidence.SPECULATIVE,
            match_status=MatchStatus.INSUFFICIENT_VISUAL_QUALITY, provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[insufficient])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.observations) == 1
        assert len(state.evidence) == 0


class TestI14RawProviderOutputCannotEnterCaseStateThroughIntegrationAPI:
    def test_unknown_matched_entry_still_raises_and_leaves_state_untouched(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Some symbol", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH,
                matched_reference_entry_id="entry-id-not-in-the-supplied-set",
                match_confidence=Confidence.HIGH, provenance=_provenance(),
            ),
        ])
        with pytest.raises(InterpretationValidationError, match="not present in the supplied"):
            ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.observations == []
        assert state.evidence == []

    def test_integration_entrypoint_has_no_parameter_accepting_raw_results_or_intake_directly(self):
        """Static confirmation: the signature is (provider, media,
        reference_set, updater, state) -- no argument accepts a bare
        list[DashboardInterpretationResult] or a pre-built
        DiagnosticIntakeResult, so there is no way to skip the governed
        B2-V/B2-D chain via this entrypoint's parameters."""
        import inspect
        params = list(inspect.signature(ingest_dashboard_interpretation).parameters)
        assert params == ["provider", "media", "reference_set", "updater", "state"]


class TestI15B2VBypassImpossible:
    def test_run_governed_interpretation_is_reached_via_b2d_from_this_entrypoint(self, monkeypatch):
        """Spies on B2-D's own imported reference to run_governed_interpretation
        (monkeypatched where diagnostic_intake_from_interpretation's
        bare-name call resolves it) to prove B2-I's entrypoint cannot
        reach case state without that call happening."""
        from pgdr.application import diagnostic_intake_from_interpretation as b2d_module

        calls = []
        original = b2d_module.run_governed_interpretation

        def spy(provider, media, reference_set):
            calls.append((provider, media, reference_set))
            return original(provider, media, reference_set)

        monkeypatch.setattr(b2d_module, "run_governed_interpretation", spy)

        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(calls) == 1


class TestI16B2DBypassImpossible:
    def test_build_diagnostic_intake_is_always_called_by_this_entrypoint(self, monkeypatch):
        calls = []
        original = b2i_module.build_diagnostic_intake

        def spy(provider, media, reference_set):
            calls.append((provider, media, reference_set))
            return original(provider, media, reference_set)

        monkeypatch.setattr(b2i_module, "build_diagnostic_intake", spy)

        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(calls) == 1


class TestI17QEvi002Unchanged:
    def test_b2i_module_never_references_the_q_evi_002_media_rule(self):
        import inspect
        source = inspect.getsource(b2i_module)
        assert "_apply_media_evidence_rule" not in source
        assert "from pgdr.automotive.evidence_mapper import" not in source

    def test_media_evidence_source_rule_id_unchanged(self):
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID
        assert MEDIA_EVIDENCE_SOURCE_RULE_ID == "automotive.media_evidence_acquired"


class TestI18NoSeparateDiagnosticEngineIntroduced:
    def test_b2i_module_creates_no_hypothesis_and_imports_no_diagnostic_loop_or_session_controller(self):
        import inspect
        source = inspect.getsource(b2i_module)
        assert "DiagnosticHypothesis(" not in source
        assert "Hypothesis(" not in source
        assert "session_controller" not in source.lower()
        assert "diagnostic_loop" not in source.lower()


# ---------------------------------------------------------------------------
# Additional required tests (mandate §16)
# ---------------------------------------------------------------------------


class TestInsertionFailureIsAtomic:
    def test_a_failing_ingestion_leaves_case_state_completely_untouched(self):
        """Same evidence as I14's first test, named for the atomicity
        requirement specifically: build_diagnostic_intake() runs to
        completion (including B2-V validation) BEFORE either
        CaseStateUpdater call, so a failure there leaves state exactly
        as it started."""
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Some symbol", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH,
                matched_reference_entry_id="entry-id-not-in-the-supplied-set",
                match_confidence=Confidence.HIGH, provenance=_provenance(),
            ),
        ])
        with pytest.raises(InterpretationValidationError):
            ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.observations == []
        assert state.evidence == []
        assert state.iteration == 0


class TestDuplicateInvocationBehaviour:
    def test_duplicate_invocation_currently_duplicates_state_no_existing_idempotency(self):
        """INVESTIGATION FINDING (mandate §16): CaseStateUpdater has no
        id-based deduplication, so calling the integration entrypoint
        twice (even with results describing the 'same' dashboard event)
        appends twice. This documents existing, unmodified
        CaseStateUpdater behaviour -- B2-I does not add deduplication
        logic that was not already there, per the mandate's own change-
        minimization instruction (§19)."""
        updater, state = _fresh_updater_and_state()
        provider_a = _ScriptedVisualProvider(planned_results=[_match_result()])
        provider_b = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider_a, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        ingest_dashboard_interpretation(provider_b, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert len(state.observations) == 2
        assert len(state.evidence) == 2
        # Distinct ids -- CaseStateUpdater does not collapse them.
        assert len({o.id for o in state.observations}) == 2
        assert len({e.id for e in state.evidence}) == 2


class TestDownstreamFailureDoesNotMutateSourceObjects:
    def test_intake_objects_are_frozen_and_unchanged_after_ingestion(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        observation = intake.observations[0]
        evidence = intake.evidence[0]
        with pytest.raises(Exception):  # pydantic frozen model -> ValidationError on attempted mutation
            observation.value = "tampered"
        with pytest.raises(Exception):
            evidence.weight = 0.9
        # Still the exact same objects stored in case state (identity, not just equality).
        assert state.observations[0] is observation
        assert state.evidence[0] is evidence


class TestProviderFailureRemainsFailClosedUpstream:
    def test_provider_exception_propagates_and_leaves_state_untouched(self):
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(raise_on_call=RuntimeError("simulated provider outage"))
        with pytest.raises(RuntimeError, match="simulated provider outage"):
            ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.observations == []
        assert state.evidence == []


class TestNoHypothesisFabricatedByIntegrationAdapter:
    def test_hypotheses_list_remains_empty_after_ingestion(self):
        """state.hypotheses is untouched by ingestion -- confirms, at
        the case-state level (not just source-scan), that B2-I performs
        no diagnostic reasoning of its own."""
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        ingest_dashboard_interpretation(provider, _RESOLVED_MEDIA, _REFERENCE_SET, updater, state)
        assert state.hypotheses == []
