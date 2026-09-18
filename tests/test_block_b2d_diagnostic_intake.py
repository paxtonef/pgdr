"""Block B2-D — Diagnostic Intake from Validated Visual Interpretation.

Covers D01-D16 of the B2-D IMPLEMENTATION MANDATE. D17 (existing
B1/B2-K/B2-V tests remain green) is not a unit test in this file -- it
is the full `pytest` run itself, confirmed green in the accompanying
report, matching the same convention test_block_b2v_visual_interpretation.py
already established for its own T14.

Reuses the same test-only fixture shape (_REFERENCE_SET, _RESOLVED_MEDIA,
_ScriptedVisualProvider, _provenance) as test_block_b2v_visual_interpretation.py,
defined locally rather than imported, per each block's own test file
owning its fixtures.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.application import diagnostic_intake_from_interpretation as b2d_module
from pgdr.application.diagnostic_intake_from_interpretation import (
    B2D_SOURCE_RULE_ID, DiagnosticIntakeResult, build_diagnostic_intake,
)
from pgdr.application.interpretation_validation import InterpretationValidationError
from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceEntry, DashboardReferenceSet, IndicatorState,
    ManufacturerDocumentReference, SourceAuthority, VehicleApplicabilityContext,
)
from pgdr.domain.enums import EvidenceDirection, ObservationSource
from pgdr.domain.media import MediaType
from pgdr.enums import Confidence
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationResult, InterpretationProvenance, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia

# ---------------------------------------------------------------------------
# Test-only fixtures (same shape as test_block_b2v_visual_interpretation.py)
# ---------------------------------------------------------------------------

_TEST_DOC = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-B2D-DOC", document_title="Test handbook",
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

_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-ref-b2d-001")


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


class TestD01ValidatedMatchCreatesExpectedIntake:
    def test_match_produces_one_observation_and_one_evidence(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert isinstance(result, DiagnosticIntakeResult)
        assert len(result.observations) == 1
        assert len(result.evidence) == 1


class TestD02ObservationContentPreserved:
    def test_observation_value_equals_the_results_observation_text(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.observations[0].value == "Amber engine-shaped warning symbol, flashing"


class TestD03ObservationConfidencePreserved:
    def test_observation_confidence_preserved_in_context(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.observations[0].context["observation_confidence"] == Confidence.HIGH.value


class TestD04MatchedReferenceIdentityPreserved:
    def test_matched_entry_id_preserved_in_observation_context(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result("oil-pressure-warning")])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.observations[0].context["matched_reference_entry_id"] == "oil-pressure-warning"

    def test_matched_entry_identity_present_in_evidence_rationale(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result("oil-pressure-warning")])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        rationale = result.evidence[0].rationale
        assert "oil-pressure-warning" in rationale
        assert "Engine oil pressure" in rationale  # manufacturer_designation


class TestD05MatchConfidencePreserved:
    def test_match_confidence_preserved_in_context(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.observations[0].context["match_confidence"] == Confidence.HIGH.value


class TestD06PrimaryMediaProvenancePreserved:
    def test_observation_source_ref_is_the_media_reference(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.observations[0].source_ref == _RESOLVED_MEDIA.reference
        assert result.observations[0].context["media_reference"] == _RESOLVED_MEDIA.reference

    def test_observation_source_type_is_provider(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.observations[0].source_type == ObservationSource.PROVIDER


class TestD07ManufacturerKnowledgeProvenancePreserved:
    def test_document_manufacturer_and_id_present_in_evidence_rationale(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        rationale = result.evidence[0].rationale
        assert _TEST_DOC.manufacturer in rationale
        assert _TEST_DOC.document_id in rationale

    def test_vehicle_applicability_present_in_observation_context(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.observations[0].context["vehicle_applicability"]["manufacturer"] == "TestMfr"


class TestD08MultipleMatchesProduceMultipleIntakeItems:
    def test_two_matches_from_one_image_produce_two_observations_and_two_evidence(self):
        provider = _ScriptedVisualProvider(planned_results=[
            _match_result("oil-pressure-warning"),
            _match_result("service-warning-lamp-fixed"),
        ])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(result.observations) == 2
        assert len(result.evidence) == 2
        assert {o.context["matched_reference_entry_id"] for o in result.observations} == {
            "oil-pressure-warning", "service-warning-lamp-fixed",
        }

    def test_evidence_is_not_collapsed_into_one_synthetic_observation(self):
        """§9: distinct signals from one photograph must not be merged."""
        provider = _ScriptedVisualProvider(planned_results=[
            _match_result("oil-pressure-warning"),
            _match_result("engine-diag-flashing"),
        ])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len({o.id for o in result.observations}) == 2
        assert len({e.id for e in result.evidence}) == 2


class TestD09AmbiguousMatchNeverSilentlyBecomesMatch:
    def test_ambiguous_match_produces_no_evidence(self):
        ambiguous = DashboardInterpretationResult(
            observation="Amber symbol, partially obscured", observation_confidence=Confidence.MEDIUM,
            match_status=MatchStatus.AMBIGUOUS_MATCH,
            candidate_reference_entry_ids=["engine-diag-flashing", "service-warning-lamp-fixed"],
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[ambiguous])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(result.observations) == 1
        assert len(result.evidence) == 0

    def test_ambiguous_candidates_preserved_in_observation_context_not_fabricated_as_certain(self):
        ambiguous = DashboardInterpretationResult(
            observation="Amber symbol, partially obscured", observation_confidence=Confidence.MEDIUM,
            match_status=MatchStatus.AMBIGUOUS_MATCH,
            candidate_reference_entry_ids=["engine-diag-flashing", "service-warning-lamp-fixed"],
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[ambiguous])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        ctx = result.observations[0].context
        assert ctx["match_status"] == MatchStatus.AMBIGUOUS_MATCH.value
        assert ctx["matched_reference_entry_id"] is None
        assert set(ctx["candidate_reference_entry_ids"]) == {"engine-diag-flashing", "service-warning-lamp-fixed"}


class TestD10NoMatchCannotCreateManufacturerIdentifiedEvidence:
    def test_no_match_produces_no_evidence(self):
        no_match = DashboardInterpretationResult(
            observation="An indicator not present in the supplied reference set",
            observation_confidence=Confidence.HIGH, match_status=MatchStatus.NO_MATCH,
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[no_match])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(result.observations) == 1
        assert len(result.evidence) == 0


class TestD11InsufficientQualityCannotCreateManufacturerIdentifiedEvidence:
    def test_insufficient_visual_quality_produces_no_evidence(self):
        insufficient = DashboardInterpretationResult(
            observation="Image too dark/blurred to resolve dashboard content",
            observation_confidence=Confidence.SPECULATIVE,
            match_status=MatchStatus.INSUFFICIENT_VISUAL_QUALITY, provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[insufficient])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(result.observations) == 1
        assert len(result.evidence) == 0


class TestD12RawProviderOutputCannotBypassGovernedValidation:
    def test_unknown_matched_entry_id_still_raises_through_the_b2d_api(self):
        """Proves B2-D's own public entrypoint does not weaken or skip
        B2-V's governed validation -- an out-of-reference-set match still
        fails closed even when reached via build_diagnostic_intake."""
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

    def test_build_diagnostic_intake_always_calls_the_governed_boundary(self, monkeypatch):
        """Spies on run_governed_interpretation (monkeypatched at module
        level, where build_diagnostic_intake's bare-name call resolves
        it) -- proves there is no path from (provider, media,
        reference_set) to a DiagnosticIntakeResult that skips it."""
        calls = []
        original = b2d_module.run_governed_interpretation

        def spy(provider, media, reference_set):
            calls.append((provider, media, reference_set))
            return original(provider, media, reference_set)

        monkeypatch.setattr(b2d_module, "run_governed_interpretation", spy)

        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        b2d_module.build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert len(calls) == 1

    def test_build_diagnostic_intake_has_no_parameter_accepting_raw_results_directly(self):
        """Static confirmation: the public entrypoint's signature is
        (provider, media, reference_set) -- structurally, there is no
        argument through which a caller could hand it an already-built
        list[DashboardInterpretationResult] and skip the provider.interpret()
        + validation sequence entirely."""
        import inspect

        params = list(inspect.signature(build_diagnostic_intake).parameters)
        assert params == ["provider", "media", "reference_set"]


class TestD13NoHypothesisCreated:
    def test_no_hypothesis_construction_anywhere_in_b2d_code(self):
        import inspect
        source = inspect.getsource(b2d_module)
        assert "DiagnosticHypothesis(" not in source
        assert "Hypothesis(" not in source


class TestD14NoDiagnosisCreated:
    def test_no_diagnosis_construction_anywhere_in_b2d_code(self):
        import inspect
        source = inspect.getsource(b2d_module)
        assert "Diagnosis(" not in source


class TestD15NoRecommendationCreated:
    def test_no_severity_driveability_or_repair_recommendation_in_executable_code(self):
        """Scans only executable bodies -- docstrings that legitimately
        name what is forbidden (e.g. 'determines no severity or
        driveability') are excluded, matching the same discipline the
        B2-V T12 test already established."""
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

        forbidden = ("severity", "driveability", "repair_recommendation", "action_recommendation", "diagnosis")
        for obj in (
            b2d_module.build_diagnostic_intake,
            b2d_module._diagnostic_intake_from_validated_results,
            b2d_module._observation_from_result,
            b2d_module._evidence_from_match,
            b2d_module.DiagnosticIntakeResult,
        ):
            code = body_only(obj).lower()
            for token in forbidden:
                assert token.lower() not in code, f"{token!r} found in executable code of {obj}"


class TestD16QEvi002Unchanged:
    def test_b2d_source_rule_id_distinct_from_q_evi_002_rule_id(self):
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID
        assert MEDIA_EVIDENCE_SOURCE_RULE_ID == "automotive.media_evidence_acquired"
        assert B2D_SOURCE_RULE_ID != MEDIA_EVIDENCE_SOURCE_RULE_ID

    def test_b2d_module_never_references_the_q_evi_002_media_rule(self):
        """Checks the module never IMPORTS or CALLS the Q-EVI-002 media
        rule function -- not a literal-string scan across the whole
        source, since this module's own docstring legitimately mentions
        MEDIA_EVIDENCE_SOURCE_RULE_ID by name to document the
        separation (a docstring naming what is forbidden is not itself
        a violation, per the same discipline test_block_b2v_visual_interpretation.py's
        T12 already established)."""
        import inspect
        source = inspect.getsource(b2d_module)
        assert "_apply_media_evidence_rule" not in source
        assert "from pgdr.automotive.evidence_mapper import" not in source

    def test_produced_evidence_never_uses_the_q_evi_002_source_rule_id(self):
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID

        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.evidence[0].source_rule_id == B2D_SOURCE_RULE_ID
        assert result.evidence[0].source_rule_id != MEDIA_EVIDENCE_SOURCE_RULE_ID


class TestB2DEvidenceIsNeutralAndUnlinked:
    """Not an explicitly-numbered D-test, but directly supports D09/§4/§10:
    confirms B2-D's Evidence never asserts a direction or targets a
    hypothesis -- both would be diagnostic reasoning, outside B2-D's
    authority."""

    def test_evidence_direction_is_neutral_and_untargeted(self):
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        result = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert result.evidence[0].direction == EvidenceDirection.NEUTRAL
        assert result.evidence[0].target_hypothesis_id is None


class TestB2DSessionControllerAndDiagnosticLoopUntouched:
    """§12: this block does not wire B2-D into SessionController or the
    DiagnosticLoop -- confirms the module simply doesn't import them."""

    def test_b2d_module_does_not_import_session_controller_or_diagnostic_loop(self):
        import inspect
        source = inspect.getsource(b2d_module)
        assert "session_controller" not in source.lower()
        assert "diagnostic_loop" not in source.lower()
