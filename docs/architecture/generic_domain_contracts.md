# Generic Domain Contracts (P3 — Pass 3)

**Conceptual interfaces only.** No code changes; none of these are
implemented as actual Python `Protocol`/ABC classes in this phase. Each
entry states purpose, what it must provide, who consumes it, and — the
part most useful for P4/P5 planning — **what in today's PGDR already
plays this role, however informally, and what's simply missing.**

---

## IdentityContextPort

**Purpose:** normalize an upstream identity resolution (of whatever
machine/asset type) into a domain-agnostic confidence-plus-status
representation the CGM can consult before permitting configuration-
specific inference.

**Must provide:**
- a categorical resolution status (resolved / provisional / ambiguous /
  insufficient / contradictory, or domain-pack-defined equivalent)
- a numeric confidence score
- unresolved fields / contradictions (detail, not just the status label)
- an opaque, domain-specific identity payload the generic engine never
  inspects directly

**Consumed by:** CGM (identity-confidence gate — MIXED-6/7 in
`generic_automotive_boundary.md`), `CaseRepositoryPort`/report building
(surfacing uncertainty detail — MIXED-8/9).

**Today:** `VehicleIdentityContext` (`models.py`) is already shaped almost
exactly like this port — resolution_status, confidence, unresolved_fields,
contradictions, opaque `vehicle_identity` dict — it simply isn't formally
exposed as a port, and (per Pass 2) nothing currently *reads* the
confidence score or the unresolved-fields detail. **This is PGDR's
cleanest port candidate already** — the data model exists; the consuming
gate does not.

---

## DomainSafetyPolicy

**Purpose:** evaluate domain-specific safety signals against the current
case and return a domain-agnostic safety verdict — severity, operating
permission, instruction — *before* any further analytical inference is
allowed to proceed.

**Must provide:**
- `evaluate(case) -> SafetyVerdict` where `SafetyVerdict` carries a
  severity rank (from a domain-supplied ordered scale), an operating
  permission (structurally excluding "confirmed safe" — see MIXED-4), an
  instruction string, and required-escalation flags (emergency
  services / roadside-assistance or domain equivalents)
- a mandatory non-affirmative disclaimer on the no-match fallback path
  (MIXED-5)

**Consumed by:** the generic execution loop, which must halt
`DomainHypothesisProvider` invocation whenever severity crosses a
domain-supplied critical threshold (MIXED-1/2).

**Today:** `SafetyEngine` + `safety_rules.yaml` already implement almost
exactly this shape — rule matching, severity ranking, structural
`safe_to_drive` exclusion, mandatory default disclaimer. The gap is
purely the Pass 4 dependency-rule violation: `SafetyEngine` type-hints
directly against `DrivingAssessment`/`TriageLevel` instead of against a
generic `OperatingPermission`/`SeverityLevel` this port would define.

---

## DomainObservationInterpreter

**Purpose:** turn raw case input (free text, structured answers,
indicator readings) into normalized observation/symptom objects the rest
of the system reasons over, without itself asserting any conclusion.

**Must provide:**
- `interpret(raw_input) -> list[Observation]`, each carrying a
  domain-taxonomy classification, confidence signals, and — closing P2
  Finding #38 — the interpretive metadata (temporal markers, explicit
  safety-relevant phrases, expressions of uncertainty) actually reaching
  a downstream consumer instead of being computed and discarded

**Consumed by:** `DomainSafetyPolicy` and CGM/`DomainHypothesisProvider` —
**both**, from a single shared interpretation, not two independent
re-derivations of the same text.

**Today:** `ComplaintParser` does the interpretation and produces a real
`ComplaintExtraction` object — but per Finding #38, nothing reads it.
`SafetyEngine` and `DiagnosticEngine` each independently re-derive their
own view of the raw text instead of consuming `ComplaintParser`'s output.
Formalizing this port would force that duplication into the open — not
fixed here, but now named.

---

## DomainHypothesisProvider

**Purpose:** given normalized observations and case context, propose
domain-specific candidate hypotheses (system/component families) with
confidence and supporting/contradicting evidence, governed by CGM's
evidentiary rules.

**Must provide:**
- `propose(observations, case_context) -> list[Hypothesis]`, where every
  returned hypothesis satisfies the CGM contracts decomposed from
  PGDR-HYP-001/002/003: cites supporting observations, exposes
  contradicting ones, and never exceeds "compatible with"-strength
  language

**Consumed by:** CGM (enforces the evidentiary contracts on whatever the
provider returns), then `CaseRepositoryPort`/report building.

