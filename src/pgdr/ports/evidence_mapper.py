"""P4 mandate §12 — EvidenceMapper is "probably the central component of
P4" per the mandate. The mechanism (turn an answer into evidence) is
generic; the mapping RULES ("cold-only -> supports H1, contradicts H3")
are automotive Domain Pack content, per P3's generic/automotive boundary
(this is exactly the DomainHypothesisProvider/DomainObservationInterpreter
boundary P3 already named).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.evidence import Evidence
from pgdr.domain.question import DiagnosticAnswer, DiagnosticQuestion


@runtime_checkable
class EvidenceMapper(Protocol):
    def from_answer(
        self,
        question: DiagnosticQuestion,
        answer: DiagnosticAnswer,
        state: DiagnosticCaseState,
    ) -> list[Evidence]:
        ...
