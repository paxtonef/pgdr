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

BLOCK B2-R10 EXTENSION (this pass) -- Bounded Generic-Inheritance Gate,
implementing the policy the accepted B2-R9 investigation established:

    existing validated population -> generic inheritance preserved
    new semantic origin            -> NO automatic generic inheritance
    explicit applicability established -> scoring Evidence may be produced
    applicability not established      -> no scoring Evidence (never
                                           CONTRADICTS, never a negative
                                           assertion -- B2-R9's own
                                           "not established != NOT
                                           APPLICABLE" invariant)

B2-R9's own historical investigation established WHY this is required,
not merely that it would be convenient: Q-COND-001's discriminating rule
(and Q-EVT-002's provisional one) were authored and tested exclusively
against the single-primary-symptom-derived population that existed
before B2-R1 -- at that time, `hypothesis_type` alone was a safe
selector because at most one hypothesis of any given type could ever be
active in one case. B2-R1 through B2-R5 introduced hypotheses from
entirely different semantic origins (dashboard interpretation) that can
coexist with, and share a `hypothesis_type` with, that original
population -- `hypothesis_type` equality alone is no longer sufficient
to imply the rule's original applicability (B2-R6's own empirical
finding: one Q-COND-001 answer could move three distinct, never-
reviewed Peugeot propositions' confidence identically).

Authorization representation (B2-R10 §9/§11/§12): each discriminating/
provisional rule entry now carries, alongside its EvidenceDirection, an
explicit, authored SET of exact `domain_ref` values for which
applicability has already been established -- `_LEGACY_SYMPTOM_DOMAIN_REFS`
below, reusing the EXISTING, closed `SymptomFamily` enum (not a new
vocabulary, not a string-shape heuristic). A hypothesis's `domain_ref`
must be an EXACT member of that set to inherit the rule -- checked by
plain set membership (`in`), never by parsing, splitting, or inspecting
`domain_ref`'s textual structure (B2-R10-I05). Every hypothesis
produced by the pre-B2-R1 symptom pathway has, unconditionally, a
`domain_ref` equal to some `SymptomFamily` value (confirmed structurally:
`generate_hypotheses()` sets `domain_ref=family_value`, itself always a
`SymptomFamily.value`) -- so this authorization set exactly and
completely covers the original validated population, with no
enumeration of which specific family maps to which hypothesis_type
required here (that pairing is already, and remains, entirely owned by
`_HYPOTHESIS_MAP`, unchanged). Any dashboard-derived hypothesis
(TestMfr or Peugeot, B2-R1 through B2-R5) has a structurally different
`domain_ref` (the `b2r_dashboard:...` compound format) that can never
equal a `SymptomFamily` value -- so it is correctly excluded, not
because its format was inspected, but because its actual value is
simply not a member of the authorized set. No B2-R10 rule entry
authorizes any Peugeot-specific `domain_ref` value -- per this pass's
own explicit prohibition (§10), that remains separate, not-yet-
established future work.
"""
from __future__ import annotations

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.enums import EvidenceDirection
from pgdr.domain.evidence import Evidence
from pgdr.domain.question import DiagnosticAnswer, DiagnosticQuestion
from pgdr.enums import SymptomFamily
from pgdr.textnorm import normalize

# B2-R10: the exact, authored set of domain_ref values for which generic
# Q&A rule applicability is already established -- the original
# symptom-derived population every existing discriminating/provisional
# rule was authored and tested against (B2-R9's own G2 finding). Reuses
# the EXISTING, closed SymptomFamily enum verbatim -- not a new
# vocabulary, not an inferred/heuristic set, not a string-shape check.
# Every symptom-path hypothesis has domain_ref == some SymptomFamily
# value BY CONSTRUCTION (AutomotiveDiagnosticDomain.generate_hypotheses()
# sets domain_ref=family_value, itself always a SymptomFamily.value) --
# so exact membership in this set is both necessary and sufficient to
# identify that population, without inspecting domain_ref's format at
# all (B2-R10-I05/I12).
_LEGACY_SYMPTOM_DOMAIN_REFS: frozenset[str] = frozenset(family.value for family in SymptomFamily)

# question_id -> { answer_choice_text -> { hypothesis_type -> (direction, authorized_domain_refs) } }
# B2-R10: each entry now carries its authorized domain_ref set alongside
# direction -- hypothesis_type alone is no longer sufficient authorization
# (B2-R9). Both existing rules below authorize exactly the pre-existing
# validated population (_LEGACY_SYMPTOM_DOMAIN_REFS) -- neither rule's
# own direction/weight/meaning changes for that population; only
# hypotheses OUTSIDE it are now correctly excluded.
_DISCRIMINATING_RULES: dict[str, dict[str, dict[str, tuple[EvidenceDirection, frozenset[str]]]]] = {
    "Q-COND-001": {
        "au ralenti / démarrage": {
            "engine_running": (EvidenceDirection.SUPPORTS, _LEGACY_SYMPTOM_DOMAIN_REFS),
            "tyre_or_wheel": (EvidenceDirection.CONTRADICTS, _LEGACY_SYMPTOM_DOMAIN_REFS),
        },
        "à vitesse stabilisée": {
            "tyre_or_wheel": (EvidenceDirection.SUPPORTS, _LEGACY_SYMPTOM_DOMAIN_REFS),
            "engine_running": (EvidenceDirection.CONTRADICTS, _LEGACY_SYMPTOM_DOMAIN_REFS),
        },
    },
}

_DISCRIMINATING_WEIGHT = 0.35

# PGDR Driver Diagnostic Execution Mandate v0 §7: a submitted media answer
# must become real, retained Evidence, not be discarded. Deliberately
# NEUTRAL / zero-weight — this release requests, receives, and preserves
# the evidence reference with full provenance; it does NOT interpret the
# media's content (automatic dashboard-light recognition is explicitly a
# later capability, §7/§15). One record per hypothesis the question
# targeted (mandate §7's "provenance... case association"). Unaffected by
# B2-R10: this path is already non-scoring (NEUTRAL/0.0) and already
# targets via question.target_hypothesis_ids, not hypothesis_type -- it
# never had an inheritance-authority problem to close.
MEDIA_EVIDENCE_SOURCE_RULE_ID = "automotive.media_evidence_acquired"

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
#
# B2-R10: same authorization gate as _DISCRIMINATING_RULES above (B2-R9's
# own "same selector contract required" finding) -- an authorized
# domain_ref set is now part of each entry, still exactly
# _LEGACY_SYMPTOM_DOMAIN_REFS for this rule's own existing, unchanged
# population.
_PROVISIONAL_WEIGHT = 0.15
_PROVISIONAL_KEYWORD_RULES: dict[str, list[tuple[list[str], str, EvidenceDirection, str, frozenset[str]]]] = {
    "Q-EVT-002": [
        (
            ["pneu", "roue", "crevaison", "degonfle"],
            "tyre_or_wheel",
            EvidenceDirection.SUPPORTS,
            "PROVISIONAL — l'entretien récent mentionne un pneu/une roue (vocabulaire repris de "
            "symptom_taxonomy.yaml), ce qui est compatible avec un lien vers le système roue/pneumatique. "
            "Non validé indépendamment — voir p6_evidence_mapping_registry.md.",
            _LEGACY_SYMPTOM_DOMAIN_REFS,
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
        if question.answer_type == "media_upload":
            return self._apply_media_evidence_rule(question, answer, state)

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
    def _apply_media_evidence_rule(
        question: DiagnosticQuestion,
        answer: DiagnosticAnswer,
        state: DiagnosticCaseState,
    ) -> list[Evidence]:
        reference = answer.value if isinstance(answer.value, str) else str(answer.value)
        return [
            Evidence(
                observation_ids=list(answer.observation_ids_created),
                direction=EvidenceDirection.NEUTRAL,
                target_hypothesis_id=h.id,
                weight=0.0,
                rationale=(
                    f"Preuve reçue en réponse à {question.id} ({question.text}) — référence : {reference}. "
                    f"Aucune interprétation automatique du contenu n'est effectuée à ce stade."
                ),
                source_rule_id=MEDIA_EVIDENCE_SOURCE_RULE_ID,
            )
            for h in state.hypotheses
            if h.id in question.target_hypothesis_ids
        ]

    @staticmethod
    def _apply_discriminating_rule(
        rule: dict[str, dict[str, tuple[EvidenceDirection, frozenset[str]]]],
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
                entry = per_hypothesis.get(h.hypothesis_type)
                if entry is None:
                    continue
                # B2-R10-I02/I03: hypothesis_type membership alone is no
                # longer sufficient -- domain_ref must be an EXACT member
                # of this entry's own authorized set (checked by plain
                # set membership, never by parsing/inspecting domain_ref's
                # format, per B2-R10-I05). No match here means
                # "applicability not established for this hypothesis",
                # never a negative assertion (B2-R10-I04) -- the loop
                # simply continues to the next candidate answer value, and
                # if none authorize it, this hypothesis receives no
                # scoring Evidence at all from this rule (see below).
                rule_direction, authorized_domain_refs = entry
                if h.domain_ref not in authorized_domain_refs:
                    continue
                direction = rule_direction
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
        rules: list[tuple[list[str], str, EvidenceDirection, str, frozenset[str]]],
        question: DiagnosticQuestion,
        answer: DiagnosticAnswer,
        state: DiagnosticCaseState,
    ) -> list[Evidence]:
        """Free-text keyword matching (accent-insensitive, reusing the
        same pgdr.textnorm.normalize() used throughout the codebase). See
        the _PROVISIONAL_KEYWORD_RULES docstring above — weaker weight,
        clearly labeled PROVISIONAL in the rationale, not equivalent-
        confidence to a fully-authored _DISCRIMINATING_RULES entry.

        B2-R10: same authorization gate as _apply_discriminating_rule --
        hypothesis_type match is necessary but no longer sufficient;
        h.domain_ref must also be an exact member of this rule's own
        authorized set."""
        raw_text = answer.value if isinstance(answer.value, str) else str(answer.value)
        text = normalize(raw_text)

        evidence: list[Evidence] = []
        for keywords, hypothesis_type, direction, rationale, authorized_domain_refs in rules:
            if not any(normalize(kw) in text for kw in keywords):
                continue
            for h in state.hypotheses:
                if h.hypothesis_type != hypothesis_type:
                    continue
                if h.domain_ref not in authorized_domain_refs:
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
