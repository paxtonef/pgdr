"""P4 mandate §18 — AutomotiveDiagnosticDomain: the first DiagnosticDomain
implementation, built from the existing v0.1 behavior. Deliberately
delegates to the UNMODIFIED ComplaintParser and the UNMODIFIED
`_HYPOTHESIS_MAP` from diagnostic.py rather than re-encoding the
automotive knowledge — the mandate's own words: "construit à partir du
comportement actuel," and P3's boundary work already established this
table as the automotive Domain Pack's content, not engine logic.
"""
from __future__ import annotations

from pgdr.complaint_parser import ComplaintParser
from pgdr.config_loader import load_questions
from pgdr.diagnostic import DiagnosticEngine, _HYPOTHESIS_MAP
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.contradiction import DiagnosticContradiction
from pgdr.domain.enums import EvidenceDirection, ObservationSource
from pgdr.domain.evidence import Evidence
from pgdr.domain.hypothesis import DiagnosticHypothesis
from pgdr.domain.observation import Observation
from pgdr.domain.question import DiagnosticQuestion
from pgdr.enums import AnswerType, SymptomFamily
from pgdr.models import InitialComplaint
from pgdr.textnorm import normalize

_SKIPPED_ANSWER_TYPES = {"media_upload"}  # evidence pipeline for media not wired in P4 — see notes


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
            entries = DiagnosticEngine._generic_entries(family)

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
