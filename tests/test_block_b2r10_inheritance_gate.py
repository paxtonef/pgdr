"""Block B2-R10 — Bounded Generic-Inheritance Gate.

Proves the B2-R9 policy is correctly implemented: existing generic Q&A
rules (Q-COND-001 discriminating, Q-EVT-002 provisional) remain valid
for the original symptom-derived population they were authored and
tested against, but no longer automatically apply to hypotheses from a
different semantic origin merely because they share a hypothesis_type.

Uses the real, unmodified AutomotiveEvidenceMapper and the real,
authored _DISCRIMINATING_RULES/_PROVISIONAL_KEYWORD_RULES tables
throughout -- no test reimplements the gate logic. Synthetic (non-
Peugeot) origin labels are used for the generic new-origin tests, per
the mandate's own explicit instruction (§23) that this invariant must
not become accidentally equivalent to "block Peugeot specifically".
Real B2-R5 Peugeot hypotheses are used separately for the Peugeot
acceptance case (§19), built via the real build_diagnostic_intake()
pipeline, never hand-constructed.
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
from pgdr.automotive import evidence_mapper as evidence_mapper_module
from pgdr.automotive.domain_adapter import AutomotiveDiagnosticDomain
from pgdr.automotive.evidence_mapper import (
    _DISCRIMINATING_RULES, _LEGACY_SYMPTOM_DOMAIN_REFS, _PROVISIONAL_KEYWORD_RULES,
    AutomotiveEvidenceMapper,
)
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.dashboard_knowledge import (
    ApplicabilityStatus, DashboardReferenceEntry, DashboardReferenceSet, IndicatorState,
    ManufacturerDocumentReference, SourceAuthority, VehicleApplicabilityContext,
)
from pgdr.domain.enums import EvidenceDirection
from pgdr.domain.hypothesis import DiagnosticHypothesis
from pgdr.domain.media import MediaType
from pgdr.domain.question import DiagnosticAnswer, DiagnosticQuestion
from pgdr.enums import Confidence
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationResult, InterpretationProvenance, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia

mapper = AutomotiveEvidenceMapper()


def _question(target_hypothesis_ids: list[str] | None = None) -> DiagnosticQuestion:
    return DiagnosticQuestion(
        id="Q-COND-001", text="...", target_hypothesis_ids=target_hypothesis_ids or [],
        answer_type="single_choice", risk_level="none", domain_ref="operating_condition",
        choices=["au ralenti / démarrage", "à vitesse stabilisée"],
    )


def _answer(value, obs_id: str = "OBS-B2R10") -> DiagnosticAnswer:
    return DiagnosticAnswer(question_id="Q-COND-001", value=value, observation_ids_created=[obs_id])


def _evt002_question() -> DiagnosticQuestion:
    return DiagnosticQuestion(
        id="Q-EVT-002", text="...", target_hypothesis_ids=[], answer_type="text", risk_level="none",
    )


# ---------------------------------------------------------------------------
# 1/2 — legacy engine_running / tyre_or_wheel behavior preserved
# ---------------------------------------------------------------------------

class TestLegacyEngineRunningPreserved:
    def test_legacy_symptom_hypothesis_still_receives_supports(self):
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(hypothesis_type="engine_running", description="legacy", domain_ref="vibration")
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_question([h.id]), _answer(["au ralenti / démarrage"]), state)
        assert len(evidence) == 1
        assert evidence[0].direction == EvidenceDirection.SUPPORTS
        assert evidence[0].weight == 0.35
        assert evidence[0].target_hypothesis_id == h.id

    def test_legacy_symptom_hypothesis_still_receives_contradicts_for_opposite_answer(self):
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(hypothesis_type="engine_running", description="legacy", domain_ref="vibration")
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_question([h.id]), _answer(["à vitesse stabilisée"]), state)
        assert len(evidence) == 1
        assert evidence[0].direction == EvidenceDirection.CONTRADICTS


class TestLegacyTyreOrWheelPreserved:
    def test_legacy_symptom_hypothesis_still_receives_supports(self):
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(hypothesis_type="tyre_or_wheel", description="legacy", domain_ref="vibration")
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_question([h.id]), _answer(["à vitesse stabilisée"]), state)
        assert len(evidence) == 1
        assert evidence[0].direction == EvidenceDirection.SUPPORTS
        assert evidence[0].weight == 0.35


# ---------------------------------------------------------------------------
# 3 — synthetic new-origin engine_running does not inherit automatically
# ---------------------------------------------------------------------------

class TestSyntheticNewOriginDoesNotInherit:
    def test_synthetic_new_origin_hypothesis_receives_no_scoring_evidence(self):
        """Deliberately NOT Peugeot -- a purely synthetic origin label,
        per the mandate's own §23 instruction, proving the gate is
        generic and not accidentally equivalent to 'block Peugeot'."""
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(
            hypothesis_type="engine_running", description="synthetic new-origin",
            domain_ref="synthetic_origin:acme_corp:fact-1:engine_running",
        )
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_question([h.id]), _answer(["au ralenti / démarrage"]), state)
        # The lone hypothesis is unauthorized, so the discriminating path
        # produces nothing for it and the dispatcher legitimately falls
        # through to the EXISTING, unchanged NEUTRAL fallback (§17 of the
        # mandate: that pre-existing behavior may remain). The invariant
        # under test is absence of SCORING evidence, not absence of any
        # Evidence record at all.
        assert all(e.direction != EvidenceDirection.SUPPORTS for e in evidence)
        assert all(e.direction != EvidenceDirection.CONTRADICTS for e in evidence)


# ---------------------------------------------------------------------------
# 4/5/6/7 — Peugeot P1/P2/P3 do not inherit Q-COND-001; no confidence movement
# ---------------------------------------------------------------------------

_PEUGEOT_DOC = ManufacturerDocumentReference(
    manufacturer="Peugeot", document_id="9999_9999_326_en-GB",
    document_title="MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL,
    source_locator="Peugeot Service Box, document 9999_9999_326_en-GB.pdf",
)
_PEUGEOT_ENTRIES = {
    "oil-pressure-warning": DashboardReferenceEntry(
        entry_id="oil-pressure-warning", manufacturer_designation="Engine oil pressure",
        colour="red", state=IndicatorState.FIXED,
        documented_meaning="Fault with the engine lubrication system.", applicability=_PEUGEOT_DOC,
    ),
    "engine-diag-fixed": DashboardReferenceEntry(
        entry_id="engine-diag-fixed", manufacturer_designation="Engine self-diagnostic system",
        colour="orange", state=IndicatorState.FIXED,
        documented_meaning="Fault in the emissions control system.", applicability=_PEUGEOT_DOC,
    ),
    "engine-diag-flashing": DashboardReferenceEntry(
        entry_id="engine-diag-flashing", manufacturer_designation="Engine self-diagnostic system",
        colour="orange", state=IndicatorState.FLASHING,
        documented_meaning="Fault in the engine management system.", applicability=_PEUGEOT_DOC,
    ),
}
_RESOLVED_MEDIA = ResolvedMedia(content=b"\xff\xd8\xff-fake", media_type=MediaType.IMAGE, reference="media-b2r10")


class _ScriptedProvider:
    def __init__(self, planned):
        self.planned = planned

    def interpret(self, media, reference_set):
        return self.planned


def _provenance():
    return InterpretationProvenance(adapter_id="scripted", media_reference=_RESOLVED_MEDIA.reference)


def _match_result(entry_id):
    return DashboardInterpretationResult(
        observation=f"match {entry_id}", observation_confidence=Confidence.HIGH,
        match_status=MatchStatus.MATCH, matched_reference_entry_id=entry_id,
        match_confidence=Confidence.HIGH, provenance=_provenance(),
    )


def _reference_set(entry):
    return DashboardReferenceSet(
        vehicle_applicability=VehicleApplicabilityContext(manufacturer="Peugeot", model="3008", generation="II"),
        candidate_documents=[_PEUGEOT_DOC], entries=[entry],
        applicability_status=ApplicabilityStatus.REFERENCE_SET_AVAILABLE,
    )


def _peugeot_state_with_p1_p2_p3():
    domain = AutomotiveDiagnosticDomain()
    updater = CaseStateUpdater(DeterministicHypothesisScorer())
    state = DiagnosticCaseState()
    for entry_id, entry in _PEUGEOT_ENTRIES.items():
        provider = _ScriptedProvider([_match_result(entry_id)])
        intake = build_diagnostic_intake(provider, _RESOLVED_MEDIA, _reference_set(entry))
        new_hyp, new_evd = domain.apply_dashboard_diagnostic_relevance(intake, state)
        if new_hyp:
            state.hypotheses.extend(new_hyp)
            state.touch()
        if new_evd:
            updater.add_evidence(state, new_evd)
    return updater, state


class TestPeugeotDoesNotInheritQCond001:
    def test_p1_p2_p3_receive_no_scoring_evidence_from_q_cond_001(self):
        updater, state = _peugeot_state_with_p1_p2_p3()
        target_ids = [h.id for h in state.hypotheses]
        evidence = mapper.from_answer(_question(target_ids), _answer(["au ralenti / démarrage"]), state)
        # Only non-scoring (NEUTRAL) evidence, if any, may result --
        # never SUPPORTS/CONTRADICTS for any of the three.
        assert all(e.direction != EvidenceDirection.SUPPORTS for e in evidence)
        assert all(e.direction != EvidenceDirection.CONTRADICTS for e in evidence)

    def test_no_confidence_movement_for_p1_p2_p3_from_q_cond_001(self):
        updater, state = _peugeot_state_with_p1_p2_p3()
        before = {h.id: h.confidence for h in state.hypotheses}
        assert all(c == pytest.approx(0.3) for c in before.values())  # B2-R5 bootstrap baseline

        target_ids = [h.id for h in state.hypotheses]
        question = _question(target_ids)
        answer = _answer(["au ralenti / démarrage"])
        new_evidence = mapper.from_answer(question, answer, state)
        if new_evidence:
            updater.add_evidence(state, new_evidence)

        after = {h.id: h.confidence for h in state.hypotheses}
        assert after == before  # unchanged -- Q-COND-001 alone must not move them


# ---------------------------------------------------------------------------
# 9 — same type + different exact identity remains unauthorized
# ---------------------------------------------------------------------------

class TestDifferentExactIdentityRemainsUnauthorized:
    def test_domain_ref_not_in_authorized_set_is_denied_even_if_similar(self):
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(
            hypothesis_type="engine_running", description="not a real symptom family",
            domain_ref="vibration_but_not_quite",  # deliberately close but NOT an exact SymptomFamily value
        )
        state.hypotheses.append(h)
        assert h.domain_ref not in _LEGACY_SYMPTOM_DOMAIN_REFS
        evidence = mapper.from_answer(_question([h.id]), _answer(["au ralenti / démarrage"]), state)
        # Lone unauthorized hypothesis -> discriminating path yields
        # nothing for it, dispatcher may legitimately fall through to
        # the existing NEUTRAL fallback (§17) -- the invariant is
        # absence of SCORING evidence, not absence of any Evidence.
        assert all(e.direction != EvidenceDirection.SUPPORTS for e in evidence)
        assert all(e.direction != EvidenceDirection.CONTRADICTS for e in evidence)


# ---------------------------------------------------------------------------
# 10 — domain_ref textual FORMAT has no semantic effect (only exact value)
# ---------------------------------------------------------------------------

class TestDomainRefFormatIndependence:
    def test_denial_does_not_depend_on_colon_presence(self):
        """Two unauthorized values, one WITH colons (dashboard-style
        format) and one WITHOUT (bare-word format) -- both must be
        denied identically, proving denial is based on exact non-
        membership, never on inspecting the string's shape."""
        state = DiagnosticCaseState()
        h_with_colons = DiagnosticHypothesis(
            hypothesis_type="engine_running", description="unauthorized, colon format",
            domain_ref="not:authorized:at:all",
        )
        h_without_colons = DiagnosticHypothesis(
            hypothesis_type="engine_running", description="unauthorized, bare format",
            domain_ref="notauthorizedatall",
        )
        state.hypotheses.extend([h_with_colons, h_without_colons])
        evidence = mapper.from_answer(
            _question([h_with_colons.id, h_without_colons.id]), _answer(["au ralenti / démarrage"]), state,
        )
        # Both unauthorized -> no SCORING evidence for either, regardless
        # of the fallback NEUTRAL record's existence (§17).
        assert all(e.direction != EvidenceDirection.SUPPORTS for e in evidence)
        assert all(e.direction != EvidenceDirection.CONTRADICTS for e in evidence)

    def test_authorization_works_for_a_colon_containing_value_if_explicitly_authored(self, monkeypatch):
        """Proves the mechanism itself is format-agnostic in the OTHER
        direction too: a colon-containing domain_ref, if explicitly
        placed in an authorized set, IS authorized -- authorization
        depends solely on exact membership, never on absence of
        colons either. Uses a monkeypatched, test-local rule -- the
        real production tables are never touched."""
        synthetic_authorized_set = frozenset({"synthetic:with:colons:value"})
        test_rules = {
            "Q-COND-001": {
                "au ralenti / démarrage": {
                    "engine_running": (EvidenceDirection.SUPPORTS, synthetic_authorized_set),
                },
            },
        }
        monkeypatch.setattr(evidence_mapper_module, "_DISCRIMINATING_RULES", test_rules)

        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(
            hypothesis_type="engine_running", description="colon-format but explicitly authorized",
            domain_ref="synthetic:with:colons:value",
        )
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_question([h.id]), _answer(["au ralenti / démarrage"]), state)
        assert len(evidence) == 1
        assert evidence[0].direction == EvidenceDirection.SUPPORTS


