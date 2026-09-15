"""Block B1 — PGDR_BLOCK_B1_PRIMARY_DIAGNOSTIC_MEDIA_CONTRACT_v0, §5/§6.

PRIMARY DIAGNOSTIC MEDIA is raw diagnostic input. It is explicitly NOT
Evidence, Observation, Identification, Confidence, a Question Answer, or
InitialComplaint (v1 §3's frozen semantics). This module exists solely so
that distinction is structural, not just documented.

Deliberately minimal, per B1's own scope boundary (§6/§16): no image
interpretation, no warning-light classification, no manufacturer meaning,
no Evidence, no diagnostic conclusion, no severity, no driveability.
Those are downstream (Block B2+/D) concerns.

This is a distinct path from the existing Q-EVI-002 answer_type=
media_upload mechanism (LEGACY_MEDIA_SEMANTICS_TO_ALIGN, per
VIR_PHOTO_PGDR_BUILD_DECOMPOSITION_v1) -- DiagnosticMediaRole exists
specifically so the two paths remain structurally distinguishable rather
than collapsing back into one opaque string, even though only
PRIMARY_DIAGNOSTIC_MEDIA is used anywhere in B1.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class MediaType(str, Enum):
    """What kind of media the reference points to. B1 does not interpret
    content -- this is purely a transport-level classification, needed so
    a future interpretation adapter (Block B2+) knows how to read the
    referenced media without PGDR having to guess."""
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class DiagnosticMediaRole(str, Enum):
    """Distinguishes PRIMARY DIAGNOSTIC MEDIA (this module's own concern,
    supplied before or independently of any question) from the existing,
    separate QUESTION_ANSWER_MEDIA path (Q-EVI-002,
    LEGACY_MEDIA_SEMANTICS_TO_ALIGN, untouched by B1). Only the first
    value is actually used anywhere in B1; the second is declared here so
    the enum itself documents the real distinction rather than letting a
    future reader assume media is a single undifferentiated concept."""
    PRIMARY_DIAGNOSTIC_MEDIA = "primary_diagnostic_media"
    QUESTION_ANSWER_MEDIA = "question_answer_media"


class PrimaryDiagnosticMedia(BaseModel):
    """The minimum typed representation of raw diagnostic media input,
    per §6: media reference, media type, diagnostic role. Nothing else.
    Frozen, matching the immutability convention `pgdr.domain.observation.
    Observation` and `pgdr.domain.evidence.Evidence` already establish for
    once-created case-input data."""
    model_config = ConfigDict(frozen=True)

    reference: str
    media_type: MediaType = MediaType.IMAGE
    role: DiagnosticMediaRole = DiagnosticMediaRole.PRIMARY_DIAGNOSTIC_MEDIA
