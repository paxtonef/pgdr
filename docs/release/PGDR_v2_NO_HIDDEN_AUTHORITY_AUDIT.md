# PGDR v2 - No Hidden Authority Audit

Grep-based audit of the entire `src/` tree for every capability listed in
the release mandate. Each finding names the exact file(s)/line(s), not a
description - reproducible by anyone re-running the same greps.

## Change analytical score

```
grep -rn "\.confidence\s*=" src/ --include="*.py" | grep -v "def \|#"
```

**One write site**: `application/case_state_updater.py:59` -
`h.confidence = self._scorer.score(h, relevant, state)`, inside
`CaseStateUpdater.update_hypotheses()`, called only by `DiagnosticLoop`.

**EXPECTED AUTHORITY** - `DiagnosticLoop` (via `CaseStateUpdater`, using
the injected `HypothesisScorer`).

## Create hypothesis

```
grep -rn "DiagnosticHypothesis(" src/ --include="*.py"
```

**One instantiation site** (excluding the class definitions in
`domain/hypothesis.py` and the unrelated legacy-schema class of the same
name in `models.py`, used only by `report_builder.py`'s translation
layer, never to originate a NEW hypothesis): `automotive/domain_adapter.py:119`,
inside `AutomotiveDiagnosticDomain.generate_hypotheses()`, called only
by `DiagnosticLoop`.

**EXPECTED AUTHORITY** - `DiagnosticLoop` (via the injected
`DiagnosticDomain` implementation).

## Select analytical question

```
grep -rn "next_question\s*=\|\.select(" src/ --include="*.py"
```

**One decision site**: `application/diagnostic_loop.py:129` -
`next_question = self._selector.select(candidates, state)`.

**EXPECTED AUTHORITY** - `DiagnosticLoop` (via the injected
`QuestionSelector`).

## Override safety

```
grep -rn "preempts_analysis\|SafetyTriage(" src/ --include="*.py"
```

`SafetyTriage()` is constructed in exactly two places:
`safety_engine.py:71` (the real evaluation, inside `SafetyEngine.evaluate()`)
and `report_builder.py` (a default-empty fallback used ONLY when
`state.safety_state` is `None` - a presentation null-guard, not a
decision). `preempts_analysis` is read (never written) by
`diagnostic_loop.py` only, as a computed property on `SafetyState` that
is itself a thin wrapper over `SafetyEngine`'s own triage.

**EXPECTED AUTHORITY** - `SafetyEngine`, exclusively. No override site
exists anywhere.

## Permit / block presentation

```
grep -rn "\.active\s*=" src/ --include="*.py"
```

**Exactly two write sites**:
- `application/case_state_updater.py:62` - `h.active = not missing`
  (P4's configuration-requirement gating - operates on the real
  `DiagnosticCaseState`, analytical authority).
- `governance/reporting.py:79` - `h.active = False` (P8's governance
  gate - operates **only on a deep copy** of the state, never the
  original; confirmed by `test_p8_t23_t24_t25_governance_does_not_alter_case_state`,
  which diffs the original state before/after and asserts equality).

**EXPECTED AUTHORITY** - analytical gating belongs to `DiagnosticLoop`
(via `CaseStateUpdater`); presentation gating belongs to governance (via
`govern_and_build_result`), and the two never touch the same object.

## Modify GGM outcome

```
grep -rn "GovernanceResult(\|DiagnosticGovernanceOutcome(" src/ --include="*.py"
```

`DiagnosticGovernanceOutcome(` is constructed in exactly three places,
all inside `governance/adapter.py`'s three outcome-handling methods
(`_handle_governance_result`, `_handle_consumption_error`,
`_fail_closed_unrecognized`), and every field on it is copied from a
**real** `GovernanceResult`/`ConsumptionError` object returned by
`GGMConsumer.evaluate()` - never synthesized independently.
`GovernanceResult(` itself is never constructed anywhere in
`src/pgdr/` (only referenced in a docstring comment in `errors.py`) -
PGDR reads this type, it never creates one.

**EXPECTED AUTHORITY** - GGM, exclusively, via `GGMConsumer.evaluate()`.
`GGMDiagnosticGovernanceAdapter` translates, never decides.

## Conclusion

```
Hypothesis creation/update    -> DiagnosticLoop                       CONFIRMED, no violation
Analytical state              -> DiagnosticCaseState                  CONFIRMED, no violation
Question selection            -> QuestionSelector (via DiagnosticLoop) CONFIRMED, no violation
Safety                        -> SafetyEngine                         CONFIRMED, no violation
External diagnostic assertion -> GGM-governed presentation path       CONFIRMED, no violation
```

No fourth (hidden) authority exists anywhere in `src/pgdr/`.
