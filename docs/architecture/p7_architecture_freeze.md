# P7 Architecture Freeze

Per mandate §29: freezing the boundary of responsibility, not every
implementation detail inside it. P8 must consume these contracts or pass
through adapters — it must not redefine them arbitrarily.

## Canonical analytical path (verified, post-retirement)

```
USER / CLI
    |
SessionController                (session lifecycle, interaction, invocation order)
    |
SafetyEngine.evaluate()          (UNCHANGED since P0 — sole safety authority)
    |
    +-- critical? --YES--> STOP (no DiagnosticLoop invocation at all)
    |
    NO
    |
DiagnosticCaseFactory.create()   (P5.2 — canonical initial-state construction)
    |
DiagnosticCaseState              (P4 — the single authoritative analytical state)
    |
DiagnosticLoop                   (P4 — the single analytical progression engine)
    |
    +-- AutomotiveDiagnosticDomain     (DiagnosticDomain implementation)
    +-- AutomotiveEvidenceMapper       (EvidenceMapper implementation)
    +-- DeterministicHypothesisScorer  (HypothesisScorer implementation)
    +-- DeterministicQuestionSelector  (QuestionSelector implementation)
    |
next_question -> user answer -> DiagnosticLoop.submit_answer()
    |
    (loop back to DiagnosticLoop for the next iteration)
    |
build_result_from_case_state()   (P5 — sole production reporting path)
    |
UserSummary + GaragePreparationReport
```

This is now the **only** path from user input to result. Confirmed by
`test_p7_t01` (no legacy symbol exists to be reachable at all) and by the
full 134-test suite passing with zero legacy code present.

## Ownership rules (frozen)

```
SessionController      owns: session lifecycle, interaction, invocation order
                        owns NOTHING analytical

DiagnosticCaseState     owns: the analytical state itself - observations,
                        evidence, hypotheses, uncertainties, contradictions,
                        questions, answers, iteration count

DiagnosticLoop           owns: analytical progression - deciding what
                        happens next given current state

SafetyEngine              owns: the deterministic safety decision.
                        DiagnosticLoop only ever *consults* it via
                        SafetyState.preempts_analysis - never recomputes
                        or reinterprets it.

ReportBuilder            owns: presentation only. Sorts, formats, groups,
(build_from_case_state/  translates labels, builds user/garage views.
build_result_from_        Does NOT create hypotheses, change scores,
case_state)               discard evidence, infer diagnosis, or resolve
                        uncertainty - verified by test_p7_t06 (calling
                        it twice produces zero state mutation).
```

No component may hold a second, competing copy of: hypothesis list,
analytical confidence, diagnostic evidence, or analytical question state.
Verified structurally — there is exactly one place each of these can live
(`DiagnosticCaseState`), and no other component in the codebase declares
a parallel collection with the same purpose.

## Frozen contracts for PGDR v2

```
DiagnosticCaseState   (src/pgdr/domain/analytical_state.py)
DiagnosticLoop         (src/pgdr/application/diagnostic_loop.py)
DiagnosticDomain        (src/pgdr/ports/diagnostic_domain.py) - Protocol
EvidenceMapper           (src/pgdr/ports/evidence_mapper.py) - Protocol
HypothesisScorer          (src/pgdr/ports/hypothesis_scorer.py) - Protocol
QuestionSelector            (src/pgdr/ports/question_selector.py) - Protocol
Safety boundary               (SafetyEngine.evaluate() -> SafetyTriage ->
                              SafetyState.preempts_analysis)
Report input boundary          (DiagnosticCaseState -> build_from_case_state()
                              / build_result_from_case_state())
```

"Frozen" means: these names, their responsibilities, and the shape of
information crossing between them do not change without a deliberate,
documented decision to unfreeze — not that every line inside their
current implementations (`AutomotiveDiagnosticDomain`,
`DeterministicHypothesisScorer`, etc.) is locked. A future domain pack,
scorer, or selector can freely replace today's implementations as long as
it implements the same Protocol.

