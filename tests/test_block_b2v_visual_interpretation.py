"""Block B2-V — Visual Interpretation + Reference Matching.

Covers T01-T13 of the B2-V EXECUTION MANDATE v0 (§14). T14, the full
existing PGDR regression, is not a unit test in this file -- it is the
full `pytest` run itself, confirmed green in the accompanying report.

Uses a test-only, deterministic scripted fake provider
(_ScriptedVisualProvider), per the mandate's own explicit §10 allowance:
"Un fake/stub déterministe est autorisé uniquement pour tester les
contrats et les invariants B2-V." No real vision provider is selected,
integrated, or simulated as if it were production-ready anywhere in this
file.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.application.interpretation_validation import (
    InterpretationValidationError, validate_against_reference_set,
)
from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceEntry, DashboardReferenceSet, IndicatorState,
    ManufacturerDocumentReference, SourceAuthority, VehicleApplicabilityContext,
)
from pgdr.domain.media import MediaType, PrimaryDiagnosticMedia
from pgdr.enums import Confidence
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationPort, DashboardInterpretationResult, InterpretationProvenance, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia


# ---------------------------------------------------------------------------
# Test-only fixtures: a small B2-K-shaped reference set (not the real
# Peugeot production seed -- a minimal, self-contained set sufficient to
# exercise every B2-V matching state), and a scripted fake provider.
# ---------------------------------------------------------------------------

_TEST_DOC = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-B2V-DOC", document_title="Test handbook",
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

_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-ref-b2v-001")


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


class TestT01ClearSingleMatch:
    def test_single_confident_match(self):
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Amber engine-shaped warning symbol, flashing",
                observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH,
                matched_reference_entry_id="engine-diag-flashing",
                match_confidence=Confidence.HIGH,
                identification="Engine self-diagnostic system",
                provenance=_provenance(),
            ),
        ])
        assert isinstance(provider, DashboardInterpretationPort)
        results = provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET)
        validated = validate_against_reference_set(results, _REFERENCE_SET)
        assert len(validated) == 1
        assert validated[0].match_status == MatchStatus.MATCH
        assert validated[0].matched_reference_entry_id == "engine-diag-flashing"


class TestT02MultipleObservationsInOneImage:
    def test_two_distinct_matches_from_one_image(self):
        """Proves interpret() is not forced into 'one image = one
        indicator' -- §9 of the mandate."""
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Red oil-can-shaped symbol", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH, matched_reference_entry_id="oil-pressure-warning",
                match_confidence=Confidence.HIGH, provenance=_provenance(),
            ),
            DashboardInterpretationResult(
                observation="Service wrench symbol, fixed", observation_confidence=Confidence.MEDIUM,
                match_status=MatchStatus.MATCH, matched_reference_entry_id="service-warning-lamp-fixed",
                match_confidence=Confidence.MEDIUM, provenance=_provenance(),
            ),
        ])
        results = validate_against_reference_set(provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET), _REFERENCE_SET)
        assert len(results) == 2
        assert {r.matched_reference_entry_id for r in results} == {"oil-pressure-warning", "service-warning-lamp-fixed"}


class TestT03AmbiguousReferenceMatch:
    def test_ambiguous_match_preserves_candidates_not_a_silent_pick(self):
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Amber symbol, partially obscured", observation_confidence=Confidence.MEDIUM,
                match_status=MatchStatus.AMBIGUOUS_MATCH,
                candidate_reference_entry_ids=["engine-diag-flashing", "service-warning-lamp-fixed"],
                provenance=_provenance(),
            ),
        ])
        results = validate_against_reference_set(provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET), _REFERENCE_SET)
        assert results[0].match_status == MatchStatus.AMBIGUOUS_MATCH
        assert results[0].matched_reference_entry_id is None  # never silently resolved (B2V-12)
        assert set(results[0].candidate_reference_entry_ids) == {"engine-diag-flashing", "service-warning-lamp-fixed"}


