# P5 Integration Map

> **Scope note (post-hoc re-labeling):** P5 was originally specified as a
> single large phase covering production-path wiring, automotive domain
> validation, legacy deprecation bookkeeping, and a comparison harness.
> That specification was subsequently judged too large and split:
> **P5 — Production Path Integration** is now scoped to the minimal wiring
> (see `p5_production_path.md` / `p5_migration_findings.md`). This
> document's content — the full KEEP/MOVE/ADAPT/DEPRECATE/REMOVE table —
> belongs to **P6 — Automotive Evidence Mapping**. It was built and tested
> during the original P5 pass and is kept as-is (working, verified,
> non-harmful) rather than discarded — delivered early as P6 groundwork.

How PGDR's production execution path changed, function by function, per
the mandate's §6 (P5.4) requirement: for each `DiagnosticEngine`
responsibility, an explicit `KEEP` / `MOVE` / `ADAPT` / `DEPRECATE` /
`REMOVE` decision.

## Before / after

```
BEFORE (v0.1 - P4)                          AFTER (P5)

SessionController                            SessionController
  ├─ calls ComplaintParser directly            ├─ calls ComplaintParser directly
  │  (for SafetyEngine's legacy shape)          │  (unchanged — SafetyEngine's
  │                                             │   input contract is untouched)
  ├─ calls SafetyEngine.evaluate()              ├─ calls SafetyEngine.evaluate()
  │  (UNCHANGED — P0/P5.3 invariant)            │  (UNCHANGED — P0/P5.3 invariant)
  │                                             │
  ├─ calls DiagnosticEngine                     ├─ calls DiagnosticCaseFactory.create()
  │    .process_answers()                       │    → DiagnosticLoop.start()
  │    .detect_contradictions()                 │      → AutomotiveDiagnosticDomain
  │    .generate_hypotheses()                   │        .interpret_observations()
  │                                             │        .generate_hypotheses()
  │  (all THREE calls REMOVED from              │        .map_evidence()
  │   the production path)                      │
  │                                             ├─ calls DiagnosticLoop.run_iteration()
  ├─ self._select_questions()                   │    → AutomotiveDiagnosticDomain
  │  (private method, static priority           │      .available_questions()
  │   sort over the whole question bank)        │    → DeterministicQuestionSelector
  │  (REMOVED)                                  │      .select() (4-tier priority)
  │                                             │
  ├─ ReportBuilder.build(session)               ├─ AutomotiveDiagnosticDomain
  │  (reconstructs everything from               │    .detect_contradictions()
  │   scattered DiagnosticSession fields)        │    (called once, at finalize —
  │                                             │     see p5_findings.md)
  │                                             │
  │                                             └─ report_builder
  │                                                  .build_result_from_case_state()
  │                                                  → build_from_case_state()
  │                                                  (translates the single
  │                                                   DiagnosticCaseState —
  │                                                   recalculates nothing)
```

## KEEP / MOVE / ADAPT / DEPRECATE / REMOVE table

| Legacy responsibility | Decision | Where it lives now |
|---|---|---|
| `SafetyEngine.evaluate()` | **KEEP** | Unchanged, called identically. P5.3 invariant: untouched. |
| `ComplaintParser.extract()` (for the safety-input shape) | **KEEP** | Still called directly by `SessionController.start()` — required because `SafetyEngine.evaluate()`'s input contract (legacy `Symptom`/`WarningIndicator` objects) was deliberately not touched. |
| `DiagnosticEngine.generate_hypotheses()` | **DEPRECATE** | Replaced by `AutomotiveDiagnosticDomain.generate_hypotheses()`. The class instance (`controller.diagnostic_engine`) still exists (kept importable) but this method is never called on the production path — proven by `test_p5_t03_legacy_diagnostic_engine_not_authoritative`, which monkeypatches it to raise and confirms a full session still completes. |
| `DiagnosticEngine.process_answers()` | **REMOVE** (from production path) | No direct replacement — the fields it populated (`operating_conditions`, `reproduction_profile`) are not currently populated by the v2 path at all. Honest, documented gap — see `p5_findings.md`. |
| `DiagnosticEngine.detect_contradictions()` | **ADAPT** | Ported faithfully (same two rules, same source text) to `AutomotiveDiagnosticDomain.detect_contradictions()` — not part of the formal `DiagnosticDomain` Protocol (P4 §18 names 4 methods only), called explicitly once by `SessionController._finalize()`. |
| `SessionController._select_questions()` | **REMOVE**, replaced by **MOVE** | The method is gone. Selection is now `AutomotiveDiagnosticDomain.available_questions()` (candidate generation, still reading `questions.yaml` + `ask_if` logic, faithfully ported) + `DeterministicQuestionSelector.select()` (the actual choice, §19's 4-tier priority — built in P4, made production-authoritative in P5). |
| `ReportBuilder.build()` (the full `DiagnosticSession`-driven assembly) | **DEPRECATE** | Class instance still constructed (`controller.report_builder`) for its `_URGENCY_COPY` table reference, but its `.build()` method is never called by the production path anymore. Replaced by `build_result_from_case_state()`. |
| `ReportBuilder._build_garage_report()` / `._build_user_summary()` | **ADAPT** | Logic re-expressed against `DiagnosticCaseState` in P4's `build_from_case_state()`, reused unchanged by P5's `build_result_from_case_state()`. |

## New components introduced in P5

| Component | Role |
|---|---|
| `DiagnosticCaseFactory` | P5.2 — canonical `PreGarageDiagnosticRequest` + pre-computed `SafetyTriage` → `DiagnosticCaseState`. |
| `AutomotiveDomainValidator` (`validate_automotive_domain()`) | P5.28/29 — startup-time, fail-closed validation of the domain's declarative evidence-mapping rules (dangling hypothesis/question references). |
| `question_classification.classify_questions()` | P5.10 — computed MAPPED/NEUTRAL/LEGACY status per question, sourced from the actual loaded rules, not hand-maintained. |
| `report_builder.build_result_from_case_state()` | P5.17/4 — the full `PreGarageDiagnosticResult` assembly from `DiagnosticCaseState`, closing the gap P4's `build_from_case_state()` (which only produced the two sub-reports) left for full production use. |
| `AutomotiveDiagnosticDomain.detect_contradictions()` | Ported legacy contradiction rule, ordinary Python method (not a formal Protocol member). |
