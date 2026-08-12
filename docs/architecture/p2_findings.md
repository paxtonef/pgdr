# P2 Findings

Source: `pgdr_rule_invariant_extraction.md` (39 rules). No behavior was
changed to produce this document — see "P2 input/output" at the bottom.

## Counts

**Total rules identified: 39**

By enforcement status:
```
ENFORCED                   15
PARTIAL                     6
DORMANT                     2
UNENFORCED                  5
MISSING                     3
ACCIDENTALLY SATISFIED      6
N/A (discovered property)   2
                          ----
                            39
```

By governance nature:
```
SAFETY       9
COGNITIVE   12
PRODUCT     13
RUNTIME      4
CORE         1
           ---
            39
```

By scope:
```
GENERIC     29
MIXED        9
AUTOMOTIVE   1
           ---
            39
```

Narrative authority risk:
```
HIGH     5
MEDIUM  10  (approx. — one row is annotated LOW-MEDIUM as a borderline case)
LOW/NONE 24
```

## Ten most important findings

Ordered by consequence, not by table position. **No fixes below — P2 does
not modify behavior.**

### Finding #1 — `PGDR-BR-001` is only PARTIAL: identity uncertainty limits *disclosure*, not *reasoning*

**Rule:** "Ambiguous vehicle identity limits vehicle-specific diagnostic
reasoning."

**What's actually implemented:** `SessionController._finalize()` appends a
limitation string to the report and downgrades `status` to
`completed_with_limitations` when `resolution_status` is `ambiguous`,
`insufficient_data`, or `contradictory`. That's it.

**What's declared but not implemented:** `DiagnosticEngine.generate_hypotheses()`
never reads `resolution_status` at all. The hypotheses produced for a
`resolved` identity and a `contradictory` identity are byte-identical
for the same complaint text. The declared 0.6 confidence threshold
(`identity_confidence_min_for_specific_reasoning` in `business_rules.yaml`)
is never read anywhere in the codebase.

**Why it matters:** the rule as worded promises that reasoning *changes*
under identity uncertainty. What actually changes is a disclaimer. This is
exactly the kind of gap P2 exists to surface before P3/P4 build a CGM on
top of an assumption that turns out to be a label, not a mechanism.

---

### Finding #2 — Safety-vs-diagnostic precedence is a structural short-circuit, not a scored comparison

**Question asked by the mandate (§10):** "SafetyEngine says X, DiagnosticEngine
says Y — which wins?"

**Answer:** for the two highest severities (`emergency_stop`,
`do_not_drive`), `SessionController.start()` returns immediately after
safety triage — `DiagnosticEngine` **never runs at all**. There is no
conflict to resolve because one side of it never executes.

For every other severity (`prompt_inspection` down to
`monitor_and_document`), both engines run independently and their outputs
are simply printed together with no reconciliation logic — safety urgency
and diagnostic confidence can point in different directions with nothing
noticing or flagging it (e.g. `prompt_inspection` alongside a
`speculative`-confidence hypothesis).

**Why it matters:** this is a genuinely clean, ENFORCED invariant for the
two most severe levels (worth preserving explicitly as CGM/RGM design
input), and a genuine gap for the four less severe ones (worth flagging,
not fixing, for P3+).

---

### Finding #3 — "Structured interpretation" is mostly the same text wearing a label

**Rule (PGDR-BR-004):** interpretation must remain separable from the raw
user statement.

**What's actually true:** `Symptom.user_description` is set to the
*entire, unmodified* complaint text for every detected symptom family. A
complaint matching three keyword families produces three `Symptom` objects
whose `user_description` are all the same full string. The "structured
interpretation" is real at the schema level (separate fields exist) but
thin at the content level (the interpretation doesn't independently derive
what part of the text supports which classification).

---

### Finding #4 — Hypothesis confidence is fixed at parse time; nothing from the Q&A ever changes it

This is the most consequential single finding in the audit.

`DiagnosticEngine.generate_hypotheses()` reads exactly one thing from the
session: `primary.family` (the symptom family detected by keyword matching,
before any question is asked). It does not read `session.answers`,
`session.operating_conditions`, `session.reproduction_profile`,
`session.warning_indicators`, or `session.contradictions`.

Practically: whether the user answers "toujours" or "je ne sais pas" to
every adaptive question, the hypotheses and their confidence levels are
identical. The entire adaptive questioning UX — 6+ questions about
frequency, severity, operating conditions, recent events — narratively
implies it's refining the diagnosis. Mechanically, it refines only the
**report text** (reproduction conditions, recent events sections) and the
**safety triage** (via `_all_text()`, which does include answer text) —
never the hypothesis list itself.

**Narrative authority risk: HIGH.** This is precisely the pattern §11 of
the mandate asks P2 to hunt for: a place where the system's presented
behavior (adaptive, evidence-responsive) is stronger than its actual
authority (fixed lookup table keyed on one field). Nothing currently
*claims* more certainty than it has — the language stays "compatible
with" — but the interaction design creates an impression of
evidence-responsiveness that the computation doesn't back up.

---

### Finding #5 — `RiskLevel.PROHIBITED` is the exact VIR-precedent pattern: accidentally satisfied

**Rule (PGDR-BR-007 / PGDR-INV-002):** dangerous observation/evidence
requests must be prohibited.

**What exists:** a `RiskLevel` enum with a `PROHIBITED` member, a
`DiagnosticQuestion.risk_level` field, and code that copies the YAML's
`risk_level` value onto each constructed question.