class TestT04NoReferenceMatch:
    def test_no_match_is_explicit_not_a_guess(self):
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="An indicator not present in the supplied reference set",
                observation_confidence=Confidence.HIGH, match_status=MatchStatus.NO_MATCH,
                provenance=_provenance(),
            ),
        ])
        results = validate_against_reference_set(provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET), _REFERENCE_SET)
        assert results[0].match_status == MatchStatus.NO_MATCH
        assert results[0].matched_reference_entry_id is None
        assert results[0].candidate_reference_entry_ids == []


class TestT05InsufficientVisualQuality:
    def test_insufficient_quality_is_explicit_not_a_positive_id(self):
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Image too dark/blurred to resolve dashboard content",
                observation_confidence=Confidence.SPECULATIVE,
                match_status=MatchStatus.INSUFFICIENT_VISUAL_QUALITY, provenance=_provenance(),
            ),
        ])
        results = validate_against_reference_set(provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET), _REFERENCE_SET)
        assert results[0].match_status == MatchStatus.INSUFFICIENT_VISUAL_QUALITY
        assert results[0].matched_reference_entry_id is None


class TestT06ObservationConfidenceVsMatchConfidence:
    def test_the_two_confidences_are_independent(self):
        """A photo can be perfectly readable (high observation_confidence)
        without the symbol being unambiguously identifiable (lower/absent
        match_confidence) -- §6 of the mandate."""
        result = DashboardInterpretationResult(
            observation="Clearly visible amber symbol, exact shape uncertain",
            observation_confidence=Confidence.HIGH,
            match_status=MatchStatus.AMBIGUOUS_MATCH,
            candidate_reference_entry_ids=["engine-diag-flashing", "service-warning-lamp-fixed"],
            match_confidence=Confidence.LOW,
            provenance=_provenance(),
        )
        assert result.observation_confidence == Confidence.HIGH
        assert result.match_confidence == Confidence.LOW
        assert result.observation_confidence != result.match_confidence


class TestT07ProviderAttemptsUnsupportedIdentificationRejected:
    def test_identification_not_matching_the_entrys_designation_is_rejected(self):
        """The provider must not supply its own free-form automotive
        meaning -- §8/§14. Here it sets `identification` to text that does
        not equal the matched entry's own manufacturer_designation."""
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Amber engine symbol, flashing", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH, matched_reference_entry_id="engine-diag-flashing",
                match_confidence=Confidence.HIGH,
                identification="probably a turbocharger fault",  # free-form, not the entry's designation
                provenance=_provenance(),
            ),
        ])
        with pytest.raises(InterpretationValidationError, match="free-form provider output"):
            validate_against_reference_set(provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET), _REFERENCE_SET)


class TestT08MatchedEntryAbsentFromReferenceSetRejected:
    def test_entry_id_not_in_supplied_reference_set_is_rejected(self):
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Some symbol", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH,
                matched_reference_entry_id="entry-id-not-in-the-supplied-set",
                match_confidence=Confidence.HIGH, provenance=_provenance(),
            ),
        ])
        with pytest.raises(InterpretationValidationError, match="not present in the supplied"):
            validate_against_reference_set(provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET), _REFERENCE_SET)

    def test_ambiguous_candidate_not_in_reference_set_is_rejected(self):
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Some symbol", observation_confidence=Confidence.MEDIUM,
                match_status=MatchStatus.AMBIGUOUS_MATCH,
                candidate_reference_entry_ids=["engine-diag-flashing", "not-a-real-entry-id"],
                provenance=_provenance(),
            ),
        ])
        with pytest.raises(InterpretationValidationError, match="not present in the supplied"):
            validate_against_reference_set(provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET), _REFERENCE_SET)


class TestT09ProviderFailureFailsClosed:
    def test_provider_exception_propagates_never_fabricates_a_result(self):
        provider = _ScriptedVisualProvider(raise_on_call=RuntimeError("simulated provider outage"))
        with pytest.raises(RuntimeError, match="simulated provider outage"):
            provider.interpret(_RESOLVED_MEDIA, _REFERENCE_SET)
        # Confirms failure is real, not swallowed into e.g. an empty
        # success list or a fabricated NO_MATCH -- the caller sees the
        # actual exception and must handle it explicitly.


