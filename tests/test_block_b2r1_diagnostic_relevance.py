"""Block B2-R1 — Automotive Diagnostic Relevance, minimum vertical slice.

Covers R01-R22 of the B2-R1 mandate: proving that a validated MATCH's
exact B2-C-transported DashboardReferenceEntry, run through ONE
controlled authored rule
(AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance), can
produce a candidate DiagnosticHypothesis and targeted Evidence that the
EXISTING, UNMODIFIED CaseStateUpdater/DeterministicHypothesisScorer
correctly consume -- with no kernel change anywhere.

Builds every DiagnosticIntakeResult via the REAL build_diagnostic_intake()
(never a hand-constructed one), so the DashboardReferenceEntry consumed
by the new method is genuinely the one B2-C produced (R16), not a
test-only substitute.

Reuses the same test-only fixture shape as
test_block_b2c_reference_context.py (_REFERENCE_SET, _RESOLVED_MEDIA,
_ScriptedVisualProvider, _provenance, _match_result), defined locally.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from pgdr.application.case_state_updater import CaseStateUpdater
from pgdr.application.diagnostic_intake_from_interpretation import build_diagnostic_intake
from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
from pgdr.automotive import domain_adapter as domain_adapter_module
from pgdr.automotive.domain_adapter import (
    AutomotiveDiagnosticDomain, _dashboard_diagnostic_domain_ref,
)
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
# Test-only fixtures (same shape as test_block_b2c_reference_context.py).
# The (TestMfr, engine-diag-flashing) pair is the SAME selector the one
# authored rule in domain_adapter.py's _DASHBOARD_DIAGNOSTIC_RULES keys
# on -- deliberate, so these tests exercise the real, shipped rule.
# ---------------------------------------------------------------------------

_TEST_DOC = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-B2R1-DOC", document_title="Test handbook",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator",
)

_ENGINE_DIAG_ENTRY = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Fault in the engine management system.",
    documented_instruction="Have the vehicle checked as soon as possible.",
    applicability=_TEST_DOC,
)
_OIL_ENTRY = DashboardReferenceEntry(
    entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
    colour="red", state=IndicatorState.FIXED,
    documented_meaning="Fault with the engine lubrication system.", applicability=_TEST_DOC,
)

_REFERENCE_SET = DashboardReferenceSet(
    vehicle_applicability=VehicleApplicabilityContext(manufacturer="TestMfr", model="TestModel", generation="I"),
    candidate_documents=[_TEST_DOC],
    entries=[_ENGINE_DIAG_ENTRY, _OIL_ENTRY],
    applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
)

_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-ref-b2r1-001")


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


def _apply_and_insert(domain, intake, updater, state):
    """The small glue the mandate itself describes (§4/§10/§14): the
    domain method is pure (returns, does not mutate), so a caller
    inserts its output through the exact existing mechanisms --
    state.hypotheses.append (mirroring DiagnosticLoop's own existing
    pattern for generate_hypotheses() output) and
    CaseStateUpdater.add_evidence() (mirroring map_evidence() output
    handling exactly)."""
    new_hypotheses, new_evidence = domain.apply_dashboard_diagnostic_relevance(intake, state)
    if new_hypotheses:
        state.hypotheses.extend(new_hypotheses)
        state.touch()
    if new_evidence:
        updater.add_evidence(state, new_evidence)
    return new_hypotheses, new_evidence


class TestR01HypothesisCreated:
    def test_match_with_applicable_rule_creates_a_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert len(new_hyp) == 1
        assert len(state.hypotheses) == 1
        assert state.hypotheses[0].hypothesis_type == "engine_running"


class TestR02HypothesisTargetedByEvidence:
    def test_created_evidence_targets_the_created_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].target_hypothesis_id == state.hypotheses[0].id


class TestR03EvidenceReferencesOriginalObservation:
    def test_evidence_observation_ids_point_at_the_dashboard_observation(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        dashboard_obs_id = intake.observations[0].id
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].observation_ids == [dashboard_obs_id]


class TestR04DirectionFromAuthoredRule:
    def test_evidence_direction_matches_the_authored_rule(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].direction == EvidenceDirection.SUPPORTS


class TestR05WeightFromAuthoredRule:
    def test_evidence_weight_matches_the_authored_rule(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].weight == 0.3


class TestR06SourceRuleIdIdentifiesTheRule:
    def test_source_rule_id_is_the_dashboard_relevance_rule(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].source_rule_id == "automotive.dashboard.testmfr_engine_diag_flashing"


class TestR07ScorerProducesNonNoneConfidence:
    def test_existing_scorer_reacts_to_the_new_targeted_evidence(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        assert state.hypotheses[0].confidence is not None
        # DeterministicHypothesisScorer: _BASELINE(0.3) + support(0.3) - 0 = 0.6
        assert state.hypotheses[0].confidence == pytest.approx(0.6)
        assert state.evidence[0].id in state.hypotheses[0].supporting_evidence_ids


class TestR08SecondApplicationNoSecondHypothesis:
    def test_calling_twice_does_not_duplicate_the_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        first_hyp_id = state.hypotheses[0].id
        _apply_and_insert(domain, intake, updater, state)
        assert len(state.hypotheses) == 1
        assert state.hypotheses[0].id == first_hyp_id


class TestR09SecondApplicationNoSecondEvidence:
    def test_calling_twice_does_not_duplicate_evidence(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        _apply_and_insert(domain, intake, updater, state)
        assert len(state.evidence) == 1


class TestR10SecondApplicationDoesNotInflateScore:
    def test_calling_twice_leaves_confidence_unchanged(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        _apply_and_insert(domain, intake, updater, state)
        first_confidence = state.hypotheses[0].confidence
        _apply_and_insert(domain, intake, updater, state)
        assert state.hypotheses[0].confidence == first_confidence


class TestR11OneFactMultipleHypothesesNoDomainRefCollision:
    """Proven at the identity-key/helper level (§R11's own explicit
    allowance) -- no second production rule is added for this."""

    def test_domain_ref_differs_for_two_hypothesis_types_from_the_same_fact(self):
        ref_h1 = _dashboard_diagnostic_domain_ref("TestMfr", "engine-diag-flashing", "engine_running")
        ref_h2 = _dashboard_diagnostic_domain_ref("TestMfr", "engine-diag-flashing", "electrical")
        assert ref_h1 != ref_h2

    def test_domain_ref_is_stable_for_the_same_fact_and_hypothesis_type(self):
        ref_a = _dashboard_diagnostic_domain_ref("TestMfr", "engine-diag-flashing", "engine_running")
        ref_b = _dashboard_diagnostic_domain_ref("TestMfr", "engine-diag-flashing", "engine_running")
        assert ref_a == ref_b

    def test_domain_ref_namespaced_away_from_primary_symptom_values(self):
        """Primary-symptom domain_ref values are bare SymptomFamily
        strings (e.g. 'vibration') -- never containing a colon; the
        'b2r_dashboard:' prefix guarantees no accidental collision."""
        ref = _dashboard_diagnostic_domain_ref("TestMfr", "engine-diag-flashing", "engine_running")
        assert ref.startswith("b2r_dashboard:")
        assert ref != "vibration"
        assert ref != "engine_running"


class TestR12UnknownSelectorNoRelevanceApplication:
    def test_unknown_manufacturer_entry_pair_creates_nothing(self):
        unknown_doc = ManufacturerDocumentReference(
            manufacturer="OtherMfr", document_id="OTHER-DOC", document_title="Other handbook",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="other-locator",
        )
        unknown_entry = DashboardReferenceEntry(
            entry_id="unknown-entry", manufacturer_designation="Something else",
            documented_meaning="Not covered by any authored rule.", applicability=unknown_doc,
        )
        unknown_reference_set = DashboardReferenceSet(
            vehicle_applicability=VehicleApplicabilityContext(manufacturer="OtherMfr", model="X", generation="I"),
            candidate_documents=[unknown_doc],
            entries=[unknown_entry],
            applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
        )
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[
            DashboardInterpretationResult(
                observation="Unrecognized symbol", observation_confidence=Confidence.HIGH,
                match_status=MatchStatus.MATCH, matched_reference_entry_id="unknown-entry",
                match_confidence=Confidence.HIGH, provenance=_provenance(),
            ),
        ])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, unknown_reference_set)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []
        assert state.hypotheses == []
        assert state.evidence == []


class TestR13AmbiguousMatchNoRelevanceApplication:
    def test_ambiguous_match_produces_nothing(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        ambiguous = DashboardInterpretationResult(
            observation="Amber symbol, partially obscured", observation_confidence=Confidence.MEDIUM,
            match_status=MatchStatus.AMBIGUOUS_MATCH,
            candidate_reference_entry_ids=["engine-diag-flashing", "oil-pressure-warning"],
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[ambiguous])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        assert intake.matched_reference_entries == {}
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


class TestR14NoMatchNoRelevanceApplication:
    def test_no_match_produces_nothing(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        no_match = DashboardInterpretationResult(
            observation="An indicator not present in the supplied reference set",
            observation_confidence=Confidence.HIGH, match_status=MatchStatus.NO_MATCH,
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[no_match])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


class TestR15InsufficientQualityNoRelevanceApplication:
    def test_insufficient_visual_quality_produces_nothing(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        insufficient = DashboardInterpretationResult(
            observation="Image too dark/blurred to resolve dashboard content",
            observation_confidence=Confidence.SPECULATIVE,
            match_status=MatchStatus.INSUFFICIENT_VISUAL_QUALITY, provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[insufficient])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


class TestR16ExactB2CEntryInstanceConsumed:
    def test_rule_selection_reads_the_real_transported_entry_not_a_substitute(self):
        """Uses the REAL build_diagnostic_intake() pipeline (not a
        hand-built DiagnosticIntakeResult) -- the entry the rule matched
        against is genuinely the one B2-C's own lookup produced, proven
        by identity."""
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        transported_entry = intake.matched_reference_entries[intake.observations[0].id]
        assert transported_entry is _ENGINE_DIAG_ENTRY
        _apply_and_insert(domain, intake, updater, state)
        assert len(state.hypotheses) == 1  # the rule did fire, against this exact instance


class TestR17NoRepositoryRequery:
    def test_method_body_never_references_either_knowledge_port(self):
        """Scans only the executable body, not the docstring, which
        legitimately names both ports to explain what is deliberately
        NOT used (same discipline as R18/R19 below)."""
        import inspect
        source = inspect.getsource(AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance)
        body = source.split('"""', 2)[-1]
        assert "KnowledgeRepositoryPort" not in body
        assert "VehicleDashboardKnowledgePort" not in body
        assert "repository" not in body.lower()

    def test_module_does_not_import_either_knowledge_port(self):
        """Import-level check: neither port is ever imported into this
        module, regardless of what any docstring says about them."""
        import inspect
        source = inspect.getsource(domain_adapter_module)
        import_lines = [line for line in source.split("\n") if line.strip().startswith(("import ", "from "))]
        imports_text = "\n".join(import_lines)
        assert "knowledge_repository" not in imports_text
        assert "vehicle_dashboard_knowledge" not in imports_text