# ---------------------------------------------------------------------------
# 11 — mixed authorized/unauthorized hypotheses behave independently
# ---------------------------------------------------------------------------

class TestMixedAuthorizedAndUnauthorizedIndependence:
    def test_legacy_gets_evidence_synthetic_new_origin_does_not_same_call(self):
        state = DiagnosticCaseState()
        h_legacy = DiagnosticHypothesis(hypothesis_type="engine_running", description="legacy", domain_ref="noise")
        h_new = DiagnosticHypothesis(
            hypothesis_type="engine_running", description="new-origin",
            domain_ref="synthetic_origin:other_corp:fact-2:engine_running",
        )
        state.hypotheses.extend([h_legacy, h_new])
        evidence = mapper.from_answer(
            _question([h_legacy.id, h_new.id]), _answer(["au ralenti / démarrage"]), state,
        )
        targets = {e.target_hypothesis_id for e in evidence}
        assert h_legacy.id in targets
        assert h_new.id not in targets
        assert len(evidence) == 1  # H2's confidence cannot move -- no Evidence targets it at all


# ---------------------------------------------------------------------------
# 12 — single-outcome guarantee (I09)
# ---------------------------------------------------------------------------

class TestSingleOutcomeGuarantee:
    def test_at_most_one_scoring_evidence_per_hypothesis_per_call(self):
        """By construction (one (direction, authorized_set) tuple per
        hypothesis_type key, per answer value), no hypothesis can ever
        receive more than one discriminating-rule Evidence record from
        a single from_answer() call -- confirmed directly, not merely
        assumed from the data shape."""
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(hypothesis_type="engine_running", description="legacy", domain_ref="vibration")
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_question([h.id]), _answer(["au ralenti / démarrage"]), state)
        matching_this_hypothesis = [e for e in evidence if e.target_hypothesis_id == h.id]
        assert len(matching_this_hypothesis) == 1


