# P6 Evidence Mapping Registry

Two mapped questions exist as of P6. Each entry below is complete enough
to understand and audit without reading `evidence_mapper.py`.

---

## Q-COND-001 — "Dans quelles conditions le symptôme apparaît-il ?"

**Status:** MAPPED (fully authored/validated, not provisional)

**Answer type:** multiple_choice

**Target hypotheses:** `engine_running`, `tyre_or_wheel`

**Source / rationale:** Direct domain authoring for P4 — the two
candidate hypotheses for the `vibration` symptom family are
`engine_running` (idle/mount-related) and `tyre_or_wheel` (speed-related
wheel imbalance). A vibration reported specifically at idle/startup is
diagnostically consistent with an idle/mount issue and inconsistent with
a wheel-imbalance issue (which requires the wheel to be turning at
meaningful speed); the reverse holds for steady highway speed.

**Effects:**

| Answer | Supports | Contradicts |
|---|---|---|
| "au ralenti / démarrage" | `engine_running` (weight 0.35) | `tyre_or_wheel` (weight 0.35) |
| "vitesse stabilisée" | `tyre_or_wheel` (weight 0.35) | `engine_running` (weight 0.35) |
| "en accélération" | — | — |
| "au freinage" | — | — |
| "en virage" | — | — |
| "je ne sais pas" | — | — |

Three of the five possible answer choices produce no mapped effect —
this is not an oversight; no validated source exists tying
"en accélération"/"au freinage"/"en virage" to `engine_running` or
`tyre_or_wheel` specifically. They fall through to the NEUTRAL fallback,
same as any other unmapped answer.

---

## Q-EVT-002 — "Précisez cet événement récent et sa date approximative"

**Status:** MAPPED — but explicitly **PROVISIONAL**, not equivalent-confidence to Q-COND-001

**Answer type:** free text

**Target hypothesis:** `tyre_or_wheel`

**Source / rationale (read carefully — this is a partial, extended source, marked accordingly):**
`symptom_taxonomy.yaml`'s own `keyword_map` already associates the words
`pneu`, `roue`, `crevaison`, `degonfle` with the `tyre_or_wheel` symptom
family — that association is genuine, existing PGDR content. What is
**not** independently validated is applying that same word list to a
*different* observation channel: the free-text detail of a recently-
completed maintenance event, rather than the initial complaint text where
the taxonomy is normally applied. The underlying idea — "the user just
mentioned recent tyre/wheel work, which is plausibly relevant to a
tyre/wheel-related hypothesis" — is a reasonable extension but is not
itself sourced from anything in the repository. Per the mandate's own
escape valve (§5, P6-T17): "All mappings have source/rationale metadata
**or** explicit PROVISIONAL status." This one has partial source
material *and* is marked PROVISIONAL, at half the weight of Q-COND-001's
fully-authored rule (0.15 vs 0.35) and support-only (no contradicting
pair).

**Effects:**

| Answer contains (any of) | Supports | Contradicts |
|---|---|---|
| "pneu", "roue", "crevaison", "degonfle" | `tyre_or_wheel` (weight 0.15) | — |
| anything else | — | — |

**What was deliberately NOT added:** a symmetric CONTRADICTS pairing
(e.g. "if the detail mentions an oil change, contradict `tyre_or_wheel`")
would require an equally-sourced justification that doesn't currently
exist — adding one to make the rule "feel complete" would itself be the
kind of invented-knowledge the mandate explicitly warns against. Support-
only, provisional, and clearly labeled as such is the honest shape of what
the data actually supports.

---

## Validation coverage

Both rules are checked by `validate_automotive_domain()` at
`SessionController.__init__()`:

- Question ID exists in `questions.yaml`
- Target `hypothesis_type` exists in `_HYPOTHESIS_MAP`
- Weight is within `[0, 1]`
- PROVISIONAL rules must carry a rationale string containing the literal
  word "PROVISIONAL" — enforced structurally, not just by convention
  (see `test_p6_t08_t17_mapping_without_provisional_marker_fails_validation`)

## What P6 deliberately did not attempt

Systematic mapping of the remaining 8 questions (`Q-STATE-001`,
`Q-STATE-002`, `Q-SYM-001`, `Q-SYM-002`, `Q-EVT-001`, `Q-EVI-001`,
`Q-EVI-002`, `Q-CLAR-001`). For each, a careful search was made for
existing PGDR source material (hypothesis descriptions, taxonomy,
business rules, prior test expectations) before concluding none exists —
see `p6_findings.md` for the specific audit trail on `Q-STATE-002`, the
closest near-miss.
