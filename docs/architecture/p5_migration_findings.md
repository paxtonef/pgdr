# P5 Migration Findings (re-scoped)

Scope: **P5 — Production Path Integration** only, per the re-scoped six
`P5-DOD` criteria. This supersedes `p5_findings.md` as the P5-relevant
findings document — `p5_findings.md` is kept in full but covers broader
(P6/P7-scoped) ground.

## Unexpected coupling discovered

**`SafetyEngine.evaluate()`'s input contract forced complaint parsing to
run twice per session.** `SafetyEngine.evaluate(session)` expects the
legacy `DiagnosticSession` shape (`session.symptoms`,
`session.warning_indicators` — Pydantic objects from `ComplaintParser`).
Since P5.2 (mandate §4) requires safety to run *before* `DiagnosticLoop`
and forbids modifying `SafetyEngine`, `SessionController.start()` must
call `ComplaintParser.extract()` directly to build that legacy shape —
and then `DiagnosticCaseFactory.create()` → `DiagnosticLoop.start()` →
`AutomotiveDiagnosticDomain.interpret_observations()` calls the
*identical* `ComplaintParser.extract()` again, independently, to build
the new `Observation` shape. This wasn't anticipated until implementation
— the two type systems (legacy Pydantic `Symptom` vs. new `Observation`)
don't share a conversion path, and building one wasn't necessary to meet
P5's DoD, so it wasn't built. Deliberate, not hidden — same complaint
text, same deterministic parser, parsed twice.

## Temporary compatibility adapters

**`build_result_from_case_state()`** (in `report_builder.py`) is the
adapter mandate §10 (P5.8) anticipated ("créer un adapter entre
`DiagnosticCaseState` et les structures attendues actuellement par
`ReportBuilder`"). It translates `DiagnosticCaseState` into the full
legacy `PreGarageDiagnosticResult` schema — including bucketing the new
continuous `analytical_score` back into the old `Confidence` enum
(HIGH/MEDIUM/LOW/SPECULATIVE) purely so the legacy-typed
`pgdr.models.DiagnosticHypothesis.confidence` field stays populated. The
underlying float score is not lost — it's directly visible via
`DiagnosticCaseState.hypotheses[i].confidence` — only the legacy schema's
field re-expresses it as a bucket.

## Remaining legacy dependencies

- `SessionController.__init__` still constructs `self.diagnostic_engine`
  (a `DiagnosticEngine` instance) and `self.report_builder` (a
  `ReportBuilder` instance) — neither's core analytical methods are
  called on the production path, but they're kept importable/constructed
  for the comparison harness and for anyone still calling them directly.
  See `p5_legacy_deprecation.md` (P7-scoped) for the full per-method
  table.
- `AutomotiveDiagnosticDomain.detect_contradictions()` is a faithful port
  of `DiagnosticEngine.detect_contradictions()`'s one existing rule (the
  "ne démarre jamais" + "roulé" pattern) — required to keep
  `test_regression_contradiction_detects_infinitive_form_of_rouler`
  (a pre-P4 test) green; not a new automotive rule.

## Questions deferred to P6/P7

- Systematic question → evidence-rule mapping beyond the one
  `Q-COND-001` vertical slice (mandate §9/§22: P5 explicitly requires
  only ≥1 fully mapped adaptive scenario, not full coverage) — **P6**.
- `AutomotiveDomainValidator` (startup config validation for the
  evidence-mapping rules) — built and tested, but is a P6-shaped
  concern (validating *domain content*, not the production wire) —
  delivered early, kept as-is.
- Full legacy `DiagnosticEngine`/`ReportBuilder` deletion — **P7**, per
  mandate §21's explicit "ne pas supprimer immédiatement."
- `DiagnosticSessionStore` as a formal `Protocol` (mandate §6) — P5 uses
  a plain dict on `SessionController` instead; revisit if/when a second
  store implementation (e.g. for a future web layer) is actually needed.

## P5-DOD verification

```
P5-DOD-01  SessionController invokes DiagnosticLoop                         PASS — test_p5_t02
P5-DOD-02  DiagnosticCaseState persists across Q&A iterations               PASS — test_p5_t06, test_p5_t14 (case_id continuity implicit in _case_states lookup)
P5-DOD-03  Critical Safety still preempts analytical execution              PASS — test_p5_t04, test_p5_t20
P5-DOD-04  ≥1 production-path Q&A changes hypothesis state via P4 mechanism PASS — test_p5_t21 (signature test)
P5-DOD-05  Existing API/CLI output remains usable                           PASS — live CLI smoke test, JSON output intact
P5-DOD-06  All existing + P4 + P5 tests pass                                PASS — 114/114
```

## Explicitly out of P5 (confirmed not built in this phase's *required* scope)

Full automotive question mapping, full evidence enrichment, legacy code
deletion, Case Repository, Vehicle Health Record, GGM/CGM integration,
LLM integration, new confidence theory, cross-brand capability reasoning.
(`AutomotiveDomainValidator` and `question_classification.py` ARE built —
delivered early as P6 groundwork per the re-scoping decision, not because
P5 required them.)