class TestT10ProvenanceRetainsMediaReference:
    def test_provenance_carries_the_original_media_reference(self):
        result = DashboardInterpretationResult(
            observation="x", observation_confidence=Confidence.HIGH, match_status=MatchStatus.NO_MATCH,
            provenance=_provenance(),
        )
        assert result.provenance.media_reference == _RESOLVED_MEDIA.reference


class TestT11NoEvidenceCreated:
    def test_no_evidence_construction_anywhere_in_b2v_code(self):
        import inspect
        from pgdr.application import interpretation_validation
        from pgdr.ports import dashboard_interpretation

        for module in (interpretation_validation, dashboard_interpretation):
            source = inspect.getsource(module)
            assert "Evidence(" not in source


class TestT12NoHypothesisCreated:
    def test_no_hypothesis_or_diagnosis_construction_anywhere_in_b2v_code(self):
        """Scans only executable bodies (docstrings explicitly naming what
        is forbidden are excluded -- they legitimately mention these
        tokens, e.g. 'carries no severity, driveability, or diagnostic
        conclusion'), matching the same discipline already established
        for the B1.5 filesystem-independence test."""
        import inspect
        from pgdr.application import interpretation_validation
        from pgdr.ports import dashboard_interpretation

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

        forbidden = ("Hypothesis(", "severity", "driveability", "repair_recommendation", "diagnosis")
        for obj in (
            interpretation_validation.validate_against_reference_set,
            interpretation_validation.InterpretationValidationError,
            dashboard_interpretation.DashboardInterpretationResult,
            dashboard_interpretation.DashboardInterpretationPort,
            dashboard_interpretation.MatchStatus,
        ):
            code = body_only(obj).lower()
            for token in forbidden:
                assert token.lower() not in code, f"{token!r} found in executable code of {obj}"


class TestT13QEvi002Unchanged:
    def test_q_evi_002_not_referenced_by_new_b2v_code(self):
        import inspect
        from pgdr.application import interpretation_validation
        from pgdr.ports import dashboard_interpretation

        for module in (interpretation_validation, dashboard_interpretation):
            source = inspect.getsource(module)
            assert "_apply_media_evidence_rule" not in source
            assert "submit_answer(" not in source

    def test_media_evidence_mapper_source_rule_id_unchanged(self):
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID
        assert MEDIA_EVIDENCE_SOURCE_RULE_ID == "automotive.media_evidence_acquired"


class TestB2VSessionControllerRemainsDisconnected:
    def test_port_still_stored_but_never_invoked_by_start(self):
        """§12/§B2V-18/19/20: B2-V is not wired into SessionController or
        the DiagnosticLoop in this pass -- re-confirms the same invariant
        B1's own AC05 already established, now against the extended B2-V
        Port signature."""
        from pgdr.enums import ResolutionStatus, VehicleLocation, VehicleState
        from pgdr.models import (
            Consent, InitialComplaint, PreGarageDiagnosticRequest, UserContext, VehicleIdentityContext,
        )
        from pgdr.session_controller import SessionController

        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="should never happen", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.NO_MATCH, provenance=_provenance(),
            ),
        ])
        controller = SessionController(governance_enabled=False, dashboard_interpretation_port=provider)
        media = PrimaryDiagnosticMedia(reference="media-ref-b2v-sc-001")
        request = PreGarageDiagnosticRequest(
            request_id="b2v-sc-test",
            vehicle_identity_context=VehicleIdentityContext(
                resolution_id="VIR-b2v-sc-test", resolution_status=ResolutionStatus.PROVISIONALLY_RESOLVED,
            ),
            initial_complaint=InitialComplaint(
                free_text="", current_vehicle_location=VehicleLocation.HOME,
                vehicle_current_state=VehicleState.ENGINE_OFF,
            ),
            user_context=UserContext(),
            consent=Consent(media_analysis_allowed=True, report_storage_allowed=True),
            primary_diagnostic_media=media,
        )
        controller.start(request)
        assert provider.calls == []
