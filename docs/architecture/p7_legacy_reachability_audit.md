# P7.1 — Legacy Reachability Audit

**No behavior changed to produce this document.** Every claim below is
traced via `grep`/direct code reading against the actual repository
(archive provided, no `.git` metadata present — content-verified against
77 files matching the known P6 state; baseline **128/128 tests pass**
before any change in this phase).

## Method

For each candidate component: read its actual callers (not name search),
classify per §4's operational test (does it interpret complaints, select
questions, generate/modify hypotheses, calculate scores, or determine the
next question — outside the v2 path?), then decide KEEP/ADAPT/DEPRECATE/REMOVE.

---

## LegacyComponentRecord — `DiagnosticEngine.process_answers()`

```
component:          DiagnosticEngine.process_answers
file:                src/pgdr/diagnostic.py
responsibility:      folds submitted answers into operating_conditions /
                     events / reproduction_profile (legacy DiagnosticSession fields)
called_by:           tests/test_p5_comparison_harness.py ONLY
                     (grep confirms zero production callers)
calls:               nothing external
production_reachable: NO
test_reachable:      YES (comparison harness only)
reads_analytical_state:   NO (reads session.answers, a request-input field)
writes_analytical_state:  NO — writes to session.operating_conditions /
                     .events / .reproduction_profile, which are legacy-
                     only fields with ZERO other readers anywhere in the
                     codebase except ReportBuilder's own unreachable methods
interprets_answers:  YES
classification:      REMOVE
decision_reason:     Unreachable in production. Its only reader
                     (ReportBuilder._build_garage_report) is itself
                     unreachable (see below) — this is a fully dead
                     subsystem end to end, not merely unauthoritative.
```

## LegacyComponentRecord — `DiagnosticEngine.generate_hypotheses()` (instance method)

```
component:           DiagnosticEngine.generate_hypotheses
file:                 src/pgdr/diagnostic.py
responsibility:       builds pgdr.models.DiagnosticHypothesis list from
                      session.symptoms, writes session.hypotheses
called_by:            tests/test_p5_comparison_harness.py;
                      monkeypatched (not called) by
                      test_p5_integration.py::test_p5_t03
production_reachable: NO
test_reachable:       YES (comparison harness)
creates_hypotheses:   YES
calculates_score:     NO (confidence is a static value from _HYPOTHESIS_MAP)
classification:       REMOVE
decision_reason:      Confirmed unauthoritative by P5-T03 already; P7
                      confirms zero remaining callers make it reachable
                      at all, production or otherwise (once the
                      comparison harness — its only caller — is
                      retired, see below).
```

## LegacyComponentRecord — `DiagnosticEngine.detect_contradictions()` (instance method)

```
component:            DiagnosticEngine.detect_contradictions
file:                  src/pgdr/diagnostic.py
responsibility:        legacy contradiction detection, writes session.contradictions
called_by:             tests/test_p5_comparison_harness.py ONLY
production_reachable:  NO — superseded by AutomotiveDiagnosticDomain
                       .detect_contradictions() (src/pgdr/automotive/domain_adapter.py),
                       a faithful, independent port called by
                       SessionController._finalize()
creates_evidence:      NO
classification:        REMOVE
decision_reason:       Duplicate authority. The ported version in
                       AutomotiveDiagnosticDomain is the sole production
                       source — this instance method's continued
                       existence would be exactly the "second collection
                       constituting a second source of truth" the
                       mandate's §14 prohibits, if it were ever reachable
                       (it isn't, but removing it removes even the
                       latent risk).
```

## LegacyComponentRecord — `DiagnosticEngine._generic_entries()` (staticmethod) — **BLOCKER FINDING**

