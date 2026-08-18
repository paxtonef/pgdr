"""P5 mandate §29 — AutomotiveDomainValidator: validates the automotive
Domain Pack's internal configuration consistency at STARTUP, not mid-
session (§28). Reuses `pgdr.errors.ConfigurationError` — the same
fail-closed signal P0 established for the safety envelope — for the same
reason: a broken domain configuration should block the runner from
becoming ready, not surface as a confusing failure partway through a
user's diagnostic session.

This does NOT duplicate P0's safety_rules.yaml validation (that stays
exactly as P0 left it, untouched). It validates the NEW P5 domain
relations: does every evidence-mapping rule reference a hypothesis_type
that actually exists in the hypothesis map, does every rule reference a
real question_id, are declared weights in range.
"""
from __future__ import annotations

from pgdr.config_loader import load_questions
from pgdr.diagnostic import _HYPOTHESIS_MAP
from pgdr.errors import ConfigurationError


def _all_declared_hypothesis_types() -> set[str]:
    types: set[str] = set()
    for entries in _HYPOTHESIS_MAP.values():
        for system_family, _description, _confidence, _tags in entries:
            types.add(system_family)
    return types


def validate_automotive_domain() -> None:
    """Raises ConfigurationError on the first violation found. Call once,
    at startup (SessionController.__init__ does this)."""
    from pgdr.automotive.evidence_mapper import (
        _DISCRIMINATING_RULES, _DISCRIMINATING_WEIGHT, _PROVISIONAL_KEYWORD_RULES, _PROVISIONAL_WEIGHT,
    )

    declared_types = _all_declared_hypothesis_types()
    question_ids = {q["question_id"] for q in load_questions().get("questions", [])}

    raw_questions = load_questions().get("questions", [])
    seen_question_ids: set[str] = set()
    for q in raw_questions:
        qid = q.get("question_id")
        if not qid:
            raise ConfigurationError("questions.yaml: a question is missing 'question_id'")
        if qid in seen_question_ids:
            raise ConfigurationError(f"questions.yaml: duplicate question_id '{qid}'")
        seen_question_ids.add(qid)

    for question_id, value_rules in _DISCRIMINATING_RULES.items():
        if question_id not in question_ids:
            raise ConfigurationError(
                f"AutomotiveEvidenceMapper: discriminating rule references unknown "
                f"question_id '{question_id}' — no such question in questions.yaml"
            )
        for value, per_hypothesis in value_rules.items():
            if not per_hypothesis:
                raise ConfigurationError(
                    f"AutomotiveEvidenceMapper: rule for {question_id}='{value}' is empty"
                )
            for hypothesis_type in per_hypothesis:
                if hypothesis_type not in declared_types:
                    raise ConfigurationError(
                        f"AutomotiveEvidenceMapper: rule for {question_id}='{value}' targets "
                        f"hypothesis_type '{hypothesis_type}', which does not appear in any "
                        f"_HYPOTHESIS_MAP entry — dangling domain reference"
                    )
    if not (0.0 <= _DISCRIMINATING_WEIGHT <= 1.0):
        raise ConfigurationError(
            f"AutomotiveEvidenceMapper: _DISCRIMINATING_WEIGHT ({_DISCRIMINATING_WEIGHT}) out of bounds [0,1]"
        )

    # P6 — provisional keyword-based rules get the same dangling-reference
    # and weight-bounds checks. PROVISIONAL status (see p6_evidence_mapping_registry.md)
    # is about evidentiary confidence, not about being exempt from
    # structural configuration validation.
    if not (0.0 <= _PROVISIONAL_WEIGHT <= 1.0):
        raise ConfigurationError(
            f"AutomotiveEvidenceMapper: _PROVISIONAL_WEIGHT ({_PROVISIONAL_WEIGHT}) out of bounds [0,1]"
        )
    for question_id, rules in _PROVISIONAL_KEYWORD_RULES.items():
        if question_id not in question_ids:
            raise ConfigurationError(
                f"AutomotiveEvidenceMapper: provisional rule references unknown "
                f"question_id '{question_id}' — no such question in questions.yaml"
            )
        for keywords, hypothesis_type, direction, rationale in rules:
            if not keywords:
                raise ConfigurationError(
                    f"AutomotiveEvidenceMapper: provisional rule for {question_id} has no keywords"
                )
            if hypothesis_type not in declared_types:
                raise ConfigurationError(
                    f"AutomotiveEvidenceMapper: provisional rule for {question_id} targets "
                    f"hypothesis_type '{hypothesis_type}', which does not appear in any "
                    f"_HYPOTHESIS_MAP entry — dangling domain reference"
                )
            if not rationale or "PROVISIONAL" not in rationale:
                raise ConfigurationError(
                    f"AutomotiveEvidenceMapper: provisional rule for {question_id} -> "
                    f"'{hypothesis_type}' must carry a rationale explicitly marked PROVISIONAL "
                    f"(P6-T17: every mapping needs source/rationale metadata OR explicit "
                    f"PROVISIONAL status)"
                )
