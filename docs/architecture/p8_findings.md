# P8 Findings

## P8A/P8B split - the pinned GGM package has no bounded runtime yet

The developer pack's own README says it plainly: "bounded-runtime
construction and embedded/remote adapters are not yet implemented." P8
therefore integrates against `DefaultGGMConsumer` (GGM's reference
implementation, wired via the exact construction pattern GGM's own tests
use), taken through dependency injection specifically so a future
`BoundedEmbeddedGGMConsumer` can be substituted with zero changes to
PGDR's own code once GGM ships one — the `GGMConsumer` Protocol is the
seam, not `DefaultGGMConsumer`.

```
P8A - Consumer-contract integration:     COMPLETE
P8B - Bounded/embedded runtime:          WAITING ON GGM
```

## A genuine discrepancy caught before coding, not after

The mandate's Axis 3 declaration (`standalone_required: true`,
`shared_service_allowed: true`) fails against the REAL
`ConsumptionResolver`'s R5 cross-axis check - verified by actually
running the resolution, not by reading the resolver's code and assuming.
Full detail in `p8_consumption_profile.md`. This is exactly the kind of
thing that only surfaces when you build against the pinned executable
package instead of the prose describing it.

## `DecisionType.LABEL` is declared but never emitted

`ggm.model.DecisionType` has 5 members: `ALLOW`, `REPAIR`, `LABEL`,
`BLOCK`, `ESCALATE`. Grepped the entire pinned package (`ggm/governance/`,
`ggm/model/`) for any code path that actually constructs a
`GovernanceResult`/`GovernanceDecision` with `outcome=DecisionType.LABEL`
- none exists. It's a reserved vocabulary member, not a currently-
reachable outcome. P8 handles it explicitly anyway (routed through the
same fail-closed path as a genuinely unknown outcome) rather than either
ignoring it or inventing presentation semantics for a decision type the
mandate never defines behavior for.

## `EvidenceRef.type` has no PGDR-facing enum to conform to

`EvidenceRef.type` is a plain `str` field with no published enum of
allowed values anywhere in the pinned package. P8 uses
`"pgdr_analytical_evidence"` as a self-descriptive label - a PGDR
naming choice, not a GGM vocabulary term, documented as such.

## What P8 v1 deliberately does not attempt

1. **`effective_permissions` enforcement beyond "presentable at all."**
   `GovernanceResult.effective_permissions` is a rich structure
   (present/explore/recommend/plan/implement/execute/persist/propagate).
   P8 v1's gate is binary: ALLOW -> presentable, everything else -> not.
   It does not yet check whether individual permission fields should
   change HOW a hypothesis is shown, only whether it's shown at all -
   a real gap, not hidden.

2. **`repair_instruction` execution.** REPAIR always resolves to
   not-presentable in P8 v1, per the mandate's own §18 sanctioned choice.
   No current PGDR mechanism exists to safely apply an arbitrary
   GGM-issued repair instruction to a hypothesis's presentation.

3. **TRANSITION / CHECK_ESCALATION calls.** Both are declared as
   required/enabled capabilities (Axis 2) and genuinely enabled in the
   resolved manifest, but the adapter only ever issues DECIDE requests.
   No PGDR use case for requesting a transition or checking escalation
   independently of DECIDE exists yet; inventing one would violate the
   mandate's own restraint instruction (§22/§23).

4. **`provenance.parent_objects` population.** Source observation IDs
   are computed and carried on the candidate DTO for audit purposes but
   not written into the serialized claim's `provenance` field - no
   GGM-defined provenance-chain semantic exists for this, and inventing
   one felt like exactly the kind of local semantic extension the
   mandate warns against.

## Cross-repository packaging test gap (a real, structural limitation)

PGDR's wheel-based packaging tests build a fresh venv and install only
the PGDR wheel - proving the artifact carries everything it needs on its
own was the whole point since P0. As of P8, PGDR has a genuine runtime
dependency on `ggm`, which is not on PyPI. Both affected tests
(`test_p0_packaging.py`'s emergency-scenario test, `test_p7_retirement.py`'s
`test_p7_t09`) now also install a GGM wheel into the fresh venv, sourced
from a `GGM_WHEEL_PATH` environment variable - if unset, they **skip
with an explicit reason** rather than silently passing or failing. This
is an honest limitation of validating a two-repository integration from
inside one repository's test suite, not a bug to paper over.

## Definition of Done - verified

```
1. Every diagnostic candidate reaching presentation was governed by a
   real GGM decision.                                                    PASS - signature test, test_p8_t10-14
2. PGDR imports only the public consumer/consumption surface.            PASS - test_p8_t01, t01b (AST-scanned)
3. Three-axis consumption declaration resolves against real GGM.         PASS - test_p8_t02_t03_t04
4. BLOCK/REPAIR/ESCALATE never leak through as presented.                PASS - test_p8_t11-14
5. ConsumptionError is a distinct, never-conflated-with-BLOCK channel.   PASS - test_p8_t15-19
6. Governance never mutates DiagnosticCaseState.                        PASS - test_p8_t13, t23-25, signature test
7. Safety-escalated path bypasses governance entirely.                  PASS - test_p8_t26
8. No silent ungoverned fallback; fail-closed at startup + readiness.   PASS - test_p8_t27, t27b
9. Analytical score never becomes epistemic/authority state.            PASS - test_p8_t09
10. Evidence direction preserved, never reinterpreted as RelationType.   PASS - test_p8_t06-08
11. All P0-P7 tests remain green with governance live by default.        PASS - 134/134 unchanged
12. New P8 tests pass, including the signature test.                     PASS - 23/23
```

## Verification summary

```
56/56    GGM's own contract test suite (baseline, run before any PGDR code)
134/134  P0-P7 PGDR tests (unchanged, governance now enabled by default)
23/23    new P8 tests
157/157  total combined suite (with GGM_WHEEL_PATH set)
2 tests  gracefully skip (not fail) without GGM_WHEEL_PATH
```
