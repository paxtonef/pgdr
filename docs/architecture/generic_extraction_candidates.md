# Generic Extraction Candidates (P2)

**Not an architecture.** This document lists MIXED-classified rules from
`pgdr_rule_invariant_extraction.md` as candidates for a future generic
diagnostic engine. No code is renamed or moved. Per the P2 mandate: if this
document said `Vehicle → Machine` or `DrivingAssessment → OperatingPermission`
anywhere in the codebase, that would be a P2 scope violation — it only says
so here, as a candidate to evaluate in P3.

Format per candidate: current automotive concept → underlying generic
concept candidate → evidence supporting generalization → counter-evidence /
automotive dependency → classification.

---

## Candidate 1

**Current automotive concept:** Vehicle identity resolution status
(`VehicleIdentityContext.resolution_status`: resolved / provisionally_resolved /
ambiguous / insufficient_data / contradictory) limiting reasoning specificity.

**Underlying generic concept candidate:** Machine/asset identity confidence
gating configuration-specific inference.

**Evidence supporting generalization:** The pattern — "don't reason about a
specific configuration when you're not sure which configuration you're
looking at" — has nothing car-specific in it. An industrial pump, a
boiler, or a generator would need the identical guard before reasoning
about *that specific model's* known failure modes.

**Counter-evidence / automotive dependency:** The current implementation
is 100% categorical (5 fixed enum values) and comes from a named external
dependency (Vehicle Identity Resolver) whose contract is automotive-shaped
(`vehicle_identity: dict` with implicitly automotive keys like make/model/
engine, per the AMD spec's example). The numeric confidence score
(`ConfidenceScore.score`) that would make this genuinely generalizable
exists on the model but — per Finding #1 in `p2_findings.md` — is never
actually read anywhere. The generalization is aspirationally clean; the
current implementation is not there yet even for the automotive case.

**Classification:** MIXED — strong candidate for P3, but P3 would need to
build the (currently absent) confidence-threshold mechanism as part of
generalizing it, not just rename it.

---

## Candidate 2

**Current automotive concept:** `DrivingAssessment` (not_assessed /
do_not_drive / limited_movement / professional_assessment_required) — the
prohibition on ever asserting `safe_to_drive`.

**Underlying generic concept candidate:** `OperatingPermission` or
`OperatingSafetyState` — an enum that can express "should not operate,"
"limited operation only," "needs professional assessment," but
structurally cannot express "certified safe to operate."

**Evidence supporting generalization:** The invariant this enforces —
"an analytical system must never assert unconditional operational safety"
— applies identically to a pump, a boiler, or a piece of factory
machinery. The mechanism (closing the enum, not adding a runtime check) is
exactly the kind of structural guarantee that ports cleanly across
domains.

**Counter-evidence / automotive dependency:** The specific *values*
(`limited_movement`, `do_not_drive`) are phrased in driving vocabulary.
"Movement" doesn't obviously apply to a stationary boiler.

**Classification:** MIXED — the strongest candidate in this document. The
*enforcement mechanism* (an enum with no "safe" member) generalizes
perfectly; only the label vocabulary needs domain-specific values, which
is a normal, expected variation point for a Domain Pack.

---

## Candidate 3

**Current automotive concept:** `GaragePreparationReport` /
`GarageReport` — the technical document handed to a professional, kept
structurally distinct from `UserSummary`.

**Underlying generic concept candidate:** `InterventionReport` — a
technical handoff document for whoever will physically examine/service the
machine, distinct from the operator-facing summary.

**Evidence supporting generalization:** The two-audience split (technical
professional vs. non-technical operator) and the specific sub-structure
(reported problem verbatim + symptom summary + safety information +
systems/checks to examine + limitations + unresolved questions) has no
car-specific dependency in its *shape*. A factory-maintenance handoff
document would want the identical structure.

**Counter-evidence / automotive dependency:** The `vehicle` field
specifically, and field names like `recent_vehicle_events` and
`warning_indicators` (dashboard-light-shaped), carry automotive
vocabulary. The content — not the structure — assumes a car.

**Classification:** MIXED — good candidate, but per Findings #3, #8 the
current implementation has real content-quality gaps (static
`unresolved_questions`, thin `symptom_summary`) that would generalize
*as-is*, i.e. a Machine Diagnostic Engine's `InterventionReport` would
inherit these gaps unless they're fixed first. Generalizing the shape
without fixing the content would just relocate the problem.

---

## Candidate 4

**Current automotive concept:** Symptom family taxonomy (`SymptomFamily`
enum: braking, steering, vibration, warning_light, fluid_leak, ...) and the
family → hypothesis mapping (`_HYPOTHESIS_MAP`).

**Underlying generic concept candidate:** A domain-specific symptom
taxonomy is inherently NOT generic — but the *mechanism* around it
(keyword-based family detection → confidence-weighted system-family
hypotheses → "compatible with" phrasing) could be a generic pattern
parameterized by a domain-supplied taxonomy.

**Evidence supporting generalization:** The *shape* of the pipeline
(text → detected category → ranked candidate causes with confidence and
caveats) is domain-agnostic; it's the same shape whether the categories
are automotive symptom families or industrial-equipment fault codes.

**Counter-evidence / automotive dependency:** Every single value in
`SymptomFamily` (braking, steering, tyre_or_wheel, charging_system_ev...)
and every entry in `_HYPOTHESIS_MAP` is car-specific content, not
structure. This is the clearest **AUTOMOTIVE** (not MIXED) case in the
audit — the taxonomy itself is domain content that belongs in an
Automotive Domain Pack, while the *pipeline mechanism* around it is a
separate, genuinely generic candidate.

**Classification:** SPLIT — taxonomy content = AUTOMOTIVE (Domain Pack);
surrounding pipeline mechanism = GENERIC (candidate for the core engine).
Do not treat this as one MIXED rule; it's two rules of different scope
that currently live in the same function.

---

## Candidate 5

**Current automotive concept:** The `contradiction_detected` generic
question trigger + `DiagnosticContradiction` (severity, impact,
resolution_action).

**Underlying generic concept candidate:** A generic contradiction-handling
protocol: detect conflicting claims about the same case, classify
severity/impact, and select a resolution action (retain both / ask
clarification / reduce confidence / block conclusion).

**Evidence supporting generalization:** Nothing about "the user said X
happened, then said Y which conflicts with X" is automotive-specific. The
two contradiction rules currently implemented (starting-vs-driven,
constant-vs-rare frequency) are automotive *content*, but the
*schema* (`ContradictionSeverity`, `ContradictionImpact`,
`ResolutionAction`) is domain-neutral.

**Counter-evidence / automotive dependency:** Per Finding #14 in the
master table (`PGDR-HYP-002`), `resolution_action` is currently declared
but never actually consulted by anything — `REDUCE_CONFIDENCE` doesn't
reduce any confidence value today, for *any* domain. Generalizing a
mechanism that doesn't yet function even for cars would just generalize
the gap.

**Classification:** MIXED, but flagged as **not ready** — the schema
generalizes cleanly; the enforcement doesn't exist yet to generalize.

---

## Candidate 6

**Current automotive concept:** The Runner Execution Contract itself
(`runner_execution_contract.yaml` — readiness, liveness, failure
semantics, packaged-resource validation).

**Underlying generic concept candidate:** A domain-agnostic Runner
Execution Contract schema that any governed runner (PGDR or a future
Machine Diagnostic Runner) would implement identically.

**Evidence supporting generalization:** Every section of the P1 contract
(identity, runtime, packaged_resources, configuration, safety,
capabilities, network, persistence, interfaces, liveness, readiness,
failure_semantics) is already domain-neutral by construction — P1 was
built with zero automotive-specific fields in the contract *schema*
itself (only the `identity.description` value is automotive-flavored
prose).

**Counter-evidence / automotive dependency:** None found. This is the
only candidate in this document where the schema already has zero
automotive coupling.

**Classification:** GENERIC (not MIXED) — this one is arguably already
done. A future generic runner would reuse this schema unchanged, only
filling in different `identity`/`packaged_resources`/`capabilities`
values.

---

## Summary table

| # | Current concept | Generic candidate | Classification | Ready to extract? |
|---|---|---|---|---|
| 1 | Vehicle identity confidence gating | Machine identity confidence gating | MIXED | No — mechanism itself needs building first |
| 2 | `DrivingAssessment` (no `safe_to_drive`) | `OperatingPermission`/`OperatingSafetyState` | MIXED | Yes — enforcement mechanism already sound |
| 3 | `GaragePreparationReport` | `InterventionReport` | MIXED | No — content-quality gaps would carry over |
| 4 | `SymptomFamily` + `_HYPOTHESIS_MAP` | (taxonomy=AUTOMOTIVE, pipeline=GENERIC) | SPLIT | Pipeline: yes. Taxonomy: N/A (stays domain content) |
| 5 | Contradiction schema + resolution_action | Generic contradiction-handling protocol | MIXED | No — `resolution_action` unenforced even today |
| 6 | Runner Execution Contract | (same, unchanged) | GENERIC | Already generic |

Six candidates, none acted on. P3's job, not P2's.
