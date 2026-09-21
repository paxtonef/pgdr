# PGDR v2 Known Limitations Register

Things v2 *does*, with bounded coverage - distinct from
`PGDR_v2_DEFERRED_CAPABILITIES.md`, which lists things v2 doesn't attempt
at all. A limitation here is a scope boundary that was chosen
deliberately and should not be mistaken for a defect or for "PGDR knows
everything about cars."

## Automotive evidence coverage is narrow by design

```
Questions:   2 MAPPED / 6 NEUTRAL / 2 UNMAPPED  (of 10)
Hypotheses:  2 EVIDENCE_LINKED / 10 TRIGGER_ONLY  (of 12)
```

PGDR does not reason about most possible automotive symptom/question
combinations with genuine evidence - most questions simply become
recorded observations with no analytical effect (NEUTRAL) rather than
influencing hypothesis confidence. This was P6's explicit target: 100%
**known status** for every question and hypothesis, not 100% mapped
coverage. See `docs/architecture/p6_automotive_domain_coverage.md` for
the full, computed (not hand-counted) matrix.

## One evidence rule is explicitly PROVISIONAL, not validated

`Q-EVT-002`'s mapping (recent-maintenance detail mentioning tyre/wheel
keywords -> supports `tyre_or_wheel`) reuses `symptom_taxonomy.yaml`'s
existing keyword vocabulary applied to a new observation channel - a
reasonable extension, not an independently validated automotive fact.
Weighted at half of the fully-authored `Q-COND-001` rule and support-only
(no fabricated contradicting pair). See
`docs/architecture/p6_evidence_mapping_registry.md`.

## Governance enforcement is coarser than GGM's full permission model

`GovernanceResult.effective_permissions` is a rich structure
(present/explore/recommend/plan/implement/execute/persist/propagate).
P8's gate is binary: ALLOW -> presentable, everything else -> not. PGDR
does not yet vary *how* a hypothesis is shown based on individual
permission fields. See `docs/architecture/p8_findings.md`.

## REPAIR is never executed

When GGM returns `outcome=REPAIR` with a `repair_instruction`, PGDR
treats the candidate as not-presentable rather than attempting to apply
the instruction. No PGDR mechanism exists to safely execute an arbitrary
GGM-issued repair on a hypothesis's presentation. Mandate-sanctioned
choice for v1, not an oversight.

## `operating_conditions` / `reproduction_profile` are not populated

Legacy fields on `DiagnosticSession` (cold/hot engine state, structured
reproduction conditions) - populated by the pre-P5 legacy engine, never
rebuilt in the v2 analytical path. The underlying answers ARE captured as
observations; only the specific structured re-shaping those fields
represented is absent. Documented since P5 (`p5_findings.md`), still true.

## Complaint parsing runs twice per session

A deliberate, documented duplication (not a hidden inefficiency) -
`SessionController.start()` and `AutomotiveDiagnosticDomain.interpret_observations()`
each independently call `ComplaintParser.extract()`, because
`SafetyEngine`'s input contract was never modified (P5.3) and the v2
`Observation` shape is structurally different from the legacy
`Symptom`/`WarningIndicator` shape. Documented since P5.

## `business_rules.yaml`'s hypothesis cap is unenforced

`thresholds.max_hypotheses_garage_report: 8` had its only reader
(`DiagnosticEngine.generate_hypotheses()`) removed at P7. Currently
inert - no `_HYPOTHESIS_MAP` family has more than 3 entries, so the cap
has never bound in practice regardless of which engine enforced it - but
genuinely unenforced today. Documented since P7
(`p7_legacy_reachability_audit.md`).

## Governance requires a network-free but package-present GGM install

PGDR materializes a bounded GGM runtime via `RuntimeMaterializer`
(GGM P2.2) rather than using `DefaultGGMConsumer` directly — see
`PGDR_v2_DEFERRED_CAPABILITIES.md` for the P8B history. This still runs
fully offline (no network calls), and still requires the `ggm` package
to be installed alongside PGDR - see `PGDR_v2_DEPENDENCY_FREEZE.md`.

## Manufacturer-backed diagnostic hypotheses are tracked but not yet scored by existing questions

The B2 series (B2-K through B2-R10, see `PGDR_v2_RELEASE_MANIFEST.md`'s
own entry) proved a full, governed mechanism for turning a validated
dashboard-photo interpretation of a manufacturer-official indicator into
a non-causal `DiagnosticHypothesis` — bootstrapped, auditable, tracked —
but deliberately non-scoring. Existing Q&A rules (`Q-COND-001`,
`Q-EVT-002`) do not automatically apply to these hypotheses merely
because they share a `hypothesis_type` with the legacy symptom-derived
population (B2-R6's own finding, closed by B2-R10's bounded
generic-inheritance gate) — and no manufacturer-specific applicability
has been separately authored or authorized. Concretely: answering
`Q-COND-001` today never changes a Peugeot manufacturer-backed
hypothesis's confidence, regardless of the answer given. This is the
correct, honest behavior of an unestablished relationship (`applicability
not established`, never `NOT_APPLICABLE`) — not a defect, and not
something this release invents a numeric answer for. See
`docs/architecture/b2_dashboard_manufacturer_relevance_freeze.md` for
the full investigation trail (B2-R4 through B2-R10) that established
this boundary deliberately, in the same spirit as P6's own "100% known
status, not 100% mapped coverage" target for the legacy symptom path.

## No real visual dashboard-interpretation provider is integrated

Every dashboard-photo interpretation exercised anywhere in this
codebase (tests, and the E2E validation referenced above) uses a
deterministic test stub (`_ScriptedVisualProvider` or equivalent) behind
the `DashboardInterpretationPort` Protocol — never a real vision
model/API. A user cannot submit an actual dashboard photo through
`pgdr run` today; the entire B2 series' own governed pipeline
(`run_governed_interpretation()` → `build_diagnostic_intake()` →
`apply_dashboard_diagnostic_relevance()`) is real, tested, and provider-
agnostic, but has nothing production-grade to call. See
`PGDR_v2_DEFERRED_CAPABILITIES.md`.
