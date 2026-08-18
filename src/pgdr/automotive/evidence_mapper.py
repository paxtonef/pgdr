"""P4 mandate §12 — AutomotiveEvidenceMapper: the automotive Domain
Pack's EvidenceMapper implementation. This is what proves the P4 mandate's
"signature test" (§24, P4-T17) — an answer to a genuinely discriminating
question must produce *different* evidence for different hypotheses, not
the same generic acknowledgment for all of them.

The one concrete discriminating rule implemented here (Q-COND-001 —
"under what conditions does the symptom occur?") is new automotive
content, written for P4, not extracted from any pre-P4 code (pre-P4 never
read this answer for anything except the static report text — see P2
Finding #4). It is intentionally the only fully-discriminating rule; every
other question falls back to a NEUTRAL, zero-weight evidence record. This
keeps the mapper's scope honest: P4 proves the MECHANISM works end to end,
not that every one of the 10 existing questions has been re-authored with
a considered discrimination rule — that remains future Domain Pack content
work, not a P4 requirement.
"""
from __future__ import annotations

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.enums import EvidenceDirection
from pgdr.domain.evidence import Evidence
from pgdr.domain.question import DiagnosticAnswer, DiagnosticQuestion
from pgdr.textnorm import normalize

# question_id -> { answer_choice_text -> { hypothesis_type -> direction } }
_DISCRIMINATING_RULES: dict[str, dict[str, dict[str, EvidenceDirection]]] = {
    "Q-COND-001": {
        "au ralenti / démarrage": {
            "engine_running": EvidenceDirection.SUPPORTS,
            "tyre_or_wheel": EvidenceDirection.CONTRADICTS,
        },
        "vitesse stabilisée": {
            "tyre_or_wheel": EvidenceDirection.SUPPORTS,
            "engine_running": EvidenceDirection.CONTRADICTS,
        },
    },
}

_DISCRIMINATING_WEIGHT = 0.35

# PROVISIONAL — weaker, support-only, free-text keyword matching. Unlike
# _DISCRIMINATING_RULES (Q-COND-001, fully authored/validated), this rule
# reuses symptom_taxonomy.yaml's own existing pneu/roue/crevaison/degonfle
# -> tyre_or_wheel keyword association — genuine existing PGDR source
# material — but applies it to a DIFFERENT observation channel (recent-
# event free text, Q-EVT-002) than where that taxonomy is normally used
# (the initial complaint). That extension itself is not independently
# validated, so it is explicitly marked PROVISIONAL rather than presented
# as equivalent-confidence to Q-COND-001. See P6 mandate §5's own
# "explicit PROVISIONAL status" escape valve (P6-T17) and
# docs/architecture/p6_evidence_mapping_registry.md for the full rationale.
_PROVISIONAL_WEIGHT = 0.15
_PROVISIONAL_KEYWORD_RULES: dict[str, list[tuple[list[str], str, EvidenceDirection, str]]] = {
    "Q-EVT-002": [
        (
            ["pneu", "roue", "crevaison", "degonfle"],
            "tyre_or_wheel",
            EvidenceDirection.SUPPORTS,
            "PROVISIONAL — l'entretien récent mentionne un pneu/une roue (vocabulaire repris de "
            "symptom_taxonomy.yaml), ce qui est compatible avec un lien vers le système roue/pneumatique. "
            "Non validé indépendamment — voir p6_evidence_mapping_registry.md.",
        ),
    ],
}


class AutomotiveEvidenceMapper:
    def from_answer(
        self,
        question: DiagnosticQuestion,
        answer: DiagnosticAnswer,
        state: DiagnosticCaseState,
    ) -> list[Evidence]:
        rule = _DISCRIMINATING_RULES.get(question.id)
        if rule is not None:
            evidence = self._apply_discriminating_rule(rule, question, answer, state)
            if evidence:
                return evidence

        provisional = _PROVISIONAL_KEYWORD_RULES.get(question.id)
        if provisional is not None:
            evidence = self._apply_provisional_keyword_rules(provisional, question, answer, state)
            if evidence:
                return evidence

        # Fallback: record that the answer was considered, without
        # asserting a direction — an explicit NEUTRAL record beats
        # silently dropping the answer's evidentiary relevance.
        return [
            Evidence(
                observation_ids=list(answer.observation_ids_created),
                direction=EvidenceDirection.NEUTRAL,
                target_hypothesis_id=h.id,
                weight=0.0,
                rationale=(
                    f"Réponse à {question.id} enregistrée ; aucune règle de "
                    f"discrimination automobile définie pour cette question."
                ),
                source_rule_id=None,
            )
            for h in state.hypotheses
            if h.id in question.target_hypothesis_ids
        ]

    @staticmethod
    def _apply_discriminating_rule(
        rule: dict[str, dict[str, EvidenceDirection]],
        question: DiagnosticQuestion,
        answer: DiagnosticAnswer,
        state: DiagnosticCaseState,
    ) -> list[Evidence]:
        raw_values = answer.value if isinstance(answer.value, list) else [answer.value]
        values = [str(v).strip() for v in raw_values]

        evidence: list[Evidence] = []
        for h in state.hypotheses:
            direction: EvidenceDirection | None = None
            for value in values:
                per_hypothesis = rule.get(value, {})
                if h.hypothesis_type in per_hypothesis:
                    direction = per_hypothesis[h.hypothesis_type]
                    break
            if direction is None:
                continue
            verb = "confirme" if direction == EvidenceDirection.SUPPORTS else "contredit"
            evidence.append(Evidence(
                observation_ids=list(answer.observation_ids_created),
                direction=direction,
                target_hypothesis_id=h.id,
                weight=_DISCRIMINATING_WEIGHT,
                rationale=f"La réponse à {question.id} ({', '.join(values)}) {verb} l'hypothèse '{h.hypothesis_type}'.",
                source_rule_id=f"automotive.{question.id.lower().replace('-', '_')}_discriminator",
            ))
        return evidence

    @staticmethod
    def _apply_provisional_keyword_rules(
        rules: list[tuple[list[str], str, EvidenceDirection, str]],
        question: DiagnosticQuestion,
        answer: DiagnosticAnswer,
        state: DiagnosticCaseState,
    ) -> list[Evidence]:
        """Free-text keyword matching (accent-insensitive, reusing the
        same pgdr.textnorm.normalize() used throughout the codebase). See
        the _PROVISIONAL_KEYWORD_RULES docstring above — weaker weight,
        clearly labeled PROVISIONAL in the rationale, not equivalent-
        confidence to a fully-authored _DISCRIMINATING_RULES entry."""
        raw_text = answer.value if isinstance(answer.value, str) else str(answer.value)
        text = normalize(raw_text)

        evidence: list[Evidence] = []
        for keywords, hypothesis_type, direction, rationale in rules:
            if not any(normalize(kw) in text for kw in keywords):
                continue
            for h in state.hypotheses:
                if h.hypothesis_type != hypothesis_type:
                    continue
                evidence.append(Evidence(
                    observation_ids=list(answer.observation_ids_created),
                    direction=direction,
                    target_hypothesis_id=h.id,
                    weight=_PROVISIONAL_WEIGHT,
                    rationale=rationale,
                    source_rule_id=f"automotive.{question.id.lower().replace('-', '_')}_provisional",
                ))
        return evidence
