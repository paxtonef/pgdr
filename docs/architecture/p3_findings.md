# P3 Findings

Source: `p2_rule_boundary_decisions.md` (Pass 1, all 39 rules),
`generic_automotive_boundary.md` (Pass 2 decomposition + Pass 4 dependency
audit), `generic_domain_contracts.md` (Pass 3). No behavior changed to
produce these documents — verified below.

## Pass 1 tally (repeated from `p2_rule_boundary_decisions.md`)

```
SPLIT             9
MOVE_GENERIC      9
CGM_CANDIDATE    10
RGG_CANDIDATE     6
KEEP_PRODUCT      3
DEFER             2
KEEP_AUTOMOTIVE   0
                 --
                 39
```

## Five findings

### Finding #1 — Zero rules landed in `KEEP_AUTOMOTIVE`

Every one of the 39 P2 rules either has an extractable generic core
(`SPLIT`/`MOVE_GENERIC`/`CGM_CANDIDATE`/`RGG_CANDIDATE`), is a product-
level UX policy (`KEEP_PRODUCT`), or is a gap needing a reclassification
decision or future construction (`DEFER`). Not one rule was purely,
irreducibly automotive.

This does **not** mean PGDR has no automotive-specific content — it has a
great deal (20 safety rule conditions, 24 symptom families, 12
hypothesis-map entries, 11 question phrasings, all in French). It means
that content lives as **data** consumed by otherwise-generic mechanisms,
not as standalone governance **rules**. The boundary this codebase
actually has is: generic rule ↔ automotive data, not generic rule ↔
automotive rule. This sharpens the mandate's own worked examples (safety
preemption vs. which observations trigger it; generic question-selection
vs. "le voyant moteur clignote-t-il ?") into a structural claim about the
*whole* rule set, not just the three examples given.

### Finding #2 — The Pass 4 dependency-rule audit found real, specific violations — not hypothetical ones

Grepping actual imports (not reasoning abstractly) found that 4 of the 7
modules that would move toward a Generic Diagnostic Engine currently
import automotive-named enums directly into what is otherwise
domain-agnostic mechanism code:

- `safety_engine.py` imports `DrivingAssessment`, `TriageLevel`
- `diagnostic.py` imports `SymptomFamily`
- `session_controller.py` imports `ResolutionStatus`
- `config_loader.py` imports `DrivingAssessment`, `TriageLevel` (for its
  otherwise fully domain-agnostic P0.3 schema-validation algorithm)

Only `readiness.py` and `errors.py` are already dependency-rule-compliant.
This is the single most actionable finding for P4/P5 planning: the
*algorithms* in these four modules are already close to the target
contracts (`DomainSafetyPolicy`, `DomainHypothesisProvider`, question
selection, config validation) — the blocking issue is type coupling, not
logic redesign.

### Finding #3 — `IdentityContextPort` and `DomainSafetyPolicy` are near-complete; `FunctionalCapabilityProvider` and `CaseRepositoryPort` don't exist in any form

Of the 7 Pass 3 contracts, 5 have an identifiable current PGDR analog
(some strong — `VehicleIdentityContext` is nearly `IdentityContextPort`
as-is; some partial — `DiagnosticEngine` implements half of
`DomainHypothesisProvider`'s contract). 2 contracts
(`FunctionalCapabilityProvider`, `CaseRepositoryPort`) have **zero**
current implementation, for automotive or any other domain — these are
new construction for P4/P5, not extraction targets. Conflating "define
the contract" with "it mostly already exists" for these two would
misestimate P4/P5 scope.

### Finding #4 — Three P2 gaps (Findings #4, #5, #38 in P2) become the same CGM construction target once mapped through Pass 1

P2 found these as three separate findings:
- Finding #4: hypothesis confidence is fixed at parse time, never updated
  by subsequent Q&A
- Finding #5: `RiskLevel.PROHIBITED` is accidentally satisfied, no actual
  enforcement exists
- Finding #38 (in the master table): `ComplaintExtraction` is computed
  and never consumed

Pass 1 classifies all three `CGM_CANDIDATE`/`RGG_CANDIDATE`. Read
together through Pass 3's `DomainObservationInterpreter` →
`DomainHypothesisProvider` → CGM chain, they describe **one** missing
capability, not three independent ones: PGDR currently has no mechanism
by which case state accumulated during a session (interpreted signals,
Q&A answers, contradictions) feeds back into hypothesis confidence or
question-risk enforcement. `DomainObservationInterpreter`'s output
existing-but-unconsumed (#38) is the same root gap as hypotheses not
reading `case_context` (#4) is the same root gap as nothing gating
question risk (#5) — they're three symptoms of PGDR's current pipeline
being a **single forward pass** (parse once → decide once) rather than
the **accumulating case state** the mandate's CGM diagram implies. This
is worth stating as one P4 construction priority, not three separate
backlog items.

### Finding #5 — One Pass 1 classification was flagged rather than decided: PGDR-BR-011's P2 scope tag looks wrong on inspection

P2 tagged PGDR-BR-011 ("prioritize reproducibility info for intermittent
symptoms") `AUTOMOTIVE`. But P2's own "generic invariant candidate"
phrasing for that same row — "adaptive questioning should prioritize
discriminating information for non-constant phenomena" — reads as
domain-agnostic; nothing in it requires a vehicle. Rather than silently
overriding P2's classification (which would violate this phase's own
"don't invent, verify what's there" discipline — P2's classification is
itself evidence, not just P3's raw material), Pass 1 marks this `DEFER`
with the discrepancy stated explicitly. This is a two-line disagreement,
not a structural problem, but flagging *how* it was resolved (deferred
with reasoning shown, not silently corrected) is itself the kind of
process transparency this phase exists to model.

## Cross-check: all 39 rules addressed, none dropped

```
P2 rule count:                     39
Pass 1 rows in
  p2_rule_boundary_decisions.md:   39
Pass 2 decompositions
  (= P2's MIXED count):             9  (of 39, all accounted for individually)
```

Verified by direct count (`grep`) against the master table in
`pgdr_rule_invariant_extraction.md`, not by re-deriving from memory.

## P3 input / output

```
P3 INPUT
70 tests passing
39 P2 rules

P3 OUTPUT
70 tests passing (unchanged — verified below)
39 P2 rules, all addressed, none dropped
+
target architecture defined (7 contracts, 4-way rule ownership split)
+
this findings synthesis

Physical extraction: NOT DONE. Deferred to post-P4/P5, per mandate.
```

Confirmed via file-modification diff that this phase created exactly 4
new files under `docs/architecture/` and modified zero `.py` files. Full
suite re-run: **70/70 pass**, unchanged from P2.