# ---------------------------------------------------------------------------
# 13/14 — provisional legacy preserved / synthetic new-origin blocked
# ---------------------------------------------------------------------------

class TestProvisionalLegacyPreserved:
    def test_legacy_tyre_or_wheel_still_matches_keyword_rule(self):
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(hypothesis_type="tyre_or_wheel", description="legacy", domain_ref="vibration")
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_evt002_question(), _answer("j'ai changé un pneu récemment"), state)
        assert len(evidence) == 1
        assert evidence[0].direction == EvidenceDirection.SUPPORTS
        assert evidence[0].weight == 0.15


class TestProvisionalSyntheticNewOriginBlocked:
    def test_synthetic_new_origin_tyre_or_wheel_does_not_inherit_provisional_rule(self):
        state = DiagnosticCaseState()
        h = DiagnosticHypothesis(
            hypothesis_type="tyre_or_wheel", description="synthetic new-origin",
            domain_ref="synthetic_origin:acme_corp:fact-3:tyre_or_wheel",
        )
        state.hypotheses.append(h)
        evidence = mapper.from_answer(_evt002_question(), _answer("j'ai changé un pneu récemment"), state)
        assert evidence == []


# ---------------------------------------------------------------------------
# 15 — no new NOT_APPLICABLE/UNKNOWN/tri-state introduced
# ---------------------------------------------------------------------------

