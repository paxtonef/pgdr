"""Block B2-R2 — Production Rule Identity & Multi-Rule Semantics.

Covers R2-01 through R2-36 of the B2-R2 mandate: production-safe
manufacturer-fact identity ((manufacturer, document_id, entry_id)),
production hypothesis identity (domain_ref extended with document_id),
multi-rule Evidence idempotency ((rule_id, target_hypothesis_id,
observation_ids)), and the source_authority eligibility gate.

The critical test (R2-14/§16/§17) proves the ONE collision B2-R1 could
not handle: two DIFFERENT rules converging on the SAME hypothesis
INSTANCE from the SAME observation must both be retained, not merely
two rules producing two DIFFERENT hypotheses (which the old fingerprint
already handled via target_hypothesis_id).

Reuses the same test-only fixture shape as
test_block_b2r1_diagnostic_relevance.py (_ScriptedVisualProvider,
_provenance, _fresh_updater_and_state, _apply_and_insert), defined
locally. Exercises the REAL, shipped _DASHBOARD_DIAGNOSTIC_RULES table
(TestMfr / TEST-DOC-A / engine-diag-flashing, with its two converging
POC rules) via the real build_diagnostic_intake(), never a hand-built
DiagnosticIntakeResult.
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
    _DASHBOARD_DIAGNOSTIC_RULES, AutomotiveDiagnosticDomain, _dashboard_diagnostic_domain_ref,
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
# Test-only fixtures. document_id="TEST-DOC-A" is deliberately the SAME
# document_id the real, shipped _DASHBOARD_DIAGNOSTIC_RULES table keys
# on -- so these tests exercise the real production rules, not a
# private substitute.
# ---------------------------------------------------------------------------

_TEST_DOC_A = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-DOC-A", document_title="Test handbook, generation A",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-a",
)
_TEST_DOC_B = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-DOC-B", document_title="Test handbook, generation B",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-b",
    supersedes_document_id="TEST-DOC-A",
)
_OTHER_MFR_DOC = ManufacturerDocumentReference(
    manufacturer="OtherMfr", document_id="TEST-DOC-A", document_title="Different manufacturer, same document_id",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL, source_locator="test-locator-other",
)
_UNVERIFIED_DOC = ManufacturerDocumentReference(
    manufacturer="TestMfr", document_id="TEST-DOC-A", document_title="Test handbook, generation A",
    source_authority=SourceAuthority.UNVERIFIED_PLACEHOLDER, source_locator="test-locator-unverified",
)

_ENGINE_DIAG_ENTRY_DOC_A = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Fault in the engine management system.", applicability=_TEST_DOC_A,
)
_ENGINE_DIAG_ENTRY_DOC_B = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Fault in the engine management system (generation B wording).",
    applicability=_TEST_DOC_B,
)
_ENGINE_DIAG_ENTRY_OTHER_MFR = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Some other manufacturer's own indicator",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Unrelated meaning under a different manufacturer.", applicability=_OTHER_MFR_DOC,
)
_ENGINE_DIAG_ENTRY_UNVERIFIED = DashboardReferenceEntry(
    entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
    colour="orange", state=IndicatorState.FLASHING,
    documented_meaning="Fault in the engine management system.", applicability=_UNVERIFIED_DOC,
)
_OIL_ENTRY_DOC_A = DashboardReferenceEntry(
    entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
    colour="red", state=IndicatorState.FIXED,
    documented_meaning="Fault with the engine lubrication system.", applicability=_TEST_DOC_A,
)


def _reference_set(entry: DashboardReferenceEntry, doc: ManufacturerDocumentReference, manufacturer: str = "TestMfr") -> DashboardReferenceSet:
    return DashboardReferenceSet(
        vehicle_applicability=VehicleApplicabilityContext(manufacturer=manufacturer, model="TestModel", generation="I"),
        candidate_documents=[doc],
        entries=[entry],
        applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
    )


_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake-jpeg-bytes", media_type=MediaType.IMAGE, reference="media-ref-b2r2-001")


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
    new_hypotheses, new_evidence = domain.apply_dashboard_diagnostic_relevance(intake, state)
    if new_hypotheses:
        state.hypotheses.extend(new_hypotheses)
        state.touch()
    if new_evidence:
        updater.add_evidence(state, new_evidence)
    return new_hypotheses, new_evidence


def _intake_for(entry, doc, manufacturer="TestMfr"):
    reference_set = _reference_set(entry, doc, manufacturer)
    provider = _ScriptedVisualProvider(planned_results=[_match_result(entry.entry_id)])
    return build_diagnostic_intake(provider, _RESOLVED_MEDIA, reference_set)


# ---------------------------------------------------------------------------
# R2-01 .. R2-03 — production selector fields
# ---------------------------------------------------------------------------

class TestR201SelectorIncludesManufacturer:
    def test_selector_key_first_component_is_manufacturer(self):
        assert ("TestMfr", "TEST-DOC-A", "engine-diag-flashing") in _DASHBOARD_DIAGNOSTIC_RULES


class TestR202SelectorIncludesDocumentId:
    def test_selector_key_second_component_is_document_id(self):
        key = ("TestMfr", "TEST-DOC-A", "engine-diag-flashing")
        assert key in _DASHBOARD_DIAGNOSTIC_RULES
        assert key[1] == "TEST-DOC-A"


class TestR203SelectorIncludesEntryId:
    def test_selector_key_third_component_is_entry_id(self):
        key = ("TestMfr", "TEST-DOC-A", "engine-diag-flashing")
        assert key[2] == "engine-diag-flashing"


# ---------------------------------------------------------------------------
# R2-04 .. R2-05 — fail-closed selector matching
# ---------------------------------------------------------------------------

class TestR204DifferentDocumentDoesNotMatch:
    def test_same_entry_id_different_document_id_produces_no_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_B, _TEST_DOC_B)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []
        assert state.hypotheses == []
        assert state.evidence == []


class TestR205DifferentManufacturerDoesNotMatch:
    def test_same_document_id_entry_id_different_manufacturer_produces_no_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_OTHER_MFR, _OTHER_MFR_DOC, manufacturer="OtherMfr")
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


# ---------------------------------------------------------------------------
# R2-06 .. R2-07 — source authority gate
# ---------------------------------------------------------------------------

class TestR206ManufacturerOfficialPermitsRule:
    def test_manufacturer_official_source_authority_allows_matching_rule_to_fire(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        assert _ENGINE_DIAG_ENTRY_DOC_A.applicability.source_authority == SourceAuthority.MANUFACTURER_OFFICIAL
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert len(new_hyp) == 1
        assert len(new_evd) >= 1


class TestR207UnverifiedPlaceholderBlocksRule:
    def test_unverified_placeholder_source_authority_blocks_the_rule(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        assert _ENGINE_DIAG_ENTRY_UNVERIFIED.applicability.source_authority == SourceAuthority.UNVERIFIED_PLACEHOLDER
        intake = _intake_for(_ENGINE_DIAG_ENTRY_UNVERIFIED, _UNVERIFIED_DOC)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []
        assert state.hypotheses == []
        assert state.evidence == []


# ---------------------------------------------------------------------------
# R2-08 .. R2-11 — production domain_ref composition
# ---------------------------------------------------------------------------

class TestR208DomainRefIncludesManufacturer:
    def test_domain_ref_contains_manufacturer(self):
        ref = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "engine-diag-flashing", "engine_running")
        assert "TestMfr" in ref


class TestR209DomainRefIncludesDocumentId:
    def test_domain_ref_contains_document_id(self):
        ref = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "engine-diag-flashing", "engine_running")
        assert "TEST-DOC-A" in ref


class TestR210DomainRefIncludesEntryId:
    def test_domain_ref_contains_entry_id(self):
        ref = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "engine-diag-flashing", "engine_running")
        assert "engine-diag-flashing" in ref


class TestR211DomainRefIncludesHypothesisType:
    def test_domain_ref_contains_hypothesis_type(self):
        ref = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "engine-diag-flashing", "engine_running")
        assert "engine_running" in ref


# ---------------------------------------------------------------------------
# R2-12 .. R2-13 — hypothesis cardinality
# ---------------------------------------------------------------------------

class TestR212OneFactMultipleHypothesisIdentities:
    def test_domain_ref_differs_for_two_hypothesis_types_from_the_same_fact(self):
        ref_1 = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "engine-diag-flashing", "engine_running")
        ref_2 = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "engine-diag-flashing", "electrical")
        assert ref_1 != ref_2


class TestR213TwoFactsSameHypothesisTypeRemainDistinct:
    def test_two_different_facts_producing_the_same_hypothesis_type_get_different_domain_ref(self):
        ref_fact_a = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "engine-diag-flashing", "engine_running")
        ref_fact_b = _dashboard_diagnostic_domain_ref("TestMfr", "TEST-DOC-A", "oil-pressure-warning", "engine_running")
        assert ref_fact_a != ref_fact_b


# ---------------------------------------------------------------------------
# R2-14 .. R2-17 — THE critical multi-rule collision (§16/§17) and scenarios
# ---------------------------------------------------------------------------

class TestR214DistinctRulesSameHypothesisSameObservationProduceTwoEvidence:
    """THE decisive test per §17: R1 and R2 must converge on the SAME
    DiagnosticHypothesis INSTANCE (not merely the same hypothesis_type
    coincidentally producing two different hypotheses) from the SAME
    Observation -- the one case B2-R1's own (target_hypothesis_id,
    observation_ids) fingerprint could not tell apart from a real
    duplicate."""

    def test_two_rules_converging_on_one_hypothesis_both_produce_evidence(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)

        # Exactly one hypothesis instance -- both rules share the same
        # (manufacturer, document_id, entry_id, hypothesis_type) key.
        assert len(new_hyp) == 1
        assert len(state.hypotheses) == 1
        hypothesis_id = state.hypotheses[0].id

        # Both rules fired: two Evidence records.
        assert len(new_evd) == 2
        assert len(state.evidence) == 2

        evidence_1, evidence_2 = state.evidence[0], state.evidence[1]
        dashboard_obs_id = intake.observations[0].id

        # Confirm explicitly, per the mandate's own required return shape:
        assert evidence_1.target_hypothesis_id == hypothesis_id  # same target_hypothesis_id: YES
        assert evidence_2.target_hypothesis_id == hypothesis_id
        assert evidence_1.observation_ids == [dashboard_obs_id]  # same observation_ids: YES
        assert evidence_2.observation_ids == [dashboard_obs_id]
        assert evidence_1.source_rule_id != evidence_2.source_rule_id  # different source_rule_id: YES
        # both Evidence retained: YES
        assert {evidence_1.id, evidence_2.id}.issubset({e.id for e in state.evidence})


class TestR215SourceRuleIdValuesRemainDistinct:
    def test_the_two_converging_rules_have_distinct_rule_ids(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        _apply_and_insert(domain, intake, updater, state)
        rule_ids = {e.source_rule_id for e in state.evidence}
        assert len(rule_ids) == 2


class TestR216SupportsAndContradictsCoexist:
    """Multi-rule Scenario 1 (§19): the real shipped rules are
    SUPPORTS(0.3) and CONTRADICTS(0.2) on purpose."""

    def test_supports_and_contradicts_contributions_both_exist(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        _apply_and_insert(domain, intake, updater, state)
        directions = {e.direction for e in state.evidence}
        assert directions == {EvidenceDirection.SUPPORTS, EvidenceDirection.CONTRADICTS}
        # Existing, unmodified scorer applies unchanged: 0.3 + 0.3 - 0.2 = 0.4
        assert state.hypotheses[0].confidence == pytest.approx(0.4)


class TestR217TwoSupportsCoexist:
    """Multi-rule Scenario 2 (§20): two SUPPORTS contributions to the
    same H/O must both be retained and additively accumulate. Proven at
    the same real method, with a temporarily monkeypatched rule table
    (no third permanent production rule is shipped, per §18's "a second
    rule MAY be added" -- singular)."""

    def test_two_supports_contributions_both_retained_and_accumulate(self, monkeypatch):
        temp_rules = {
            ("TestMfr", "TEST-DOC-A", "engine-diag-flashing"): [
                ("engine_running", "R1 test-only.", EvidenceDirection.SUPPORTS, 0.3, "test.r2s17.rule_one"),
                ("engine_running", "R2 test-only.", EvidenceDirection.SUPPORTS, 0.1, "test.r2s17.rule_two"),
            ],
        }
        monkeypatch.setattr(domain_adapter_module, "_DASHBOARD_DIAGNOSTIC_RULES", temp_rules)

        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)

        assert len(new_hyp) == 1
        assert len(new_evd) == 2
        assert all(e.direction == EvidenceDirection.SUPPORTS for e in state.evidence)
        # 0.3 baseline + 0.3 + 0.1 = 0.7
        assert state.hypotheses[0].confidence == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# R2-18 .. R2-20 — re-execution idempotency (with rule_id now in the fingerprint)