```
component:             DiagnosticEngine._generic_entries
file:                   src/pgdr/diagnostic.py
responsibility:         fallback hypothesis-entry generator for any
                        SymptomFamily without a curated _HYPOTHESIS_MAP entry
called_by:              AutomotiveDiagnosticDomain.generate_hypotheses()
                        (src/pgdr/automotive/domain_adapter.py:87) — DIRECTLY,
                        ON THE PRODUCTION PATH
production_reachable:   **YES**
test_reachable:         YES (test_regression_all_symptom_families_produce_non_unknown_hypothesis
                        in test_runner.py exercises this fallback via a
                        family with no curated entry)
creates_hypotheses:     YES (fallback entries)
classification:         **ADAPT / MOVE** — not REMOVE
decision_reason:        Per mandate §6/§34: this is exactly the "useful
                        transformation X → ADAPT/MOVE" case, discovered by
                        tracing actual callers rather than assuming
                        "DiagnosticEngine = all legacy, delete wholesale."
                        Deleting DiagnosticEngine without addressing this
                        would silently break the fallback path for any
                        symptom family without a curated hypothesis-map
                        entry. Retirement plan: extract this pure function
                        out of the DiagnosticEngine class entirely (it has
                        no dependency on `self` or `self.config` — it's
                        already effectively a free function wearing a
                        staticmethod's clothes) and relocate it to
                        `automotive/domain_adapter.py`, its sole caller.
```

## LegacyComponentRecord — `_HYPOTHESIS_MAP` (module-level dict)

```
component:             _HYPOTHESIS_MAP
file:                   src/pgdr/diagnostic.py
responsibility:         automotive domain DATA — symptom family → candidate
                        hypothesis entries
called_by:              AutomotiveDiagnosticDomain (generate_hypotheses),
                        automotive/coverage.py, automotive/domain_validator.py
production_reachable:   YES
creates_hypotheses:     NO (it's data, not logic — the calling code decides
                        what to do with it)
classification:         KEEP
decision_reason:        Per mandate §4's explicit carve-out: this is
                        content, not a competing analytical authority.
                        P3 already established this table as Automotive
                        Domain Pack DATA, not engine logic.
```

## LegacyComponentRecord — `ReportBuilder.build()` / `._build_garage_report()` / `._build_user_summary()` / `._determine_status()`

```
component:              ReportBuilder (class, 4 methods)
file:                    src/pgdr/report_builder.py
responsibility:          full PreGarageDiagnosticResult assembly from a
                         DiagnosticSession's scattered fields
called_by:               NOBODY — grep confirms zero callers anywhere in
                         src/ or tests/, production or test
production_reachable:    NO
test_reachable:          NO
reads_analytical_state:  reads session.hypotheses / .contradictions /
                         .operating_conditions / .events /
                         .reproduction_profile — all of which are ALSO
                         only ever written by the DiagnosticEngine methods
                         above, which are themselves unreachable. This is
                         a fully dead subsystem on BOTH ends.
builds_report_only:      YES
classification:          REMOVE
decision_reason:         Zero reachability from any direction — not
                         merely unauthoritative (P5's state) but
                         genuinely unreachable code as of this audit.
                         Superseded entirely by build_from_case_state() /
                         build_result_from_case_state() (P4/P5, additive,
                         already the sole production path).
```

## LegacyComponentRecord — `SessionController.diagnostic_engine` / `.report_builder` (attributes)

```
component:              SessionController.__init__'s construction of
                        self.diagnostic_engine and self.report_builder
file:                    src/pgdr/session_controller.py
called_by:               nothing reads these attributes anywhere except
                        test_p5_integration.py::test_p5_t03 (which
                        monkeypatches them specifically to PROVE they're
                        never called — a test about their unreachability,
                        not a caller of their functionality)
production_reachable:    NO (constructed, never invoked)
classification:          REMOVE (the construction lines) — direct
                        consequence of removing the DiagnosticEngine and
                        ReportBuilder classes themselves.
```

## LegacyComponentRecord — `tests/test_p5_comparison_harness.py` (whole file)

