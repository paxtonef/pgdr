"""P5 mandate §10 — three statuses for question migration. Computed from
the actual loaded configuration (questions.yaml + AutomotiveEvidenceMapper's
_DISCRIMINATING_RULES + AutomotiveDiagnosticDomain's _SKIPPED_ANSWER_TYPES)
rather than hand-typed here — this is deliberate: a hand-maintained list
drifts from the code the moment either changes, and P5's own principle
(§9: "SOURCE REQUIRED") applies equally to documentation about the domain,
not only to the domain rules themselves.

    MAPPED  — has an explicit, testable evidence rule (a genuine analytical effect)
    NEUTRAL — becomes an observation, no validated hypothesis effect yet
    LEGACY  — cannot yet be represented safely in v2 (today: media_upload,
              since the Evidence/photo pipeline is dormant end-to-end — P2 Finding #7)

P5's target is NOT 100% MAPPED (mandate §10 is explicit about this) — it
is 100% explicitly classified, so no question gives the impression of
influencing the diagnosis when it structurally cannot.
"""
from __future__ import annotations

from enum import Enum

from pgdr.automotive.evidence_mapper import _DISCRIMINATING_RULES
from pgdr.config_loader import load_questions


class QuestionMigrationStatus(str, Enum):
    MAPPED = "MAPPED"
    NEUTRAL = "NEUTRAL"
    LEGACY = "LEGACY"


_LEGACY_ANSWER_TYPES = {"media_upload"}


def classify_questions() -> dict[str, QuestionMigrationStatus]:
    result: dict[str, QuestionMigrationStatus] = {}
    for q in load_questions().get("questions", []):
        qid = q["question_id"]
        if q.get("answer_type") in _LEGACY_ANSWER_TYPES:
            result[qid] = QuestionMigrationStatus.LEGACY
        elif qid in _DISCRIMINATING_RULES:
            result[qid] = QuestionMigrationStatus.MAPPED
        else:
            result[qid] = QuestionMigrationStatus.NEUTRAL
    return result