class TestNoTriStateIntroduced:
    def test_evidence_direction_enum_unchanged(self):
        values = {d.value for d in EvidenceDirection}
        assert values == {"SUPPORTS", "CONTRADICTS", "NEUTRAL"}

    def test_no_not_applicable_or_unknown_token_in_evidence_mapper_module(self):
        import inspect
        source = inspect.getsource(evidence_mapper_module)
        assert "NOT_APPLICABLE" not in source
        assert "UNKNOWN" not in source


# ---------------------------------------------------------------------------
# 16 — scorer unchanged
# ---------------------------------------------------------------------------

class TestScorerUnchanged:
    def test_scorer_module_untouched(self):
        import inspect
        from pgdr.application import hypothesis_scorer as scorer_module
        assert scorer_module._BASELINE == 0.3
        assert scorer_module._DEFAULT_EVIDENCE_WEIGHT == 0.2
        source = inspect.getsource(scorer_module)
        assert source.count("EvidenceDirection.SUPPORTS") == 1
        assert source.count("EvidenceDirection.CONTRADICTS") == 1


# ---------------------------------------------------------------------------
# 17 — existing B2-R5 invariants remain valid
# ---------------------------------------------------------------------------

class TestB2R5InvariantsStillHold:
    def test_peugeot_bootstrap_evidence_still_neutral_zero_weight(self):
        _updater, state = _peugeot_state_with_p1_p2_p3()
        bootstrap_evidence = [e for e in state.evidence if e.source_rule_id and "peugeot" in e.source_rule_id]
        assert len(bootstrap_evidence) == 3
        assert all(e.direction == EvidenceDirection.NEUTRAL for e in bootstrap_evidence)
        assert all(e.weight == 0.0 for e in bootstrap_evidence)

    def test_peugeot_hypotheses_still_distinct_domain_refs(self):
        _updater, state = _peugeot_state_with_p1_p2_p3()
        assert len({h.domain_ref for h in state.hypotheses}) == 3


