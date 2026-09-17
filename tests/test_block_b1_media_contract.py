"""Block B1 — PGDR_BLOCK_B1_PRIMARY_DIAGNOSTIC_MEDIA_CONTRACT_v0.

Covers B1-AC01, B1-AC02, B1-AC03, B1-AC04, B1-AC05 (the PGDR-side
acceptance tests). B1-AC06/07/08 are covered on the PI side.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pgdr.domain.media import DiagnosticMediaRole, MediaType, PrimaryDiagnosticMedia
from pgdr.enums import Confidence, ResolutionStatus, VehicleLocation, VehicleState
from pgdr.models import (
    Consent, InitialComplaint, PreGarageDiagnosticRequest, UserContext,
    VehicleIdentityContext,
)
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationPort, DashboardInterpretationResult, InterpretationProvenance, MatchStatus,
)
from pgdr.session_controller import SessionController


def _make_request(request_id: str, media: PrimaryDiagnosticMedia | None = None) -> PreGarageDiagnosticRequest:
    return PreGarageDiagnosticRequest(
        request_id=request_id,
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=f"VIR-{request_id}", resolution_status=ResolutionStatus.PROVISIONALLY_RESOLVED,
        ),
        initial_complaint=InitialComplaint(
            free_text="", current_vehicle_location=VehicleLocation.HOME,
            vehicle_current_state=VehicleState.ENGINE_OFF,
        ),
        user_context=UserContext(),
        consent=Consent(media_analysis_allowed=True, report_storage_allowed=True),
        primary_diagnostic_media=media,
    )


class TestB1AC01TypedMediaInputExists:
    def test_pregarage_request_accepts_primary_diagnostic_media(self):
        """B1-AC01: PGDR can receive Primary Diagnostic Media through its
        canonical diagnostic input contract (PreGarageDiagnosticRequest)."""
        media = PrimaryDiagnosticMedia(reference="media-ref-ac01")
        request = _make_request("AC01", media=media)
        assert request.primary_diagnostic_media is media
        assert request.primary_diagnostic_media.reference == "media-ref-ac01"
        assert request.primary_diagnostic_media.role == DiagnosticMediaRole.PRIMARY_DIAGNOSTIC_MEDIA
        assert request.primary_diagnostic_media.media_type == MediaType.IMAGE

    def test_field_is_optional_and_defaults_to_none(self):
        """The existing text-only request shape remains valid without
        supplying any media."""
        request = _make_request("AC01B")
        assert request.primary_diagnostic_media is None


class TestB1AC02MediaIsNotEvidence:
    def test_media_alone_creates_no_evidence_observation_or_confidence(self):
        """B1-AC02: receiving Primary Diagnostic Media does not itself
        create Evidence, Observation, Identification, or Confidence --
        confirmed by running a real session with media supplied and
        checking that nothing in the resulting case state is attributable
        to the media (no observation sourced from it, no evidence
        referencing it). This is deliberately NOT an assertion that
        case_state.evidence/observations are empty overall: PGDR's
        pre-existing complaint-classification pipeline produces its own
        baseline observation/evidence from the complaint text alone
        (confirmed here even for an empty string, via the existing
        'unknown' symptom-family fallback) -- unrelated to B1 and out of
        this block's scope to change."""
        controller = SessionController(governance_enabled=False)
        media = PrimaryDiagnosticMedia(reference="media-ref-ac02")
        request = _make_request("AC02", media=media)
        session = controller.start(request)

        case_state = controller._case_states.get(session.session_id)
        if case_state is not None:
            for observation in case_state.observations:
                assert observation.source_ref != media.reference
                assert "media" not in (observation.kind or "").lower()
            for evidence in case_state.evidence:
                assert media.reference not in (evidence.rationale or "")
                assert (evidence.source_rule_id or "") != "automotive.media_evidence_acquired"


class TestB1AC03NoQEvi002Dependency:
    def test_primary_media_ingestion_does_not_reference_q_evi_002(self):
        """B1-AC03: Primary media ingestion does not invoke or depend upon
        Q-EVI-002."""
        import inspect
        from pgdr import models, session_controller
        from pgdr.domain import media as media_module

        for source in (
            inspect.getsource(media_module),
            inspect.getsource(models.PreGarageDiagnosticRequest),
            inspect.getsource(session_controller.SessionController.__init__),
        ):
            assert "Q-EVI-002" not in source or "LEGACY_MEDIA_SEMANTICS_TO_ALIGN" in source
            assert "_apply_media_evidence_rule" not in source

    def test_media_evidence_mapper_untouched(self):
        """Q-EVI-002's existing NEUTRAL-evidence behaviour is unchanged
        and unrelated to the new media model."""
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID
        assert MEDIA_EVIDENCE_SOURCE_RULE_ID == "automotive.media_evidence_acquired"


