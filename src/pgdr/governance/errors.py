"""P8 governance error types.

`GovernanceUnavailableError` subclasses `pgdr.errors.ConfigurationError`
deliberately — it reuses the exact fail-closed CLI boundary P0 already
established (cli.py's single try/except around SessionController
construction) rather than requiring a second catch site. This is a
mechanical reuse of an existing fail-closed pattern, not a new one.

Per mandate §20/§27: "GOVERNANCE UNAVAILABLE" (this module) is a distinct
concept from "GOVERNANCE BLOCKED" (a real GovernanceResult(outcome=BLOCK))
and from "PGDR CONFIGURATION INVALID" (P0's domain-config errors). All
three currently surface through the same ConfigurationError-derived
fail-closed boundary at startup, but the message/exception type keeps them
distinguishable — see p8_findings.md for why a full three-way status enum
was judged out of scope for P8 v1.
"""
from __future__ import annotations

from pgdr.errors import ConfigurationError


class GovernanceUnavailableError(ConfigurationError):
    """Raised when governance is required (the production default) and
    either the PGDR consumption declaration fails to resolve against GGM,
    or a GGMConsumer cannot be constructed. Never raised for a real
    governance decision (ALLOW/BLOCK/REPAIR/ESCALATE) — those are
    GovernanceResult, not an error, and never raised for a per-request
    ConsumptionError either (that's handled per-candidate at governance
    time, not at startup)."""
