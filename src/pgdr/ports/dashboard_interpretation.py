"""Block B1 — PGDR_BLOCK_B1_PRIMARY_DIAGNOSTIC_MEDIA_CONTRACT_v0, §7/§8/§9/
§10.

The capability boundary: PRIMARY DIAGNOSTIC MEDIA -> DASHBOARD
INTERPRETATION. B1 defines the Port and its result contract only -- no
concrete adapter, no vision provider, no real interpretation. The
conceptual responsibility of any future implementation of this Port is
"interpret observable dashboard content from diagnostic media", never
"diagnose the vehicle from an image" -- DashboardInterpretationResult is
therefore deliberately NOT Evidence and carries no severity, driveability,
or diagnostic conclusion. The conversion of a DashboardInterpretationResult
into real PGDR Evidence belongs to Block D, not B1.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from pgdr.domain.media import PrimaryDiagnosticMedia
from pgdr.enums import Confidence


class InterpretationProvenance(BaseModel):
    """§10: structural capability to preserve where an interpretation
    came from -- required later to distinguish observed-from-media,
    manufacturer statement, technical-source evidence, and PGDR inference
    from one another. B1 only establishes the shape; no adapter exists
    yet to populate it with anything but placeholder/identity data."""
    model_config = ConfigDict(frozen=True)

    adapter_id: Optional[str] = None
    media_reference: str
    interpreted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DashboardInterpretationResult(BaseModel):
    """§8: the minimum typed interpretation result necessary for the next
    B slice. Field names follow the same vocabulary
    `pgdr.domain.observation.Observation` already uses (`observation`
    mirrors `Observation.value`'s descriptive role; `confidence` reuses
    the existing `pgdr.enums.Confidence` bucket rather than inventing a
    parallel scale) -- deliberately NOT an `Observation` or `Evidence`
    instance itself, per §8's own explicit distinction, since neither of
    those models' existing semantics (case-state membership, weighted
    hypothesis targeting) apply to a not-yet-ingested interpretation
    result."""
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"DIR-{uuid4().hex[:8].upper()}")
    observation: str
    identification: Optional[str] = None
    confidence: Confidence
    provenance: InterpretationProvenance


@runtime_checkable
class DashboardInterpretationPort(Protocol):
    """§7: a Port only in B1 -- capability boundary, no real adapter.
    Follows the same `typing.Protocol` / `@runtime_checkable` convention
    `ports/diagnostic_domain.py` already establishes for PGDR's other
    capability boundaries, rather than introducing a different pattern
    (e.g. abc.ABC) for this one.

    Any future concrete implementation MUST NOT return a final PGDR
    diagnosis; its conceptual responsibility stops at identifying
    observable dashboard content, with confidence and provenance."""

    def interpret(self, media: PrimaryDiagnosticMedia) -> DashboardInterpretationResult:
        """Interpret observable dashboard content from diagnostic media.
        Not: diagnose the vehicle from an image."""
        ...
