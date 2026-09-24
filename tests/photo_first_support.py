"""Shared test support for the B2 photo-first completion tests.

EVERYTHING here is an integration-test mechanism. The deterministic provider
is NOT a visual capability: it never looks at pixels, it only maps the
SHA-256 of the bytes it is handed to a scripted interpretation result. Its
purpose is to prove the WIRING (real upload endpoint -> real MediaResolverPort
-> real DashboardInterpretationPort call -> governed B2 chain). A PASS
obtained with it is never a Real-World Photo-First PASS.

The repository entries below reuse the three real Peugeot entry ids/content
shape so that the existing B2-R5 rules fire, plus TWO SYNTHETIC entries
(airbag / brake) that are NOT part of any Peugeot seed -- they exist only so
that the EXISTING governed safety rules (PGDR-SAF-011, PGDR-SAF-012) can be
exercised by photo-derived signals.
"""
from __future__ import annotations

import copy
import hashlib
import json
import secrets
import struct
import zlib
from pathlib import Path

from pgdr.domain.dashboard_knowledge import (
    DashboardReferenceEntry, IndicatorState, KnowledgeLifecycleStatus, ManufacturerDocumentReference,
    SourceAuthority, VehicleApplicabilityContext,
)
from pgdr.enums import Confidence
from pgdr.models import VehicleIdentityContext
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationResult, InterpretationProvenance, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia

DETERMINISTIC_ADAPTER_ID = "test.deterministic_dashboard_provider"


