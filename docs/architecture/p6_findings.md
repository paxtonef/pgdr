# P6 Findings

## The central tension P6 actually hit: finding a second sourced mapping was hard

The mandate's DoD requires "multiple validated automotive mappings...
beyond the P4 demonstration slice" and a two-step adaptive scenario. This
required finding a **second genuinely sourced discriminating relation** —
not just adding more answer-values to the existing `Q-COND-001` rule
(the mandate's own §24 is explicit: "au moins deux questions
analytiquement mappées, pas seulement Q-COND-001").

A systematic audit of every hypothesis description, `symptom_taxonomy.yaml`,
`business_rules.yaml`, and existing test expectations found **no second
relation with the same quality of source as Q-COND-001**. The closest
candidate — `Q-STATE-002` (cold/hot engine state) — was rejected rather
than forced: `engine_running`'s own description text mentions
"comportement à chaud/froid," but describes BOTH states as consistent
with the hypothesis, giving no directional (SUPPORTS vs. CONTRADICTS)
signal to build a rule from. Using it anyway would have meant inventing
the direction, which the mandate prohibits more strongly than it requires
hitting the "2+ mappings" target.

**Resolution:** the mandate itself anticipates exactly this situation —
P6-T17 explicitly allows "source/rationale metadata **or** explicit
PROVISIONAL status." A partial, honestly-labeled source was found:
`symptom_taxonomy.yaml`'s `pneu`/`roue`/`crevaison`/`degonfle` →
`tyre_or_wheel` keyword association, applied to a new observation channel
(`Q-EVT-002`'s free-text detail) rather than invented from nothing. This
became the second mapping, explicitly marked PROVISIONAL, at roughly half
the weight of `Q-COND-001`'s rule, support-only (no fabricated
contradicting pair). See `p6_evidence_mapping_registry.md` for the full
writeup — this finding is documented there in detail, not just here,
because it's exactly the kind of reasoning a future domain author needs
to see before adding the next mapping.

**Why this is a genuine finding, not a workaround:** it demonstrates the
mandate's own anti-invention discipline actually constraining real
implementation choices, not just being stated as a principle and then
quietly bypassed under DoD pressure. The alternative — inventing a
clean-looking `Q-STATE-002` rule to hit "2 mappings" more comfortably —
was available and was not taken.

## Validator extended, not rebuilt

`validate_automotive_domain()` (built in P5 as groundwork) already
checked discriminating-rule references. P6 extended it to also validate
the new PROVISIONAL rule set — same dangling-reference checks, plus a
new structural check: any rule not backed by a clean source must contain
the literal word "PROVISIONAL" in its rationale, enforced at validation
time (not just as a code-review convention). This closes a real gap: a
future PROVISIONAL rule that forgets to say so would previously have
looked identical to a fully-validated one in any downstream display.

## Coverage numbers, read plainly

```
Questions:   2 MAPPED / 6 NEUTRAL / 2 UNMAPPED / 0 INVALID  (of 10)
Hypotheses:  2 EVIDENCE_LINKED / 0 PARTIALLY_LINKED / 10 TRIGGER_ONLY / 0 UNMAPPED  (of 12)
```

20% question coverage and 17% hypothesis coverage are not close to "done"
— but per the mandate's own framing, "done" for P6 was never 100% MAPPED.
It was 100% KNOWN STATUS (achieved — verified by `test_p6_t01`/`t02`) plus
proof that the mechanism scales past one question (achieved — the
two-step signature test). Future domain-enrichment passes have a clear,
computed starting point rather than an unknown one.

## P6-DOD verification

```
1. Every existing automotive question has explicit classification.        PASS — test_p6_t01
2. Every current hypothesis has explicit evidence-coverage status.        PASS — test_p6_t02
3. Multiple validated automotive mappings exist beyond the P4 slice.      PASS — Q-COND-001 (full) + Q-EVT-002 (provisional)
4. At least one two-step adaptive scenario demonstrated end-to-end.       PASS — test_p6_signature_two_step_adaptive_discrimination
5. Neutral/unmapped information never fabricates analytical effect.       PASS — test_p6_t05 (pre-existing from P5, re-verified)
6. Domain configuration validated fail-closed.                            PASS — test_p6_t06/t07/t08/t09
7. Safety and diagnostic causality remain separated.                      PASS — test_p6_t13
8. Coverage metrics produced.                                             PASS — p6_automotive_domain_coverage.md, computed
9. Analytical effects traceable question → answer → observation →         PASS — same DiagnosticCaseState mechanism as P4/P5;
   evidence → hypothesis.                                                        no new traceability code needed, already held
10. P0-P5 tests remain green + P6 tests green.                            PASS — 128/128
```

## Verification

```
114 pre-P6 tests (P0-P5)   PASS (unchanged)
14 P6 tests                 PASS (new)
                           -----
128 total                   PASS
```

Wheel rebuilt; all 11 P0 packaging tests re-pass against it.
`install.sh` re-validated end-to-end.

## What P6 did not build (per its own explicit non-goals)

GGM/CGM, LLM integration, Case Repository, historical-case reasoning,
cross-brand learning, Vehicle Health Record, post-garage outcome loop,
PostgreSQL, legacy code deletion, new generic-engine architecture. The
`required_capabilities` (combustion_engine/turbocharging/etc.) concept
from mandate §8 was also not built — no current hypothesis has a
sufficiently clear functional-capability requirement to justify it over
the existing `configuration_requirements` mechanism (already proven by
P4/P6's config-dependent-hypothesis tests); deferred to whenever the
Capability Model itself is built, per the mandate's own "DEFER TO
CAPABILITY MODEL" instruction.