```
component:              test_no_major_regression_between_legacy_and_v2 (4 cases)
                        + _run_legacy_standalone()
file:                    tests/test_p5_comparison_harness.py
responsibility:          P5 mandate §20 — compares legacy DiagnosticEngine
                        output against v2 SessionController output on the
                        same input, migration-period regression detection
called_by:               pytest only
classification:          REMOVE (the file)
decision_reason:         Its own docstring states its purpose was
                        migration-period comparison. Once
                        DiagnosticEngine.generate_hypotheses/.process_answers/
                        .detect_contradictions are removed (this audit's
                        REMOVE decisions above), there is no "legacy" left
                        to compare against — the harness's core mechanism
                        becomes structurally impossible to run.
                        Per mandate §16 ("don't delete a test just because
                        the tested code disappears — if it expresses a
                        still-valid invariant, rewrite it against v2"):
                        checked each invariant this harness asserted
                        (emergency still blocks, hypotheses non-empty,
                        identity preserved, complaint verbatim) against
                        the rest of the suite — ALL FOUR are independently
                        covered by test_scenario_2 (test_runner.py) and
                        test_p5_t01/t05/t06/t17-19 (test_p5_integration.py).
                        No invariant is lost by removing this file — see
                        p7_retirement_result.md for the explicit mapping.
```

## LegacyComponentRecord — `test_p5_integration.py::test_p5_t03_legacy_diagnostic_engine_not_authoritative`

```
component:              test_p5_t03_legacy_diagnostic_engine_not_authoritative
file:                    tests/test_p5_integration.py
responsibility:          proves, via monkeypatch-and-raise, that
                        controller.diagnostic_engine's methods are never
                        called during a real session
classification:          ADAPT (rewritten, not removed)
decision_reason:         Its mechanism (monkeypatch an attribute that's
                        about to not exist) breaks once
                        SessionController.diagnostic_engine is removed.
                        Its INVARIANT — "no legacy analytical component
                        is reachable from production" — is still exactly
                        what P7 needs proven, now more strongly: instead
                        of proving a specific method isn't CALLED, P7
                        proves the symbol doesn't exist to be called at
                        all. Rewritten in place (same test name/intent)
                        to assert `DiagnosticEngine` is no longer
                        importable from pgdr.diagnostic and
                        SessionController carries no diagnostic_engine/
                        report_builder attribute. This IS effectively
                        P7-T01 (§19), implemented as an update to this
                        existing test rather than a parallel new one.
```

## LegacyComponentRecord — `ComplaintParser`

```
component:              ComplaintParser (class, all methods)
file:                    src/pgdr/complaint_parser.py
called_by:               SessionController.start() directly (legacy-shaped
                        extraction for SafetyEngine's input contract) AND
                        AutomotiveDiagnosticDomain.interpret_observations()
                        (v2-shaped extraction) — two live callers, same
                        underlying deterministic parser, no competing
                        analytical inference in either call
production_reachable:    YES (both paths)
interprets_answers:      NO (interprets the initial complaint only)
creates_hypotheses:       NO
selects_questions:        NO
classification:           KEEP
decision_reason:          Per mandate §11: linguistic/domain extraction,
                        not parallel analytical inference. Does not
                        decide diagnosis, only structures raw text — the
                        exact KEEP carve-out the mandate names explicitly.
```

## LegacyComponentRecord — `SafetyEngine` (all methods)

```
classification:  KEEP
decision_reason: Explicitly out of scope per mandate §10/§3 example.
                 Never replaced by DiagnosticLoop; DiagnosticLoop only
                 ever *consults* its verdict.
```

## Structural checks (§12–§15), confirmed clean by direct trace — no remediation needed