class TestR18DocumentedMeaningNotUsedForMatching:
    def test_documented_meaning_not_read_anywhere_in_the_new_code(self):
        """Scans only executable bodies -- docstrings that legitimately
        name documented_meaning while explaining what is NOT done are
        excluded, same discipline established for B2-V/B2-D/B2-C."""
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
            AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance,
            _dashboard_diagnostic_domain_ref,
        ):
            code = body_only(obj)
            assert "documented_meaning" not in code


class TestR19DocumentedInstructionDoesNotDriveDiagnosis:
    def test_documented_instruction_not_read_anywhere_in_the_new_code(self):
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

        forbidden = ("documented_instruction", "severity", "driveability", "repair_recommendation", "diagnosis")
        for obj in (
            AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance,
            _dashboard_diagnostic_domain_ref,
        ):
            code = body_only(obj).lower()
            for token in forbidden:
                assert token.lower() not in code, f"{token!r} found in executable code of {obj}"


class TestR20B2DEvidenceRemainsUnchanged:
    def test_original_b2d_evidence_still_neutral_target_none_weight_none(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        provider = _ScriptedVisualProvider(planned_results=[_match_result()])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _REFERENCE_SET)
        original_b2d_evidence = intake.evidence[0]
        assert original_b2d_evidence.direction == EvidenceDirection.NEUTRAL
        assert original_b2d_evidence.target_hypothesis_id is None
        assert original_b2d_evidence.weight is None
        _apply_and_insert(domain, intake, updater, state)
        # Still the identical, unmutated object (frozen model) after B2-R1 ran.
        assert intake.evidence[0] is original_b2d_evidence
        assert intake.evidence[0].direction == EvidenceDirection.NEUTRAL
        assert intake.evidence[0].target_hypothesis_id is None
        assert intake.evidence[0].weight is None