## What is NOT frozen

```
exact scoring algorithm            (DeterministicHypothesisScorer is one
                                    implementation of HypothesisScorer,
                                    not the contract itself)
complete automotive evidence
  knowledge                        (P6's 2-of-10 MAPPED questions is a
                                    snapshot, not a ceiling — domain
                                    enrichment continues independently)
database implementation            (none exists; when one is built, it
                                    implements a port, doesn't redefine
                                    DiagnosticCaseState)
UI / CLI presentation               (cli.py can change freely; it consumes
                                    SessionController, doesn't define the
                                    analytical contract)
provider implementation             (AutomotiveDiagnosticDomain is A domain
                                    pack, not THE domain pack contract)
GGM implementation                  (explicitly not designed here — see seam below)
case repository                     (does not exist; not this phase's concern)
```

## Safety boundary (unchanged since P0, re-confirmed here)

```
Incoming case
    |
SafetyEngine.evaluate()   <- UNMODIFIED since P0. Deterministic. No LLM.
    |
critical (emergency_stop / do_not_drive)?
    +-- YES --> STOP. DiagnosticLoop is never invoked. No hypothesis is
    |           ever generated from a safety-critical case
    |           (test_p7_t01, test_p7_t07 confirm hypotheses == []).
    +-- NO  --> DiagnosticLoop proceeds, consulting (never overriding)
                the safety verdict via SafetyState.preempts_analysis.
```

`driving_assessment` structurally cannot express "confirmed safe" — no
such enum member exists (`PGDR-INV-003`, unchanged since P0). This
invariant survived every phase from P0 through P7 without modification —
the single longest-lived, most consistently enforced rule in the codebase.

## Reporting boundary (re-confirmed by P7-T06)

```
DiagnosticCaseState
    |
build_from_case_state() / build_result_from_case_state()
    |
CAN: sort, format, group, translate labels, bucket a continuous score
     into a legacy enum for schema compatibility, build user/garage views
CANNOT: create a new hypothesis, change a score, discard contradictory
        evidence as false, infer a diagnosis, resolve an uncertainty
```

Verified mechanically, not just asserted: `test_p7_t06_reporting_does_not_mutate_analytical_state`
calls the report builder twice against the same state and diffs
hypotheses/evidence-count/uncertainties/contradictions before and after —
zero difference.

## P8 integration seam (documented, NOT implemented)

```
DiagnosticCaseState
    |
candidate analytical output (hypotheses + their evidence + confidence)
    |
    [ P8 SEAM — not built in P7 ]
    |
governed claims (VERIFIED / GENERATED / authority / permissions — none
                  of these concepts exist in PGDR today)
    |
presentation
```

The seam sits **after** `DiagnosticCaseState` is fully formed for a given
iteration and **before** presentation — meaning GGM/CGM, when built, reads
the same `DiagnosticCaseState` (or a snapshot of it) that
`build_from_case_state()` reads today, without needing to reach inside
`DiagnosticLoop`, `EvidenceMapper`, or the scorer. This is deliberate: P8
should govern what PGDR is *allowed to claim* about analytical output it
already produced, not become a second producer of that output.

**Not built in P7, per explicit instruction:** `GGMAdapter`, `GGMStatus`,
`VERIFIED`, `GENERATED`, any authority or claim-permission model.
`DiagnosticStopReason` still deliberately has no `CONFIRMED_DIAGNOSIS`
member (unchanged since P4) — that determination belongs to GGM, not to
this phase or any phase before it.

## Why this freeze matters before P8 starts

Prevents the failure mode the mandate names explicitly: GGM reaching
inside PGDR and changing `DiagnosticLoop` internals, `EvidenceMapper`, or
the scorer to fit its own needs. With this freeze in place, GGM has
exactly one legitimate entry point — reading `DiagnosticCaseState` through
the same boundary `ReportBuilder` already uses — and no legitimate reason
to touch anything upstream of it.
