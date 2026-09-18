"""P4 mandate §18 — AutomotiveDiagnosticDomain: the first DiagnosticDomain
implementation, built from the existing v0.1 behavior. Deliberately
delegates to the UNMODIFIED ComplaintParser and the UNMODIFIED
`_HYPOTHESIS_MAP` from diagnostic.py rather than re-encoding the
automotive knowledge — the mandate's own words: "construit à partir du
comportement actuel," and P3's boundary work already established this
table as the automotive Domain Pack's content, not engine logic.

P7 note: `_generic_hypothesis_entries()` below was relocated here from
the legacy `DiagnosticEngine._generic_entries()` staticmethod during P7's
legacy retirement — it was the one piece of that now-removed class
genuinely reachable from the production path (P7.1 audit finding), so it
was moved rather than deleted.

BLOCK B2-R1 EXTENSION (this pass) -- Automotive Diagnostic Relevance,
minimum vertical slice: a SEPARATE new method,
apply_dashboard_diagnostic_relevance(), added to this same class (the
lowest sufficient existing authority, per the B2-R1/B2-C investigations)
-- NOT part of the generic DiagnosticDomain Protocol (that Protocol's
4 methods all take `state` only, and structurally cannot carry a
DiagnosticIntakeResult's matched_reference_entries; see the
investigation's own §O finding). Called synchronously, right where a
caller already holds the DiagnosticIntakeResult B2-D/B2-C produced --
before that object goes out of scope, per B2-R1 §4. Existing
generate_hypotheses()/map_evidence()/interpret_observations()/
available_questions()/detect_contradictions() are byte-for-byte
unchanged by this pass (confirmed by diff: only additions, zero
modified lines in any pre-existing method).

_DASHBOARD_DIAGNOSTIC_RULES below is ONE controlled TEST/POC rule
(TestMfr/engine-diag-flashing, the same fixture already exercised
throughout the B2-V/B2-D/B2-C test suites) -- not real Peugeot
diagnostic knowledge, and not a rule engine/framework. Same
authored-data-constant pattern _DISCRIMINATING_RULES/
_PROVISIONAL_KEYWORD_RULES already use in automotive/evidence_mapper.py,
applied to a new fact origin.
"""
from __future__ import annotations

from pgdr.application.diagnostic_intake_from_interpretation import DiagnosticIntakeResult
from pgdr.complaint_parser import ComplaintParser
from pgdr.config_loader import load_questions
from pgdr.diagnostic import _HYPOTHESIS_MAP
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.contradiction import DiagnosticContradiction
from pgdr.domain.dashboard_knowledge import DashboardReferenceEntry
from pgdr.domain.enums import EvidenceDirection, ObservationSource
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis
from pgdr.domain.observation import Observation
from pgdr.domain.question import DiagnosticQuestion
from pgdr.enums import AnswerType, Confidence, SymptomFamily
from pgdr.models import InitialComplaint
from pgdr.textnorm import normalize

_SKIPPED_ANSWER_TYPES: set[str] = set()
# PGDR Driver Diagnostic Execution Mandate v0 §7: media_upload is no
# longer skipped. Q-EVI-002 (already gated behind Q-EVI-001==true, already
# risk_level=low, "vehicle stationary only") is now reachable; a submitted
# media answer becomes a real, retained Evidence record (see
# automotive/evidence_mapper.py) rather than being silently dropped.

# BLOCK B2-R1 -- ONE controlled TEST/POC automotive diagnostic relevance
# rule, in the same authored-data-constant style as _HYPOTHESIS_MAP /
# _DISCRIMINATING_RULES / _PROVISIONAL_KEYWORD_RULES. Keyed on a
# structured (manufacturer, entry_id) selector -- never entry_id alone
# (B2-R1 §6, and the prior investigation's own §E finding that entry_id
# alone is not version-/manufacturer-safe), never documented_meaning
# text (§17/§18). Each selector maps to a LIST of rule specs -- so ONE
# manufacturer fact can structurally drive multiple hypotheses (§8) even
# though this slice ships only one -- each spec is
# (hypothesis_type, description, EvidenceDirection, weight, rule_id).
#
# TestMfr/engine-diag-flashing is the SAME test fixture already used
# throughout test_block_b2v_visual_interpretation.py /
# test_block_b2d_diagnostic_intake.py / test_block_b2c_reference_context.py
# -- deliberately test/POC knowledge, never presented as real Peugeot
# diagnostic content (§5).
_DASHBOARD_DIAGNOSTIC_RULES: dict[tuple[str, str], list[tuple[str, str, "EvidenceDirection", float, str]]] = {
    ("TestMfr", "engine-diag-flashing"): [
        (
            "engine_running",
            "Le témoin de diagnostic moteur signalé par l'interprétation visuelle du tableau de "
            "bord est compatible avec un défaut du système de gestion moteur.",
            EvidenceDirection.SUPPORTS,
            0.3,
            "automotive.dashboard.testmfr_engine_diag_flashing",
        ),
    ],
}


