"""P8 mandate §5-6 — PGDR's three-axis GGM consumption declaration and its
resolution into a ResolvedConsumptionManifest.

P2.2 migration (see PGDR -> GGM P2.2 Pre-Implementation Evidence Note v1,
gate items 8/9/13): PGDR now declares and requires exactly `DECIDE`.
`TRANSITION` and `CHECK_ESCALATION` were previously declared-but-unused
(P8 v1 called only DECIDE from day one — mandate §14) purely to satisfy
GovernanceDecisionEngine's historical constructor, which mechanically
required live TransitionEngine/EscalationDetector instances regardless of
which operations were actually enabled. GGM P2.2 repaired that coupling
(transition_engine/escalation_detector are now optional constructor
dependencies) and ships RuntimeMaterializer, which builds only the
machinery an enabled operation set actually needs (structural
minimality). With the coupling gone, there is no remaining reason for
PGDR to over-declare operations it never calls — see the evidence note
§9 ("PGDR has no remaining evidence-based reason to declare TRANSITION /
CHECK_ESCALATION solely to make DECIDE constructible").

Every value declared below was verified against the GGM P2.2 source tree
(target commit ac99750 — see the evidence note §1/§3 for the identity
caveat: this is the supplied target identity, not independently
git-verifiable from the source archive), not guessed from any mandate's
prose:

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
from ggm.materialization import (
    MaterializedGGMRuntime,
    RuntimeMaterializationError,
    RuntimeMaterializer,
)

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
# Exactly DECIDE is declared as required (P8's adapter has only ever
# CALLED DECIDE — mandate §14). Prior to GGM P2.2, TRANSITION and
# CHECK_ESCALATION were also declared solely to satisfy
# GovernanceDecisionEngine's historical constructor coupling (see module
# docstring); P2.2's constructor repair plus RuntimeMaterializer's
# structural-minimality guarantee (evidence note §9/§10) removed that
# need, so they are no longer requested. audit_requirements lists what
# PGDR reads out of every GovernanceResult/ConsumptionError for its trace
# (mandate §25/§26) — not a request FOR GGM to compute anything extra.
GGM_CAPABILITY_PROFILE = GGMCapabilityProfile(
    capability_profile_id="pgdr",
    capability_profile_version="1.0",
    operations_required=[Operation.DECIDE.value],
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


def materialize_pgdr_runtime_or_raise(consumer_id: str = "pgdr") -> MaterializedGGMRuntime:
    """P2.2 migration — the fail-closed entry point that replaces
    constructing `DefaultGGMConsumer()` directly (evidence note §12/§13's
    revised readiness/runtime flow):

        resolve_pgdr_consumption_manifest_or_raise()
                v
        RuntimeMaterializer().materialize(manifest)
                v
        RuntimeMaterializationError? -> GovernanceUnavailableError
        else                        -> MaterializedGGMRuntime

    Used by both SessionController.__init__() (to obtain
    runtime.consumer for GGMDiagnosticGovernanceAdapter) and
    readiness.py's ggm_consumption check, so both share exactly one
    materialization path — no second ad hoc construction of
    RuntimeMaterializer elsewhere in PGDR.

    Raises GovernanceUnavailableError (never returns a
    RuntimeMaterializationError) — same fail-closed contract as
    resolve_pgdr_consumption_manifest_or_raise (mandate §32, "No
    ungoverned fallback").
    """
    manifest = resolve_pgdr_consumption_manifest_or_raise(consumer_id=consumer_id)
    materialized = RuntimeMaterializer().materialize(manifest)
    if isinstance(materialized, RuntimeMaterializationError):
        raise GovernanceUnavailableError(
            f"PGDR resolved consumption manifest failed to materialize into a GGM runtime: "
            f"{materialized.error_type.value} — {materialized.details}"
        )
    return materialized
