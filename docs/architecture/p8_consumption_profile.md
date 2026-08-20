# P8 Consumption Profile

PGDR's three-axis declaration, resolved through GGM's own
`ConsumptionResolver` (never a second/local resolver) at `SessionController`
construction time, fail-closed on failure.

## Axis 1 - GovernanceProfileSelection

```
selection_id:      pgdr.governance_selection
selection_version: 1.0
profile_refs:       [ggm.base @ 1.0]
```

P8 v1 selects only `ggm.base` - the one canonical profile that exists in
the pinned package's registry (confirmed by reading
`ggm/profiles/__init__.py::build_default_profiles()` directly). No
PGDR/diagnostic-specific governance profile exists yet; this module does
not invent one.

## Axis 2 - GGMCapabilityProfile

```
capability_profile_id:      pgdr
capability_profile_version: 1.0
operations_required:        [DECIDE, TRANSITION, CHECK_ESCALATION]
mandatory_kernel_version:   ggm/1.1   (read from ggm.consumption.CANONICAL_KERNEL_VERSION,
                                       never hardcoded - see consumption_profile.py)
persistence_required:       False
audit_requirements:         [rules_applied, profile_trace, runtime_version, request_correlation]
```

All three contract operations are declared/enabled, though P8 v1's
adapter only actually *calls* DECIDE (see `p8_ggm_integration.md`).
TRANSITION and CHECK_ESCALATION are enabled-but-unused today - declared
because they're part of the frozen §3 vocabulary, not because P8 v1 has
a genuine use case for them yet (mandate §22's explicit instruction: "do
not invent transitions just because the operation exists").

## Axis 3 - DeploymentProfile

```
deployment_profile_id:        pgdr.embedded
deployment_profile_version:   1.0
deployment_mode:               embedded
offline_required:              True
standalone_required:           True
version_pinning_required:      True
shared_service_allowed:        False
```

**Discovered discrepancy, resolved and documented (not silently
"fixed"):** the mandate's own Axis 3 spec declares both
`standalone_required=true` and `shared_service_allowed=true`
simultaneously. GGM's real `ConsumptionResolver` (R5 cross-axis check)
rejects exactly this combination -
`INCOMPATIBLE_DECLARATIONS: "standalone_required and shared_service_allowed
cannot both be true"`. This is a genuine logical conflict in the source
spec (requiring guaranteed standalone operation is incompatible with
also permitting a shared-service dependency), not a naming/signature
mismatch. Resolved in favor of `standalone_required=True` /
`shared_service_allowed=False`, matching PGDR's actual current
deployment reality (a standalone CLI; no shared GGM service exists to
allow reliance on). Verified: resolution succeeds cleanly with this
correction (see `test_p8_t02_t03_t04_consumption_resolves_with_kernel_and_operations`).

## Resolved manifest (representative - resolution_id/timestamp vary per call, everything else is deterministic)

```
manifest_id:              d9fe1146-cae3-5a3d-862a-697984ac252f  (deterministic uuid5 of the 3 axes)
mandatory_kernel:          ggm/1.1, invariants: [GGM-I01, GGM-I03, GGM-I08, GGM-I10]
operations_enabled:        [DECIDE, TRANSITION, CHECK_ESCALATION]
contract_version:          1.2
resolver_version:          1.3
profiles_resolved:         [ggm.base @ 1.0]
```

`manifest_id` is derived (uuid5, not uuid4) from the resolved axis
identities, per GGM's own §13 determinism guarantee - the SAME manifest
ID results from re-resolving the same three axes, confirmed live against
the real resolver, not merely asserted.

## Where PGDR reads this manifest

`SessionController.__init__()` calls
`resolve_pgdr_consumption_manifest_or_raise()` once, fail-closed. The
resulting `manifest_id` and `capability_profile_version` are threaded
into every `DiagnosticGovernanceTrace` this session ever produces (see
`p8_ggm_integration.md`'s trace fields) - every governed decision is
traceable back to exactly which consumption declaration was in effect.
`readiness.py`'s `_check_ggm_consumption()` performs the same resolution
independently at readiness-check time, verifying the mandatory kernel is
present and all three required operations are enabled.