# ---------------------------------------------------------------------------

class TestR218SameRuleHypothesisObservationNoDuplicateEvidence:
    def test_second_identical_execution_adds_no_evidence(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        _apply_and_insert(domain, intake, updater, state)
        count_after_first = len(state.evidence)
        _apply_and_insert(domain, intake, updater, state)
        assert len(state.evidence) == count_after_first


class TestR219SameFactHypothesisNoDuplicateHypothesis:
    def test_second_identical_execution_adds_no_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        _apply_and_insert(domain, intake, updater, state)
        first_id = state.hypotheses[0].id
        _apply_and_insert(domain, intake, updater, state)
        assert len(state.hypotheses) == 1
        assert state.hypotheses[0].id == first_id


class TestR220SecondExecutionDoesNotInflateScore:
    def test_second_identical_execution_leaves_confidence_unchanged(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        _apply_and_insert(domain, intake, updater, state)
        confidence_after_first = state.hypotheses[0].confidence
        _apply_and_insert(domain, intake, updater, state)
        assert state.hypotheses[0].confidence == confidence_after_first


# ---------------------------------------------------------------------------
# R2-21 .. R2-24 — no-rule / non-match states
# ---------------------------------------------------------------------------

class TestR221UnknownFactProducesNothing:
    def test_unknown_selector_produces_no_hypothesis_or_evidence(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_OIL_ENTRY_DOC_A, _TEST_DOC_A)  # no rule authored for oil-pressure-warning
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


class TestR222AmbiguousProducesNothing:
    def test_ambiguous_match_produces_no_diagnostic_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        reference_set = _reference_set(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        ambiguous = DashboardInterpretationResult(
            observation="Amber symbol, partially obscured", observation_confidence=Confidence.MEDIUM,
            match_status=MatchStatus.AMBIGUOUS_MATCH,
            candidate_reference_entry_ids=["engine-diag-flashing"],
            provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[ambiguous])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, reference_set)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


class TestR223NoMatchProducesNothing:
    def test_no_match_produces_no_diagnostic_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        reference_set = _reference_set(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        no_match = DashboardInterpretationResult(
            observation="Nothing recognizable", observation_confidence=Confidence.HIGH,
            match_status=MatchStatus.NO_MATCH, provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[no_match])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, reference_set)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


class TestR224InsufficientQualityProducesNothing:
    def test_insufficient_visual_quality_produces_no_diagnostic_hypothesis(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        reference_set = _reference_set(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        insufficient = DashboardInterpretationResult(
            observation="Too dark", observation_confidence=Confidence.SPECULATIVE,
            match_status=MatchStatus.INSUFFICIENT_VISUAL_QUALITY, provenance=_provenance(),
        )
        provider = _ScriptedVisualProvider(planned_results=[insufficient])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, reference_set)
        new_hyp, new_evd = _apply_and_insert(domain, intake, updater, state)
        assert new_hyp == []
        assert new_evd == []


# ---------------------------------------------------------------------------
# R2-25 .. R2-28 — B2-C consumption discipline
# ---------------------------------------------------------------------------

class TestR225ExactB2CObjectConsumed:
    def test_transported_entry_used_by_rule_matching_is_the_real_b2c_object(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        transported = intake.matched_reference_entries[intake.observations[0].id]
        assert transported is _ENGINE_DIAG_ENTRY_DOC_A
        new_hyp, _ = _apply_and_insert(domain, intake, updater, state)
        assert len(new_hyp) == 1  # the rule did fire against this exact instance


class TestR226NoRepositoryRequery:
    def test_method_body_never_references_either_knowledge_port(self):
        import inspect
        source = inspect.getsource(AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance)
        body = source.split('"""', 2)[-1]
        assert "KnowledgeRepositoryPort" not in body
        assert "VehicleDashboardKnowledgePort" not in body
        assert "repository" not in body.lower()

    def test_module_does_not_import_either_knowledge_port(self):
        import inspect
        source = inspect.getsource(domain_adapter_module)
        import_lines = [line for line in source.split("\n") if line.strip().startswith(("import ", "from "))]
        imports_text = "\n".join(import_lines)
        assert "knowledge_repository" not in imports_text
        assert "vehicle_dashboard_knowledge" not in imports_text


class TestR227DocumentedMeaningNotUsedForSelection:
    def test_documented_meaning_not_read_in_executable_code(self):
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
            assert "documented_meaning" not in body_only(obj)


class TestR228DocumentedInstructionNotUsedForInference:
    def test_documented_instruction_and_diagnostic_tokens_not_read(self):
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


# ---------------------------------------------------------------------------
# R2-29 .. R2-31 — unchanged existing behaviour
# ---------------------------------------------------------------------------

class TestR229B2DNeutralEvidenceUnchanged:
    def test_original_b2d_evidence_still_neutral_target_none_weight_none(self):
        domain = AutomotiveDiagnosticDomain()
        updater, state = _fresh_updater_and_state()
        intake = _intake_for(_ENGINE_DIAG_ENTRY_DOC_A, _TEST_DOC_A)
        original_b2d_evidence = intake.evidence[0]
        assert original_b2d_evidence.direction == EvidenceDirection.NEUTRAL
        assert original_b2d_evidence.target_hypothesis_id is None
        assert original_b2d_evidence.weight is None
        _apply_and_insert(domain, intake, updater, state)
        assert intake.evidence[0] is original_b2d_evidence
        assert intake.evidence[0].direction == EvidenceDirection.NEUTRAL
        assert intake.evidence[0].target_hypothesis_id is None
        assert intake.evidence[0].weight is None


class TestR230QEvi002Unchanged:
    def test_media_evidence_source_rule_id_unchanged(self):
        from pgdr.automotive.evidence_mapper import MEDIA_EVIDENCE_SOURCE_RULE_ID
        assert MEDIA_EVIDENCE_SOURCE_RULE_ID == "automotive.media_evidence_acquired"

    def test_domain_module_still_never_references_the_q_evi_002_media_rule(self):
        import inspect
        source = inspect.getsource(domain_adapter_module)
        assert "_apply_media_evidence_rule" not in source


class TestR231PrimarySymptomPathUnchanged:
    def test_existing_methods_are_byte_for_byte_unmodified_in_behaviour(self):
        from pgdr.domain.enums import EvidenceDirection as ED
        from pgdr.domain.enums import ObservationSource
        from pgdr.domain.observation import Observation

        domain = AutomotiveDiagnosticDomain()
        state = DiagnosticCaseState()
        state.observations.append(Observation(
            kind="symptom", value="vibration", source_type=ObservationSource.USER,
            context={"is_primary": True, "user_description": "x", "frequency": "constant", "severity": "medium"},
        ))
        hyps = domain.generate_hypotheses(state)
        assert len(hyps) == 2
        state.hypotheses.extend(hyps)
        evd = domain.map_evidence(state)
        assert len(evd) == 2
        assert all(e.direction == ED.SUPPORTS and e.weight == 0.3 for e in evd)


# ---------------------------------------------------------------------------
# R2-32 .. R2-33 — rule table validation
# ---------------------------------------------------------------------------

class TestR232RuleIdsNonEmpty:
    def test_every_rule_id_in_the_table_is_non_empty(self):
        for rules in _DASHBOARD_DIAGNOSTIC_RULES.values():
            for spec in rules:
                rule_id = spec[4]
                assert rule_id

    def test_validator_rejects_an_empty_rule_id(self, monkeypatch):
        from pgdr.automotive.domain_adapter import _validate_dashboard_diagnostic_rule_ids

        bad_table = {("TestMfr", "TEST-DOC-A", "x"): [("t", "d", EvidenceDirection.SUPPORTS, 0.1, "")]}
        monkeypatch.setattr(domain_adapter_module, "_DASHBOARD_DIAGNOSTIC_RULES", bad_table)
        with pytest.raises(ValueError, match="non-empty"):
            _validate_dashboard_diagnostic_rule_ids()

    def test_validator_rejects_a_duplicate_rule_id(self, monkeypatch):
        from pgdr.automotive.domain_adapter import _validate_dashboard_diagnostic_rule_ids

        bad_table = {
            ("TestMfr", "TEST-DOC-A", "x"): [
                ("t1", "d1", EvidenceDirection.SUPPORTS, 0.1, "dup.rule"),
                ("t2", "d2", EvidenceDirection.SUPPORTS, 0.1, "dup.rule"),
            ],
        }
        monkeypatch.setattr(domain_adapter_module, "_DASHBOARD_DIAGNOSTIC_RULES", bad_table)
        with pytest.raises(ValueError, match="duplicate"):
            _validate_dashboard_diagnostic_rule_ids()


class TestR233RuleIdsUnique:
    def test_every_rule_id_in_the_table_is_globally_unique(self):
        all_ids = [
            spec[4]
            for rules in _DASHBOARD_DIAGNOSTIC_RULES.values()
            for spec in rules
        ]
        assert len(all_ids) == len(set(all_ids))

    def test_the_two_converging_rules_have_distinct_ids_in_the_real_table(self):
        rules = _DASHBOARD_DIAGNOSTIC_RULES[("TestMfr", "TEST-DOC-A", "engine-diag-flashing")]
        ids = [spec[4] for spec in rules]
        assert len(ids) == 2
        assert len(set(ids)) == 2

    def test_module_import_time_validation_already_ran_successfully(self):
        """The module imported cleanly (this test file itself proves
        that), which already exercised
        _validate_dashboard_diagnostic_rule_ids() against the real,
        shipped table at import time -- a duplicate or empty rule_id
        there would have raised before any test could even collect."""
        from pgdr.automotive.domain_adapter import _validate_dashboard_diagnostic_rule_ids
        _validate_dashboard_diagnostic_rule_ids()  # must not raise


# ---------------------------------------------------------------------------
# R2-34 .. R2-36 — no model/scorer change, no real Peugeot rule
# ---------------------------------------------------------------------------

class TestR234NoModelChange:
    def test_evidence_and_hypothesis_and_observation_models_unchanged_fields(self):
        from pgdr.domain.evidence import Evidence
        from pgdr.domain.hypothesis import DiagnosticHypothesis
        from pgdr.domain.observation import Observation

        assert set(Evidence.model_fields) == {
            "id", "observation_ids", "direction", "target_hypothesis_id", "weight", "rationale", "source_rule_id",
        }
        assert set(DiagnosticHypothesis.model_fields) == {
            "id", "hypothesis_type", "description", "supporting_evidence_ids", "contradicting_evidence_ids",
            "required_evidence_ids", "confidence", "domain_ref", "configuration_requirements", "active",
        }
        assert set(Observation.model_fields) == {"id", "kind", "value", "source_type", "source_ref", "context", "timestamp"}


class TestR235NoScorerChange:
    def test_scorer_source_unchanged_shape(self):
        import inspect
        from pgdr.application.hypothesis_scorer import DeterministicHypothesisScorer
        source = inspect.getsource(DeterministicHypothesisScorer)
        assert "_BASELINE" in source
        assert "_DEFAULT_EVIDENCE_WEIGHT" in source
        # Confirms the scorer still only sums SUPPORTS/CONTRADICTS --
        # no new direction-handling branch was added for this capability.
        assert source.count("EvidenceDirection.SUPPORTS") == 1
        assert source.count("EvidenceDirection.CONTRADICTS") == 1


class TestR236NoRealPeugeotRuleIntroducedByB2R2:
    """R2-36 originally asserted NO Peugeot rule existed -- correct at
    B2-R2 time. B2-R5 (a later, separately authorized block) explicitly
    introduced three real Peugeot rules on purpose. This test now
    asserts the NARROWER, still-true B2-R2-era property: the specific
    TestMfr POC selector this block itself introduced is still present
    and still exactly what B2-R2 shipped -- not that Peugeot is absent
    from the table altogether, which is no longer the case and is not
    what R2-36 was actually protecting against (accidental/unauthorized
    introduction, not deliberate, separately-mandated introduction)."""

    def test_the_testmfr_poc_selector_b2r2_introduced_is_still_present_unchanged(self):
        assert ("TestMfr", "TEST-DOC-A", "engine-diag-flashing") in _DASHBOARD_DIAGNOSTIC_RULES

    def test_testmfr_rule_specs_are_unchanged_by_later_blocks(self):
        rules = _DASHBOARD_DIAGNOSTIC_RULES[("TestMfr", "TEST-DOC-A", "engine-diag-flashing")]
        rule_ids = {spec[4] for spec in rules}
        assert rule_ids == {
            "automotive.dashboard.testmfr_engine_diag_flashing_r1_poc",
            "automotive.dashboard.testmfr_engine_diag_flashing_r2_poc",
        }
