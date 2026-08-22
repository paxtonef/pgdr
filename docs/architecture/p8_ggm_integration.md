# P8 — PGDR x GGM Governed Consumption Integration

## What P8 does

Every active hypothesis PGDR's analytical engine (P4-P7) produces is now
governed by GGM before it can appear in a diagnostic report. Governance
runs between `DiagnosticCaseState` (the frozen P7 analytical boundary) and
`PreGarageDiagnosticResult` (the frozen P7 reporting boundary) — it never
reaches into either.

```
DiagnosticCaseState (unchanged, P4-P7)
    |
[P8 SEAM]
    |
    DiagnosticGovernanceCandidate  (1 per active hypothesis)
        |
    PGDRGGMObjectMapper.to_governed_claim_dict()
        |
    GovernanceRequest(operation=DECIDE)
        |
    GGMConsumer.evaluate()   <-- the REAL pinned ggm package, commit 4fda597
        |
    GovernanceResult | ConsumptionError
        |
    DiagnosticGovernanceOutcome (presentable: bool)
        |
    [deactivate non-presentable hypotheses on a COPY of the case state]
        |
build_result_from_case_state()  (P5, UNCHANGED - the frozen reporting function)
    |
PreGarageDiagnosticResult
```

## Real GGM contract, verified against source

Every symbol used was confirmed by reading the pinned package's own code,
not the mandate's prose:

```
ggm.contract.types.CONTRACT_VERSION        = "1.2"
ggm.contract.types.RUNTIME_VERSION         = "ggm/1.1"
ggm.consumption.CANONICAL_KERNEL_VERSION   = "ggm/1.1"
ggm.consumption.MANDATORY_INVARIANT_IDS    = [GGM-I01, GGM-I03, GGM-I08, GGM-I10]
ggm.profiles.build_default_profiles()      -> {"ggm.base": version "1.0", ...}
```

56/56 GGM's own contract tests pass against this pinned package
(`test_ggm_consumer_contract.py`, `test_ggm_consumption_resolution.py`),
confirmed before any PGDR code was written against it.

## Import boundary (enforced by test, not just convention)

`src/pgdr/governance/` imports exclusively from `ggm.contract`,
`ggm.consumption`, and `ggm.model` — never `InvariantEngine`,
`ProfileResolver`, `TransitionEngine`, `GovernanceDecisionEngine`,
`EscalationDetector`, or any P2.2 lab/evaluation module
(`semantic_provider.py`, `openai_semantic_provider.py`, `sgri_validator.py`,
etc. — all present in the pinned repo's root but explicitly out of scope
per the developer pack's own README). `test_p8_t01_no_forbidden_ggm_imports_in_governance_package`
and `test_p8_t01b_only_contract_and_consumption_ggm_modules_imported`
scan the actual AST of every file in the governance package for this —
not a manual review, a mechanical guarantee.

## Safety boundary (unchanged)

The safety-escalation path in `SessionController.start()` (unchanged
since P0) returns its report via `build_result_from_case_state()`
directly — it never touches governance. `test_p8_t26_safety_preemption_unchanged`
confirms zero governance traces exist for a safety-escalated session.
This matches mandate §28: GGM governs what PGDR may *express* about its
diagnostic reasoning, not the deterministic safety verdict, which was
never PGDR's own reasoning to govern in the first place.

## What P8 does NOT do (deliberately)

- Does not implement GGM locally — every governance decision comes from
  a real `GGMConsumer.evaluate()` call.
- Did not originally build/consume a bounded/embedded GGM runtime — the
  pinned package did not provide one at P8 time. UPDATE: GGM P2.2
  shipped `RuntimeMaterializer`, and PGDR now materializes and consumes
  a bounded runtime by default (see `p8_findings.md`, "P8A/P8B split",
  and `PGDR_v2_DEPENDENCY_FREEZE.md`).
- Does not attempt to execute `repair_instruction` — REPAIR is treated
  as not-presentable in P8 v1 (mandate's own sanctioned conservative
  choice, §18).
- Does not enforce `effective_permissions` field-by-field beyond
  "is this candidate presentable at all" — a coarser gate than the full
  permission model GGM returns; documented as a known v1 limitation.
- Does not build a PGDR-specific governance profile — selects only the
  canonical `ggm.base`.

## Verification

```
56/56   GGM's own contract test suite (baseline, unmodified)
134/134 P0-P7 PGDR tests (unchanged, governance now live by default)
23/23   new P8 tests (test_p8_ggm_integration.py)
157/157 total combined suite
```

See `p8_consumption_profile.md` for the three-axis declaration detail,
`p8_mapping_contract.md` for the PGDR-GGM object mapping, and
`p8_findings.md` for discrepancies discovered and honest limitations.