**What doesn't exist:** any check, anywhere, that reads `risk_level` to
actually filter or reject a question. `_select_questions()` filters on
`answer_type == media_upload` + consent, and on `ask_if` conditions — never
on `risk_level`.

**Why it's `ACCIDENTALLY SATISFIED`, not `ENFORCED`:** today's
`questions.yaml` happens to contain zero `risk_level: prohibited` entries
(9 are `none`, 1 is `low`). If a future question author — human or,
eventually, an LLM-assisted question generator — added one, it would be
asked without any resistance. This is structurally identical to the VIR
finding that motivated adding this status category in the first place.

---

### Finding #6 — "Compatible with" phrasing is enforced by author discipline, not by any checkable mechanism

**Rule (PGDR-HYP-003 / PGDR-BR-006):** no exact component-failure claim
without professional evidence.

Every string in `_HYPOTHESIS_MAP` (12 entries) is hand-written with
careful "compatible with" / "peut être compatible avec" phrasing. It holds
today. But it holds because whoever wrote the table was careful, not
because any code would reject a definitive-sounding string. There is no
test that scans hypothesis descriptions for prohibited phrasing (e.g. "est
en panne", "confirmé").

**Narrative authority risk: HIGH.** This is the single most important gap
to close *before* P5 (Analytical Engine v2) introduces an LLM into this
path — an LLM-generated hypothesis description has no equivalent "careful
human author" safeguard, and nothing downstream would catch language
drift toward false certainty.

---

### Finding #7 — The entire Evidence pipeline is dormant end-to-end

Three independent findings compound into one system-level fact: **no
`Evidence` object is ever constructed anywhere in the runtime code.**

- `PGDR-BR-010` (user evidence vs. automated interpretation
  distinguishable) is `ACCIDENTALLY SATISFIED` — the two fields that would
  need distinguishing are never populated.
- The `Q-EVI-002` media-upload answer is captured from the user but never
  converted into an `Evidence` object (`DORMANT`).
- `evidence_ids` on both `Symptom` and `VehicleEvent` are declared,
  default to empty, and are never populated by anything.

A user who dutifully provides a photo path gets nothing for it in the
report — `evidence_index` stays empty regardless.

---

### Finding #8 — `unresolved_questions` is two hardcoded strings, identical for every session ever run

```python
unresolved_questions=[
    "L'origine exacte du symptôme nécessite une inspection physique.",
    "La reproduction du symptôme en atelier reste à confirmer.",
],
```

`PGDR-BR-013` ("the garage report must include unresolved questions") is
satisfied in the sense that the field is never empty — but its content has
zero relationship to the actual session: same two sentences whether there
were 0 or 2 detected contradictions, whether the identity was resolved or
contradictory, regardless of which questions were actually left
unanswered (`ask_if` conditions that never triggered, optional questions
skipped, etc.).

---

### Finding #9 — Three captured user inputs are read once and then never again: `perceived_urgency`, `driving_status`, `technical_level`

All three are CLI flags / model fields, all three are stored on
`InitialComplaint` / `UserContext`, and **none of the three is read by any
component after being stored.**

- `perceived_urgency` — the user's own self-reported urgency has zero
  effect on triage or hypothesis generation.
- `technical_level` — declared to support "less technical" tailoring
  (`PGDR-BR-015`); never consulted.
- `driving_status` — see Finding #10, this one has a real safety-adjacent
  consequence.

`locale` (defaults `"fr-FR"`) is a fourth case: passing `--locale en-US`
has literally no effect — every string PGDR ever produces is French,
regardless of the declared locale.

---

### Finding #10 — `PGDR-IN-003` ("must not interrogate a driver who is currently driving") is `MISSING`, not merely unenforced

The AMD input-contract validation rule explicitly states the system must
not request interactive input from someone currently driving. `UserContext.driving_status`
exists precisely to support this check. Nothing reads it. `pgdr run
--driving-status not_driving_at_all_currently_driving_actually` (any
value) still runs the full interactive Q&A loop identically.

This is the one finding in this audit with a plausible real-world safety
angle distinct from the vehicle-mechanical safety rules — a driver being
prompted through 6+ questions while operating a vehicle is itself a hazard
the original spec anticipated and named, and current PGDR does nothing
about it.

---

## What P2 did *not* find

Worth stating explicitly, since absence-of-finding is easy to
under-report:

- **No case of an LLM or generative component overriding a safety
  decision** — because no LLM exists in the codebase yet. This audit
  found the *structural gaps* (Findings #5, #6) that would make such an
  override easy to introduce later without noticing, which is the
  actionable version of this concern at this stage.
- **No case of the `safe_to_drive` boundary being violated or
  circumventable** — `PGDR-INV-003` is the strongest-enforced rule in the
  codebase (type-level, not runtime-checked).
- **No genuinely `DORMANT` implementation of a *safety* rule** — the two
  `DORMANT` findings (#1's extraction pipeline, Q-EVI-002 evidence
  capture) are both `COGNITIVE`/`PRODUCT`, not `SAFETY`. Safety-nature
  gaps in this audit are all `ACCIDENTALLY SATISFIED` or `PARTIAL`, never
  `DORMANT` — meaning where safety enforcement is thin, it's thin because
  a check was never written, not because a written check is silently
  bypassed.

## P2 input / output

```
P2 INPUT
70 tests passing

P2 OUTPUT
70 tests passing (unchanged — verified by re-running the full suite
after writing these documents)
+
39-rule architectural evidence map
+
this findings synthesis
+
generic_extraction_candidates.md
```