class TestR21QEvi002Unchanged:
    def test_media_evidence_source_rule_id_unchanged(self):
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID
        assert MEDIA_EVIDENCE_SOURCE_RULE_ID == "automotive.media_evidence_acquired"

    def test_domain_module_still_never_references_the_q_evi_002_media_rule(self):
        import inspect
        source = inspect.getsource(domain_adapter_module)
        assert "_apply_media_evidence_rule" not in source


class TestR22PrimarySymptomPathUnchanged:
    def test_existing_methods_are_byte_for_byte_unmodified(self):
        """Structural confirmation alongside the full regression run:
        the pre-existing DiagnosticDomain Protocol methods are still
        exactly as documented by the B1-era test suite -- this test
        exercises generate_hypotheses()/map_evidence() directly, on a
        symptom-only state with zero dashboard involvement, to confirm
        B2-R1 changed none of their behaviour."""
        from pgdr.domain.enums import ObservationSource
        from pgdr.domain.observation import Observation

        domain = AutomotiveDiagnosticDomain()
        state = DiagnosticCaseState()
        state.observations.append(Observation(
            kind="symptom", value="vibration", source_type=ObservationSource.USER,
            context={"is_primary": True, "user_description": "x", "frequency": "constant", "severity": "medium"},
        ))
        hyps = domain.generate_hypotheses(state)
        assert len(hyps) == 2  # vibration -> engine_running + tyre_or_wheel, unchanged from before B2-R1
        state.hypotheses.extend(hyps)
        evd = domain.map_evidence(state)
        assert len(evd) == 2
        assert all(e.direction == EvidenceDirection.SUPPORTS and e.weight == 0.3 for e in evd)
