# PGDR v2 Architecture Freeze

Supersedes nothing from `p7_architecture_freeze.md` (P7's analytical
architecture freeze remains fully valid and unchanged) - this document
extends it with the P8 governance boundary to produce the complete v2
picture in one place.

## Full v2 architecture

```
USER / CLI
    |
SessionController
    |
    +------------------> SafetyEngine.evaluate()
    |                          |
    |                      PREEMPT?
    |                          |
    |            YES ----------+---------- NO
    |             |                         |
    |             v                         v
    |     safety-escalated result    DiagnosticCaseState
    |     (bypasses governance          |
    |      entirely - mandate para 28)   v
    |             |                DiagnosticLoop
    |             |                     |
    |             |         +-----------+-----------+
    |             |         |           |           |
    |             |   DiagnosticDomain  EvidenceMapper
    |             |         |    HypothesisScorer  QuestionSelector
    |             |         |
    |             |         v
    |             |   Candidate Diagnostic Output
    |             |         |
    |             |   === GGM BOUNDARY ===
    |             |         |
    |             |         v
    |             |   DiagnosticGovernancePort
    |             |         |
    |             |         v
    |             |   GGMDiagnosticGovernanceAdapter
    |             |         |
    |             |         v
    |             |   GGMConsumer.evaluate()  (real pinned GGM, commit 4fda597)
    |             |         |
    |             |         v
    |             |   GovernanceResult | ConsumptionError
    |             |         |
    |             |         v
    |             |   Governed Presentation Decision
    |             |         |
    +-------------+---------+
                  |
                  v
        User Summary  /  Garage Report
```

## Three distinct authorities - the central v2 architectural achievement

```
SAFETY AUTHORITY
    -> SafetyEngine (unchanged since P0)
    -> deterministic, rule-based, no LLM
    -> cannot be overridden, reinterpreted, or reached by DiagnosticLoop
       or GGM - DiagnosticLoop only ever *consults*
       SafetyState.preempts_analysis; GGM never sees a safety-escalated
       case at all (governance is bypassed entirely on that path)

ANALYTICAL AUTHORITY
    -> DiagnosticCaseState (sole analytical state, frozen at P7)
       + DiagnosticLoop (sole progression engine, frozen at P7)
    -> decides: which hypotheses exist, their evidence, their
       analytical_score, which question comes next
    -> GGM cannot mutate this - verified mechanically, not just
       asserted (governance runs against a deep COPY of the state;
       test_p8_t23_t24_t25 diffs the original before/after every
       governance call and asserts byte-for-byte equality)

GOVERNANCE AUTHORITY
    -> GGM, consumed exclusively through GGMConsumer.evaluate()
    -> decides: whether a candidate diagnostic statement may be
       *expressed* to the user - never what PGDR analytically believes
    -> PGDR never reimplements this locally (test_p8_t01/t01b scan the
       AST of the entire governance package for exactly this)
```

No fourth authority exists. Confirmed by the "No Hidden Authority Audit"
document.

## Frozen contracts - P7 (unchanged) + P8 (frozen as of this release)

```
P7 (unchanged):
  DiagnosticCaseState, DiagnosticLoop, DiagnosticDomain, EvidenceMapper,
  HypothesisScorer, QuestionSelector, Safety boundary, Report input boundary

P8 (frozen as of v2.0.0):
  DiagnosticGovernancePort       (src/pgdr/governance/port.py)
  DiagnosticGovernanceCandidate  (neutral PGDR->GGM DTO)
  DiagnosticGovernanceOutcome    (neutral GGM->PGDR DTO)
  GGMConsumer                    (external - GGM's own Protocol, not PGDR's)
```

"Frozen" carries the same meaning P7 established: names, responsibilities,
and the shape of information crossing between them do not change without
a deliberate, documented decision - not that every implementation detail
(e.g. exactly which `GGMConsumer` is injected) is locked.
