# Generic Diagnostic Engine / Automotive Domain Boundary (P3)

**No behavior change. No refactoring. No package split.** Target
architecture defined; physical extraction deferred until P4 (CGM) and P5
(Analytical Engine v2) exist to build against it.

## The question this document answers

> If tomorrow we replace the automobile with an industrial pump, a solar
> installation, or any other machine, which parts of PGDR stay
> conceptually unchanged, and which parts must be replaced by a new
> Domain Pack?

**Short answer, established below:** the *sequencing, precedence,
evidentiary-governance, and permission-gating mechanisms* stay unchanged.
Every safety rule condition, every hypothesis-mapping entry, every
question's phrasing, and every YAML value in the four config files gets
replaced. Nothing in between is ambiguous once Pass 2's nine decompositions
are read — see the worked table at the end of this document.

---

## Pass 2 — Mixed rule decomposition

The 9 rules P2 scoped `MIXED` are the ones where an automotive
*implementation* currently expresses what P2 already suspected was a
*generic* invariant. Each is decomposed here into: current automotive
expression → underlying generic invariant → automotive-specific
policy/data → target split.

### MIXED-1 — PGDR-BR-002 / INV-005 (safety before hypothesis generation)

- **Current automotive expression:** `SessionController.start()` calls
  `SafetyEngine.evaluate()` (vehicle safety triage) before
  `DiagnosticEngine.generate_hypotheses()` (vehicle system hypotheses) can
  ever run.
- **Underlying generic invariant:** *A governed diagnostic action must
  evaluate domain safety state before further analytical inference
  proceeds.*
- **Automotive-specific policy/data:** which vehicle observations
  (keywords, warning-light color/behavior) trigger which triage level —
  the entire content of `safety_rules.yaml`.
- **Target split:** GENERIC → the execution-ordering gate itself
  (evaluate `DomainSafetyPolicy` before invoking `DomainHypothesisProvider`)
  belongs in the engine loop, governed by CGM/RGG. AUTOMOTIVE → the 20
  rule definitions stay in the Automotive Domain Pack, exposed through a
  `DomainSafetyPolicy` implementation.

### MIXED-2 — PGDR-INV-006 (must not encourage driving to reproduce a dangerous symptom)

- **Current automotive expression:** No dedicated code — satisfied only
  as a side effect of the early-return in `SessionController.start()`
  when triage is `emergency_stop`/`do_not_drive`.
- **Underlying generic invariant:** *Must not solicit further interaction
  with a system already assessed as unsafe to operate.*
- **Automotive-specific policy/data:** "driving" as the specific unsafe-
  operation vocabulary; which vehicle actions constitute "driving."
- **Target split:** GENERIC → the halt-on-critical-severity mechanism
  (already the actual enforcement path — see rule #2 in
  `p2_rule_boundary_decisions.md`) stays in the engine. AUTOMOTIVE → the
  Domain Pack supplies the specific "unsafe operation" vocabulary
  (`driving` here; e.g. `energizing`/`pressurizing` for an industrial
  pump) purely as label text, not as logic.

### MIXED-3 — PGDR-BR-008 / INV-004 (highest severity wins)

- **Current automotive expression:** `TriageLevel` is a fixed 6-level
  scale (`monitor_and_document` → `emergency_stop`); `SafetyEngine`
  compares matched rules' ranks and keeps the highest.
- **Underlying generic invariant:** *When multiple safety signals apply
  simultaneously, the most severe governs the resulting state.*
- **Automotive-specific policy/data:** the specific 6 `TriageLevel`
  values and the vehicle rule conditions in `safety_rules.yaml` that
  populate them.
- **Target split:** GENERIC → `DomainSafetyPolicy`'s contract requires an
  ORDERED severity scale plus a "highest wins" resolution algorithm — the
  algorithm belongs in the engine, parameterized by whatever scale the
  Domain Pack declares. AUTOMOTIVE → the concrete 6-level `TriageLevel`
  scale and its rule conditions are Domain Pack content.

### MIXED-4 — PGDR-INV-003 (`driving_assessment` never asserts unconditional safety)

- **Current automotive expression:** `DrivingAssessment` enum has 4
  members, none of which is `safe_to_drive`.
- **Underlying generic invariant:** *An analytical system must never
  assert unconditional operational safety for the governed machine.*
- **Automotive-specific policy/data:** the vocabulary itself
  (`do_not_drive`, `limited_movement`, `professional_assessment_required`).
- **Target split:** GENERIC → an `OperatingPermission`/`OperatingSafetyState`
  contract in the generic engine that is *structurally* prevented from
  having a "confirmed safe" member — this is the strongest-enforced rule
  in the whole codebase (type-level closure) and the mechanism generalizes
  perfectly. AUTOMOTIVE → `DrivingAssessment` becomes the Domain Pack's
  concrete implementation of that contract, with car-specific member
  names.

