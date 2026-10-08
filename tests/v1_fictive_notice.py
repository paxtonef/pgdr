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

from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository, content_fingerprint
from pgdr.application.part1_first_finding import entry_fingerprint

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


BELT_MEANING_FIXED = "The fictive belt light stays on while the fictive belt is open."
BELT_MEANING_FLASHING = "The fictive belt light flashes while the fictive vehicle moves with the belt open."
TWIN_COMMON = "Contact a fictive workshop when convenient."
TWIN_A = "The fictive twin symbol shows a fictive fault A. " + TWIN_COMMON
TWIN_B = "The fictive twin symbol shows a fictive fault B. " + TWIN_COMMON
MODE_X = "The fictive mode X is selected."
MODE_Y = "The fictive mode Y is active on the fictive display."
ALARM_A = "The fictive alarm light shows a fictive pressure loss."
ALARM_B = "The fictive alarm light shows a fictive service reminder."
ALARM_STOP = "If the fictive alarm light comes on while driving, stop the fictive vehicle immediately."
ALARM_STOP_PHRASE = "stop the fictive vehicle immediately"
CODE_A = "The fictive code symbol shows a fictive code fault. Contact a fictive workshop soon."
CODE_A_INSTRUCTION = "Contact a fictive workshop soon."
CODE_B = "The fictive code symbol comes on with a dedicated message to report a fictive intrusion attempt."
PRESSURE = ("The fictive pressure symbol shows that the fictive pressure is lower than the recommended value. "
            "In this case restore the fictive pressure value.")
PRESSURE_CONSIGNE = "restore the fictive pressure value"
FROST = "The fictive frost symbol comes on when the fictive outside air is cold."
STEER_A = "The fictive steering light stays on: fictive assistance may be reduced."
STEER_PROCEDURE = ("In this case, stop the fictive vehicle, stop the fictive motor for about 20 seconds "
                   "and then restart the fictive motor.")
STEER_CONDITION = "In some fictive circumstances, an independent factor could switch the light on."
STEER_INSTRUCTION = STEER_CONDITION + " " + STEER_PROCEDURE
STEER_MIXED = ("If the fictive steering light flashes, stop the fictive vehicle at once. "
               "Otherwise stop the fictive motor for about 20 seconds and then restart it.")
STEER_B = "The fictive steering light shows a fictive steering setup to do."
LAMP_FAULT = "The fictive lamp symbol shows a fault on the fictive stop lights."
TYRE_LOW = "The fictive tyre symbol shows that the fictive tyre pressure is lower than the recommended value."
TYRE_ACTION = "In this case restore the fictive tyre pressure."
TYRE_FAULT = "The fictive tyre symbol flashes to indicate that the fictive tyre system is temporarily deactivated or faulty."
TYRE_CONDITION = "The fictive system cannot indicate a sudden fictive tyre burst."
TYRE_STOP = "In this case, stop the fictive car, braking with caution and avoiding abrupt steering."
TYRE_WARNING = TYRE_CONDITION + " " + TYRE_STOP + " Low pressure reduces the fictive tyre life."
PB_TITLE = "FICTIVE PARKING BRAKE FAILURE / LOW BRAKE FLUID / PARKING BRAKE APPLIED"
PB_FAILURE = "The fictive light flashes when the fictive parking brake fails. Contact a fictive workshop."
PB_FLUID = "The fictive light comes on when the fictive brake fluid is below the minimum level."
PB_FLUID_WARNING = "If the fictive light comes on while driving, stop the fictive vehicle immediately and contact a fictive workshop."
PB_APPLIED = "The fictive light comes on when the fictive parking brake is applied."
LOOK_A = "The fictive look-alike symbol shows fictive message A."
LOOK_B = "The fictive look-alike symbol shows fictive message B."


