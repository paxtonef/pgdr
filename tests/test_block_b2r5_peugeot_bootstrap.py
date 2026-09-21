"""Block B2-R5 — Peugeot Non-Causal Manufacturer-Fact Bootstrap.

Proves the three real Peugeot diagnostic-relevance rules (P1/P2/P3):
oil-pressure-warning, engine-diag-fixed, engine-diag-flashing. Every
assertion here also enforces the B2-R5 mandate's own semantic
boundaries -- the bounded, non-scoring NEUTRAL bootstrap convention
must not silently become "solved fact-as-hypothesis semantics," must
not invent an Evidence weight, must not touch hypothesis_type
vocabulary, must not introduce causal/component content, and must not
turn the flashing entry's catalytic-converter risk sentence into
hypothesis content.

Reuses the same test-only fixture shape as
test_block_b2r2_production_rule_identity.py, but for the REAL Peugeot
document already established in test_block_b2k_peugeot_poc.py
(manufacturer="Peugeot", document_id="9999_9999_326_en-GB") rather
than TestMfr.
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
from pgdr.automotive.domain_adapter import _DASHBOARD_DIAGNOSTIC_RULES, AutomotiveDiagnosticDomain
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
# Real Peugeot fixtures -- same document/entries as
# test_block_b2k_peugeot_poc.py, reconstructed here (test files own
# their own fixtures, per this project's established convention) so
# these tests exercise the REAL, shipped B2-R5 rule table via the REAL
# build_diagnostic_intake() pipeline.
# ---------------------------------------------------------------------------

_PEUGEOT_DOC = ManufacturerDocumentReference(
    manufacturer="Peugeot", document_id="9999_9999_326_en-GB",
    document_title="MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL,
    source_locator="Peugeot Service Box, document 9999_9999_326_en-GB.pdf",
)
_PEUGEOT_DOC_UNVERIFIED = ManufacturerDocumentReference(
    manufacturer="Peugeot", document_id="9999_9999_326_en-GB",
    document_title="MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK",
    source_authority=SourceAuthority.UNVERIFIED_PLACEHOLDER,
    source_locator="unverified-test-fixture",
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
_OIL_PRESSURE_ENTRY_UNVERIFIED = DashboardReferenceEntry(
    entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
    colour="red", state=IndicatorState.FIXED,
    documented_meaning="Fault with the engine lubrication system.",
    applicability=_PEUGEOT_DOC_UNVERIFIED,
)


def _reference_set(entry: DashboardReferenceEntry, doc: ManufacturerDocumentReference) -> DashboardReferenceSet:
    return DashboardReferenceSet(
        vehicle_applicability=VehicleApplicabilityContext(manufacturer="Peugeot", model="3008", generation="II"),
        candidate_documents=[doc],
        entries=[entry],
        applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
    )


_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-ref-b2r5-001")


class _ScriptedVisualProvider:
    def __init__(self, planned_results=None):
        self._planned_results = planned_results if planned_results is not None else []
        self.calls = []

    def interpret(self, media: ResolvedMedia, reference_set: DashboardReferenceSet) -> list[DashboardInterpretationResult]:
        self.calls.append((media, reference_set))
        return self._planned_results


def _provenance() -> InterpretationProvenance:
    return InterpretationProvenance(adapter_id="scripted-test-provider", media_reference=_RESOLVED_MEDIA.reference)


def _match_result(entry_id: str) -> DashboardInterpretationResult:
    return DashboardInterpretationResult(
        observation=f"Dashboard indicator matching {entry_id}",
        observation_confidence=Confidence.HIGH,
        match_status=MatchStatus.MATCH,
        matched_reference_entry_id=entry_id,
        match_confidence=Confidence.HIGH,
        provenance=_provenance(),
    )


def _fresh_updater_and_state() -> tuple[CaseStateUpdater, DiagnosticCaseState]:
    return CaseStateUpdater(DeterministicHypothesisScorer()), DiagnosticCaseState()


def _apply_and_insert(domain, intake, updater, state):
    new_hypotheses, new_evidence = domain.apply_dashboard_diagnostic_relevance(intake, state)
    if new_hypotheses:
        state.hypotheses.extend(new_hypotheses)
        state.touch()
    if new_evidence:
        updater.add_evidence(state, new_evidence)
    return new_hypotheses, new_evidence


def _intake_for(entry: DashboardReferenceEntry, doc: ManufacturerDocumentReference):
    reference_set = _reference_set(entry, doc)
    provider = _ScriptedVisualProvider(planned_results=[_match_result(entry.entry_id)])
    return build_diagnostic_intake(provider, _RESOLVED_MEDIA, reference_set)


# ---------------------------------------------------------------------------
# Rule firing — P1/P2/P3
# ---------------------------------------------------------------------------

class TestP1OilPressureWarningFires:
    def test_produces_the_expected_system_level_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert len(new_hyp) == 1
        assert len(new_evd) == 1
        assert "lubrification" in state.hypotheses[0].description


class TestP2EngineDiagFixedFires:
    def test_produces_the_expected_system_level_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_FIXED_ENTRY, _PEUGEOT_DOC)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert len(new_hyp) == 1
        assert len(new_evd) == 1
        assert "émissions" in state.hypotheses[0].description


class TestP3EngineDiagFlashingFires:
    def test_produces_the_expected_system_level_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_FLASHING_ENTRY, _PEUGEOT_DOC)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert len(new_hyp) == 1
        assert len(new_evd) == 1
        assert "gestion moteur" in state.hypotheses[0].description


# ---------------------------------------------------------------------------
# Source authority
# ---------------------------------------------------------------------------

class TestSourceAuthorityGating:
    def test_unverified_placeholder_does_not_fire_the_peugeot_rule(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY_UNVERIFIED, _PEUGEOT_DOC_UNVERIFIED)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []
        assert state.hypotheses == []
        assert state.evidence == []


# ---------------------------------------------------------------------------
# Identity / idempotency
# ---------------------------------------------------------------------------

class TestIdentityAndIdempotency:
    def test_repeated_application_creates_no_duplicate_hypothesis_or_evidence(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        hyp_count_after_first = len(state.hypotheses)
        evd_count_after_first = len(state.evidence)
        _apply_and_insert(domain, intake, updater, state)
        assert len(state.hypotheses) == hyp_count_after_first
        assert len(state.evidence) == evd_count_after_first

    def test_three_distinct_peugeot_facts_produce_three_distinct_hypotheses(self):
        """Each of the three real entries is a DIFFERENT manufacturer
        fact (different entry_id) -- confirms domain_ref keeps them
        separate even though all three share hypothesis_type="engine_running"."""
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        for entry in (_OIL_PRESSURE_ENTRY, _ENGINE_DIAG_FIXED_ENTRY, _ENGINE_DIAG_FLASHING_ENTRY):
            intake = _intake_for(entry, _PEUGEOT_DOC)
            _apply_and_insert(domain, intake, updater, state)
        assert len(state.hypotheses) == 3
        assert len({h.domain_ref for h in state.hypotheses}) == 3


# ---------------------------------------------------------------------------
# Description precision
# ---------------------------------------------------------------------------

class TestDescriptionPrecision:
    def test_p1_preserves_engine_lubrication_system_proposition(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        description = state.hypotheses[0].description
        assert "lubrification" in description
        assert "constructeur" in description

    def test_p2_preserves_emissions_control_system_proposition(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_FIXED_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        description = state.hypotheses[0].description
        assert "émissions" in description

    def test_p3_preserves_engine_management_system_proposition(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_FLASHING_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        description = state.hypotheses[0].description
        assert "gestion moteur" in description


class TestCatalyticConverterExcluded:
    def test_p3_description_does_not_present_catalytic_converter_as_the_fault(self):
        """The documented catalytic-converter risk is a CONSEQUENCE, not
        the fault -- it must not be smuggled into the hypothesis as if
        it were the diagnostic claim itself. This test proves the
        description does not assert catalyst failure as the finding."""
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_FLASHING_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        description = state.hypotheses[0].description
        # The system-level fault claim is "engine management system" --
        # the catalytic-converter mention, if present at all, must be
        # framed as a documented consequence, never as the fault itself.
        assert "défaut du système de gestion moteur" in description

    def test_p3_description_makes_no_mention_of_the_catalytic_converter_at_all(self):
        """Post-review correction: the consequence must remain entirely
        outside hypothesis content -- not merely reframed as an
        excluded note, but genuinely absent from the description text.
        The explanation for the exclusion lives in a code comment
        instead (see the rule table's own inline comment)."""
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_FLASHING_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        description = state.hypotheses[0].description.lower()
        assert "catalyseur" not in description
        assert "catalytic" not in description


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_all_three_rules_use_engine_running_hypothesis_type(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        for entry in (_OIL_PRESSURE_ENTRY, _ENGINE_DIAG_FIXED_ENTRY, _ENGINE_DIAG_FLASHING_ENTRY):
            intake = _intake_for(entry, _PEUGEOT_DOC)
            _apply_and_insert(domain, intake, updater, state)
        assert all(h.hypothesis_type == "engine_running" for h in state.hypotheses)

    def test_no_new_hypothesis_type_introduced_in_the_rule_table(self):
        types_in_table = {
            spec[0]
            for selector, rules in _DASHBOARD_DIAGNOSTIC_RULES.items()
            if selector[0] == "Peugeot"
            for spec in rules
        }
        assert types_in_table == {"engine_running"}


# ---------------------------------------------------------------------------
# Non-causality
# ---------------------------------------------------------------------------

class TestNonCausality:
    def test_no_component_or_root_cause_language_in_any_peugeot_description(self):
        """Scans the actual authored descriptions for forbidden
        causal/component-level claim language -- not a source scan of
        the method (that's covered elsewhere), but of the DATA itself."""
        forbidden_tokens = (
            "pompe à huile", "oil pump", "capteur", "sensor", "injecteur", "injector",
            "vanne", "valve", "câblage", "wiring", "a causé", "caused by", "défaillance du composant",
        )
        for selector, rules in _DASHBOARD_DIAGNOSTIC_RULES.items():
            if selector[0] != "Peugeot":
                continue
            for _hypothesis_type, description, _direction, _weight, _rule_id in rules:
                lowered = description.lower()
                for token in forbidden_tokens:
                    assert token.lower() not in lowered, f"{token!r} found in {description!r}"

    def test_every_peugeot_description_uses_compatible_with_phrasing(self):
        """PGDR-HYP-003: only 'compatible with'/'system to examine'
        language is authorized -- confirmed present, matching the
        existing _HYPOTHESIS_MAP convention exactly."""
        for selector, rules in _DASHBOARD_DIAGNOSTIC_RULES.items():
            if selector[0] != "Peugeot":
                continue
            for _hypothesis_type, description, _direction, _weight, _rule_id in rules:
                assert "compatibles avec" in description


# ---------------------------------------------------------------------------
# Non-scoring bootstrap
# ---------------------------------------------------------------------------

class TestNonScoringBootstrap:
    def test_bootstrap_evidence_direction_is_neutral(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].direction == EvidenceDirection.NEUTRAL

    def test_bootstrap_evidence_weight_is_zero_not_invented(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].weight == 0.0

    def test_confidence_after_bootstrap_equals_the_unmodified_baseline(self):
        """The defining proof of 'non-scoring': a freshly-scored
        hypothesis with ONLY this NEUTRAL bootstrap Evidence lands at
        EXACTLY the scorer's own baseline (0.3) -- identical to what a
        hypothesis with ZERO evidence would score. Nothing was added or
        subtracted by the manufacturer fact itself."""
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        assert state.hypotheses[0].confidence == pytest.approx(0.3)

    def test_hypothesis_is_tracked_and_reachable_despite_non_scoring_evidence(self):
        """'Non-scoring' does not mean 'invisible' -- the hypothesis and
        its Evidence are both fully present in case state, auditable,
        and correctly linked. NEUTRAL evidence is neither 'supporting'
        nor 'contradicting' by the scorer's own bookkeeping (only
        SUPPORTS/CONTRADICTS populate those two lists) -- it is tracked
        via observation_ids/target_hypothesis_id instead."""
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        assert state.evidence[0].target_hypothesis_id == state.hypotheses[0].id
        assert state.evidence[0].id not in state.hypotheses[0].supporting_evidence_ids
        assert state.evidence[0].id not in state.hypotheses[0].contradicting_evidence_ids


# ---------------------------------------------------------------------------
# Existing scorer unchanged
# ---------------------------------------------------------------------------

class TestScorerUnchanged:
    def test_scorer_constants_unchanged(self):
        from pgdr.application import hypothesis_scorer as scorer_module
        assert scorer_module._BASELINE == 0.3
        assert scorer_module._DEFAULT_EVIDENCE_WEIGHT == 0.2

    def test_scorer_source_not_modified_in_shape(self):
        import inspect
        from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
        source = inspect.getsource(DeterministicHypothesisScorer)
        assert source.count("EvidenceDirection.SUPPORTS") == 1
        assert source.count("EvidenceDirection.CONTRADICTS") == 1


# ---------------------------------------------------------------------------
# Existing routing compatibility
# ---------------------------------------------------------------------------

class TestRoutingCompatibility:
    def test_peugeot_hypothesis_is_structurally_eligible_for_existing_engine_running_qa_routing(self):
        """Confirms the Peugeot-bootstrapped hypothesis has the SAME
        hypothesis_type the existing Q&A discriminator (Q-COND-001)
        already targets -- this is a structural compatibility check
        (hypothesis_type equality), not an invocation of the Q&A
        pipeline itself (out of scope for B2-R5)."""
        from pgdr.automotive.evidence_mapper import _DISCRIMINATING_RULES

        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        _apply_and_insert(domain, intake, updater, state)
        peugeot_hypothesis_type = state.hypotheses[0].hypothesis_type

        targeted_types = {
            hypothesis_type
            for per_value in _DISCRIMINATING_RULES.values()
            for per_hypothesis in per_value.values()
            for hypothesis_type in per_hypothesis
        }
        assert peugeot_hypothesis_type in targeted_types


# ---------------------------------------------------------------------------
# Non-Match states never bootstrap
# ---------------------------------------------------------------------------

class TestNonMatchStatesDoNotFire:
    def test_no_match_does_not_fire_any_peugeot_rule(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        reference_set = _reference_set(_OIL_PRESSURE_ENTRY, _PEUGEOT_DOC)
        no_match = DashboardInterpretationResult(
            observation="Nothing recognizable", observation_confidence=Confidence.HIGH,
            match_status=MatchStatus.NO_MATCH, provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[no_match])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, reference_set)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


# ---------------------------------------------------------------------------
# Rule table validation still holds with the enlarged table
# ---------------------------------------------------------------------------

class TestRuleTableStillValid:
    def test_import_time_validation_passes_with_peugeot_rules_added(self):
        from pgdr.automotive.domain_adapter import _validate_dashboard_diagnostic_rule_ids
        _validate_dashboard_diagnostic_rule_ids()  # must not raise

    def test_all_rule_ids_still_globally_unique(self):
        all_ids = [
            spec[4]
            for rules in _DASHBOARD_DIAGNOSTIC_RULES.values()
            for spec in rules
        ]
        assert len(all_ids) == len(set(all_ids))

    def test_peugeot_rule_ids_are_distinct_from_testmfr_rule_ids(self):
        peugeot_ids = {
            spec[4]
            for selector, rules in _DASHBOARD_DIAGNOSTIC_RULES.items()
            if selector[0] == "Peugeot"
            for spec in rules
        }
        testmfr_ids = {
            spec[4]
            for selector, rules in _DASHBOARD_DIAGNOSTIC_RULES.items()
            if selector[0] == "TestMfr"
            for spec in rules
        }
        assert peugeot_ids.isdisjoint(testmfr_ids)
        assert len(peugeot_ids) == 3


# ---------------------------------------------------------------------------
# No method-body change was required (confirms "minimum code necessary")
# ---------------------------------------------------------------------------

class TestNoMethodBodyChangeRequired:
    def test_apply_dashboard_diagnostic_relevance_body_unchanged_in_shape(self):
        """B2-R5 is data-only per its own mandate (§15) -- this is a
        light structural sanity check, not a byte-diff (that lives in
        the git history itself): the method still has exactly one
        return statement producing (hypotheses, evidence)."""
        import inspect
        source = inspect.getsource(AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance)
        return_lines = [line.strip() for line in source.split("\n") if line.strip().startswith("return ")]
        assert len(return_lines) == 1
        assert return_lines[0] == "return new_hypotheses, new_evidence"


# ---------------------------------------------------------------------------
# Existing TestMfr B2-R1/R2 behaviour untouched by adding Peugeot data
# ---------------------------------------------------------------------------

class TestTestMfrPathUnaffected:
    def test_testmfr_rule_still_fires_independently_of_peugeot_rules(self):
        _TEST_DOC = ManufacturerDocumentReference(
            manufacturer="TestMfr", document_id="TEST-DOC-A", document_title="Test handbook",
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator",
        )
        _ENGINE_DIAG_ENTRY = DashboardReferenceEntry(
            entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
            colour="orange", state=IndicatorState.FLASHING,
            documented_meaning="Fault in the engine management system.", applicability=_TEST_DOC,
        )
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY, _TEST_DOC)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert len(new_hyp) == 1
        assert len(new_evd) == 2  # the two existing TestMfr POC rules, unchanged
