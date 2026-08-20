"""P8 mandate §5-6 — PGDR's three-axis GGM consumption declaration and its
resolution into a ResolvedConsumptionManifest.

Every value declared below was verified against the pinned GGM package
(commit 4fda5974312f1949771fc4993ced4c98fe0d1ac0), not guessed from the
mandate's prose:

  - "ggm.base"/"1.0" is the actual profile_id/version returned by
    ggm.profiles.build_default_profiles() (confirmed by reading
    ggm/profiles/__init__.py directly).
  - CANONICAL_KERNEL_VERSION ("ggm/1.1") is imported from
    ggm.consumption.registry, never hardcoded here — per the mandate's own
    "do not hardcode the mandatory invariants/kernel in PGDR" instruction
    (§5 Axis 2), PGDR declares its REQUESTED kernel version by reading the
    same canonical constant GGM itself resolves against, so a future GGM
    kernel bump is reflected here automatically rather than drifting.

Per mandate §5 Axis 1: PGDR selects only `ggm.base` — no
domain.software_production or PGDR/diagnostic-specific profile exists
canonically yet, and this module does not invent one.
"""
from __future__ import annotations

from typing import Union

from ggm.consumption import (
    CanonicalProfileRef,
    CANONICAL_KERNEL_VERSION,
    ConsumptionResolutionError,
    ConsumptionResolver,
    DeploymentProfile,
    GGMCapabilityProfile,
    GovernanceProfileSelection,
    ResolvedConsumptionManifest,
)
from ggm.contract.types import Operation

from pgdr.governance.errors import GovernanceUnavailableError

# -- Axis 1: which canonical governance profile(s) apply --------------------
# P8 v1: ggm.base only. A PGDR/diagnostic-specific profile is explicitly
# DEFERRED (mandate §5) until GGM authors one — PGDR does not select or
# invent a domain profile here.
GOVERNANCE_PROFILE_SELECTION = GovernanceProfileSelection(
    selection_id="pgdr.governance_selection",
    selection_version="1.0",
    profile_refs=[CanonicalProfileRef(profile_id="ggm.base", profile_version="1.0")],
)

# -- Axis 2: what GGM machinery PGDR requires --------------------------------
# All three contract operations are DECLARED as required (enabling them in
# the resolved manifest), even though P8 v1's adapter only actually CALLS
# DECIDE (mandate §14) — TRANSITION/CHECK_ESCALATION are enabled-but-unused
# today, per mandate §22/§23's instruction not to invent a use case just
# because the operation exists. audit_requirements lists what PGDR reads
# out of every GovernanceResult/ConsumptionError for its trace (mandate
# §25/§26) — not a request FOR GGM to compute anything extra.
GGM_CAPABILITY_PROFILE = GGMCapabilityProfile(
    capability_profile_id="pgdr",
    capability_profile_version="1.0",
    operations_required=[Operation.DECIDE.value, Operation.TRANSITION.value, Operation.CHECK_ESCALATION.value],
    mandatory_kernel_version=CANONICAL_KERNEL_VERSION,
    persistence_required=False,
    audit_requirements=["rules_applied", "profile_trace", "runtime_version", "request_correlation"],
)

# -- Axis 3: how/where governance must be consumable -------------------------
# Preferred target is embedded/bounded (mandate §5); the pinned GGM package
# does not yet implement a bounded runtime (see README_HANDOFF.md /
# p8_findings.md), so `deployment_mode` here declares the *requirement*,
# independent of which GGMConsumer implementation is actually injected at
# runtime (see adapter.py / consumption_profile.resolve_pgdr_consumption_manifest
# callers).
#
# DISCOVERED DISCREPANCY (documented per the developer pack's own
# instruction: "if names/signatures differ, report before coding"): the
# mandate's Axis 3 spec (§5) declares BOTH standalone_required=true AND
# shared_service_allowed=true. GGM's real ConsumptionResolver (R5
# cross-axis check, ggm/consumption/resolver.py) rejects exactly this
# combination — INCOMPATIBLE_DECLARATIONS, "standalone_required and
# shared_service_allowed cannot both be true." This is a genuine logical
# conflict in the source spec, not a naming mismatch: requiring guaranteed
# standalone operation is incompatible with also allowing a shared-service
# dependency. Resolved in favor of `standalone_required=True` (matching
# PGDR's actual current deployment reality — a standalone CLI, no shared
# service exists) and `shared_service_allowed=False`. See p8_findings.md.
DEPLOYMENT_PROFILE = DeploymentProfile(
    deployment_profile_id="pgdr.embedded",
    deployment_profile_version="1.0",
    deployment_mode="embedded",
    offline_required=True,
    standalone_required=True,
    version_pinning_required=True,
    shared_service_allowed=False,
)


def resolve_pgdr_consumption_manifest(
    consumer_id: str = "pgdr",
) -> Union[ResolvedConsumptionManifest, ConsumptionResolutionError]:
    """Resolves PGDR's three-axis declaration through the one canonical
    GGM resolver. Returns the manifest, or a ConsumptionResolutionError if
    resolution itself fails (distinct from a governance decision or a
    per-request ConsumptionError — see errors.py)."""
    resolver = ConsumptionResolver()
    return resolver.resolve(
        GOVERNANCE_PROFILE_SELECTION, GGM_CAPABILITY_PROFILE, DEPLOYMENT_PROFILE,
        consumer_id=consumer_id,
    )


def resolve_pgdr_consumption_manifest_or_raise(consumer_id: str = "pgdr") -> ResolvedConsumptionManifest:
    """Same as resolve_pgdr_consumption_manifest(), but raises
    GovernanceUnavailableError on resolution failure — the fail-closed
    entry point SessionController.__init__() and readiness.py use, per
    mandate §32 ("No ungoverned fallback")."""
    result = resolve_pgdr_consumption_manifest(consumer_id=consumer_id)
    if isinstance(result, ConsumptionResolutionError):
        raise GovernanceUnavailableError(
            f"PGDR consumption declaration failed to resolve against GGM: "
            f"{result.error_type.value} — {result.details}"
        )
    return result
