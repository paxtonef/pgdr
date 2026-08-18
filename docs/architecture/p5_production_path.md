# P5 Production Path (re-scoped)

Scope: **P5 — Production Path Integration** only. Single question this
phase answers: *can the existing PGDR product execute through the P4
`DiagnosticLoop` / `DiagnosticCaseState` without breaking existing
behavior?* Full automotive question mapping, legacy code deletion, domain
validation frameworks, and the comparison harness are **P6/P7** —
delivered early alongside this phase (see the scope notes at the top of
`p5_integration_map.md`, `p5_domain_mapping.md`, `p5_legacy_deprecation.md`,
`p5_findings.md`), not required by this document's Definition of Done.

## Old execution path

```
USER / CLI
    ↓
SessionController
    ↓
SafetyEngine.evaluate()          (unchanged, still first)
    ↓
DiagnosticEngine.generate_hypotheses() / .process_answers()   (legacy — owned hypotheses)
    ↓
SessionController._select_questions()                          (legacy — owned question selection)
    ↓
ReportBuilder.build(session)                                    (reconstructed from scattered DiagnosticSession fields)
    ↓
Report
```

## New execution path

```
USER / CLI
    ↓
SessionController                (session lifecycle, interaction, invocation order — owns nothing analytical)
    ↓
SafetyEngine.evaluate()          (UNCHANGED — same code, same rules, still runs first)
    ↓
DiagnosticCaseFactory.create()   → DiagnosticCaseState              (analytical state owner)
    ↓
DiagnosticLoop.start() / .run_iteration()   (analytical progression owner)
    ↓
next_question  (from DiagnosticLoop — the only source of the user-facing question)
    ↓
[user answers]
    ↓
DiagnosticLoop.submit_answer()  → DiagnosticCaseState updated
    ↓
DiagnosticLoop.run_iteration()  (next iteration reads the SAME state, not a fresh one)
    ↺
    ↓
build_result_from_case_state(state)   (presents the state — recalculates nothing)
    ↓
Report
```

## Component responsibilities (ownership, per the mandate's table)

| Component | Owns |
|---|---|
| `SessionController` | Session lifecycle, interaction, invocation order. Does **not** own analytical state — verified by `test_p5_t03_legacy_diagnostic_engine_not_authoritative` (monkeypatches the legacy hypothesis/answer methods to raise; a full session still completes without touching them). |
| `DiagnosticCaseState` | The analytical state itself — observations, evidence, hypotheses, contradictions, questions, answers, iteration count. One instance per session, held in `SessionController._case_states[session_id]`. |
| `DiagnosticLoop` | Analytical progression — deciding what happens next given the current state (new hypotheses, evidence, next question, stop reason). |
| `SafetyEngine` | The deterministic safety decision. Completely unchanged code, unchanged rules. `DiagnosticLoop` only ever *consults* `SafetyState.preempts_analysis` — it never recomputes or reinterprets the verdict. |

## State ownership / continuity

`DiagnosticCaseState` survives between interactions via
`SessionController._case_states: dict[str, DiagnosticCaseState]`, keyed by
`session.session_id`. Between "question presented" and "answer received,"
the *same* object is retrieved and mutated in place — never rebuilt from
the original complaint. `case_id` is stable across the full session
(assigned once, in `DiagnosticCaseFactory.create()` →
`DiagnosticLoop.start()`, never reassigned).

This is in-memory only, scoped to the process — an
`InMemoryDiagnosticSessionStore`-shaped mechanism in spirit, though P5
implements it as a plain dict on `SessionController` rather than a
separate `DiagnosticSessionStore` Protocol class, since one
implementation with no swap-need yet didn't justify the extra
indirection. No PostgreSQL, no cross-process persistence — explicitly out
of scope, per the mandate's own §6 caution about the word "persistence."

## Safety ordering

```
Request
   ↓
SafetyEngine.evaluate(...)     (same call, same code as pre-P5)
   ↓
SafetyState wraps the result
   ↓
critical (emergency_stop / do_not_drive)?
   ├── YES → DiagnosticLoop.start() still runs interpret_observations(),
   │         but generate_hypotheses()/map_evidence() are skipped —
   │         state.analytical_status becomes STOPPED,
   │         stop_reason = SAFETY_PREEMPTED, hypotheses stay empty.
   │         No further DiagnosticLoop.run_iteration() call is ever made.
   │
   └── NO  → normal iteration proceeds
```

`DiagnosticLoop` never decides whether safety applies — it is handed an
already-computed `SafetyTriage` (via `SafetyState`) and only reads
`.preempts_analysis`.

## Legacy status (short version — full table in `p5_legacy_deprecation.md`, P7-scoped)

```
DiagnosticEngine.generate_hypotheses() / .process_answers()   DEPRECATED — not called on the production path
SessionController._select_questions()                          REMOVED — deleted, zero external callers
ReportBuilder.build()                                           DEPRECATED — not called on the production path
DiagnosticLoop                                                   ACTIVE — the only path producing authoritative results
```

## External API/CLI compatibility

`pgdr run` and the request/response schemas
(`PreGarageDiagnosticRequest`/`PreGarageDiagnosticResult`) are unchanged.
One visible difference: hypothesis confidence now displays as a numeric
`analytical_score` (e.g. `confiance : 0.6`) instead of the old fixed
HIGH/MEDIUM/LOW/SPECULATIVE label — documented, not hidden, and not a
breaking schema change (the field is still populated, just with different
values sourced from real analytical state instead of a static table).