**Today:** `DiagnosticEngine` + `_HYPOTHESIS_MAP` implement the "propose
candidates for a family" half of this contract, but — per Finding #4, the
single most consequential P2 finding — it does not yet honor the
`case_context` half: hypotheses are selected purely from
`observations` (specifically, the primary symptom family) and never
change based on subsequent Q&A, warning-indicator data, or detected
contradictions. This port formalizes the contract `DiagnosticEngine`
would need to actually fulfill, not merely partially satisfy.

---

## DomainQuestionProvider

**Purpose:** given current case state and what remains uncertain, propose
the next question(s) most likely to reduce that uncertainty — generic
selection principle, domain-specific phrasing.

**Must provide:**
- `next_questions(case_context, uncertainty_state) -> list[Question]`,
  each tagged with a domain-agnostic category (e.g. "safety",
  "operating_condition") the generic engine uses for priority ordering,
  and a risk level the RGG can enforce before the question is ever
  surfaced

**Consumed by:** the generic execution loop (selection/ordering — see
implicit rules #31/#32 in `p2_rule_boundary_decisions.md`), RGG
(risk-level gating — PGDR-BR-007/PGDR-IN-002, Finding #5).

**Today:** `questions.yaml` + `SessionController._select_questions()`
implement selection and ordering, but selection logic and domain content
are entangled in one function/file rather than split across a generic
selector plus a domain-supplied bank. This is also precisely why
PGDR-INV-001 ("a question must materially affect the outcome") is
`UNENFORCED` today — there is no generic selector positioned to audit
that claim, because there's no boundary between "which question" and
"why this question" for anything to audit across.

---

## FunctionalCapabilityProvider

**Purpose:** expose what the specific machine instance is functionally
capable of / configured as — directly the mandate's own example
("Vehicle Functional Profile → maps into FunctionalCapabilityProfile").
Feeds both `DomainHypothesisProvider` (which systems are even present on
this machine) and `DomainSafetyPolicy` (which safety rules are even
applicable to this configuration).

**Must provide:**
- `get_profile(identity_context) -> FunctionalCapabilityProfile`
  containing applicable systems, known variants, and the relevant safety-
  rule subset for this specific instance

**Consumed by:** `DomainHypothesisProvider`, `DomainSafetyPolicy`.

**Today: nothing implements this, for automotive or otherwise.** Every
one of the ~20 safety rules and ~12 hypothesis-map entries applies
unconditionally to every case regardless of the actual vehicle's
configuration — a `charging_system_ev` safety rule (PGDR-SAF-009/009B)
fires identically whether the vehicle identity resolved to an EV or a
diesel car with no high-voltage battery at all, because nothing filters
rules by what's actually present on the machine. This is a genuinely new
port with zero current implementation, not a refactor target — worth
stating plainly rather than implying it's a rename away from existing.

---

## CaseRepositoryPort

**Purpose:** persist and retrieve case state (observations, hypotheses,
outcomes) — the minimal contract PGDR's current in-memory
`DiagnosticSession` object informally satisfies for a single session, and
the eventual foundation for the P5+ Diagnostic Case & Capability
Repository (explicitly NOT built here — P3 names the port, not the
repository).

**Must provide (minimum, session-scoped):**
- `get_case(id)`, `save_case(case)`

**Must provide (future, cross-session — not built anywhere yet):**
- `list_related_cases(identity)`, `record_outcome(case, outcome)` — this
  is exactly the gap behind Finding #7 (the entire Evidence pipeline is
  dormant end-to-end) and Finding #8 (`unresolved_questions` is two
  static strings instead of derived from actual case state)

**Consumed by:** the session/execution controller equivalent, report
building.

**Today: nothing implements this, for automotive or otherwise.**
`DiagnosticSession` is a Pydantic object with zero persistence — confirmed
in `runner_execution_contract.yaml`: `persistence.required: false`. This
port, like `FunctionalCapabilityProvider`, is entirely prospective.

---

## Summary — what exists today vs. what's genuinely new

| Contract | Closest existing PGDR analog | Status |
|---|---|---|
| `IdentityContextPort` | `VehicleIdentityContext` | Data model exists; consuming gate does not |
| `DomainSafetyPolicy` | `SafetyEngine` + `safety_rules.yaml` | Nearly complete; dependency-rule violation only |
| `DomainObservationInterpreter` | `ComplaintParser` | Implemented, but output is dormant (unconsumed) |
| `DomainHypothesisProvider` | `DiagnosticEngine` + `_HYPOTHESIS_MAP` | Implements half the contract (observations, not case_context) |
| `DomainQuestionProvider` | `questions.yaml` + `_select_questions()` | Selection and domain content currently entangled |
| `FunctionalCapabilityProvider` | *(none)* | Does not exist in any form |
| `CaseRepositoryPort` | *(none)* | Does not exist in any form |

Five of seven contracts have a real, identifiable current analog worth
building toward. Two are genuinely new construction for P4/P5, not
extractions from existing code.
