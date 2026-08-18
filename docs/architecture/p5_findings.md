# P5 Findings

> **Scope note (post-hoc re-labeling):** this document covers the
> original, larger P5 specification (domain validation, question
> classification, comparison harness, full deprecation). Under the
> re-scoped phase split, its content spans **P5 — Production Path
> Integration** (the parts about `SessionController`/`DiagnosticLoop`
> wiring and the signature test) and **P6 — Automotive Evidence Mapping**
> / **P7 — Legacy Analytical Path Retirement** (the domain-validator,
> question-classification, and comparison-harness material). For the
> lean, P5-scoped version of these findings, see
> `p5_migration_findings.md`. This document is kept in full as-is —
> nothing here is wrong, it's simply broader than P5's narrowed DoD
> required.

## A real gap caught by the test suite mid-migration

While rewriting `SessionController`, `test_regression_contradiction_detects_infinitive_form_of_rouler`
(a pre-existing, pre-P4 test) failed: 23/24 passed, one broke. The cause
— legacy `DiagnosticEngine.detect_contradictions()` had a specific,
sourced rule (the "ne démarre jamais" + "roulé" pattern) that I had never
ported to the new pipeline when building P4's `AutomotiveDiagnosticDomain`.
Per the mandate's own §9 principle ("SOURCE REQUIRED"), this rule had a
clear source (the exact legacy method), so I ported it faithfully rather
than either inventing a replacement or leaving the regression in place.
Fixed in `AutomotiveDiagnosticDomain.detect_contradictions()` — all 24
tests in `test_runner.py` pass again. This is the same "build → test →
fix → verify" discipline P4's anti-loop bug fix used.

## Five things P5 explicitly did NOT build (honest gaps, not oversights)

### 1. `operating_conditions` / `reproduction_profile` are not populated on the v2 path

Legacy `DiagnosticEngine.process_answers()` populated
`session.operating_conditions` (engine cold/hot, vehicle state) and
`session.reproduction_profile` from specific question answers
(`Q-STATE-002`, `Q-COND-001`). No equivalent mechanism exists in the v2
path — `process_answers()` is REMOVED from production (per mandate §6)
with no replacement built. This does not fail any test (nothing in the 70
pre-P4 tests or 24 new P5 tests reads these fields directly), and the
answers themselves ARE still captured as `Observation`s — but the
specific *structured* `OperatingConditions`/`ReproductionProfile` re-shaping
that legacy code did is simply not reproduced. A future phase should
either build a generic equivalent or confirm it's not needed.

### 2. `AutomotiveDiagnosticDomain` never generates `DiagnosticUncertainty` objects

`state.uncertainties` stays empty for the entire session, always. P5-T13
("resolved uncertainty is not targeted again") is consequently tested at
the mechanism level directly against `CaseStateUpdater`, not through a
real automotive scenario — because no real automotive scenario currently
produces an uncertainty to resolve. This is the single largest "declared
capability, zero domain content" gap left after P5, mirroring the exact
shape of P2's Finding #26 (`PGDR-INV-007`, the `Uncertainty` model that
was never instantiated) — P4 built the `DiagnosticUncertainty` domain
object and the resolve/unresolve mechanism; P5 did not connect it to any
automotive-generated uncertainty. Recommended for the next domain-content
pass, not invented here.

### 3. Complaint parsing runs twice per session

