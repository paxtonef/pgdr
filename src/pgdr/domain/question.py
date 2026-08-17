"""P4 mandate §10-11 — DiagnosticQuestion / DiagnosticAnswer.

The key change from the v0.1 question model: a question must carry an
explicit analytical reason (`target_uncertainty_ids` / `target_hypothesis_ids`)
— pre-P4, PGDR-INV-001 ("a question must materially affect the outcome")
was UNENFORCED because nothing recorded *why* a question was selected in
a way that could be audited (P2 Finding, `p2_findings.md`).

DiagnosticAnswer.observation_ids_created is populated by CaseStateUpdater
after the observation is created — it's the explicit link the P4 mandate
requires (§11): Answer -> Observation -> Evidence -> Hypothesis update,
never just "append to report."
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pgdr.enums import AnswerType


class DiagnosticQuestion(BaseModel):
    id: str = Field(default_factory=lambda: f"DQ-{uuid4().hex[:8].upper()}")
    text: str
    target_uncertainty_ids: list[str] = Field(default_factory=list)
    target_hypothesis_ids: list[str] = Field(default_factory=list)
    answer_type: AnswerType
    risk_level: str | None = None
    domain_ref: str | None = None
    choices: list[str] | None = None
    active: bool = True
    repeatable: bool = False


class DiagnosticAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    value: Any
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observation_ids_created: list[str] = Field(default_factory=list)