class TestB1AC04InterpretationPortContractExists:
    def test_port_and_result_types_exist_and_are_typed(self):
        """B1-AC04: a typed Dashboard Interpretation Port exists with a
        typed interpretation-result contract. Updated for the B2-V
        extension (observation_confidence/match_status are now required;
        confidence/identification remain as optional B1-era compat
        fields)."""
        from pgdr.ports.dashboard_interpretation import MatchStatus
        assert hasattr(DashboardInterpretationPort, "interpret")
        result = DashboardInterpretationResult(
            observation="yellow engine-shaped dashboard symbol",
            observation_confidence=Confidence.HIGH,
            match_status=MatchStatus.MATCH,
            matched_reference_entry_id="engine-diag-flashing",
            match_confidence=Confidence.HIGH,
            identification="engine management warning",
            confidence=Confidence.HIGH,
            provenance=InterpretationProvenance(media_reference="media-ref-ac04"),
        )
        assert result.observation
        assert result.confidence == Confidence.HIGH
        assert result.provenance.media_reference == "media-ref-ac04"

    def test_result_is_not_evidence(self):
        """§8: DashboardInterpretationResult != Evidence."""
        from pgdr.domain.evidence import Evidence
        assert DashboardInterpretationResult is not Evidence
        assert not issubclass(DashboardInterpretationResult, Evidence)

    def test_port_is_runtime_checkable_protocol(self):
        """A concrete adapter can be structurally verified against the
        Port without inheriting from it -- matching the existing
        ports/diagnostic_domain.py convention exactly. Updated for the
        B2-V signature: interpret(media: ResolvedMedia, reference_set:
        DashboardReferenceSet) -> list[DashboardInterpretationResult]."""
        from pgdr.domain.dashboard_knowledge import DashboardReferenceSet, ApplicabilityStatus, VehicleApplicabilityContext
        from pgdr.ports.dashboard_interpretation import MatchStatus
        from pgdr.ports.media_resolver import ResolvedMedia
        from pgdr.domain.media import MediaType as _MediaType

        class _FakeAdapter:
            def interpret(self, media: ResolvedMedia, reference_set: DashboardReferenceSet) -> list[DashboardInterpretationResult]:
                return [DashboardInterpretationResult(
                    observation="x", observation_confidence=Confidence.SPECULATIVE,
                    match_status=MatchStatus.NO_MATCH,
                    provenance=InterpretationProvenance(media_reference=media.reference),
                )]
        assert isinstance(_FakeAdapter(), DashboardInterpretationPort)


class TestB1AC05NoInterpretationExecuted:
    def test_starting_with_media_never_invokes_the_port(self):
        """B1-AC05: starting a diagnostic with Primary Diagnostic Media
        does not invoke a real vision provider or generate an
        interpretation under B1 -- confirmed by injecting a spy Port and
        asserting it is never called."""
        calls = []

        class _SpyPort:
            def interpret(self, media, reference_set) -> list[DashboardInterpretationResult]:
                calls.append(media)
                return [DashboardInterpretationResult(
                    observation="should never happen", observation_confidence=Confidence.HIGH,
                    match_status=MatchStatus.NO_MATCH, confidence=Confidence.HIGH,
                    provenance=InterpretationProvenance(media_reference=media.reference),
                )]

        controller = SessionController(governance_enabled=False, dashboard_interpretation_port=_SpyPort())
        media = PrimaryDiagnosticMedia(reference="media-ref-ac05")
        request = _make_request("AC05", media=media)
        controller.start(request)

        assert calls == [], "DashboardInterpretationPort.interpret() was invoked -- B1 must not execute interpretation"

    def test_port_reference_is_stored_but_inert(self):
        class _SpyPort:
            def interpret(self, media):
                raise AssertionError("must never be called in B1")

        port = _SpyPort()
        controller = SessionController(governance_enabled=False, dashboard_interpretation_port=port)
        assert controller._dashboard_interpretation_port is port
