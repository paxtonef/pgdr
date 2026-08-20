# P8 Mapping Contract

The exact PGDR to GGM object mapping, readable without the code.

## DiagnosticGovernanceCandidate -> GovernedClaim

| PGDR field | GGM field | Value / rule |
|---|---|---|
| `hypothesis_id` | `id` | preserved verbatim - enables direct correlation |
| `statement` | `content` | preserved verbatim |
| `case_id` | `origin.run_id` | the case is the "run" that produced this claim |
| (fixed) | `origin.origin_type` | `DETERMINISTIC_SYSTEM` - PGDR's scorer is literally deterministic, not an LLM |
| (fixed) | `origin.producer_id` | `"pgdr.diagnostic_loop"` |
| (fixed) | `classification.families` | `[HYPOTHETICAL]` - PGDR hypotheses never assert fact (PGDR-HYP-003's "compatible with" language); this is GGM's own vocabulary used accurately, not extended |
| `analytical_score` | `classification.confidence` | clamped to `[0,1]`, defaults to `0.0` if `None` - **metadata only**, never used to compute epistemic/authority state |
| (default) | `epistemic.status` | `UNKNOWN` - the literal dataclass default in `ggm.model.EpistemicState`, the "lowest/non-authoritative canonical state" |
| (default) | `authority.level` | `NONE` - the literal dataclass default in `ggm.model.AuthorityState` |
| (default) | `permissions.*` | all `False` - PGDR pre-asserts no permission; `effective_permissions` from DECIDE is what governs, never anything PGDR sets |
| (default) | `risk.level` | `R0` - PGDR does not assess GGM-vocabulary risk levels |
| (default) | `lifecycle.status` | `ACTIVE` - a currently-active candidate, not superseded/rejected/retracted |

**Never set:** `EpistemicStatus.VERIFIED`, `EpistemicStatus.GENERATED`,
`AuthorityLevel.DOMAIN_AUTHORIZED`, or any authority/epistemic value
beyond the defaults above - confirmed by
`test_p8_t09_analytical_score_does_not_create_authority`, which builds a
candidate with `analytical_score=0.99` and asserts the serialized claim
still carries `epistemic.status == "UNKNOWN"` and `authority.level ==
"NONE"`.

## Evidence -> EvidenceRef

| PGDR field | GGM field | Value / rule |
|---|---|---|
| evidence id | `EvidenceRef.ref` | preserved verbatim |
| (fixed) | `EvidenceRef.type` | `"pgdr_analytical_evidence"` - a PGDR-chosen descriptive label; `EvidenceRef.type` has no published GGM enum (confirmed by reading `ggm/contract/types.py` - it's a plain `str` field) |
| PGDR's `EvidenceDirection` (SUPPORTS/CONTRADICTS/NEUTRAL) | `EvidenceRef.details["direction"]` | preserved verbatim, as a plain string |

**Never converted:** PGDR's `SUPPORTS`/`CONTRADICTS` direction is never
translated into GGM's `RelationType` vocabulary (`RelationType.CAUSES`,
`.SUPPORTS`, `.CONTRADICTS`, etc.) - `RelationType` describes relations
*between* two `GovernedClaim`/`GovernedRelation` objects, a different
object type P8 v1 does not construct (P8 v1 governs candidate claims, not
inter-claim relations). Confirmed by
`test_p8_t06_t07_t08_evidence_direction_preserved`, which asserts neither
`"causes"` nor `"CAUSES"` ever appears among the mapped directions.

## What is intentionally NOT mapped

- `source_observation_ids` (on `DiagnosticGovernanceCandidate`) is
  computed and carried for audit purposes but not folded into the
  serialized claim itself - GGM's `GovernedClaim` has no field for
  "which raw observations this traces back to" beyond `provenance`, and
  P8 v1 doesn't populate `provenance.parent_objects` with observation IDs
  (a defensible future extension, not attempted here to avoid inventing
  a provenance-chain semantic GGM itself doesn't define for this case).
- `presentation_target` ("user_summary" vs "garage_report") is passed in
  `GovernanceRequest.context`, not the claim object - it describes *where*
  PGDR intends to show this, not a property of the claim itself.

## GovernanceResult -> DiagnosticGovernanceOutcome

| GGM outcome | `presentable` | `escalated` | P8 v1 behavior |
|---|---|---|---|
| `ALLOW` | `True` | `False` | hypothesis stays active in the report copy |
| `BLOCK` | `False` | `False` | hypothesis deactivated; statement text confirmed absent from the final report (`test_p8_t11_t12`) |
| `REPAIR` | `False` | `False` | treated as not-presentable - **`repair_instruction` is never executed** (mandate §18's sanctioned conservative choice for v1) |
| `ESCALATE` | `False` | `True` | hypothesis deactivated; a distinct "requires further verification" limitation is added instead of the BLOCK wording |
| `LABEL` | `False` | `False` | declared `DecisionType` member, **never currently emitted** by the pinned engine (confirmed by reading `ggm/governance/` and `ggm/model/`) - routed through the same fail-closed path as a genuinely unknown outcome, since no presentation semantics are defined for it anywhere |
| *(anything else)* | `False` | `False` | fail-closed - no `else: allow` exists anywhere in `adapter.py` |

## ConsumptionError -> DiagnosticGovernanceOutcome

Always `presentable=False`, `result_channel="CONSUMPTION_ERROR"` -
**never** `result_channel="GOVERNANCE_RESULT"` with a synthesized BLOCK.
This distinction is load-bearing and directly tested
(`test_p8_t15_to_t19_consumption_error_default_denies_and_is_not_block`,
parametrized across all 4 real `ErrorType` values read from
`ggm/contract/errors.py`).