# ---------------------------------------------------------------------------
# Non-goals explicitly reconfirmed: no Peugeot applicability authored,
# no domain_ref parsing anywhere in the touched module.
# ---------------------------------------------------------------------------

class TestNoPeugeotApplicabilityAuthored:
    def test_no_peugeot_domain_ref_value_appears_in_any_authorized_set(self):
        for value_rules in _DISCRIMINATING_RULES.values():
            for per_hypothesis in value_rules.values():
                for _direction, authorized_domain_refs in per_hypothesis.values():
                    for value in authorized_domain_refs:
                        assert "peugeot" not in value.lower()
                        assert "b2r_dashboard" not in value.lower()
        for rules in _PROVISIONAL_KEYWORD_RULES.values():
            for _keywords, _hypothesis_type, _direction, _rationale, authorized_domain_refs in rules:
                for value in authorized_domain_refs:
                    assert "peugeot" not in value.lower()
                    assert "b2r_dashboard" not in value.lower()


class TestNoDomainRefParsing:
    def test_discriminating_rule_body_never_parses_domain_ref(self):
        import inspect
        source = inspect.getsource(AutomotiveEvidenceMapper._apply_discriminating_rule)
        body = source.split('"""', 2)[-1] if source.count('"""') >= 2 else source
        assert ".split(" not in body
        assert ".startswith(" not in body
        assert '":" in' not in body

    def test_provisional_rule_body_never_parses_domain_ref(self):
        import inspect
        source = inspect.getsource(AutomotiveEvidenceMapper._apply_provisional_keyword_rules)
        forbidden_snippets = [".split(", ".startswith("]
        body = source.split('"""', 2)[-1] if source.count('"""') >= 2 else source
        for snippet in forbidden_snippets:
            assert snippet not in body


class TestManufacturerNeutralExecution:
    def test_no_manufacturer_branch_in_evidence_mapper(self):
        import inspect
        source = inspect.getsource(AutomotiveEvidenceMapper)
        assert "Peugeot" not in source
        assert "TestMfr" not in source
        assert "manufacturer ==" not in source
