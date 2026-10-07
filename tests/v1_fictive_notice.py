"""A FICTIVE notice package for the V1 parcours tests. Every text, image and
identifier here is invented; nothing comes from a real manufacturer manual.
The package is written to a temporary directory at test time, never to the
repository."""
from __future__ import annotations

import hashlib
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from pgdr.adapters.manifest_notice_repository import content_fingerprint

VEHICLE = {"manufacturer": "Fictiva", "model": "Testmobile", "generation": "X1"}
VIR_IDENTITY = {"manufacturer": "Fictiva", "model": "Testmobile", "generation": "X1"}

SHARED_WARNING = ("If the fictive light stays on, stop the fictive vehicle in a safe place "
                  "and contact a fictive workshop.")
RED_MEANING = "The fictive red light switches on when the fictive brake fluid is low."
RED_STARTUP = "The fictive red light switches on at fictive start-up and goes off after a few seconds."
AMBER_MEANING = "The fictive amber symbol means a fictive sensor fault."
GREEN_MEANING = "The fictive green light shows that the fictive lamps are on."
WHITE_MEANING = "The fictive white symbol shows the fictive cruise mode."


def png(rgb: tuple[int, int, int], size: int = 6) -> bytes:
    """A valid, minimal solid-colour PNG (no imaging library needed)."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _picto(text: str, pos: int, image: str, digest: str, ids: list[str]) -> dict:
    return {"position": pos, "text_before": text[:pos][-10:], "text_after": text[pos:].lstrip()[:10],
            "image_file": image, "image_sha256": digest, "pdf_page": 2, "printed_page": "F-2",
            "identified_entry_ids": ids, "identification_basis": "Same fictive drawing as the red entry."}


def build(root: Path, *, applicability_established: bool = False, approve: bool = True) -> Path:
    """Writes the fictive package under `root` and returns the manifest path."""
    (root / "images").mkdir(parents=True, exist_ok=True)
    files = {
        "manual.pdf": b"%PDF-1.4\n% FICTIVE manual for tests only\n%%EOF\n",
        "images/red.png": png((200, 0, 0)), "images/amber.png": png((230, 150, 0)),
        "images/green.png": png((0, 160, 0)), "images/white.png": png((240, 240, 240)),
        "images/picto.png": png((0, 0, 0), 4),
    }
    for name, data in files.items():
        (root / name).write_bytes(data)
    h = {name: sha(data) for name, data in files.items()}

    def entry(entry_id, designation, colour, image, meaning, page, **extra):
        e = {"entry_id": entry_id, "manufacturer_designation": designation, "symbol_descriptor": None,
             "colour": colour, "state": "fixed", "displayed_message": None, "audible_signal": None,
             "documented_meaning": meaning, "documented_instruction": None, "combined_with_entry_ids": [],
             "image_file": image, "image_sha256": h[image], "pdf_page": page, "page_reference": f"F-{page}",
             "where_provided": False, "documented_startup_check": None, "linked_warnings": [],
             "inline_pictograms": [], "notes": [], "field_sources": {}}
        e.update(extra)
        return e

    warning = {"number": "7)", "text": SHARED_WARNING, "printed_page": "F-2", "pdf_page": 2,
               "inline_pictograms": [_picto(SHARED_WARNING, 6, "images/picto.png", h["images/picto.png"], ["fx_red_fluid"])]}
    entries = [
        entry("fx_red_fluid", "FICTIVE LOW FLUID", "red", "images/red.png", RED_MEANING, 1,
              documented_instruction="Stop the fictive vehicle.", where_provided=True,
              documented_startup_check=RED_STARTUP, linked_warnings=[warning],
              inline_pictograms=[_picto(RED_MEANING, 10, "images/picto.png", h["images/picto.png"], ["fx_red_fluid"])],
              notes=["Fictive curation note."],
              field_sources={"audible_signal": {"text": "A fictive chime sounds.", "printed_page": "F-3", "pdf_page": 3}},
              audible_signal="A fictive chime sounds."),
        entry("fx_amber_sensor", "FICTIVE SENSOR FAULT", "amber", "images/amber.png", AMBER_MEANING, 2,
              linked_warnings=[dict(warning, inline_pictograms=list(warning["inline_pictograms"]))]),
        entry("fx_green_lamps", "FICTIVE LAMPS ON", "green", "images/green.png", GREEN_MEANING, 2),
        entry("fx_white_cruise", "FICTIVE CRUISE", "white", "images/white.png", WHITE_MEANING, 3, where_provided=True),
    ]
    d = {"schema_version": 2, "document_id": "FICTIVE-NOTICE-001", "title": "FICTIVE OWNER HANDBOOK",
         "edition": "Fictive edition 1", "source_authority": "manufacturer_official",
         "source_locator": "fictive fixture only", "vehicle": dict(VEHICLE),
         "applicability_period_start": None, "applicability_period_end": None, "applicability_period_note": None,
         "manual_file": "manual.pdf", "manual_sha256": h["manual.pdf"], "language": "en",
         "applicability_vehicle_under_review": {"applicability_established": applicability_established},
         "entries": entries}
    d["review"] = {"status": "pending", "reviewer_id": "", "reviewer_name": "", "reviewed_at": "", "content_sha256": ""}
    if approve:
        approve_manifest(d)
    path = root / "manifest.yaml"
    save(path, d)
    return path


def approve_manifest(d: dict) -> None:
    d["review"] = {"status": "approved", "reviewer_id": "fictive-reviewer", "reviewer_name": "Fictive Reviewer",
                   "reviewed_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                   "content_sha256": content_fingerprint(d)}


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def save(path: Path, d: dict) -> None:
    path.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
