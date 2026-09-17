"""Block B1 (original contract) + Block B2-V (this extension) —
PGDR_BLOCK_B1_PRIMARY_DIAGNOSTIC_MEDIA_CONTRACT_v0 §7/§8/§9/§10, extended
by the B2-V EXECUTION MANDATE v0.

The capability boundary: RESOLVED MEDIA + APPLICABLE B2-K REFERENCE
KNOWLEDGE -> DASHBOARD INTERPRETATION. B2-V's conceptual responsibility
remains exactly what B1 named it: "interpret observable dashboard
content from diagnostic media", never "diagnose the vehicle from an
image". DashboardInterpretationResult remains deliberately NOT Evidence,
carries no severity, driveability, or diagnostic conclusion. The
conversion of a DashboardInterpretationResult into real PGDR Evidence
belongs to a downstream block, not B2-V.

B2-V EXTENSION (this pass) -- what changed and why, per the mandate's own
§3/§5/§6/§7/§9:
  - interpret() now receives ResolvedMedia (real bytes/type/reference,
    from MediaResolverPort -- B1.5) plus the applicable
    DashboardReferenceSet (B2-K's own manufacturer knowledge for this
    vehicle), instead of the raw PrimaryDiagnosticMedia reference alone.
    The provider must match against the supplied reference set, never
    identify freely from its own trained knowledge (§3/§8).
  - interpret() now returns a list[DashboardInterpretationResult], since
    one image can contain multiple dashboard signals (§9) -- never
    forced into "one image = one indicator".
  - DashboardInterpretationResult gains observation_confidence (how
    certain the provider is about what it perceptually observed) as
    distinct from match_confidence (how certain the match against a
    specific DashboardReferenceEntry is) -- a readable photo does not
    guarantee an unambiguous symbol identification (§6).
  - DashboardInterpretationResult gains match_status (MATCH/
    AMBIGUOUS_MATCH/NO_MATCH/INSUFFICIENT_VISUAL_QUALITY, §7) -- always
    explicit, never collapsed into a generic failure or a silent best
    guess.
  - matched_reference_entry_id / candidate_reference_entry_ids replace
    free-form `identification` as the authoritative match record: a
    positive match MUST reference a real DashboardReferenceEntry.entry_id
    from the supplied reference set (§5/§8/§17) -- manufacturer meaning
    (documented_meaning/documented_instruction) is never produced by the
    provider itself, only looked up afterward from the matched entry, by
    whoever consumes this result.
  - `identification` (B1's original field) and the original singular
    `confidence` are both retained, now optional, for backward
    compatibility with existing B1-era code that reads them -- neither is
    populated with free-form provider output; `identification`, when set,
    must equal the matched entry's own manufacturer_designation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pgdr.domain.dashboard_knowledge import DashboardReferenceSet
from pgdr.enums import Confidence
from pgdr.ports.media_resolver import ResolvedMedia


class InterpretationProvenance(BaseModel):
    """§10 (B1) / §B2V-16: structural capability to preserve where an
    interpretation came from -- required later to distinguish observed-
    from-media, manufacturer statement, technical-source evidence, and
    PGDR inference from one another."""
    model_config = ConfigDict(frozen=True)

    adapter_id: Optional[str] = None
    media_reference: str
    interpreted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MatchStatus(str, Enum):
    """§7 of the B2-V mandate: always explicit, never collapsed into a
    generic failure. NO_MATCH != "best guess"; AMBIGUOUS_MATCH != silent
    selection of the first candidate."""
    MATCH = "match"
    AMBIGUOUS_MATCH = "ambiguous_match"
    NO_MATCH = "no_match"
    INSUFFICIENT_VISUAL_QUALITY = "insufficient_visual_quality"


class DashboardInterpretationResult(BaseModel):
    """§6/§8 of the B2-V mandate. Field names follow the same vocabulary
    `pgdr.domain.observation.Observation` already uses where applicable --
    deliberately NOT an `Observation` or `Evidence` instance itself, per
    B1's own explicit distinction (unchanged by this extension), since
    neither of those models' existing semantics (case-state membership,
    weighted hypothesis targeting) apply to a not-yet-ingested
    interpretation result.

    A positive match (match_status == MATCH) MUST set
    matched_reference_entry_id to a real DashboardReferenceEntry.entry_id
    drawn from the DashboardReferenceSet supplied to interpret() -- this
    type carries no field capable of holding manufacturer meaning
    (documented_meaning/documented_instruction/severity/driveability/
    repair recommendation) itself; that content is looked up from the
    matched entry by whoever consumes this result, never produced here."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"DIR-{uuid4().hex[:8].upper()}")
    observation: str
    observation_confidence: Confidence
    match_status: MatchStatus
    matched_reference_entry_id: Optional[str] = None
    """Set only when match_status == MATCH. Must equal a real entry_id
    present in the DashboardReferenceSet supplied to interpret() -- never
    a free-form or fabricated identifier."""
    candidate_reference_entry_ids: list[str] = Field(default_factory=list)
    """Populated only when match_status == AMBIGUOUS_MATCH -- the set of
    plausible entry_id candidates, preserved rather than silently
    resolved to one (§B2V-12)."""
    match_confidence: Optional[Confidence] = None
    """Distinct from observation_confidence (§6) -- how certain the match
    against a specific reference entry is, not how certain the raw visual
    observation is."""
    identification: Optional[str] = None
    """B1-era compatibility field. When set, must equal the matched
    entry's own manufacturer_designation -- never free-form provider
    output (§8/§14)."""
    confidence: Optional[Confidence] = None
    """B1-era compatibility field, now optional -- superseded by the
    separate observation_confidence/match_confidence pair (§6)."""
    provenance: InterpretationProvenance


@runtime_checkable
class DashboardInterpretationPort(Protocol):
    """§5 of the B2-V mandate: the B1 Port extended minimally, not
    replaced. Follows the same `typing.Protocol` / `@runtime_checkable`
    convention `ports/diagnostic_domain.py` already establishes for
    PGDR's other capability boundaries.

    Any concrete implementation MUST NOT return a final PGDR diagnosis;
    its responsibility stops at observing dashboard content and matching
    it against the supplied reference knowledge, with confidence and
    provenance. It MUST NOT introduce manufacturer meaning of its own
    (§B2V-14) -- only DashboardReferenceSet is an authoritative source of
    that meaning (§B2V-15). It MUST NOT resolve media itself
    (MediaResolverPort's own responsibility, §5) or select applicable
    manufacturer documents itself (VehicleDashboardKnowledgePort's own
    responsibility) -- interpret() receives both already resolved."""

    def interpret(
        self, media: ResolvedMedia, reference_set: DashboardReferenceSet,
    ) -> list[DashboardInterpretationResult]:
        """Observe dashboard content in the resolved media and match it
        against the supplied applicable reference knowledge. Returns zero,
        one, or many results -- one image may contain multiple dashboard
        signals (§9); a photo with no relevant dashboard content visible
        returns an empty list, never a fabricated result. Not: diagnose
        the vehicle from an image. Not: identify a symbol using knowledge
        outside the supplied reference_set."""
        ...
