# P2 Rule Boundary Decisions (P3 — Pass 1)

**No behavior change. No refactoring. No package split.** This is a
classification exercise over the 39 rules from
`pgdr_rule_invariant_extraction.md`. Every rule gets exactly one target
owner decision from: `KEEP_AUTOMOTIVE`, `MOVE_GENERIC`, `SPLIT`,
`CGM_CANDIDATE`, `RGG_CANDIDATE`, `KEEP_PRODUCT`, `DEFER`.

`SPLIT` is used precisely for the 9 rules P2 already scoped `MIXED` — Pass
2 (`generic_automotive_boundary.md`) decomposes each of those individually.
No rule disappears; all 39 are accounted for below.

| # | Rule ID | Rule (short) | P2 status | P2 scope | Target owner decision | Rationale |
|---|---|---|---|---|---|---|
| 1 | PGDR-BR-002/INV-005 | Safety triage before hypothesis generation | ENFORCED | MIXED | **SPLIT** | Sequencing gate is generic; which observations drive vehicle safety state is automotive. See Pass 2. |
| 2 | (implicit) | Escalation halts further questions | ENFORCED | GENERIC | **MOVE_GENERIC** | "Halt evidence-gathering once critical state reached" has zero automotive coupling in its mechanism (an early-return in a state machine). |
| 3 | PGDR-INV-006 | Must not encourage driving to reproduce a dangerous symptom | ENFORCED (indirect) | MIXED | **SPLIT** | Generic: don't solicit interaction with an unsafe system. Automotive: "driving" as the unsafe-operation vocabulary. |
| 4 | PGDR-BR-008/INV-004 | Highest-severity matching rule wins | ENFORCED | MIXED | **SPLIT** | Generic: severity-ordered precedence algorithm. Automotive: the 6-level `TriageLevel` scale and the rule conditions that populate it. |
| 5 | PGDR-INV-003 | `driving_assessment` never asserts unconditional safety | ENFORCED | MIXED | **SPLIT** | Generic: an operating-permission type must structurally exclude a "confirmed safe" value. Automotive: `DrivingAssessment`'s concrete vocabulary. |
| 6 | PGDR-BR-014/INV-003 | Absence of hazard ≠ proof of safety | ENFORCED | MIXED | **SPLIT** | Generic: every no-match fallback must carry a non-affirmative disclaimer. Automotive: the actual French disclaimer text. |
| 7 | PGDR-BR-001/ID-003 | Identity uncertainty limits vehicle-specific reasoning | PARTIAL | MIXED | **SPLIT** | Generic: identity confidence gates configuration-specific inference. Automotive: VIR's `resolution_status` → confidence mapping. |
| 8 | `identity_confidence_min_for_specific_reasoning` | Numeric identity-confidence threshold | UNENFORCED | MIXED | **SPLIT** | Generic: threshold-comparison mechanism. Automotive: the specific value `0.6`. Tied to #7 — same underlying gate, not yet built either way. |
| 9 | PGDR-ID-004 | Identity contradictions must reach the final report | MISSING | MIXED | **SPLIT** | Generic: uncertainty detail must survive to the downstream consumer, not collapse to a status label. Automotive: VIR's specific field shape. |
| 10 | PGDR-ID-001/002 | VIR resolution consumed verbatim, never recomputed | ENFORCED | GENERIC | **MOVE_GENERIC** | "Trust, don't re-derive, an upstream identity resolution" is the exact shape of `IdentityContextPort`. |
| 11 | PGDR-BR-003 | User complaint preserved verbatim | ENFORCED | GENERIC | **MOVE_GENERIC** | "Preserve the raw source statement unmodified" — Case Repository concern, zero domain content. |
| 12 | PGDR-BR-004 | Structured interpretation separated from user statement | PARTIAL | GENERIC | **MOVE_GENERIC** | Schema-separation principle is generic. (The *content* that fills the interpretation is `DomainObservationInterpreter`'s job — see Pass 3.) |
| 13 | PGDR-HYP-001/BR-005 | Every hypothesis cites supporting observations | PARTIAL | GENERIC | **CGM_CANDIDATE** | Evidentiary-traceability requirement on any hypothesis, from any domain provider — core CGM enforcement duty. |
| 14 | PGDR-HYP-002 | Contradicting observations remain visible | UNENFORCED | GENERIC | **CGM_CANDIDATE** | Same reasoning as #13 — CGM must cross-reference `DomainHypothesisProvider` output against detected contradictions. |
| 15 | PGDR-HYP-003/BR-006 | No exact-failure claims — "compatible with" only | PARTIAL | GENERIC | **CGM_CANDIDATE** | Confidence-language governance over hypothesis text is precisely CGM's job — currently only "author discipline" in a Domain Pack table. |
| 16 | PGDR-BR-007 | Dangerous observation requests prohibited | ACCIDENTALLY SATISFIED | GENERIC | **RGG_CANDIDATE** | "May this question be asked given its risk level" is a runtime permission gate — RGG's exact pattern (§8 of the mandate). |
| 17 | PGDR-IN-002 | Dangerous evidence instructions not generated | ACCIDENTALLY SATISFIED | GENERIC | **RGG_CANDIDATE** | Same underlying gap as #16, listed separately per P2. |
| 18 | PGDR-BR-009 | Incomplete report OK if disclosed | ENFORCED | GENERIC | **KEEP_PRODUCT** | Report-completeness-disclosure policy is a product/UX concern, not a reasoning or runtime-permission concern. |
| 19 | PGDR-BR-010 | User evidence vs. automated interpretation distinguishable | ACCIDENTALLY SATISFIED | GENERIC | **MOVE_GENERIC** | Belongs to a future `CaseRepositoryPort`/Evidence subsystem — the distinction itself has no automotive content. |
| 20 | PGDR-BR-011 | Reproducibility prioritized for intermittent symptoms | UNENFORCED | AUTOMOTIVE (P2) | **DEFER** | P2 scoped this AUTOMOTIVE, but P2's own "generic invariant candidate" phrasing for this row ("prioritize discriminating information for non-constant phenomena") reads as domain-agnostic. Flagging for reclassification rather than silently overriding P2 — see `p3_findings.md`. |
| 21 | PGDR-BR-012 | No repair cost ever estimated | ACCIDENTALLY SATISFIED | GENERIC | **RGG_CANDIDATE** | "A report artifact must not contain an unconfirmed cost claim" is an output-governance permission rule, RGG's pattern. |
| 22 | PGDR-BR-013 | Unresolved questions included in report | PARTIAL | GENERIC | **MOVE_GENERIC** | Deriving unresolved questions FROM actual case state (vs. today's static strings) is a `CaseRepositoryPort` concern with no domain content. |
| 23 | PGDR-BR-015 | User summary less technical than garage report | UNENFORCED | GENERIC | **KEEP_PRODUCT** | Readability/audience-tailoring policy — product concern. |
| 24 | PGDR-INV-001 | A question must materially affect the outcome | UNENFORCED | GENERIC | **CGM_CANDIDATE** | This IS the mandate's own worked example: "select the next question that reduces uncertainty." |
| 25 | PGDR-INV-002 | No evidence request may expose the user to hazards | ACCIDENTALLY SATISFIED | GENERIC | **RGG_CANDIDATE** | Same gap as #16/#17. |
| 26 | PGDR-INV-007 | Uncertainty explicit, never silently confident | MISSING | GENERIC | **CGM_CANDIDATE** | The defining concern of CGM — an explicit uncertainty-representation channel, not yet built anywhere. |
| 27 | PGDR-AC-011 | Vehicle identity uncertainty remains visible | PARTIAL | MIXED | **SPLIT** | Same underlying gap as #9 (duplicate finding via a different citation) — see Pass 2. |
| 28 | PGDR-IN-003 | Must not interrogate a currently-driving operator | MISSING | GENERIC | **RGG_CANDIDATE** | "May the system solicit interactive input given the operator's current context" — a runtime permission gate. |
| 29 | PGDR-IN-004 | Media analysis requires explicit consent | ENFORCED | GENERIC | **RGG_CANDIDATE** | Already P2-tagged RUNTIME; a clean, already-working consent gate — the strongest existing RGG-shaped mechanism in the codebase. |
| 30 | PGDR-IN-006 | Absent media must not block text-only operation | ACCIDENTALLY SATISFIED | GENERIC | **KEEP_PRODUCT** | Graceful-degradation-of-optional-input is a product behavior, not a reasoning or permission concern. |
| 31 | (implicit) | A question already answered is never re-asked | ENFORCED | GENERIC | **MOVE_GENERIC** | Pure dialogue-state bookkeeping, zero domain content. |
| 32 | (implicit) | Safety-category questions asked first | ENFORCED | GENERIC | **CGM_CANDIDATE** | The priority-ordering *mechanism* is generic; the category taxonomy itself (`safety`, `operating_condition`, ...) is Domain-Pack-supplied via `DomainQuestionProvider`. |
| 33 | (implicit) | Insufficient evidence degrades to explicit "unknown," never a fabricated specific conclusion | ENFORCED | GENERIC | **CGM_CANDIDATE** | Directly the mandate's own worked pattern for evidence-insufficiency governance. |
| 34 | (implicit) | Hypothesis confidence fixed regardless of subsequent Q&A | N/A (discovered gap) | GENERIC | **CGM_CANDIDATE** | Not a rule to relocate — a gap CGM must close. Flagged as the construction target, not a migration. |
| 35 | (implicit) | Warning-indicator data reaches safety but not diagnosis | N/A (discovered gap) | GENERIC | **CGM_CANDIDATE** | Same treatment as #34 — a cross-provider data-flow gap CGM should own once built. |
| 36 | REC `fail_closed_requirement` | Config failure blocks execution, never fabricates a verdict | ENFORCED | GENERIC | **MOVE_GENERIC** | Already fully generic, already living in domain-agnostic infrastructure (`errors.py`, `cli.py`'s boundary catch). Nothing to change. |
| 37 | REC `readiness` | READY requires config + safety engine + capabilities operational | ENFORCED | GENERIC | **MOVE_GENERIC** | `readiness.py` has zero automotive imports today — already compliant with the Pass 4 dependency rule. |
| 38 | (implicit) | `ComplaintExtraction` computed, never consumed | DORMANT | GENERIC | **CGM_CANDIDATE** | The exact shape of interpretive signal (uncertainty terms, safety phrases) a `DomainObservationInterpreter` → CGM handoff should carry. Currently produced and discarded. |
| 39 | (implicit) | Media-upload answer captured, never becomes evidence | DORMANT | GENERIC | **DEFER** | No partial mechanism exists to relocate — belongs to a `CaseRepositoryPort`/Evidence subsystem that doesn't exist yet in any form. Construction, not migration. |

## Tally

```
SPLIT             9   (rows 1,3,4,5,6,7,8,9,27 — exactly P2's 9 MIXED rules)
MOVE_GENERIC      9   (rows 2,10,11,12,19,22,31,36,37)
CGM_CANDIDATE    10   (rows 13,14,15,24,26,32,33,34,35,38)
RGG_CANDIDATE     6   (rows 16,17,21,25,28,29)
KEEP_PRODUCT      3   (rows 18,23,30)
DEFER             2   (rows 20,39)
KEEP_AUTOMOTIVE   0
                 --
                 39
```

**`KEEP_AUTOMOTIVE` was assigned zero times.** This is itself a finding,
not an oversight — see `p3_findings.md` Finding #1. Every rule P2 found
either has an extractable generic core, or is a gap/absence with no content
to keep at all. The automotive-specific material in this codebase lives as
**data** (`_HYPOTHESIS_MAP`, `symptom_taxonomy.yaml`, `safety_rules.yaml`
conditions, French UI strings) that Domain Pack implementations of the
Pass 3 contracts would supply — not as standalone governance *rules* that
themselves belong exclusively to automotive.