def build(root: Path, *, applicability_established: bool = False, approve: bool = True,
          with_groups: bool = False) -> Path:
    """Writes the fictive package under `root` and returns the manifest path.
    with_groups adds: one identical-file group the notice tells apart by
    fixed/flashing, one identical-file group it does NOT tell apart, and two
    different files that look alike (displayed messages differ)."""
    (root / "images").mkdir(parents=True, exist_ok=True)
    files = {
        "manual.pdf": b"%PDF-1.4\n% FICTIVE manual for tests only\n%%EOF\n",
        "images/red.png": png((200, 0, 0)), "images/amber.png": png((230, 150, 0)),
        "images/green.png": png((0, 160, 0)), "images/white.png": png((240, 240, 240)),
        "images/picto.png": png((0, 0, 0), 4),
        "images/belt.png": png((180, 0, 0), 8), "images/twin.png": png((200, 140, 0), 8),
        "images/look_a.png": png((0, 120, 0), 8), "images/look_b.png": png((0, 121, 0), 8),
        "images/mode.png": png((0, 0, 200), 8), "images/alarm.png": png((210, 10, 10), 8),
        "images/code.png": png((220, 160, 0), 8),
        "images/pressure.png": png((225, 155, 0), 8), "images/frost.png": png((0, 130, 200), 8),
        "images/steer.png": png((190, 0, 0), 8), "images/lamp.png": png((228, 150, 0), 8),
        "images/tyre.png": png((232, 158, 0), 8), "images/pbrake.png": png((205, 5, 5), 8),
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
    if with_groups:
        entries += [
            entry("fx_red_belt_fixed", "FICTIVE BELT", "red", "images/belt.png", BELT_MEANING_FIXED, 4, state="fixed"),
            entry("fx_red_belt_flashing", "FICTIVE BELT", "red", "images/belt.png", BELT_MEANING_FLASHING, 4,
                  state="flashing",
                  field_sources={"state": {"text": "The fictive belt light flashes.", "printed_page": "F-4", "pdf_page": 4}}),
            entry("fx_amber_twin_a", "FICTIVE TWIN", "amber", "images/twin.png", TWIN_A, 5, state=None),
            entry("fx_amber_twin_b", "FICTIVE TWIN", "amber", "images/twin.png", TWIN_B, 5, state=None),
            entry("fx_green_look_a", "FICTIVE LOOK", "green", "images/look_a.png", LOOK_A, 6, state=None,
                  displayed_message="LOOK A"),
            entry("fx_green_look_b", "FICTIVE LOOK", "green", "images/look_b.png", LOOK_B, 6, state=None,
                  displayed_message="LOOK B"),
            # Identical file, nothing distinctive, NO common text (designations differ too); informative.
            entry("fx_blue_mode_x", "FICTIVE MODE X", "blue", "images/mode.png", MODE_X, 7, state=None),
            entry("fx_blue_mode_y", "FICTIVE MODE Y", "blue", "images/mode.png", MODE_Y, 8, state=None),
            # Identical file, red, nothing distinctive; only variant A carries a stop instruction (warning 9).
            entry("fx_red_alarm_a", "FICTIVE ALARM", "red", "images/alarm.png", ALARM_A, 9, state="flashing",
                  linked_warnings=[{"number": "9)", "text": ALARM_STOP, "printed_page": "F-10", "pdf_page": 10,
                                    "inline_pictograms": []}]),
            entry("fx_red_alarm_b", "FICTIVE ALARM", "red", "images/alarm.png", ALARM_B, 9, state="flashing"),
            # Identical file, nothing distinctive; only variant B speaks of a (non documented) message.
            entry("fx_amber_code_a", "FICTIVE CODE FAULT", "amber", "images/code.png", CODE_A, 11, state=None,
                  documented_instruction=CODE_A_INSTRUCTION),
            entry("fx_amber_code_b", "FICTIVE INTRUSION", "amber", "images/code.png", CODE_B, 11, state=None),
            # A state without failure term (one instruction), an event without any instruction.
            entry("fx_amber_pressure", "FICTIVE PRESSURE", "amber", "images/pressure.png", PRESSURE, 12,
                  documented_instruction="In this case restore the fictive pressure value."),
            entry("fx_blue_frost", "FICTIVE FROST", "blue", "images/frost.png", FROST, 12),
            # Identical file; variant A documents a temporary stop + wait + restart procedure, and
            # (warning 3) a mixed passage whose immediate stop must stay urgent.
            entry("fx_red_steer_a", "FICTIVE STEERING FAILURE", "red", "images/steer.png", STEER_A, 13, state=None,
                  documented_instruction=STEER_INSTRUCTION,
                  linked_warnings=[{"number": "3)", "text": STEER_MIXED, "printed_page": "F-14", "pdf_page": 14,
                                    "inline_pictograms": []}]),
            entry("fx_red_steer_b", "FICTIVE STEERING FAILURE", "red", "images/steer.png", STEER_B, 13, state=None),
            # « stop lights » is never a stop instruction.
            entry("fx_amber_lamp_fault", "FICTIVE LAMP FAULT", "amber", "images/lamp.png", LAMP_FAULT, 15),
            # Identical file: an under-inflation state (expected action) and a system fault, both with
            # the same CONDITIONAL stop instruction (warning 5), shown apart from the type.
            entry("fx_amber_tyre_low", "FICTIVE TYRES", "amber", "images/tyre.png", TYRE_LOW + " " + TYRE_ACTION, 16,
                  state=None, documented_instruction=TYRE_ACTION,
                  linked_warnings=[{"number": "5)", "text": TYRE_WARNING, "printed_page": "F-17", "pdf_page": 17,
                                    "inline_pictograms": []}]),
            # Identical file, red: parking brake failure / low brake fluid (immediate stop, warning 8) / applied.
            entry("fx_red_pb_failure", PB_TITLE, "red", "images/pbrake.png", PB_FAILURE, 18, state=None),
            entry("fx_red_pb_fluid", PB_TITLE, "red", "images/pbrake.png", PB_FLUID, 18, state=None,
                  linked_warnings=[{"number": "8)", "text": PB_FLUID_WARNING, "printed_page": "F-19", "pdf_page": 19,
                                    "inline_pictograms": []}]),
            entry("fx_red_pb_applied", PB_TITLE, "red", "images/pbrake.png", PB_APPLIED, 18, state=None),
            entry("fx_amber_tyre_fault", "FICTIVE TYRES", "amber", "images/tyre.png", TYRE_FAULT, 16, state=None,
                  linked_warnings=[{"number": "5)", "text": TYRE_WARNING, "printed_page": "F-17", "pdf_page": 17,
                                    "inline_pictograms": []}]),
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


STOP_PHRASE = "stop the fictive vehicle in a safe place"
CONTACT_PHRASE = "contact a fictive workshop"


def build_findings(manifest: Path, *, status: str = "VALIDE", approved_by: str = "Fictive Owner") -> Path:
    """FICTIVE structured classification (Part 1 mapping format) of the
    fictive notice: the red entry's linked warning 7) carries a stop
    instruction and a contact instruction. Amber/green/white: no record
    (every structured field « non établi »)."""
    repo = ManifestNoticeRepository(manifest)
    live = {e.entry_id: e for e in repo.entries_for_document("FICTIVE-NOTICE-001")}
    records = [{
        "document_id": "FICTIVE-NOTICE-001", "entry_id": "fx_red_fluid",
        "fingerprint": entry_fingerprint(live["fx_red_fluid"]),
        "items": {
            "stop_vehicle_engine_off": {"value": "required", "basis": "documented",
                                        "source_field": "linked_warnings", "source_phrase": STOP_PHRASE},
            "professional_attention": {"value": "required", "basis": "documented",
                                       "source_field": "linked_warnings", "source_phrase": CONTACT_PHRASE},
            "documented_suitability": {"value": "a fictive workshop", "basis": "documented",
                                       "source_field": "linked_warnings", "source_phrase": "a fictive workshop"},
        },
    }]
    if "fx_red_alarm_a" in live:
        records.append({"document_id": "FICTIVE-NOTICE-001", "entry_id": "fx_red_alarm_a",
                        "fingerprint": entry_fingerprint(live["fx_red_alarm_a"]),
                        "items": {"stop_vehicle_engine_off": {"value": "required", "basis": "documented",
                                                              "source_field": "linked_warnings",
                                                              "source_phrase": ALARM_STOP_PHRASE}}})
    doc = {
        "header": {"status": status, "approved_by": approved_by, "approval_date": "2026-10-07",
                   "nature": "FICTIVE derivation layer for tests", "catalogue_content_sha256": repo.catalogue.content_sha256,
                   "covered_entry_ids": [e.entry_id for e in repo.catalogue.entries]},
        "rules": {r: "fictive" for r in ("R-1", "R-2", "R-3", "R-4", "R-5")},
        "entries": records,
    }
    path = manifest.parent / "classement.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def build_groups(manifest: Path, *, status: str = "VALIDE", validated_by: str = "Fictive Owner") -> Path:
    """FICTIVE groups file: the two look-alike images with different files."""
    repo = ManifestNoticeRepository(manifest)
    doc = {"header": {"status": status, "validated_by": validated_by, "validated_on": "2026-10-08",
                      "catalogue_content_sha256": repo.catalogue.content_sha256},
           "groups": [{"entry_ids": ["fx_green_look_a", "fx_green_look_b"], "note": "fictive look-alikes"}]}
    path = manifest.parent / "groupes.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


EXPLANATION_RED = {
    "indique": [{"texte": "La notice fictive associe ce voyant à un niveau de liquide fictif bas.",
                 "source_field": "documented_meaning", "source_phrase": "when the fictive brake fluid is low"}],
    "maintenant": [{"texte": "La note 7) demande d'arrêter le véhicule fictif dans un endroit sûr.",
                    "source_field": "linked_warnings", "source_phrase": STOP_PHRASE},
                   {"texte": "Elle demande aussi de contacter un atelier fictif.",
                    "source_field": "linked_warnings", "source_phrase": CONTACT_PHRASE}],
    "inconnu": [{"texte": "La notice fictive n'indique pas la cause du niveau bas.",
                 "source_field": "documented_meaning", "source_phrase": "the fictive brake fluid is low"}],
}
EXPLANATION_GREEN = {
    "indique": [{"texte": "Ce voyant fictif indique que les feux fictifs sont allumés.",
                 "source_field": "documented_meaning", "source_phrase": "the fictive lamps are on"}],
    "maintenant": [{"texte": "Le passage fictif ne donne pas de consigne pour ce voyant.",
                    "source_field": "documented_meaning", "source_phrase": GREEN_MEANING}],
    "inconnu": [{"texte": "Rien d'autre n'est précisé par ce passage fictif.",
                 "source_field": "documented_meaning", "source_phrase": GREEN_MEANING}],
}


def build_explanations(manifest: Path, *, status: str = "BROUILLON_NON_VALIDE", validated_by: str = "",
                       entries: dict | None = None) -> Path:
    repo = ManifestNoticeRepository(manifest)
    header = {"status": status, "catalogue_content_sha256": repo.catalogue.content_sha256}
    if validated_by:
        header.update(validated_by=validated_by, validated_on="2026-10-08")
    doc = {"header": header,
           "entries": entries if entries is not None else {"fx_red_fluid": EXPLANATION_RED, "fx_green_lamps": EXPLANATION_GREEN}}
    path = manifest.parent / "explications.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def situation(nature: str, phrase: str, field: str = "documented_meaning", *, consignes=(), conditions=(),
              intitule: str | None = None) -> dict:
    """consignes: (phrase, field, condition_phrase_or_None, condition_field[, presentation]) tuples."""
    d = {"nature": nature, "justification": {"source_field": field, "source_phrase": phrase},
         "consignes": [{"source_field": c[1], "source_phrase": c[0],
                        **({"condition": {"source_field": c[3], "source_phrase": c[2]}} if c[2] else {}),
                        **({"presentation": c[4]} if len(c) > 4 else {})}
                       for c in consignes],
         "conditions": [{"source_field": f, "source_phrase": ph} for ph, f in conditions]}
    if intitule:
        d["intitule"] = intitule
    return d


SITUATIONS = {
    "fx_green_lamps": situation("fonctionnement_normal", "the fictive lamps are on", intitule="Feux fictifs allumés"),
    "fx_blue_mode_x": situation("fonctionnement_normal", "The fictive mode X is selected.", intitule="Mode X fictif choisi"),
    "fx_blue_mode_y": situation("fonctionnement_normal", "The fictive mode Y is active", intitule="Mode Y fictif actif"),
    "fx_red_belt_fixed": situation("action_conducteur", "while the fictive belt is open", intitule="Ceinture fictive ouverte"),
    "fx_red_belt_flashing": situation("action_conducteur", "while the fictive vehicle moves with the belt open",
                                      intitule="Ceinture fictive ouverte en roulant"),
    "fx_red_alarm_a": situation("alerte_consigne_immediate", "a fictive pressure loss",
                                consignes=[(ALARM_STOP_PHRASE, "linked_warnings",
                                            "If the fictive alarm light comes on while driving", "linked_warnings")],
                                intitule="Perte de pression fictive"),
    "fx_red_alarm_b": situation("action_conducteur", "a fictive service reminder", intitule="Rappel d'entretien fictif"),
    "fx_amber_code_a": situation("anomalie_defaut", "a fictive code fault",
                                 consignes=[(CODE_A_INSTRUCTION, "documented_instruction", None, None)],
                                 intitule="Défaut du code fictif"),
    "fx_amber_pressure": situation("information_a_prendre_en_compte", "the fictive pressure is lower than the recommended value",
                                   consignes=[(PRESSURE_CONSIGNE, "documented_instruction", "In this case", "documented_instruction")],
                                   intitule="Pression fictive basse"),
    "fx_blue_frost": situation("information_a_prendre_en_compte", "when the fictive outside air is cold",
                               intitule="Air extérieur fictif froid"),
    "fx_red_steer_a": situation("situation_non_determinee", "fictive assistance may be reduced",
                                consignes=[(STEER_PROCEDURE, "documented_instruction", STEER_CONDITION, "documented_instruction"),
                                           ("stop the fictive vehicle at once", "linked_warnings",
                                            "If the fictive steering light flashes", "linked_warnings")],
                                intitule="Assistance fictive peut-être réduite"),
    "fx_amber_lamp_fault": situation("anomalie_defaut", "a fault on the fictive stop lights", intitule="Défaut d'un feu fictif"),
    "fx_amber_tyre_low": situation("information_a_prendre_en_compte", "the fictive tyre pressure is lower than the recommended value",
                                   consignes=[("restore the fictive tyre pressure", "documented_instruction", None, None, "action_attendue"),
                                              ("stop the fictive car", "linked_warnings", TYRE_CONDITION, "linked_warnings")],
                                   intitule="Pression fictive des pneus basse"),
    "fx_amber_tyre_fault": situation("anomalie_defaut", "temporarily deactivated or faulty",
                                     consignes=[(TYRE_STOP, "linked_warnings", TYRE_CONDITION, "linked_warnings")],
                                     intitule="Système fictif des pneus désactivé ou en défaut"),
    "fx_red_pb_failure": situation("anomalie_defaut", "the fictive parking brake fails",
                                   consignes=[("Contact a fictive workshop.", "documented_meaning", None, None)],
                                   intitule="Défaut du frein de stationnement fictif"),
    "fx_red_pb_fluid": situation("alerte_consigne_immediate", "the fictive brake fluid is below the minimum level",
                                 consignes=[("stop the fictive vehicle immediately and contact a fictive workshop", "linked_warnings",
                                             "If the fictive light comes on while driving", "linked_warnings")],
                                 intitule="Liquide de frein fictif bas"),
    "fx_red_pb_applied": situation("fonctionnement_normal", "the fictive parking brake is applied",
                                   intitule="Frein de stationnement fictif serré"),
    "fx_red_steer_b": situation("action_conducteur", "a fictive steering setup to do", intitule="Réglage fictif à faire"),
    "fx_amber_code_b": situation("situation_non_determinee", "to report a fictive intrusion attempt",
                                 conditions=[("comes on with a dedicated message", "documented_meaning")],
                                 intitule="Possible tentative d'intrusion fictive"),
}


def build_situations(manifest: Path, *, status: str = "BROUILLON_NON_VALIDE", validated_by: str = "",
                     entries: dict | None = None) -> Path:
    repo = ManifestNoticeRepository(manifest)
    known = {e.entry_id for e in repo.catalogue.entries}
    header = {"status": status, "catalogue_content_sha256": repo.catalogue.content_sha256}
    if validated_by:
        header.update(validated_by=validated_by, validated_on="2026-10-08")
    doc = {"header": header,
           "entries": entries if entries is not None else {k: v for k, v in SITUATIONS.items() if k in known}}
    path = manifest.parent / "situations.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
