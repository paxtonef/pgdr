# B2 Series — Dashboard / Manufacturer-Fact Diagnostic Relevance Freeze

Per the same discipline P0-P8 established: this freezes the boundary of
responsibility the B2 series actually built and proved, not every
implementation detail inside it, and not what a future series might add.
Written at PGDR v1 Completion Program time, consolidating a long,
incremental investigation-then-implementation sequence (B2-K through
B2-R10) into one canonical reference, matching the standard every P-phase
already set with its own `pX_findings.md`/`pX_architecture_freeze.md`.

## Canonical governed pipeline (verified, current state)

```
PrimaryDiagnosticMedia (a dashboard photo)
    |
MediaResolverPort -> ResolvedMedia                          (B1/B1.5)
    |
Vehicle Identity -> VehicleDashboardKnowledgePort
    -> DashboardReferenceSet                                (B2-K)
    |
ResolvedMedia + DashboardReferenceSet
    |
DashboardInterpretationPort.interpret()                     (B2-V)
    -> UNTRUSTED DashboardInterpretationResult(s)
    |
run_governed_interpretation()                                (B2-V)
    -- the mandatory validation boundary; unavoidable, no bypass exists
    -> VALIDATED DashboardInterpretationResult(s)
    |
build_diagnostic_intake()                                    (B2-D)
    -> DiagnosticIntakeResult (Observation(s) + Evidence[MATCH only]
       + matched_reference_entries, the exact B2-K entry, never
       re-queried — B2-C)
    |
ingest_dashboard_interpretation()                             (B2-I)
    -> CaseStateUpdater.add_observations()/.add_evidence()   (existing,
       unmodified — no new CaseState mutation mechanism)
    |
AutomotiveDiagnosticDomain.apply_dashboard_diagnostic_relevance()
    (B2-R1/R2/R5)
    -> 0/1/N candidate DiagnosticHypothesis, non-causal, system-level
    -> targeted Evidence, EvidenceDirection.NEUTRAL, weight=0.0
       (bounded bootstrap convention — tracked/auditable, deliberately
       non-scoring; NEVER a claim of epistemic neutrality toward the
       hypothesis — B2-R4)
    |
AutomotiveEvidenceMapper (_apply_discriminating_rule /
    _apply_provisional_keyword_rules)                         (B2-R10)
    -- bounded generic-inheritance gate: hypothesis_type membership
       alone is NOT sufficient authorization; h.domain_ref must be an
       EXACT member of the rule's own authored authorized set
       (_LEGACY_SYMPTOM_DOMAIN_REFS, reusing the existing SymptomFamily
       enum verbatim) — never parsed, never inferred from string shape
    |
DeterministicHypothesisScorer (existing, unmodified)
```

Every arrow above is real, executed, production code — proved not only
by unit tests but by a dedicated end-to-end validation run (see
`docs/release/PGDR_v1_COMPLETION_E2E.md`) driving the real
`build_diagnostic_intake()`/`apply_dashboard_diagnostic_relevance()`/
`AutomotiveEvidenceMapper` functions, not hand-constructed fixtures.

## What is NOT part of this pipeline (frozen boundary)

- **No real visual provider.** `DashboardInterpretationPort` has zero
  production implementations anywhere in this repository — only
  deterministic test stubs. This was authorized as an explicit,
  repeated boundary from B2-V's own founding mandate onward, never
  revisited.
- **No wiring into `SessionController`/`DiagnosticLoop`/the CLI.**
  `build_diagnostic_intake()` and `apply_dashboard_diagnostic_relevance()`
  are called directly by tests and by the E2E validation — never by any
  production orchestration layer. Every B2-D/B2-I mandate deliberately
  deferred this as "a separate acceptance decision." The PGDR v1
  Completion Program's own Closure Assessment confirmed this remains the
  correct boundary: wiring an entry point that cannot yet produce a real
  `MATCH` (no provider exists to call) would be dead or misleading code,
  not genuine completion.
- **No causal/component-level diagnosis, no repair recommendation.**
  Preserved throughout, unchanged, from B1's own original mandate.
- **No manufacturer-specific Q&A applicability authored.** B2-R6 found
  that existing generic rules (`Q-COND-001`) could silently cross-route
  Evidence to manufacturer-backed hypotheses merely by sharing a
  `hypothesis_type`. B2-R7 traced the actual (and, it turned out, only
  partially contractual) authority for this to the `EvidenceMapper`'s
  own rule tables. B2-R8 proved the existing rule-table shape could
  represent finer authorization using only already-existing fields
  (`domain_ref`, exact match, never parsed) without new architecture.
  B2-R9 resolved the one remaining constitutional question — new-origin
  hypotheses do NOT automatically inherit rules authored and tested
  against the original single-primary-symptom population — using
  evidence reaching back to the very first commit of this repository
  (pre-P4 `DiagnosticEngine`, where `hypothesis_type`/`system_family`
  never once represented more than one concurrent hypothesis instance
  until B2-R1 changed that cardinality). B2-R10 implemented the
  resulting bounded gate. **The three real Peugeot hypotheses
  (`oil-pressure-warning`, `engine-diag-fixed`, `engine-diag-flashing`)
  remain fully tracked and auditable but receive zero scoring effect
  from any existing question — this is `applicability not established`,
  never `NOT_APPLICABLE`, and is the correct, intended current state, not
  a defect.**

## Evidence weight / calibration (unresolved, explicitly not invented)

B2-R4's own investigation established, with direct code evidence, that
**no Evidence weight anywhere in this codebase — POC or pre-existing —
has ever had a calibration methodology**. `_BASELINE = 0.3`,
`_DISCRIMINATING_WEIGHT = 0.35`, `_PROVISIONAL_WEIGHT = 0.15`, and every
B2-series weight are all author-chosen constants with no documented
epistemic derivation; `DeterministicHypothesisScorer`'s own docstring
says so explicitly ("the contract is what matters, not this specific
scoring strategy"). This is a pre-existing, project-wide characteristic,
not something the B2 series introduced or is responsible for resolving.

## Test evidence

`test_block_b2v_visual_interpretation.py`, `test_block_b2d_diagnostic_intake.py`,
`test_block_b2i_pipeline_integration.py`, `test_block_b2c_reference_context.py`,
`test_block_b2r1_diagnostic_relevance.py`, `test_block_b2r2_production_rule_identity.py`,
`test_block_b2r5_peugeot_bootstrap.py`, `test_block_b2r10_inheritance_gate.py`,
plus the real Peugeot B2-K fixture (`test_block_b2k_peugeot_poc.py`) —
roughly 230 tests across this series, all included in the current
471/471 (full suite) baseline.

## Governing principle carried forward from every block in this series

> Prove the mechanism against real, executed inputs before authoring any
> new diagnostic content. Never let a technical capability (a finer
> selector, a governed boundary, a bootstrap convention) become, by
> itself, permission to assert diagnostic knowledge that has not been
> separately, honestly established.