def png_bytes(seed: int) -> bytes:
    """A small, valid, distinct PNG (so real bytes differ per scenario)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    width = height = 8
    # (row = filter byte + width RGB pixels)
    rows = []
    for y in range(height):
        row = b"\x00"
        for x in range(width):
            row += bytes([(seed * 37 + x * 5 + y) % 256, (seed * 11 + y) % 256, (x * y + seed) % 256])
        rows.append(row)
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ---- VIR identity artifacts (captured real VIR -> PI map_resolution()) ---

_VIR_HANDOFFS = json.loads((Path(__file__).parent / "fixtures" / "vir_handoff_contexts.json").read_text())
HANDOFF_TOKEN = secrets.token_hex(16)  # per run; reaches PGDR only via its environment variable


def vir_identity(name: str = "peugeot_3008_ii_by_plate", **vehicle_overrides) -> dict:
    """A PGDR VehicleIdentityContext payload exactly as PI's map_resolution()
    produced it from a real VIR resolution (see the fixture's _provenance).
    Overrides only edit vehicle_identity fields, to model other VIR outcomes."""
    payload = copy.deepcopy(_VIR_HANDOFFS[name])
    payload["vehicle_identity"].update(vehicle_overrides)
    VehicleIdentityContext.model_validate(payload)
    return payload


def handoff(client, identity: dict | None = None, token: str | None = HANDOFF_TOKEN):
    """PI's role in these tests: hand the VIR identity artifact to PGDR."""
    headers = {"X-PGDR-Identity-Handoff-Token": token} if token is not None else {}
    return client.post("/api/photo/identity-handoff", json=identity or vir_identity(), headers=headers)


# ---- reference knowledge (TEST fixtures) --------------------------------

PEUGEOT_DOC = ManufacturerDocumentReference(
    manufacturer="Peugeot", document_id="9999_9999_326_en-GB",
    document_title="MY PEUGEOT 3008 / MY PEUGEOT 5008 HANDBOOK",
    source_authority=SourceAuthority.MANUFACTURER_OFFICIAL,
    source_locator="Peugeot Service Box, document 9999_9999_326_en-GB.pdf",
)


def _entry(entry_id, designation, colour, state, meaning):
    return DashboardReferenceEntry(
        entry_id=entry_id, manufacturer_designation=designation, colour=colour, state=state,
        documented_meaning=meaning, applicability=PEUGEOT_DOC,
    )


OIL = _entry("oil-pressure-warning", "Engine oil pressure", "red", IndicatorState.FIXED,
             "Fault with the engine lubrication system.")
ENGINE_FIXED = _entry("engine-diag-fixed", "Engine self-diagnostic system", "orange", IndicatorState.FIXED,
                      "Fault in the emissions control system.")
ENGINE_FLASHING = _entry("engine-diag-flashing", "Engine self-diagnostic system", "orange", IndicatorState.FLASHING,
                         "Fault in the engine management system.")
# SYNTHETIC, test-only (see module docstring) -- they carry no B2-R rule.
AIRBAG = _entry("test-airbag-warning", "Airbag / SRS warning", "red", IndicatorState.FIXED,
                "TEST-ONLY synthetic entry.")
BRAKE = _entry("test-brake-warning", "Brake system warning", "red", IndicatorState.FIXED,
               "TEST-ONLY synthetic entry.")
ALL_ENTRIES = [OIL, ENGINE_FIXED, ENGINE_FLASHING, AIRBAG, BRAKE]


class InMemoryKnowledgeRepository:
    """KnowledgeRepositoryPort test double: Peugeot 3008 II only."""

    def __init__(self):
        self._key = ("Peugeot", "3008", "II")

    def find_applicable_documents(self, vehicle: VehicleApplicabilityContext):
        key = (vehicle.manufacturer, vehicle.model, vehicle.generation)
        if key == self._key and PEUGEOT_DOC.lifecycle_status == KnowledgeLifecycleStatus.ACTIVE:
            return [PEUGEOT_DOC]
        return []

    def entries_for_document(self, document_id: str):
        return list(ALL_ENTRIES) if document_id == PEUGEOT_DOC.document_id else []

    def get_document_by_id(self, document_id: str):
        return PEUGEOT_DOC if document_id == PEUGEOT_DOC.document_id else None


# ---- deterministic provider ---------------------------------------------

def _result(media: ResolvedMedia, *, observation, status, entry_id=None, candidates=(), match_conf=None):
    return DashboardInterpretationResult(
        observation=observation, observation_confidence=Confidence.HIGH, match_status=status,
        matched_reference_entry_id=entry_id, candidate_reference_entry_ids=list(candidates),
        match_confidence=match_conf, identification=None,
        provenance=InterpretationProvenance(adapter_id=DETERMINISTIC_ADAPTER_ID, media_reference=media.reference),
    )


def match(entry: DashboardReferenceEntry, observation: str):
    return lambda media: _result(
        media, observation=observation, status=MatchStatus.MATCH, entry_id=entry.entry_id,
        match_conf=Confidence.HIGH,
    )


def ambiguous(candidates: list[DashboardReferenceEntry], observation: str = "Voyant orange, forme peu nette"):
    return lambda media: _result(
        media, observation=observation, status=MatchStatus.AMBIGUOUS_MATCH,
        candidates=[c.entry_id for c in candidates],
    )


def no_match(observation: str = "Voyant non répertorié"):
    return lambda media: _result(media, observation=observation, status=MatchStatus.NO_MATCH)


def insufficient(observation: str = "Image floue"):
    return lambda media: _result(media, observation=observation, status=MatchStatus.INSUFFICIENT_VISUAL_QUALITY)


class DeterministicDashboardProvider:
    """Implements DashboardInterpretationPort (structurally). Maps
    sha256(image bytes) -> scripted results, and records what it was handed
    so tests can prove the REAL uploaded bytes reached it."""

    def __init__(self):
        self._plans: dict[str, list] = {}
        self.calls: list[dict] = []

    def script(self, image_bytes: bytes, *result_factories) -> bytes:
        self._plans[sha(image_bytes)] = list(result_factories)
        return image_bytes

    def interpret(self, media: ResolvedMedia, reference_set):
        digest = sha(media.content)
        self.calls.append({
            "sha256": digest, "length": len(media.content), "media_reference": media.reference,
            "entry_ids": [e.entry_id for e in reference_set.entries],
        })
        if digest not in self._plans:
            raise AssertionError("deterministic provider received bytes it was not scripted for")
        return [factory(media) for factory in self._plans[digest]]


# ---- PGDR Part 1: the 11 REAL owner-attested Peugeot entries --------------
#
# Copied verbatim (by literal extraction) from PI's seed_peugeot_3008.py --
# see fixtures/peugeot_3008_manufacturer_entries.json `_provenance`. TEST
# FIXTURE ONLY: the manufacturer knowledge record lives in PI persistence.

_REAL = json.loads((Path(__file__).parent / "fixtures" / "peugeot_3008_manufacturer_entries.json").read_text(encoding="utf-8"))
REAL_DOC = ManufacturerDocumentReference(
    manufacturer=_REAL["document"]["manufacturer"], document_id=_REAL["document"]["document_id"],
    document_title=_REAL["document"]["document_title"], source_authority=SourceAuthority.MANUFACTURER_OFFICIAL,
    source_locator=_REAL["document"]["source_locator"],
)
REAL_ENTRIES = {
    raw["entry_id"]: DashboardReferenceEntry(applicability=REAL_DOC, **raw) for raw in _REAL["entries"]
}
REAL_ENTRY_IDS = list(REAL_ENTRIES)


class RealPeugeotKnowledgeRepository(InMemoryKnowledgeRepository):
    """KnowledgeRepositoryPort test double serving the 11 real attested
    entries (Peugeot 3008 II only)."""

    def find_applicable_documents(self, vehicle: VehicleApplicabilityContext):
        key = (vehicle.manufacturer, vehicle.model, vehicle.generation)
        return [REAL_DOC] if key == self._key else []

    def entries_for_document(self, document_id: str):
        return list(REAL_ENTRIES.values()) if document_id == REAL_DOC.document_id else []

    def get_document_by_id(self, document_id: str):
        return REAL_DOC if document_id == REAL_DOC.document_id else None