```
Question path (§12):    CONFIRMED CLEAN. SessionController._select_questions()
                         was already removed in P5 — grep finds no trace of
                         it, no "questions[index + 1]" pattern, no static
                         sequence. The only question source reaching
                         session.pending_questions is DiagnosticLoop.run_iteration()
                         via SessionController._advance().

Answer path (§13):      CONFIRMED CLEAN. submit_answer() routes exclusively
                         through DiagnosticLoop.submit_answer(); the only
                         component that ever ran a parallel answer-processing
                         path (DiagnosticEngine.process_answers) is
                         unreachable (see above) and now removed.

Hypothesis path (§14):  CONFIRMED CLEAN (with a nuance). session.hypotheses
                         (the legacy DiagnosticSession field) is NOT a
                         "second source of truth" in the sense §14 warns
                         against — nothing in production ever writes to it,
                         so it isn't a competing authority, just dead
                         schema. Left untouched (see models.py note below).
                         DiagnosticCaseState.hypotheses is the sole
                         populated, read, and authoritative collection.

Reporting boundary (§15): CONFIRMED CLEAN. build_from_case_state() /
                         build_result_from_case_state() (the sole
                         production reporting path since P5) create no
                         new hypothesis, change no score, discard no
                         evidence, infer no diagnosis, resolve no
                         uncertainty — verified by re-reading both
                         functions in full during this audit.

Double-calculation
pattern (§8):            CONFIRMED ABSENT. No
                         "new_result = ...; legacy_result = ...; merge()"
                         pattern, or any variant, exists anywhere in
                         session_controller.py or diagnostic_loop.py.

Silent fallback
pattern (§9):             CONFIRMED ABSENT. No try/except that catches a
                         v2 failure and falls through to legacy reasoning
                         exists anywhere in the codebase.
```

## Scope boundary note — `pgdr/models.py` is explicitly NOT touched

`DiagnosticSession.hypotheses` / `.contradictions` / `.operating_conditions`
/ `.reproduction_profile` / `.events`, and the `OperatingConditions` /
`ReproductionProfile` / `VehicleEvent` Pydantic classes, remain in
`models.py` unchanged. These are part of the **public request/response
schema** (§28: "existing public entry points remain usable" — models.py
IS that public contract, not internal analytical logic). They become
permanently-empty-by-default fields once their only writer
(`DiagnosticEngine.process_answers`) is removed — a schema field with no
current writer is not the architectural ambiguity P7 targets; a
competing analytical authority would be, and this isn't one.

## Discovered finding (not a blocker, documented per §34): an inert governance gap

`business_rules.yaml`'s `thresholds.max_hypotheses_garage_report: 8` was
enforced only by `DiagnosticEngine.generate_hypotheses()`, which is being
removed. No equivalent cap exists in `AutomotiveDiagnosticDomain.generate_hypotheses()`.
**Currently inert** — checked every `_HYPOTHESIS_MAP` family; the largest
(`noise`) has 3 entries, well under the cap of 8, so no session has ever
been able to trigger this limit regardless of which path is authoritative.
Documented rather than silently dropped, and rather than built (building
new enforcement is new capability work, out of P7 scope per its own
"P7 ne construit aucune nouvelle capacité diagnostique").

---

## Classification summary

```
KEEP:        SafetyEngine, ComplaintParser, _HYPOTHESIS_MAP, CLI (cli.py, run_pgdr.py)
ADAPT/MOVE:  DiagnosticEngine._generic_entries() -> relocate to automotive/domain_adapter.py
             test_p5_t03 -> rewritten in place against the new (stronger) invariant
REMOVE:      DiagnosticEngine.process_answers()
             DiagnosticEngine.generate_hypotheses() (instance method)
             DiagnosticEngine.detect_contradictions() (instance method)
             DiagnosticEngine class itself (once the above are gone/moved)
             ReportBuilder class (all 4 methods — zero reachability either direction)
             SessionController.diagnostic_engine / .report_builder attribute construction
             tests/test_p5_comparison_harness.py (whole file — invariants preserved elsewhere)
```

No component required a DEPRECATE (temporarily-kept-for-compatibility)
status — everything found was either cleanly reachable (KEEP/ADAPT) or
cleanly unreachable (REMOVE), with no external compatibility contract
requiring a transitional state.