def _dashboard_diagnostic_domain_ref(manufacturer: str, entry_id: str, hypothesis_type: str) -> str:
    """B2-R1 §8: the hypothesis identity/dedup key for a dashboard-fact-
    originated candidate hypothesis. Deliberately compound -- (source
    manufacturer fact) + (specific hypothesis_type) -- NOT just the
    manufacturer selector, precisely because ONE manufacturer fact may
    legitimately drive SEVERAL distinct hypotheses (FACT F -> H1, FACT F
    -> H2): if domain_ref only encoded the fact, generating H2 after H1
    already exists would incorrectly look like a duplicate of H1 to the
    existing generate_hypotheses()-style `domain_ref in already_seen`
    check this method itself replicates (see
    AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance).
    Applying the SAME rule (same fact + same hypothesis_type) a second
    time still produces the SAME domain_ref, which is exactly what makes
    hypothesis reuse (idempotency, §13) work.

    Namespaced with 'b2r_dashboard:' so this can never collide with the
    primary-symptom path's own domain_ref values (bare SymptomFamily
    strings such as 'vibration', 'noise' -- never containing a colon)."""
    return f"b2r_dashboard:{manufacturer}:{entry_id}:{hypothesis_type}"


def _generic_hypothesis_entries(family: SymptomFamily) -> list[tuple[str, str, "Confidence", list[str]]]:
    """P7 — relocated from the (now-removed) DiagnosticEngine._generic_entries
    staticmethod. This is AutomotiveDiagnosticDomain.generate_hypotheses()'s
    sole caller, and was the only production-reachable piece of the legacy
    DiagnosticEngine class (P7.1 audit finding) — moved here rather than
    removed, per the mandate's ADAPT/MOVE guidance for a still-needed
    transformation living inside an otherwise-retired component.

    Fallback for any SymptomFamily without a curated entry in
    _HYPOTHESIS_MAP. Ensures every recognized family still produces a
    genuine 'system to examine' hypothesis instead of silently degrading
    to 'unknown' — only complaints that match *no* keyword at all (true
    SymptomFamily.UNKNOWN) should ever reach that state."""
    if family == SymptomFamily.UNKNOWN:
        return _HYPOTHESIS_MAP["unknown"]
    return [(
        family.value,
        f"Les observations sont compatibles avec un problème concernant le système : {family.value}.",
        Confidence.LOW,
        [f"symptome_{family.value}"],
    )]


