"""Block B1.5 — Media Acquisition / Storage / Resolution capability.

Makes PrimaryDiagnosticMedia.reference (Block B1) actually dereferenceable.
Before this module, `reference` was an arbitrary caller-supplied opaque
string with no guarantee anything real backed it (confirmed absent: no
upload endpoint, no storage adapter, no resolution mechanism, anywhere in
PI or PGDR, prior to B1.5).

This module defines the PGDR-side contract only:
  PGDR domain -> MediaResolverPort -> (concrete storage adapter, owned by
  the caller injecting it -- e.g. PI's own local-filesystem-backed
  implementation, B1.5's own deliverable on the PI side).

PGDR domain code MUST NOT perform filesystem operations itself -- no
`open(path)`, no path construction, nowhere in this module or any PGDR
domain module. This mirrors the existing ports/diagnostic_domain.py and
ports/dashboard_interpretation.py convention exactly: PGDR defines the
capability boundary; a concrete adapter, injected from outside PGDR's
domain layer, does the actual work.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from pgdr.domain.media import MediaType


class ResolvedMedia(BaseModel):
    """What a future interpretation adapter (Block B2) actually needs:
    the real content, its type, and the reference it was resolved from
    (for provenance -- see DashboardInterpretationResult.provenance,
    which already carries media_reference). Deliberately NOT Evidence,
    NOT Observation, NOT DashboardInterpretationResult -- resolving media
    creates zero diagnostic meaning (frozen semantic invariant, unchanged
    by B1.5)."""
    model_config = ConfigDict(frozen=True)

    content: bytes
    media_type: MediaType
    reference: str


@runtime_checkable
class MediaResolverPort(Protocol):
    """Provider-neutral resolution boundary. A concrete implementation
    (e.g. a local-filesystem-backed adapter) is injected by the caller --
    PGDR domain code never imports or depends on a specific storage
    mechanism. Raises MediaResolutionError (see below) when the reference
    cannot be resolved -- never returns a partial or fabricated result."""

    def resolve(self, reference: str) -> ResolvedMedia:
        """Resolve an opaque media reference to its real content. The
        reference is treated as fully opaque by PGDR -- it carries no
        assumption about filesystem paths, URLs, or any other physical
        storage detail; only the injected adapter knows how to interpret
        it."""
        ...


class MediaResolutionError(Exception):
    """Raised by a MediaResolverPort implementation when a reference
    cannot be resolved to real media content (not found, corrupted,
    inaccessible, or -- critically -- rejected because it looks like an
    attempt to smuggle a filesystem path or URL through the opaque
    reference contract). PGDR domain code must treat this as a genuine
    resolution failure, never silently substitute empty/placeholder
    content."""