`SessionController.start()` calls `ComplaintParser.extract()` directly
(to populate `session.symptoms` in the legacy shape `SafetyEngine.evaluate()`
requires — unchanged, per P5.3), and `DiagnosticCaseFactory.create()` →
`DiagnosticLoop.start()` → `AutomotiveDiagnosticDomain.interpret_observations()`
calls the identical `ComplaintParser.extract()` a second time, independently,
producing the new `Observation` shape. This is a deliberate, documented
choice (see `session_controller.py`'s docstring on `start()`), not a
hidden inefficiency — avoiding it would have meant either modifying
`SafetyEngine`'s input contract (explicitly forbidden by P5.3) or building
a translation layer from the new `Observation` shape back to the legacy
`Symptom`/`WarningIndicator` shape `SafetyEngine.evaluate()` expects. Both
are legitimate future refactors; neither was necessary to satisfy P5's
Definition of Done, so neither was built.

### 4. `Q-EVI-002` (media upload) is unconditionally unavailable in v2, regardless of consent

Legacy behavior: available if `consent.media_analysis_allowed=True`. New
behavior: never available, consent notwithstanding — `AutomotiveDiagnosticDomain`
excludes all `media_upload` questions outright (see `_SKIPPED_ANSWER_TYPES`).
No test exercises `media_analysis_allowed=True` (confirmed by search — see
`p5_integration_map.md`), so this doesn't break anything measurable, but
it IS a real behavioral difference worth stating plainly rather than
letting it hide: v2 currently offers *less* than v0.1 here, not more,
because the entire Evidence pipeline downstream of that question is still
dormant (P2 Finding #7) — asking the question without anything consuming
the answer would be worse than not asking it (matches the NEUTRAL/LEGACY
philosophy: don't create the impression of a capability that doesn't
exist).

### 5. No custom exception for "submit_answer called with an unknown session_id"

`self._case_states[session.session_id]` raises a plain `KeyError` if the
session was never started through this controller instance. This is loud,
not silent (consistent with P0's "no silent fallback" principle), but it
isn't wrapped in a friendlier, more diagnosable exception type yet. Left
as-is; noted per mandate §27's request to classify failure behaviors
explicitly rather than leave them undocumented.

## Definition of Done — verified against all 5 conditions

```
1. Production SessionController uses DiagnosticLoop.
   VERIFIED — test_p5_t02_session_controller_uses_diagnostic_loop
   (case_state.iteration only ever advances inside DiagnosticLoop.run_iteration()).

2. DiagnosticCaseState is the only authoritative analytical session state.
   VERIFIED — hypotheses, evidence, contradictions, and the resulting
   report are all sourced from DiagnosticCaseState; DiagnosticEngine's
   analytical methods are proven unreachable
   (test_p5_t03_legacy_diagnostic_engine_not_authoritative).

3. At least one complete real product scenario proves the full chain.
   VERIFIED — test_p5_t21_signature_adaptive_product_path, through
   SessionController (the real product path), not the isolated engine:
   answering Q-COND-001 moves engine_running and tyre_or_wheel confidence
   in opposite directions, and a genuinely different next question follows.

4. Legacy analytical path no longer produces authoritative results.
   VERIFIED — same as condition 2's test; also confirmed by the
   comparison harness deliberately calling DiagnosticEngine standalone
   (outside SessionController) as the ONLY place in the codebase still
   invoking it directly.

5. All previous safety guarantees remain green.
   VERIFIED — test_p5_t04, test_p5_t20 (emergency behavior unchanged
   through the new path), plus all pre-existing P0 safety/config-integrity
   tests pass unmodified (test_p0_config_integrity.py: 22/22).
```

## Verification summary

```
70 pre-P4 tests           PASS (unchanged)
16 P4 tests                PASS (unchanged)
24 P5 integration tests    PASS (new)
4 comparison-harness tests PASS (new)
                          -----
114 total                  PASS
```

Wheel rebuilt and re-validated: all 11 P0 packaging tests pass against
the wheel containing the migrated `session_controller.py`.

## What P5 gives PGDR

Before P5: a diagnostic engine (P4) existed, fully tested, entirely
isolated from the product. After P5: the product itself is the engine —
`pgdr run` today genuinely reasons across a session, not merely collects
answers for a static report template. The distinction between P4-T17
(proves the engine is adaptive) and P5-T21 (proves the *product* is
adaptive) is the entire point of this phase.
