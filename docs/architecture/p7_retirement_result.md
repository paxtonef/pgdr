# P7 Retirement Result

Executed exactly per the classification in
`p7_legacy_reachability_audit.md`. No component was removed or changed
that audit didn't already classify.

## REMOVED

```
DiagnosticEngine.process_answers()          — src/pgdr/diagnostic.py
DiagnosticEngine.generate_hypotheses()      — src/pgdr/diagnostic.py
DiagnosticEngine.detect_contradictions()    — src/pgdr/diagnostic.py
DiagnosticEngine class itself (__init__,
  self.config)                              — src/pgdr/diagnostic.py
ReportBuilder.build()                       — src/pgdr/report_builder.py
ReportBuilder._build_garage_report()        — src/pgdr/report_builder.py
ReportBuilder._build_user_summary()         — src/pgdr/report_builder.py
ReportBuilder._determine_status()           — src/pgdr/report_builder.py
ReportBuilder class itself                  — src/pgdr/report_builder.py
SessionController.diagnostic_engine
  (construction line)                       — src/pgdr/session_controller.py
SessionController.report_builder
  (construction line)                       — src/pgdr/session_controller.py
tests/test_p5_comparison_harness.py         — whole file (4 test cases)
```

`diagnostic.py`: 210 lines -> 105 lines (now contains only `_HYPOTHESIS_MAP`
and its module docstring).
`report_builder.py`: 441 lines -> 292 lines (now contains only
`_URGENCY_COPY`, `build_from_case_state()`, `build_result_from_case_state()`,
and their private helpers).

## ADAPTED

```
DiagnosticEngine._generic_entries() (staticmethod)
  -> relocated to automotive/domain_adapter.py as
     _generic_hypothesis_entries() (module-level function, its sole caller)
  -> ZERO behavior change: same logic, same signature shape, only its
     location and the fact that it's no longer wearing a class changed.

test_p5_t03_legacy_diagnostic_engine_not_authoritative
  -> rewritten in place (same name, same position in the file, same
     intent) — mechanism changed from "monkeypatch a method to raise"
     to "assert the symbol doesn't exist." Stronger, not weaker.

readiness.py::_check_session_controller() docstring
  -> updated to remove stale references to DiagnosticEngine/ReportBuilder
     as things SessionController construction "exercises" — pure
     documentation accuracy fix, zero behavior change (the function body
     itself, `SessionController()` + exception handling, is untouched).

session_controller.py module docstring
  -> rewritten to describe the post-retirement state instead of the
     P5 "kept but unauthoritative" framing, which was no longer accurate.

automotive/domain_adapter.py module docstring
  -> added a note explaining where _generic_hypothesis_entries() came
     from and why.
```

## KEPT (confirmed, not touched)

```
SafetyEngine (all methods)           — explicitly out of scope, mandate §10
ComplaintParser (all methods)        — linguistic/domain extraction, not
                                        parallel analytical inference, mandate §11
_HYPOTHESIS_MAP                      — automotive domain DATA, mandate §4
pgdr/models.py (all fields/classes)  — public request/response schema,
                                        mandate §28. DiagnosticSession.hypotheses/
                                        .contradictions/.operating_conditions/
                                        .reproduction_profile/.events remain in
                                        the schema, permanently empty-by-default
                                        now that their only writer is gone —
                                        this is a dead field, not a competing
                                        authority, and out of P7's scope to remove
CLI (cli.py, run_pgdr.py)            — no changes, confirmed by P7-T10
business_rules.yaml (the file)       — still required by P0's 4-config
                                        fail-closed contract regardless of
                                        DiagnosticEngine's removal; see the
                                        "inert governance gap" finding below
                                        for the one field within it that's
                                        now unenforced
```

## DEPRECATED

None. The audit found no component requiring a temporary
compatibility-only status — everything was either cleanly reachable
(KEEP/ADAPT) or cleanly unreachable (REMOVE), confirmed by direct trace
before any change was made.

## Tests migrated

```
test_p5_comparison_harness.py (4 cases, all REMOVED)
  -> invariants preserved elsewhere, explicit mapping:

     "emergency still blocks"
       -> test_scenario_2_brake_pedal_loss_triggers_emergency_stop (test_runner.py)
       -> test_p7_t07_safety_scenarios_unchanged_post_retirement (new)

     "hypotheses non-empty for non-emergency complaints"
       -> test_p5_t01_session_controller_initializes_case_state (test_p5_integration.py)
       -> test_p7_t01_no_reachable_legacy_analytical_component (new)

     "identity context preserved"
       -> test_p5_t06_vir_context_preserved_in_case_state (test_p5_integration.py)

     "complaint preserved verbatim"
       -> test_p5_t17_t18_t19_reports_generated_from_same_canonical_state
          (test_p5_integration.py)
       -> test_p7_t10_cli_entry_point_unchanged (new, via CLI subprocess)

test_p5_t03_legacy_diagnostic_engine_not_authoritative
  -> rewritten in place (see ADAPTED above)

10 new tests added: tests/test_p7_retirement.py (P7-T01 through P7-T10)
```

## Configs removed

None. All 4 YAML files (`safety_rules.yaml`, `symptom_taxonomy.yaml`,
`questions.yaml`, `business_rules.yaml`) remain required by P0's
fail-closed configuration contract, which P7 does not alter. Per the
"inert governance gap" finding in `p7_legacy_reachability_audit.md`:
`business_rules.yaml`'s `thresholds.max_hypotheses_garage_report` field
is now unenforced (its only reader, `DiagnosticEngine.generate_hypotheses()`,
is removed) — the field itself was NOT deleted from the YAML, since
`business_rules.yaml` as a whole remains required and P7 doesn't purge
individual unused keys from an otherwise-required file (that would be new
config-hygiene work, not retirement of a competing analytical authority).

## Compatibility elements remaining

None. This is a genuinely clean retirement — no shim, no compatibility
wrapper, no feature flag was needed, because the audit found zero external
callers requiring one. The mandate's own §12 warning ("le flag sert au
rollback/test, pas à maintenir deux architectures éternellement") never
had to be tested against reality — no flag was introduced in the first
place, because none of the retired code had any production reachability
to guard a rollback against.

## Verification

```
Baseline (before P7):                128/128 PASS
After retirement (before P7 tests):  124/124 PASS (128 - 4 removed
                                      comparison-harness cases)
After P7 test suite added:           134/134 PASS (124 + 10 new P7-T01..T10)
```

No test was skipped, xfailed, or silently disabled to reach this number.
