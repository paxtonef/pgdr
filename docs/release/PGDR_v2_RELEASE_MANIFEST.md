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

## Dashboard / Manufacturer-Fact Diagnostic Relevance (B2 series)

| | |
|---|---|
| Implementation | `ports/dashboard_interpretation.py`, `domain/dashboard_knowledge.py`, `adapters/peugeot_dashboard_knowledge.py`, `ports/knowledge_repository.py`, `ports/vehicle_dashboard_knowledge.py`, `application/diagnostic_intake_from_interpretation.py` (B2-D), `application/diagnostic_intake_ingestion.py` (B2-I), `automotive/domain_adapter.py` extension `apply_dashboard_diagnostic_relevance()` (B2-R1/R2/R5), `automotive/evidence_mapper.py` bounded-inheritance gate `_LEGACY_SYMPTOM_DOMAIN_REFS` (B2-R10) |
| Authoritative component | `build_diagnostic_intake()` (governed B2-V validation boundary `run_governed_interpretation()` is unavoidable), `AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance()`, `CaseStateUpdater` (reused unmodified) |
| What it does | A validated dashboard photo interpretation (`MATCH` only; `AMBIGUOUS_MATCH`/`NO_MATCH`/`INSUFFICIENT_VISUAL_QUALITY` never bootstrap anything) against a manufacturer-official (`SourceAuthority.MANUFACTURER_OFFICIAL`) B2-K reference entry becomes a non-causal, system-level `DiagnosticHypothesis`, bootstrapped via `EvidenceDirection.NEUTRAL`/`weight=0.0` (tracked and auditable, deliberately non-scoring — never a claim of epistemic neutrality toward the hypothesis). Three real Peugeot entries are authored (`oil-pressure-warning`, `engine-diag-fixed`, `engine-diag-flashing`), classified under the existing `engine_running` `hypothesis_type` with the precise manufacturer proposition preserved in `description`. Existing Q&A scoring rules (`Q-COND-001`, `Q-EVT-002`) do **not** automatically apply to these hypotheses merely because they share a `hypothesis_type` with the legacy symptom-derived population — B2-R10's bounded generic-inheritance gate requires exact `domain_ref` authorization, reusing the existing `SymptomFamily` enum as that authorized set; applicability of existing questions to any Peugeot proposition remains explicitly `UNDETERMINED` (unauthorized), never silently inherited and never asserted as `NOT_APPLICABLE`. |
| What it deliberately does NOT do | No real visual provider is integrated (only a deterministic test stub exists — `DashboardInterpretationPort` has no production implementation); no wiring from this capability into `SessionController`/`DiagnosticLoop`/the CLI exists — a user cannot submit a dashboard photo through `pgdr run` today. Both are intentional v1 boundaries, not partial/incomplete integration — see `PGDR_v2_DEFERRED_CAPABILITIES.md`. No causal/component-level diagnosis, no repair recommendation, no Evidence-weight calibration methodology exists for this or any other Evidence source (pre-existing, unrelated to this series). |
| Test evidence | `test_block_b2v_visual_interpretation.py`, `test_block_b2d_diagnostic_intake.py`, `test_block_b2i_pipeline_integration.py`, `test_block_b2c_reference_context.py`, `test_block_b2r1_diagnostic_relevance.py`, `test_block_b2r2_production_rule_identity.py`, `test_block_b2r5_peugeot_bootstrap.py`, `test_block_b2r10_inheritance_gate.py`, plus the real Peugeot B2-K fixture in `test_block_b2k_peugeot_poc.py` (~230 tests total across this series) |
| Status | **ACTIVE** (mechanism, governed boundary, inheritance gate) / **DEFERRED** (SessionController/CLI wiring; real visual provider — see `PGDR_v2_DEFERRED_CAPABILITIES.md`) |

## Summary

```
471/471 tests passing (GGM_WHEEL_PATH set — full suite incl. packaging/wheel);
460 passed / 11 skipped without the wheel installed (11 skips are the
packaging tests that specifically require it — see Known Limitations)
9 legacy (P0-P8) test files + 9 B2-series test files
0 DEPRECATED capabilities (P7 retirement was clean - nothing left half-removed)
1 EXPERIMENTAL-adjacent item: the Q-EVT-002 PROVISIONAL evidence rule (see Known Limitations)
1 ADDITIVE, self-contained capability built after the original v2 freeze
  (dashboard/manufacturer-fact diagnostic relevance, B2 series) — proven
  end-to-end (see PGDR_v1_COMPLETION_E2E.md) but not wired into the
  primary user-facing entry point; see this document's own B2 series
  entry above and PGDR_v2_DEFERRED_CAPABILITIES.md
```
