# P5 Legacy Deprecation

> **Scope note (post-hoc re-labeling):** the narrower
> **P5 — Production Path Integration** does not require a full legacy
> deprecation table — only that the legacy engine is no longer
> authoritative on the production path (which it isn't — see
> `p5_production_path.md`'s "legacy status" section for the short version).
> This full per-method table belongs to **P7 — Legacy Analytical Path
> Retirement**. Built and tested during the original P5 pass; kept as-is,
> delivered early.

Per mandate §21: no duplicate path may remain without an explicit status.

| Component | Status | Detail |
|---|---|---|
| `DiagnosticEngine.generate_hypotheses()` | **DEPRECATED** | Class still constructed (`SessionController.diagnostic_engine`), method never called on the production path. Kept importable for the comparison harness (`tests/test_p5_comparison_harness.py`) and for anyone still using `DiagnosticEngine` directly outside `SessionController`. |
| `DiagnosticEngine.process_answers()` | **REMOVED** (from production path) | No replacement exists yet — see the honest gap noted in `p5_findings.md` (§ "What P5 did not build"). Still callable directly (unchanged code), just never invoked by `SessionController`. |
| `DiagnosticEngine.detect_contradictions()` | **DEPRECATED**, superseded | Logic ported faithfully into `AutomotiveDiagnosticDomain.detect_contradictions()`. The original method is untouched and still callable (used by the comparison harness), but production code calls only the new one. |
| `SessionController._select_questions()` | **REMOVED** | Deleted entirely in the P5 rewrite. No legacy reference kept — it was a private method with zero external callers (confirmed via repo-wide search before removal), so no compatibility shim was needed. |
| `ReportBuilder.build()` | **DEPRECATED** | Class still constructed (`SessionController.report_builder`) for its `_URGENCY_COPY` table reference; `.build()` itself is never called by the production path. Still fully functional and covered by its own pre-P4 tests if called directly. |
| `ReportBuilder._build_garage_report()` / `._build_user_summary()` | **DEPRECATED** | Same status as `.build()` — still work if called directly (they operate on the same `DiagnosticSession`/`SafetyTriage` types as before), just not reached from `SessionController` anymore. |
| Old question-selection priority (`_CATEGORY_PRIORITY` dict, `SessionController`'s static category sort) | **REMOVED** | No longer exists anywhere. Superseded by `DeterministicQuestionSelector`'s 4-tier priority (contradiction > multi-hypothesis > high-severity-uncertainty > remaining). |

## Verified, not asserted

`test_p5_t03_legacy_diagnostic_engine_not_authoritative` monkeypatches
`DiagnosticEngine.generate_hypotheses` and `.process_answers` to raise
`AssertionError` if called, then runs a full production session to
completion. It passes — proving these methods are genuinely unreachable
from `SessionController`, not merely undocumented as deprecated.

## Nothing was physically removed from the codebase except one method

Per the mandate's own framing (§6): "Le but n'est pas nécessairement de
supprimer physiquement `DiagnosticEngine` dès P5" — only
`_select_questions()` was deleted outright (a private method, zero
external callers, no reason to keep it). Every other legacy component
remains present, importable, and independently functional — deprecated in
the sense of "not on the authoritative production path," not in the sense
of "broken" or "about to be deleted without notice."
