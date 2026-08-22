# PGDR v2 Release Manifest

Inventories what actually exists in the code at release time (commit
`aa3a760` + this freeze's own commit), not what was planned. Every
"TEST EVIDENCE" entry names real, currently-passing tests. Status is one
of `ACTIVE`, `DEFERRED`, `EXPERIMENTAL`, `DEPRECATED` - no other value is
used anywhere in this document.

## Packaging / Installation

| | |
|---|---|
| Implementation | `pyproject.toml` (hatchling), `install.sh` (self-contained installer, vendors the pinned GGM wheel) |
| Authoritative component | `pyproject.toml` force-include of 4 config YAMLs; `vendor/ggm-1.2.0-py3-none-any.whl` |
| Test evidence | `test_p0_packaging.py` (11 tests), `test_p7_t09_wheel_build_install_scenario_after_retirement`, `test_p8_t30_cli_regression_with_governance_enabled` |
| Status | **ACTIVE** |
| Version/dependency | Python >=3.10; pydantic>=2.0, pyyaml>=6.0, rich>=13.0, click>=8.0, ggm>=1.2.0 |

## Configuration Integrity

| | |
|---|---|
| Implementation | `config_loader.py` - fail-closed loading + full semantic validation of `safety_rules.yaml` |
| Authoritative component | `load_all_configs()`, `SafetyEngine.__init__` |
| Test evidence | `test_p0_config_integrity.py` (22 tests) |
| Status | **ACTIVE** |

## Readiness

| | |
|---|---|
| Implementation | `readiness.py` - 4 required checks: packaged config, safety engine, session controller, GGM consumption |
| Authoritative component | `check_readiness()` |
| Test evidence | `test_p1_readiness.py` (13 tests), `test_p8_t27_t28_readiness_false_and_fail_closed_when_ggm_unavailable` |
| Status | **ACTIVE** |

## Rule / Invariant Enforcement

| | |
|---|---|
| Implementation | `safety_rules.yaml` (20 rules), `automotive/domain_validator.py` (fail-closed domain-config validation) |
| Authoritative component | `SafetyEngine.evaluate()`, `validate_automotive_domain()` |
| Test evidence | `test_p0_config_integrity.py`, `test_p6_t06`-`t09` (invalid reference/weight/provisional-marker rejection) |
| Status | **ACTIVE** |

## Generic Diagnostic Domain (DiagnosticCaseState / DiagnosticLoop / EvidenceMapper / HypothesisScorer / QuestionSelector)

| | |
|---|---|
| Implementation | `domain/analytical_state.py`, `application/diagnostic_loop.py`, `ports/*.py` (4 Protocols), `application/case_state_updater.py`, `application/hypothesis_scorer.py`, `application/question_selector.py` |
| Authoritative component | `DiagnosticCaseState` (sole analytical state), `DiagnosticLoop` (sole progression engine) - frozen at P7 |
| Test evidence | `test_p4_diagnostic_loop.py` (16 tests, P4-T01..T17), `test_p7_retirement.py` (single-authority proofs) |
| Status | **ACTIVE** |

## Automotive Domain Adapter / Evidence Mappings / Coverage

| | |
|---|---|
| Implementation | `automotive/domain_adapter.py` (`AutomotiveDiagnosticDomain`), `automotive/evidence_mapper.py`, `automotive/coverage.py` |
| Authoritative component | `_HYPOTHESIS_MAP` (12 hypothesis types, 16 entries), 2 of 10 questions MAPPED (1 fully-authored, 1 PROVISIONAL) |
| Test evidence | `test_p6_evidence_enrichment.py` (14 tests, P6-T01..T17 + signature), `test_p5_integration.py`'s domain-enrichment tests |
| Status | **ACTIVE** - see `PGDR_v2_KNOWN_LIMITATIONS.md` for coverage scope |

## SafetyEngine

| | |
|---|---|
| Implementation | `safety_engine.py` - unchanged since P0 |
| Authoritative component | `SafetyEngine.evaluate()` - sole safety authority; driving-assessment vocabulary structurally cannot express "confirmed safe" |
| Test evidence | `test_p0_config_integrity.py`, `test_runner.py`'s safety scenarios (24 tests incl. brake/steering/EV-battery/fluid-leak), `test_p8_t26_safety_preemption_unchanged` |
| Status | **ACTIVE** |

## SessionController / User Summary / Garage Report

| | |
|---|---|
| Implementation | `session_controller.py` (orchestration only, no analytical authority since P5/P7), `report_builder.py` (`build_from_case_state`/`build_result_from_case_state`) |
| Authoritative component | `SessionController.start()`/`.submit_answer()`; the two report-builder functions are the sole production reporting path |
| Test evidence | `test_p5_integration.py` (24 tests incl. signature P5-T21), `test_runner.py` (24 scenario/regression tests) |
| Status | **ACTIVE** |

## Legacy Retirement

| | |
|---|---|
| Implementation | N/A - `DiagnosticEngine` and `ReportBuilder` (legacy classes) removed entirely at P7 |
| Authoritative component | `docs/architecture/p7_legacy_reachability_audit.md`, `p7_retirement_result.md` |
| Test evidence | `test_p7_retirement.py` (10 tests, P7-T01..T10 incl. AST/attribute-absence proof) |
| Status | **ACTIVE** (retirement itself; nothing to defer - it's complete) |

## GGM Consumer Integration / Governance Traces / Fail-Closed Governance

| | |
|---|---|
| Implementation | `governance/` package (7 modules): `consumption_profile.py`, `port.py`, `object_mapper.py`, `adapter.py`, `trace.py`, `reporting.py`, `errors.py` |
| Authoritative component | `GGMDiagnosticGovernanceAdapter` (sole caller of `GGMConsumer.evaluate()`); `DiagnosticCaseState` never mutated by governance (deep-copy gate) |
| Test evidence | `test_p8_ggm_integration.py` (23 tests incl. signature, BLOCK/REPAIR/ESCALATE/ConsumptionError handling, AST-scanned import boundary) |
| Status | **ACTIVE** (P8A - consumer-contract integration) / **ACTIVE** (P8B - bounded/embedded GGM runtime, delivered via GGM P2.2 `RuntimeMaterializer`; see `PGDR_v2_DEFERRED_CAPABILITIES.md`) |
| Version/dependency | GGM package `1.2.0`, target source commit `ac99750`, contract v1.3, resolver v1.3, kernel/runtime `ggm/1.1`, wheel SHA-256 `7340c166918e5b9bb83008a8f5944ef0ae64b0c1995189fc3860d7a90b1baff2` (full provenance: `PGDR_v2_DEPENDENCY_FREEZE.md`) |

## Summary

```
157/157 tests passing (verified baseline for this freeze, before any change)
9 test files, 8 phases (P0, P1, P4-P8) each with dedicated coverage
0 DEPRECATED capabilities (P7 retirement was clean - nothing left half-removed)
1 EXPERIMENTAL-adjacent item: the Q-EVT-002 PROVISIONAL evidence rule (see Known Limitations)
```
