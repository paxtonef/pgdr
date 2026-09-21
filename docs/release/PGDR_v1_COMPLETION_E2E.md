# PGDR v1 Completion Program — Final E2E Suite

Four scenarios, executed against real, unmodified production code
(`DiagnosticLoop`, `build_diagnostic_intake()`,
`apply_dashboard_diagnostic_relevance()`, `AutomotiveEvidenceMapper`,
`report_builder.build_from_case_state()`) — never hand-fabricated
Evidence or hypotheses. Run at completion-branch HEAD, against the
471/471 (full-suite) regression baseline.

## E2E-1 — Legacy symptom case

Input: `"La voiture tremble au ralenti"`, driven through the real CLI-
equivalent path (`DiagnosticLoop.start()` → `run_iteration()` →
`submit_answer()`, the same machinery `pgdr run` itself calls).

Result: two hypotheses generated (`engine_running`, `tyre_or_wheel`,
both `domain_ref="vibration"`). Answering `Q-COND-001` with `"au ralenti
/ démarrage"` produced exactly the documented `SUPPORTS 0.35` /
`CONTRADICTS 0.35` pair. Confidence reconstructed independently from
`0.3 + Σsupport − Σcontradict` matched the observed value exactly for
both hypotheses (0.95 and 0.25). Report (`build_from_case_state()`)
rendered both propositions faithfully, "compatible with" phrasing
preserved, no causal claim, no repair recommendation.

**PASS.**

## E2E-2 — Manufacturer fact case

Input: the real Peugeot `oil-pressure-warning` B2-K entry (manufacturer=
Peugeot, document_id=9999_9999_326_en-GB, source_authority=
MANUFACTURER_OFFICIAL), through the real `build_diagnostic_intake()` →
`apply_dashboard_diagnostic_relevance()` path (the only existing
production path for this capability — see
`docs/architecture/b2_dashboard_manufacturer_relevance_freeze.md`).

Result: one hypothesis (`engine_running`, `domain_ref=b2r_dashboard:
Peugeot:...`), bootstrap Evidence NEUTRAL/weight=0.0, confidence=0.3.
Answering `Q-COND-001` produced exactly one new record — the pre-
existing, unmodified fallback NEUTRAL/weight=0.0 (never SUPPORTS,
never CONTRADICTS). Confidence unchanged, 0.3 before and after. Report
rendered the exact B2-R5 authored description verbatim, LOW confidence
bucket (consistent with raw 0.3), no causal transformation.

**PASS.**

## E2E-3 — Mixed-origin same-type case

One legacy `engine_running` hypothesis (via `DiagnosticLoop.start()`)
and one Peugeot `engine_running` hypothesis (via the B2-D/B2-R5 path),
combined into ONE shared `DiagnosticCaseState`, driven to `Q-COND-001`
through the real loop/selector, answered once.

Result: the legacy hypothesis received `SUPPORTS 0.35` (confidence
0.6 → 0.95); the Peugeot hypothesis received **no** Evidence at all from
that call (the legacy match short-circuits the dispatcher's fallback
globally for that call — pre-existing, unmodified behavior, not
introduced by this program) — confidence unchanged, 0.3 → 0.3. Two
hypotheses sharing one `hypothesis_type`, same case, same answer, same
call — only the explicitly authorized one moved.

**PASS.** This is the strongest available confirmation that B2-R10's
bounded generic-inheritance gate holds under real, combined execution,
not merely in isolated unit tests.

## E2E-4 — Failure/boundary case

Two sub-cases, both through the real `build_diagnostic_intake()` →
`apply_dashboard_diagnostic_relevance()` path:

1. **Insufficient visual quality.** A `DashboardInterpretationResult`
   with `match_status=INSUFFICIENT_VISUAL_QUALITY` (no matched entry).
   Result: `intake.matched_reference_entries = {}`, zero hypotheses,
   zero Evidence — the observation itself is preserved
   (`intake.observations` has 1 entry, honestly recording that a photo
   was received and could not be resolved), but nothing invents a
   diagnosis from it.

2. **Unverified source authority.** A real `MATCH` against an entry
   whose document carries `SourceAuthority.UNVERIFIED_PLACEHOLDER`
   instead of `MANUFACTURER_OFFICIAL`. Result: zero hypotheses, zero
   Evidence — the B2-R2 source-authority gate correctly blocks
   unverified content from ever bootstrapping a diagnostic claim,
   confirmed with a genuine `MATCH` (not merely an unmatched case) to
   prove the gate is what blocks it, not the absence of a match.

**PASS** for both — unsupported/insufficient knowledge is represented
honestly (as absence, or as a preserved-but-inert observation), never
silently upgraded into an invented diagnosis.

## Summary

```
E2E-1 (legacy):        PASS
E2E-2 (manufacturer):  PASS
E2E-3 (mixed-origin):  PASS
E2E-4 (failure/boundary): PASS
```

No repository modification occurred during this suite's execution;
all driving code was temporary, non-committed scratch, deleted after
use.
