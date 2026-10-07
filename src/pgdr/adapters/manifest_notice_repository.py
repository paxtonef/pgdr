"""V1 parcours — read-only KnowledgeRepositoryPort over a curated notice
package: its SOURCE manifest (manifest.yaml, schema v2, see
outils/preparation_v1) and the files next to it (PDF, entry images, inline
pictograms).

Nothing is trusted from declarations alone. At load time this adapter:
  * recomputes the content fingerprint of the manifest itself (every field
    except `review`, same canonical JSON as notices.py::content_fingerprint)
    and requires it to equal review.content_sha256 of an `approved` review
    with a named reviewer and a past, timezone-aware date;
  * hashes the PDF and every image / pictogram file and requires each digest
    to equal the one the manifest declares;
  * refuses absolute paths and any path (symlinks included) resolving
    outside the package directory.
Any failure raises NoticeRejected and no catalogue is exposed.

The verified image bytes are kept in memory and served from there, so what
is shown is exactly what was hashed (no re-read after verification). The
adapter never writes anything: no file, no database, no CPL.

PDF page counts are NOT re-checked here (no PDF parser in the PGDR
environment); page numbers are bound by the reviewed fingerprint and by the
manual's own digest, and range-checked by notices.py during preparation.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from pgdr.domain.dashboard_knowledge import (
    ApplicabilityPeriod, DashboardReferenceEntry, IndicatorState, KnowledgeFreshnessStatus,
    ManufacturerDocumentReference, SourceAuthority, VehicleApplicabilityContext,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_STATES = {None, "fixed", "flashing", "unknown"}


class NoticeRejected(Exception):
    """The notice package is not usable: review pending/obsolete, or a file
    or field does not match what the manifest declares."""


def content_fingerprint(manifest: dict) -> str:
    """Identical to outils/preparation_v1/scripts/notices.py::content_fingerprint
    (a test pins the equality): binds the review to every field but itself."""
    payload = {k: v for k, v in manifest.items() if k != "review"}
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


@dataclass(frozen=True)
class Pictogram:
    """A pictogram printed inside a text, at character offset `position`."""
    position: int
    image_sha256: str
    pdf_page: int
    printed_page: str
    identified_entry_ids: tuple[str, ...]
    identification_basis: str


@dataclass(frozen=True)
class LinkedWarning:
    number: str
    text: str
    printed_page: str
    pdf_page: int
    pictograms: tuple[Pictogram, ...]


@dataclass(frozen=True)
class FieldSource:
    field: str
    text: str
    printed_page: str
    pdf_page: int


@dataclass(frozen=True)
class NoticeEntry:
    """One catalogue image with everything the notice says about it, exact."""
    manual_order: int
    entry_id: str
    designation: str
    colour: Optional[str]
    state: Optional[str]
    symbol_descriptor: Optional[str]
    displayed_message: Optional[str]
    audible_signal: Optional[str]
    documented_meaning: str
    documented_instruction: Optional[str]
    combined_with_entry_ids: tuple[str, ...]
    image_sha256: str
    pdf_page: int
    page_reference: str
    meaning_pictograms: tuple[Pictogram, ...]
    linked_warnings: tuple[LinkedWarning, ...]
    field_sources: tuple[FieldSource, ...]
    notes: tuple[str, ...]
    where_provided: Optional[bool]
    documented_startup_check: Optional[str]


@dataclass(frozen=True)
class NoticeCatalogue:
    document: ManufacturerDocumentReference
    vehicle: dict
    language: Optional[str]
    content_sha256: str
    manual_sha256: str
    applicability_established: bool
    entries: tuple[NoticeEntry, ...]  # manual order

    def entry(self, entry_id: str) -> Optional[NoticeEntry]:
        return next((e for e in self.entries if e.entry_id == entry_id), None)


def _text(v, label: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise NoticeRejected(f"{label} required")
    return v


def _opt_text(v, label: str) -> Optional[str]:
    if v is not None and not isinstance(v, str):
        raise NoticeRejected(f"invalid {label}")
    return v


def _page(v) -> int:
    if type(v) is not int or v < 1:
        raise NoticeRejected("invalid PDF page")
    return v


class ManifestNoticeRepository:
    """KnowledgeRepositoryPort, read-only, over one notice package."""

    def __init__(self, manifest_path: Path | str) -> None:
        self._path = Path(manifest_path).expanduser()
        self._root = self._path.parent.resolve()
        self._blobs: dict[str, bytes] = {}
        self._catalogue = self._load()

    # -- verification --------------------------------------------------------

    def _verified_file(self, name, expected_sha256, keep: bool) -> str:
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise NoticeRejected("relative file path required")
        f = (self._root / name).resolve()
        if not f.is_relative_to(self._root) or not f.is_file():
            raise NoticeRejected("missing file or path outside package")
        if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
            raise NoticeRejected("SHA-256 required")
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise NoticeRejected(f"file fingerprint mismatch: {name}")
        if keep:
            self._blobs[expected_sha256] = data
        return expected_sha256

    def _pictograms(self, items, text: str) -> tuple[Pictogram, ...]:
        if not isinstance(items, list):
            raise NoticeRejected("invalid pictograms")
        out = []
        for p in items:
            if not isinstance(p, dict):
                raise NoticeRejected("invalid pictogram")
            pos = p.get("position")
            if type(pos) is not int or not 0 <= pos <= len(text):
                raise NoticeRejected("pictogram position outside its text")
            ids = p.get("identified_entry_ids")
            if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
                raise NoticeRejected("invalid pictogram entry references")
            out.append(Pictogram(
                position=pos,
                image_sha256=self._verified_file(p.get("image_file"), p.get("image_sha256"), keep=True),
                pdf_page=_page(p.get("pdf_page")),
                printed_page=_text(p.get("printed_page"), "printed_page"),
                identified_entry_ids=tuple(ids),
                identification_basis=_text(p.get("identification_basis"), "identification_basis"),
            ))
        return tuple(out)

    def _load(self) -> NoticeCatalogue:
        try:
            d = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise NoticeRejected("manifest unreadable") from exc
        if not isinstance(d, dict) or d.get("schema_version") != 2:
            raise NoticeRejected("schema version 2 required")

        # 1. Review: approved, named, dated, and bound to the content as it is NOW.
        r = d.get("review")
        if not isinstance(r, dict) or r.get("status") != "approved":
            raise NoticeRejected("review pending or absent")
        _text(r.get("reviewer_id"), "reviewer_id")
        _text(r.get("reviewer_name"), "reviewer_name")
        try:
            reviewed_at = datetime.fromisoformat(str(r.get("reviewed_at")).replace("Z", "+00:00"))
        except ValueError as exc:
            raise NoticeRejected("invalid review date") from exc
        if reviewed_at.tzinfo is None or reviewed_at > datetime.now(timezone.utc):
            raise NoticeRejected("invalid review date")
        try:
            actual = content_fingerprint(d)
        except (TypeError, ValueError) as exc:
            raise NoticeRejected("manifest not fingerprintable") from exc
        if r.get("content_sha256") != actual:
            raise NoticeRejected("review obsolete: content fingerprint differs")

        # 2. Every file against its declared digest.
        if d.get("source_authority") != "manufacturer_official":
            raise NoticeRejected("manufacturer source required")
        manual_sha = self._verified_file(d.get("manual_file"), d.get("manual_sha256"), keep=False)
        vehicle = d.get("vehicle")
        if not isinstance(vehicle, dict):
            raise NoticeRejected("vehicle required")
        for k in ("manufacturer", "model", "generation"):
            _text(vehicle.get(k), k)

        document = ManufacturerDocumentReference(
            manufacturer=vehicle["manufacturer"],
            document_id=_text(d.get("document_id"), "document_id"),
            document_title=_text(d.get("title"), "title"),
            edition=_text(d.get("edition"), "edition"),
            applicability_period=ApplicabilityPeriod(
                start_date=d.get("applicability_period_start"), end_date=d.get("applicability_period_end"),
                note=d.get("applicability_period_note"),
            ),
            source_authority=SourceAuthority.MANUFACTURER_OFFICIAL,
            source_locator=_text(d.get("source_locator"), "source_locator"),
            verified_at=reviewed_at.isoformat(),
            # A named owner attestation, not an independently reproducible verification.
            freshness_status=KnowledgeFreshnessStatus.OWNER_ATTESTED_UNVERIFIED,
        )

        raw = d.get("entries")
        if not isinstance(raw, list) or not raw:
            raise NoticeRejected("no catalogue entries")
        entries, seen = [], set()
        for i, e in enumerate(raw):
            if not isinstance(e, dict):
                raise NoticeRejected("entry object required")
            entry_id = _text(e.get("entry_id"), "entry_id")
            if entry_id in seen:
                raise NoticeRejected("duplicate entry ID")
            seen.add(entry_id)
            if e.get("state") not in _STATES:
                raise NoticeRejected("invalid state")
            meaning = _text(e.get("documented_meaning"), "documented_meaning")
            warnings = []
            for w in e.get("linked_warnings", []) or []:
                if not isinstance(w, dict):
                    raise NoticeRejected("invalid linked warning")
                wtext = _text(w.get("text"), "warning text")
                warnings.append(LinkedWarning(
                    number=_text(w.get("number"), "warning number"), text=wtext,
                    printed_page=_text(w.get("printed_page"), "printed_page"), pdf_page=_page(w.get("pdf_page")),
                    pictograms=self._pictograms(w.get("inline_pictograms", []), wtext),
                ))
            sources = e.get("field_sources", {}) or {}
            if not isinstance(sources, dict) or any(not isinstance(v, dict) for v in sources.values()):
                raise NoticeRejected("invalid field sources")
            notes = e.get("notes", []) or []
            if not isinstance(notes, list):
                raise NoticeRejected("invalid notes")
            wp = e.get("where_provided")
            if wp is not None and type(wp) is not bool:
                raise NoticeRejected("invalid where_provided")
            ids = e.get("combined_with_entry_ids") or []
            if not isinstance(ids, list):
                raise NoticeRejected("invalid combined IDs")
            entries.append(NoticeEntry(
                manual_order=i, entry_id=entry_id,
                designation=_text(e.get("manufacturer_designation"), "manufacturer_designation"),
                colour=_opt_text(e.get("colour"), "colour"), state=e.get("state"),
                symbol_descriptor=_opt_text(e.get("symbol_descriptor"), "symbol_descriptor"),
                displayed_message=_opt_text(e.get("displayed_message"), "displayed_message"),
                audible_signal=_opt_text(e.get("audible_signal"), "audible_signal"),
                documented_meaning=meaning,
                documented_instruction=_opt_text(e.get("documented_instruction"), "documented_instruction"),
                combined_with_entry_ids=tuple(ids),
                image_sha256=self._verified_file(e.get("image_file"), e.get("image_sha256"), keep=True),
                pdf_page=_page(e.get("pdf_page")),
                page_reference=_text(e.get("page_reference"), "page_reference"),
                meaning_pictograms=self._pictograms(e.get("inline_pictograms", []), meaning),
                linked_warnings=tuple(warnings),
                field_sources=tuple(
                    FieldSource(field=k, text=_text(v.get("text"), "source text"),
                                printed_page=_text(v.get("printed_page"), "printed_page"),
                                pdf_page=_page(v.get("pdf_page")))
                    for k, v in sorted(sources.items())
                ),
                notes=tuple(_text(n, "note") for n in notes),
                where_provided=wp,
                documented_startup_check=_opt_text(e.get("documented_startup_check"), "documented_startup_check"),
            ))
        for e in entries:
            if any(x not in seen or x == e.entry_id for x in e.combined_with_entry_ids):
                raise NoticeRejected("invalid combined reference")

        avr = d.get("applicability_vehicle_under_review")
        return NoticeCatalogue(
            document=document, vehicle=dict(vehicle), language=d.get("language"),
            content_sha256=actual, manual_sha256=manual_sha,
            applicability_established=isinstance(avr, dict) and avr.get("applicability_established") is True,
            entries=tuple(entries),
        )

    # -- read access ---------------------------------------------------------

    @property
    def catalogue(self) -> NoticeCatalogue:
        return self._catalogue

    def asset(self, sha256: str) -> Optional[bytes]:
        """Verified bytes of an image or pictogram of this notice, by digest."""
        return self._blobs.get(sha256)

    def matches(self, vehicle: VehicleApplicabilityContext) -> bool:
        v = self._catalogue.vehicle

        def same(a, b) -> bool:
            return isinstance(a, str) and isinstance(b, str) and a.strip().casefold() == b.strip().casefold()

        return (same(vehicle.manufacturer, v["manufacturer"]) and same(vehicle.model, v["model"])
                and same(vehicle.generation, str(v["generation"])))

    # -- KnowledgeRepositoryPort ---------------------------------------------

    def find_applicable_documents(self, vehicle: VehicleApplicabilityContext) -> list[ManufacturerDocumentReference]:
        return [self._catalogue.document] if self.matches(vehicle) else []

    def entries_for_document(self, document_id: str) -> list[DashboardReferenceEntry]:
        c = self._catalogue
        if document_id != c.document.document_id:
            return []
        return [
            DashboardReferenceEntry(
                entry_id=e.entry_id, manufacturer_designation=e.designation, symbol_descriptor=e.symbol_descriptor,
                colour=e.colour, state=IndicatorState(e.state) if e.state else None,
                displayed_message=e.displayed_message, audible_signal=e.audible_signal,
                documented_meaning=e.documented_meaning, documented_instruction=e.documented_instruction,
                applicability=c.document, combined_with_entry_ids=list(e.combined_with_entry_ids),
            )
            for e in c.entries
        ]

    def get_document_by_id(self, document_id: str) -> Optional[ManufacturerDocumentReference]:
        return self._catalogue.document if document_id == self._catalogue.document.document_id else None