### MIXED-5 — PGDR-BR-014 / INV-003 (absence of hazard ≠ proof of safety)

- **Current automotive expression:** `safety_rules.yaml`'s `default`
  block's French disclaimer text, shown whenever no vehicle safety rule
  fires.
- **Underlying generic invariant:** *Silence from a detection system is
  not a certification of the negative.*
- **Automotive-specific policy/data:** the actual disclaimer wording and
  its vehicle framing.
- **Target split:** GENERIC → `DomainSafetyPolicy`'s contract requires
  every "no rule fired" fallback path to carry a mandatory
  non-affirmative disclaimer field (structurally required, not merely
  conventional). AUTOMOTIVE → the disclaimer string itself is Domain Pack
  content.

### MIXED-6 — PGDR-BR-001 / ID-003 (identity uncertainty limits vehicle-specific reasoning)

- **Current automotive expression:** when VIR's `resolution_status` is
  `ambiguous`/`insufficient_data`/`contradictory`, `SessionController`
  appends a French limitation string and downgrades report status — but
  (per P2 Finding #1) `DiagnosticEngine.generate_hypotheses()` never
  actually reads `resolution_status`.
- **Underlying generic invariant:** *Insufficient machine identity
  confidence must limit configuration-specific diagnostic inference.*
- **Automotive-specific policy/data:** VIR's specific `resolution_status`
  enum and the `vehicle_identity` dict shape.
- **Target split:** GENERIC → `IdentityContextPort` normalizes any
  upstream identity resolution into a domain-agnostic
  `MachineIdentityContext` (status + numeric confidence); CGM consults it
  *before* invoking `DomainHypothesisProvider` in configuration-specific
  mode, actually implementing the gate that's currently only a disclaimer.
  AUTOMOTIVE → mapping VIR's `resolution_status`/`confidence.score` into
  that normalized context is the Domain Pack's `IdentityContextPort`
  implementation.

### MIXED-7 — `identity_confidence_min_for_specific_reasoning` (0.6 threshold)

- **Current automotive expression:** declared in `business_rules.yaml`
  `thresholds`, never read anywhere.
- **Underlying generic invariant:** *A numeric confidence floor gates
  whether configuration-specific inference is permitted.*
- **Automotive-specific policy/data:** the specific value `0.6`.
- **Target split:** GENERIC → the threshold-comparison mechanism is part
  of the same CGM gate as MIXED-6 (they are one gap, not two — P2 listed
  them as separate rows because they came from separate YAML/code
  locations, but they're the same unbuilt mechanism). AUTOMOTIVE → `0.6`
  is a Domain-Pack-supplied tunable parameter, not hardcoded in the
  engine.

### MIXED-8 — PGDR-ID-004 (identity contradictions must reach the final report)

- **Current automotive expression:**
  `VehicleIdentityContext.unresolved_fields`/`.contradictions` are
  populated on the model but `ReportBuilder._build_garage_report()` never
  reads them — only the categorical `resolution_status` is echoed.
- **Underlying generic invariant:** *Upstream identity uncertainty detail
  must be surfaced downstream, not collapsed to a single categorical
  status.*
- **Automotive-specific policy/data:** VIR's specific
  `unresolved_fields`/`contradictions` field shape.
- **Target split:** GENERIC → `CaseRepositoryPort`'s report-building
  contract requires surfacing identity-uncertainty *detail* via
  `MachineIdentityContext`, not just its status. AUTOMOTIVE → the
  specific VIR field names stay inside the Domain Pack's
  `IdentityContextPort` implementation, mapped into the generic shape.

### MIXED-9 — PGDR-AC-011 (vehicle identity uncertainty remains visible)

Same underlying gap as MIXED-8 — P2 found it twice via two different
citations (an acceptance criterion vs. a spec-pack rule ID). Decomposition
is identical: GENERIC → visibility of identity confidence at the
`CaseRepositoryPort`/reporting boundary. AUTOMOTIVE → VIR's specific
vocabulary. Listed separately here only to keep the "all 39 addressed"
guarantee explicit — not a second, independent gap to close.

---

## Pass 4 — Dependency rule

> Generic Diagnostic Engine MUST NOT depend on automotive concepts.
> Automotive Domain Pack may implement generic contracts.

This is verified here against **today's actual imports**, not asserted.
Grepped every module whose *mechanism* (as opposed to config data) would
plausibly move toward the Generic Diagnostic Engine per Pass 1:

| Module | Would move toward Generic Engine? | Automotive imports today | Dependency rule violated if extracted as-is? |
|---|---|---|---|
| `safety_engine.py` | Yes (severity-ranking, rule-matching mechanism) | `from pgdr.enums import DrivingAssessment, TriageLevel, WarningBehavior, WarningColor` | **YES** — the matching/ranking mechanism type-hints directly against automotive-named enums |
| `diagnostic.py` | Yes (hypothesis-generation shape, `_generic_entries` fallback) | `from pgdr.enums import ClaimStatus, Confidence, SymptomFamily` | **YES** — `SymptomFamily` is automotive taxonomy, imported directly into the generation loop |
| `session_controller.py` | Yes (state machine, question selection/ordering) | `from pgdr.enums import AnswerType, ResolutionStatus, SessionState` | **YES** — `ResolutionStatus` is VIR/automotive-shaped |
| `config_loader.py` | Yes (P0 schema validation is domain-agnostic in principle) | `from pgdr.enums import DrivingAssessment, TriageLevel` | **YES** — `validate_safety_rules()`'s enum-membership check is hardcoded against automotive enum types, even though the *validation algorithm itself* ("check id uniqueness, non-empty conditions, valid enum membership") has no automotive content |
| `readiness.py` | Yes (readiness mechanism) | none | **NO** — already compliant |
| `errors.py` | Yes (`ConfigurationError`) | none | **NO** — already compliant |
| `textnorm.py` | Yes (accent normalization) | none | **NO** — already compliant, though also arguably French-specific rather than automotive-specific (a separate, orthogonal boundary not in scope for this document) |

**Finding: 4 of 7 candidate-generic modules would violate the dependency
rule if extracted today.** This is expected and not a defect — P2/P3 exist
specifically to make this visible before P4/P5 attempt construction. The
violation pattern is consistent: each module's *algorithm* is generic, but
its *type signatures* are borrowed directly from the Automotive Domain
Pack's enums rather than from a generic contract the Domain Pack would
implement. Closing this is P4/P5 construction work, explicitly out of
scope for P3 (no refactoring).

`readiness.py` and `errors.py` are the two modules in the entire codebase
that are *already* dependency-rule-compliant — worth preserving as the
reference shape for how the other four should eventually look.

---

## Answering the mandate's success question

> Which parts of PGDR stay conceptually unchanged if the automobile is
> replaced by an industrial pump, a solar installation, or another
> machine domain?

**Stays conceptually unchanged (would be re-implemented against the same
contract, not redesigned):**
- Safety-before-inference sequencing and the halt-on-critical-severity gate
  (MIXED-1, MIXED-2)
- Severity-ranking / highest-wins precedence algorithm (MIXED-3)
- The structural prohibition on asserting unconditional operating safety
  (MIXED-4 — this is the single cleanest generic mechanism in the
  codebase)
- The "no-match fallback must disclaim, never affirm" requirement
  (MIXED-5)
- Identity-confidence gating of configuration-specific inference, once
  built (MIXED-6/7/8/9)
- Every `CGM_CANDIDATE` and `RGG_CANDIDATE` from Pass 1 (evidentiary
  traceability, contradiction visibility, confidence-language governance,
  question-materiality, risk-level gating, consent gating, driver/operator-
  attention gating)
- Dialogue mechanics: never re-ask an answered question, ask
  safety-category questions first, verbatim preservation of the raw
  complaint, config fail-closed behavior, the readiness mechanism

**Must be replaced by a new Domain Pack:**
- Every condition in `safety_rules.yaml` (20 rules) — pump/solar-specific
  hazard signals replace vehicle ones entirely
- The entire `SymptomFamily` taxonomy and `_HYPOTHESIS_MAP` — an
  industrial pump has cavitation/seal-wear/bearing-noise families, not
  braking/steering/tyre_or_wheel
- Every question in `questions.yaml` — phrasing, categories' concrete
  labels, and `ask_if` dependencies are all vehicle-shaped
  ("moteur froid ou chaud" has no equivalent for a static pump)
- `DrivingAssessment`'s concrete member names (the *contract* — no
  "confirmed safe" value — stays; the labels don't)
- `TriageLevel`'s concrete 6 values (the *algorithm* over them stays; the
  labels and which conditions map to which level don't)
- The VIR-specific identity mapping (the `IdentityContextPort` contract
  stays; VIR itself is replaced by whatever identity resolver exists for
  pumps/solar installations)
- `GaragePreparationReport`'s vehicle-shaped fields
  (`recent_vehicle_events`, `warning_indicators` as dashboard-light
  concepts) — the two-audience report *structure* (Candidate 3 in
  `generic_extraction_candidates.md`) stays; the field semantics don't

**Does not exist yet, for either domain, and must be built (not moved) in
P4/P5:** `FunctionalCapabilityProvider` (nothing in PGDR today filters
rules/hypotheses by which systems are actually present on a given
machine instance — an EV-charging safety rule fires unconditionally even
for a diesel vehicle) and `CaseRepositoryPort` (no persistence layer
exists at all — see `runner_execution_contract.yaml`
`persistence.required: false`).