class AutomotiveDiagnosticDomain:
    def __init__(self) -> None:
        self._complaint_parser = ComplaintParser()
        self._questions_raw = load_questions().get("questions", [])

    # -- DiagnosticDomain protocol ---------------------------------------

    def interpret_observations(self, state: DiagnosticCaseState) -> list[Observation]:
        raw = next((o for o in state.observations if o.kind == "raw_complaint"), None)
        if raw is None:
            return []

        complaint = InitialComplaint(free_text=str(raw.value))
        extraction, symptoms = self._complaint_parser.extract(complaint)
        warning_indicators = self._complaint_parser.extract_warning_indicators(complaint)

        observations: list[Observation] = []
        for s in symptoms:
            observations.append(Observation(
                kind="symptom",
                value=s.family.value,
                source_type=ObservationSource.USER,
                source_ref=raw.id,
                context={
                    "user_description": s.user_description,
                    "frequency": s.frequency.value,
                    "severity": s.severity.value,
                    "is_primary": s.is_primary,
                },
            ))
        for wi in warning_indicators:
            observations.append(Observation(
                kind="warning_indicator",
                value=wi.label,
                source_type=ObservationSource.USER,
                source_ref=raw.id,
                context={"color": wi.observed_color.value, "behavior": wi.behavior.value},
            ))
        return observations

    def generate_hypotheses(self, state: DiagnosticCaseState) -> list[DiagnosticHypothesis]:
        primary_obs = next(
            (o for o in state.observations if o.kind == "symptom" and o.context.get("is_primary")), None
        )
        if primary_obs is None:
            return []

        already_generated_for = {h.domain_ref for h in state.hypotheses}
        family_value = primary_obs.value
        if family_value in already_generated_for:
            return []

        try:
            family = SymptomFamily(family_value)
        except ValueError:
            family = SymptomFamily.UNKNOWN

        entries = _HYPOTHESIS_MAP.get(family.value)
        if entries is None:
            entries = _generic_hypothesis_entries(family)

        return [
            DiagnosticHypothesis(
                hypothesis_type=system_family,
                description=description,
                domain_ref=family_value,
            )
            for system_family, description, confidence, tags in entries
        ]

    def map_evidence(self, state: DiagnosticCaseState) -> list[Evidence]:
        """Initial evidence: the primary symptom observation supports
        every hypothesis it originated (satisfies P4-T02/T03 — an initial
        observation must generate evidence, and that evidence must
        support a hypothesis, not just exist as an inert record)."""
        primary_obs = next(
            (o for o in state.observations if o.kind == "symptom" and o.context.get("is_primary")), None
        )
        if primary_obs is None:
            return []

        already_linked = {
            (e.target_hypothesis_id, tuple(e.observation_ids)) for e in state.evidence
        }
        evidence: list[Evidence] = []
        for h in state.hypotheses:
            if h.domain_ref != primary_obs.value:
                continue
            key = (h.id, (primary_obs.id,))
            if key in already_linked:
                continue
            evidence.append(Evidence(
                observation_ids=[primary_obs.id],
                direction=EvidenceDirection.SUPPORTS,
                target_hypothesis_id=h.id,
                weight=0.3,
                rationale=f"Symptôme initial classé dans la famille '{primary_obs.value}'.",
                source_rule_id="automotive.initial_symptom_support",
            ))
        return evidence

    def available_questions(self, state: DiagnosticCaseState) -> list[DiagnosticQuestion]:
        active_ids = [h.id for h in state.active_hypotheses()]
        answers_by_question_id = {a.question_id: a for a in state.answers}

        result: list[DiagnosticQuestion] = []
        for raw in self._questions_raw:
            if raw.get("answer_type") in _SKIPPED_ANSWER_TYPES:
                continue

            ask_if = raw.get("ask_if", "")
            if ask_if == "contradiction_detected":
                if not state.unresolved_contradictions():
                    continue
            elif ask_if and "==" in ask_if:
                dep_id, expected = ask_if.split("==", 1)
                dep_id, expected = dep_id.strip(), expected.strip().strip('"').strip("'").lower()
                dep_answer = answers_by_question_id.get(dep_id)
                if dep_answer is None or str(dep_answer.value).lower() != expected:
                    continue

            result.append(DiagnosticQuestion(
                id=raw["question_id"],
                text=raw["prompt"],
                target_hypothesis_ids=list(active_ids),
                answer_type=AnswerType(raw["answer_type"]),
                risk_level=raw.get("risk_level", "none"),
                domain_ref=raw.get("target"),
                choices=raw.get("choices"),
                repeatable=False,
                is_evidence_acquisition=bool(raw.get("evidence_acquisition", False)),
            ))
        return result

    # -- extra: not part of the DiagnosticDomain Protocol (P4's §18 names
    # 4 methods only) — contradiction detection is called explicitly by
    # SessionController._finalize(), not by DiagnosticLoop. Faithfully
    # ported from the legacy DiagnosticEngine.detect_contradictions() (P5
    # mandate §9: "SOURCE REQUIRED" — this rule has one, unlike inventing
    # new automotive knowledge would). -----------------------------------

    def detect_contradictions(self, state: DiagnosticCaseState) -> list[DiagnosticContradiction]:
        raw = next((o for o in state.observations if o.kind == "raw_complaint"), None)
        if raw is None:
            return []
        text = normalize(str(raw.value))
        contradictions: list[DiagnosticContradiction] = []

        if ("ne demarre jamais" in text or "ne demarre plus" in text) and (
            "roul" in text or "conduit" in text or "conduire" in text or "j'ai pu" in text
        ):
            contradictions.append(DiagnosticContradiction(
                evidence_ids=[],
                hypothesis_ids=[h.id for h in state.hypotheses],
                description=(
                    "Le texte indique que le véhicule ne démarre jamais / plus, mais aussi "
                    "qu'il a roulé après l'apparition du problème."
                ),
            ))

        symptom_observations = [o for o in state.observations if o.kind == "symptom"]
        frequencies = {o.context.get("frequency") for o in symptom_observations}
        if "constant" in frequencies and "rare" in frequencies:
            contradictions.append(DiagnosticContradiction(
                evidence_ids=[],
                hypothesis_ids=[h.id for h in state.hypotheses],
                description=(
                    "Un symptôme est décrit comme constant tandis qu'un autre est décrit comme rare."
                ),
            ))

        return contradictions

    # -- BLOCK B2-R1: Automotive Diagnostic Relevance, minimum vertical
    # slice. Not part of the DiagnosticDomain Protocol (see module
    # docstring) -- called explicitly and synchronously by whoever holds
    # a DiagnosticIntakeResult (B2-D/B2-C's output), before it goes out
    # of scope. Pure: reads `intake` and `state`, returns what should be
    # inserted -- never mutates `state` itself, mirroring
    # generate_hypotheses()/map_evidence()'s own existing shape exactly,
    # so the SAME existing CaseStateUpdater/scorer glue already trusted
    # for the primary-symptom path applies here unchanged. -------------

    def apply_dashboard_diagnostic_relevance(
        self, intake: DiagnosticIntakeResult, state: DiagnosticCaseState,
    ) -> tuple[list[DiagnosticHypothesis], list[Evidence]]:
        """Manufacturer Fact (the exact DashboardReferenceEntry B2-C
        transported) -> authored automotive diagnostic rule -> 0/1/N
        candidate DiagnosticHypothesis -> targeted Evidence.

        Only ever sees MATCH results: intake.matched_reference_entries
        (B2-C) is populated exclusively for match_status == MATCH: it is
        empty, and this method iterates nothing, for a MATCH-free result
        set produced entirely from AMBIGUOUS_MATCH/NO_MATCH/
        INSUFFICIENT_VISUAL_QUALITY -- no special-casing is needed here
        to keep those three states from bootstrapping manufacturer-
        identified hypotheses (B2-R1 §12); it falls out structurally
        from what B2-C already does and does not populate.

        Consumes entry.applicability.manufacturer and entry.entry_id
        only, for rule selection -- never documented_meaning (§17) and
        never documented_instruction (§18); neither field is read
        anywhere in this method's body. No KnowledgeRepositoryPort /
        VehicleDashboardKnowledgePort is used -- the exact, already-
        transported entry object is the sole source of manufacturer
        fact data (§3).

        Idempotent by construction (§13): reads state.hypotheses (for
        domain_ref-based hypothesis reuse, mirroring
        generate_hypotheses()'s own existing discipline) and
        state.evidence (for an already_linked (target_hypothesis_id,
        observation_ids) fingerprint check, mirroring map_evidence()'s
        own existing `already_linked` set exactly) BEFORE deciding what
        to return -- a second call with identical inputs returns two
        empty lists, since everything it would otherwise produce is
        already visible in `state`."""
        observations_by_id = {o.id: o for o in intake.observations}
        existing_by_domain_ref = {h.domain_ref: h for h in state.hypotheses if h.domain_ref}
        already_linked = {
            (e.target_hypothesis_id, tuple(e.observation_ids)) for e in state.evidence
        }

        new_hypotheses: list[DiagnosticHypothesis] = []
        new_evidence: list[Evidence] = []

        for observation_id, entry in intake.matched_reference_entries.items():
            observation = observations_by_id.get(observation_id)
            if observation is None:
                continue  # defensive only -- B2-D always produces a matching Observation

            selector = (entry.applicability.manufacturer, entry.entry_id)
            rules = _DASHBOARD_DIAGNOSTIC_RULES.get(selector)
            if not rules:
                continue  # §11/§12 of the investigation: UNRESOLVED, no guessing

            for hypothesis_type, description, direction, weight, rule_id in rules:
                domain_ref = _dashboard_diagnostic_domain_ref(
                    entry.applicability.manufacturer, entry.entry_id, hypothesis_type,
                )
                hypothesis = existing_by_domain_ref.get(domain_ref)
                if hypothesis is None:
                    hypothesis = DiagnosticHypothesis(
                        hypothesis_type=hypothesis_type, description=description, domain_ref=domain_ref,
                    )
                    new_hypotheses.append(hypothesis)
                    # Visible to a second rule/entry in this SAME call
                    # immediately, not only on a future call.
                    existing_by_domain_ref[domain_ref] = hypothesis

                link_key = (hypothesis.id, (observation.id,))
                if link_key in already_linked:
                    continue  # §13: this exact fact->hypothesis link already recorded
                new_evidence.append(Evidence(
                    observation_ids=[observation.id],
                    direction=direction,
                    target_hypothesis_id=hypothesis.id,
                    weight=weight,
                    rationale=(
                        f"Fait constructeur validé (entry_id={entry.entry_id}, "
                        f"manufacturer={entry.applicability.manufacturer}, "
                        f"document={entry.applicability.document_id}) observé sur le média "
                        f"{observation.context.get('media_reference')}, évalué par la règle de "
                        f"pertinence diagnostique automobile '{rule_id}'."
                    ),
                    source_rule_id=rule_id,
                ))
                already_linked.add(link_key)

        return new_hypotheses, new_evidence
