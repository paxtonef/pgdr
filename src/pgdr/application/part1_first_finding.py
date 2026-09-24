"""PGDR Part 1 — Manufacturer First Finding (Execution Mandate v0.2 FINAL).

Three pure, deterministic pieces:

  * load_part1_mapping(): loads and validates the PGDR derivation/rule layer
    (config/part1_manufacturer_findings.yaml, §4). Fail-closed: any
    structural or rule inconsistency raises ConfigurationError.
  * build_manufacturer_first_finding(): per identified manufacturer entry,
    combines the LIVE manufacturer record (the DashboardReferenceEntry that
    reached PGDR through PI) with that layer. Manufacturer text is always
    read from the live record, never from the mapping (knowledge boundary).
  * compose_triage(): R-5, the bounded composition that may RAISE the
    SafetyEngine result and never lower it (D-C4). SafetyEngine itself is
    not modified and not re-run here.

Knowledge boundary (§4): the mapping is a governed derivation layer over
manufacturer knowledge, NOT a manufacturer knowledge store. It holds only
item values, bases, rule ids, verbatim phrase anchors, the fixed T6
{meaning} strings and a fingerprint binding each record to the exact source
text. A fingerprint mismatch turns the whole entry NOT_ESTABLISHED.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

import yaml

from pgdr.domain.dashboard_knowledge import DashboardReferenceEntry
from pgdr.enums import (
    DrivingAssessment, FindingBasis, ImmediateRequirement, ManufacturerOperability, PracticalRequirement,
    TriageLevel,
)
from pgdr.errors import ConfigurationError
from pgdr.safety_engine import _severity_rank as _safety_engine_severity_rank
from pgdr.models import (
    FINDING_SOURCE_FIELDS, DocumentedFigure, DocumentedPhrase, EntryFinding, FindingItem, FindingProvenance,
    ManufacturerFirstFinding, PracticalAssistanceRequirement, SafetyTriage,
)

MAPPING_PATH = Path(__file__).resolve().parent.parent / "config" / "part1_manufacturer_findings.yaml"

RULE_IDS = ("R-1", "R-2", "R-3", "R-4", "R-5")
# Only R-1 and R-2 ever produce a stored DERIVED value. R-3/R-4 explain why
# nothing is derived (review notes only); R-5 is the triage composition.
_STORABLE_RULES = {"R-1", "R-2"}
WITHOUT_DELAY = "without delay"

# Items of the per-entry mapping, and their allowed values (§3).
_IMMEDIATE = {v.value for v in ImmediateRequirement}
ITEM_VALUE_SETS: dict[str, Optional[set[str]]] = {
    "stop_vehicle_engine_off": _IMMEDIATE,
    "vehicle_immobilization": _IMMEDIATE,
    "exit_vehicle": _IMMEDIATE,
    "move_away_from_vehicle": _IMMEDIATE,
    "environment_dependent_requirement": _IMMEDIATE,
    "operability": {v.value for v in ManufacturerOperability},
    # Documented value = the verbatim phrase itself (None = free phrase).
    "max_speed": None,
    "max_distance": None,
    "max_duration": None,
    "professional_attention": _IMMEDIATE,
    "urgency_phrase": None,
    "documented_suitability": None,
    "practical_assistance": {v.value for v in PracticalRequirement},
}
_MAY_DRIVE = {ManufacturerOperability.MAY_DRIVE.value, ManufacturerOperability.MAY_DRIVE_WITH_RESTRICTIONS.value}


# ---------------------------------------------------------------------------
# Fingerprint (§4 rule 1)
# ---------------------------------------------------------------------------

def entry_fingerprint(entry: DashboardReferenceEntry) -> str:
    """sha256 over document_id | entry_id | documented_meaning |
    documented_instruction | displayed_message (absent field = "")."""
    parts = [
        entry.applicability.document_id, entry.entry_id, entry.documented_meaning,
        entry.documented_instruction or "", entry.displayed_message or "",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Mapping loader (§4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MappingRecord:
    document_id: str
    entry_id: str
    fingerprint: str
    items: Mapping[str, FindingItem]
    stop_conditions: tuple[DocumentedPhrase, ...]
    documented_figures: tuple[DocumentedFigure, ...]


Part1Mapping = Mapping[tuple[str, str], MappingRecord]


def _fail(where: str, message: str) -> ConfigurationError:
    return ConfigurationError(f"part1_manufacturer_findings.yaml {where}: {message}")


def _item(where: str, name: str, raw: dict) -> FindingItem:
    if not isinstance(raw, dict):
        raise _fail(where, f"{name} must be a mapping")
    unknown = set(raw) - {"value", "basis", "rule_id", "source_field", "source_phrase"}
    if unknown:
        raise _fail(where, f"{name}: unknown keys {sorted(unknown)}")
    try:
        item = FindingItem(
            value=raw.get("value"), basis=FindingBasis(raw.get("basis")), rule_id=raw.get("rule_id"),
            source_field=raw.get("source_field"), source_phrase=raw.get("source_phrase"),
        )
    except (ValueError, TypeError) as exc:
        raise _fail(where, f"{name}: {exc}") from None
    if item.basis == FindingBasis.NOT_ESTABLISHED:
        raise _fail(where, f"{name}: NOT_ESTABLISHED items are omitted, never stored")
    allowed = ITEM_VALUE_SETS[name]
    if allowed is not None and item.value not in allowed:
        raise _fail(where, f"{name}: invalid value {item.value!r}")
    if allowed is None and item.value != item.source_phrase:
        raise _fail(where, f"{name}: a documented phrase item's value must be its verbatim source_phrase")
    if item.basis == FindingBasis.DERIVED and item.rule_id not in _STORABLE_RULES:
        raise _fail(where, f"{name}: rule_id {item.rule_id!r} cannot produce a stored value (only R-1/R-2)")
    if name == "operability" and item.value in _MAY_DRIVE and item.basis != FindingBasis.DOCUMENTED:
        raise _fail(where, "MAY_DRIVE* may only be DOCUMENTED (Decision 1 / PGDR-INV-003 / D-C1)")
    return item


def _check_rule_consistency(where: str, items: Mapping[str, FindingItem]) -> None:
    def val(name: str) -> str:
        return items[name].value if name in items else "not_established"

    for name, item in items.items():
        if item.rule_id == "R-1":
            if (name, item.value) not in {("operability", "do_not_drive"), ("vehicle_immobilization", "required")}:
                raise _fail(where, f"R-1 cannot produce {name}={item.value}")
            svo = items.get("stop_vehicle_engine_off")
            if svo is None or svo.basis != FindingBasis.DOCUMENTED:
                raise _fail(where, "R-1 requires a DOCUMENTED stop_vehicle_engine_off")
        elif item.rule_id == "R-2":
            if (name, item.value) != ("practical_assistance", "towing_required"):
                raise _fail(where, f"R-2 cannot produce {name}={item.value}")
            if val("operability") not in ("do_not_drive", "starting_prevented"):
                raise _fail(where, "R-2 requires operability DO_NOT_DRIVE or STARTING_PREVENTED")
            if val("professional_attention") != "required":
                raise _fail(where, "R-2 requires professional_attention REQUIRED")


def load_part1_mapping(path: Path | str = MAPPING_PATH) -> Part1Mapping:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"part1_manufacturer_findings.yaml unreadable: {exc}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        raise _fail("root", "missing 'entries' list")
    header = raw.get("header") or {}
    for key in ("approved_by", "approval_date", "nature"):
        if not header.get(key):
            raise _fail("header", f"missing {key}")
    if list(raw.get("rules") or {}) != list(RULE_IDS):
        raise _fail("rules", f"must declare exactly {list(RULE_IDS)}")

    records: dict[tuple[str, str], MappingRecord] = {}
    for idx, rec in enumerate(raw["entries"]):
        where = f"entries[{idx}]"
        try:
            key = (str(rec["document_id"]), str(rec["entry_id"]))
            fingerprint = str(rec["fingerprint"])
        except (KeyError, TypeError):
            raise _fail(where, "document_id, entry_id and fingerprint are required") from None
        where = f"{where} ({key[1]})"
        if key in records:
            raise _fail(where, "duplicate record")
        unknown = set(rec) - {"document_id", "entry_id", "fingerprint", "items", "stop_conditions", "documented_figures"}
        if unknown:
            raise _fail(where, f"unknown keys {sorted(unknown)}")
        raw_items = rec.get("items") or {}
        unknown_items = set(raw_items) - set(ITEM_VALUE_SETS)
        if unknown_items:
            raise _fail(where, f"unknown items {sorted(unknown_items)}")
        items = {name: _item(where, name, value) for name, value in raw_items.items()}
        _check_rule_consistency(where, items)

        stop_conditions = []
        for sc in rec.get("stop_conditions") or []:
            try:
                stop_conditions.append(DocumentedPhrase(source_field=sc["source_field"], source_phrase=sc["source_phrase"]))
            except (KeyError, TypeError, ValueError):
                raise _fail(where, "stop_conditions entries need source_field and source_phrase") from None
        figures = []
        for fg in rec.get("documented_figures") or []:
            try:
                figures.append(DocumentedFigure(
                    source_field=fg["source_field"], source_phrase=fg["source_phrase"], meaning=fg["meaning"],
                    caution=bool(fg["caution"]),
                ))
            except (KeyError, TypeError, ValueError):
                raise _fail(where, "documented_figures entries need source_field, source_phrase, meaning, caution") from None
        for phrase in [*stop_conditions, *figures]:
            if phrase.source_field not in FINDING_SOURCE_FIELDS:
                raise _fail(where, f"unknown source_field {phrase.source_field!r}")
        # R-4, structurally: a figure never populates a distance/duration limit.
        figure_phrases = {f.source_phrase for f in figures}
        for limit in ("max_distance", "max_duration"):
            if limit in items and items[limit].source_phrase in figure_phrases:
                raise _fail(where, f"R-4: a documented figure cannot populate {limit}")

        records[key] = MappingRecord(
            document_id=key[0], entry_id=key[1], fingerprint=fingerprint, items=items,
            stop_conditions=tuple(stop_conditions), documented_figures=tuple(figures),
        )
    return records


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _check_phrases(record: MappingRecord, entry: DashboardReferenceEntry) -> None:
    """§4 rule 2 against the LIVE record: every anchor must be an exact
    substring of its source field. Fail closed."""
    anchors = [(n, i.source_field, i.source_phrase) for n, i in record.items.items()]
    anchors += [("stop_condition", p.source_field, p.source_phrase) for p in record.stop_conditions]
    anchors += [("documented_figure", f.source_field, f.source_phrase) for f in record.documented_figures]
    for name, field, phrase in anchors:
        text = getattr(entry, field) or ""
        if phrase not in text:
            raise ConfigurationError(
                f"part1_manufacturer_findings.yaml ({record.entry_id}): {name} source_phrase {phrase!r} "
                f"is not a substring of the live {field}"
            )


def build_entry_finding(
    entry: DashboardReferenceEntry, *, identification_origin: str, mapping: Part1Mapping,
) -> EntryFinding:
    document = entry.applicability
    record = mapping.get((document.document_id, entry.entry_id))
    audit_flags: list[str] = []
    fingerprint_match = record is not None and record.fingerprint == entry_fingerprint(entry)
    if record is None:
        audit_flags.append("no_mapping_record")
    elif not fingerprint_match:
        audit_flags.append("mapping_fingerprint_mismatch")
        record = None  # a stale interpretation never survives a source change
    else:
        _check_phrases(record, entry)

    def item(name: str) -> FindingItem:
        if record is None or name not in record.items:
            return FindingItem.not_established()
        return record.items[name]

    practical = item("practical_assistance")
    suitability = item("documented_suitability")
    urgency = item("urgency_phrase")
    return EntryFinding(
        provenance=FindingProvenance(
            document_id=document.document_id, document_title=document.document_title,
            source_authority=document.source_authority.value, freshness_status=document.freshness_status.value,
            entry_id=entry.entry_id, manufacturer_designation=entry.manufacturer_designation,
            colour=entry.colour, state=entry.state.value if entry.state else None,
            identification_origin=identification_origin, mapping_fingerprint_match=fingerprint_match,
        ),
        manufacturer_designation=entry.manufacturer_designation,
        documented_meaning=entry.documented_meaning,
        documented_instruction=entry.documented_instruction,
        displayed_message=entry.displayed_message,
        combined_with_entry_ids=list(entry.combined_with_entry_ids),
        stop_vehicle_engine_off=item("stop_vehicle_engine_off"),
        vehicle_immobilization=item("vehicle_immobilization"),
        exit_vehicle=item("exit_vehicle"),
        move_away_from_vehicle=item("move_away_from_vehicle"),
        environment_dependent_requirement=item("environment_dependent_requirement"),
        operability=item("operability"),
        max_speed=item("max_speed"),
        max_distance=item("max_distance"),
        max_duration=item("max_duration"),
        stop_conditions=list(record.stop_conditions) if record else [],
        documented_figures=list(record.documented_figures) if record else [],
        professional_attention=item("professional_attention"),
        urgency_phrase=urgency,
        documented_suitability=suitability,
        practical_assistance=PracticalAssistanceRequirement(
            requirement=practical, documented_suitability=suitability, urgency_phrase=urgency,
            precise_location_needed=practical.value in (
                PracticalRequirement.GARAGE_REQUIRED.value, PracticalRequirement.TOWING_REQUIRED.value,
            ),
        ),
        audit_flags=audit_flags,
    )


def build_manufacturer_first_finding(
    identified: Iterable[tuple[DashboardReferenceEntry, str]], *, mapping: Part1Mapping,
) -> ManufacturerFirstFinding:
    """`identified`: (live manufacturer entry, identification origin) pairs,
    in identification order. Origin is 'visual_provider_match' or
    'user_selection' (never merged)."""
    return ManufacturerFirstFinding(entries=[
        build_entry_finding(entry, identification_origin=origin, mapping=mapping) for entry, origin in identified
    ])


# ---------------------------------------------------------------------------
# R-5 — monotonic triage composition (D-C4)
# ---------------------------------------------------------------------------

def severity_rank(level: TriageLevel) -> int:
    """The existing SafetyEngine severity order (never redefined here)."""
    return _safety_engine_severity_rank(level)


@dataclass(frozen=True)
class R5Row:
    """One applicable row of the §9 R-5 table."""
    level: TriageLevel
    sets_do_not_drive: bool
    sets_roadside: bool
    label: str          # traceability: which row, for which entry


def r5_rows(finding: ManufacturerFirstFinding) -> list[R5Row]:
    rows: list[R5Row] = []
    for e in finding.entries:
        eid = e.provenance.entry_id
        if e.stop_vehicle_engine_off.value == ImmediateRequirement.REQUIRED.value:
            rows.append(R5Row(TriageLevel.EMERGENCY_STOP, True, True, f"R-5:stop_vehicle_engine_off:{eid}"))
        elif e.operability.value == ManufacturerOperability.DO_NOT_DRIVE.value:
            rows.append(R5Row(TriageLevel.DO_NOT_DRIVE, True, True, f"R-5:operability_do_not_drive:{eid}"))
        elif (e.professional_attention.value == ImmediateRequirement.REQUIRED.value
              and e.urgency_phrase.value == WITHOUT_DELAY):
            rows.append(R5Row(TriageLevel.PROMPT_INSPECTION, False, False, f"R-5:professional_without_delay:{eid}"))
    return rows


def compose_triage(
    engine: SafetyTriage, finding: ManufacturerFirstFinding, *, raised_instruction: Mapping[str, str] | None = None,
) -> tuple[SafetyTriage, list[str]]:
    """R-5. Returns (composed triage, applied row labels).

    Component-wise, never lowering:
      level               = max(engine.level, rows' levels)
      driving_assessment  = DO_NOT_DRIVE if a row sets it, else engine's
      roadside_assistance = engine's OR a row's
      emergency_services  = engine's, always (R-5 never writes it)
    When (and only when) R-5 raises the LEVEL, the SafetyEngine default
    wording no longer describes the result, so user_instruction is replaced
    by the approved §7.1 label of the winning row (`raised_instruction`,
    keyed by the row kind); the engine's reasons and triggered rules are
    kept and the applied R-5 row is appended to both."""
    rows = r5_rows(finding)
    if not rows:
        return engine, []
    top = max(rows, key=lambda r: severity_rank(r.level))
    raised = severity_rank(top.level) > severity_rank(engine.level)
    composed = engine.model_copy(deep=True)
    if raised:
        composed.level = top.level
        kind = top.label.split(":")[1]
        if raised_instruction and kind in raised_instruction:
            composed.user_instruction = raised_instruction[kind]
    if any(r.sets_do_not_drive for r in rows):
        composed.driving_assessment = DrivingAssessment.DO_NOT_DRIVE
    composed.roadside_assistance_recommended = engine.roadside_assistance_recommended or any(r.sets_roadside for r in rows)
    composed.emergency_services_required = engine.emergency_services_required
    labels = [r.label for r in rows]
    composed.triggered_rules = [*engine.triggered_rules, *labels]
    composed.reasons = [*engine.reasons, *(
        f"PGDR Part 1 {label} (Manufacturer First Finding, monotonic composition)" for label in labels
    )]
    return composed, labels


# ---------------------------------------------------------------------------
# Approved driver-facing wording (Execution Mandate v0.2 FINAL §7 / §7.1,
# approved by the owner under D-C7). Byte-for-byte copies: never edit here
# without a new owner approval. '**' markdown emphasis is presentation only
# and is not part of the text; placeholders are substituted at render time.
# ---------------------------------------------------------------------------

APPROVED_BANNERS: dict[str, tuple[str, ...]] = {
    "T1": (
        'PGDR lit le voyant de votre tableau de bord avec la notice du constructeur de votre véhicule.',
        "PGDR n'établit pas la cause mécanique d'une panne et ne remplace pas l'examen du véhicule par un professionnel.",
    ),
    "T2": (
        'Premier Constat Constructeur',
        "Ce constat reprend ce que la notice du constructeur indique pour le voyant identifié sur votre photo. Lorsque la notice donne une consigne — par exemple arrêter le véhicule ou couper le contact — cette consigne s'applique : suivez-la.",
        "Ce constat ne recherche pas la cause mécanique de la panne et ne remplace pas l'examen du véhicule par un professionnel.",
    ),
    "T3": (
        "Source : notice constructeur « {document_title} » (réf. {document_id}). Transcription fournie et attestée par l'exploitant de PGDR ; elle n'a pas été vérifiée de façon indépendante. Le texte du constructeur est reproduit en anglais, sans traduction.",
    ),
    "T4": (
        '« Non établi » signifie que la notice du constructeur ne précise pas ce point. Cela ne veut jamais dire que rouler, ou continuer à rouler, est sans risque.',
    ),
    "T5": (
        'Texte du constructeur (anglais, tel que fourni) :',
    ),
    "T6": (
        "Ce chiffre est indiqué par le constructeur pour décrire {meaning}. Ce n'est ni une autorisation de rouler, ni une distance de conduite sûre.",
    ),
    "T7": (
        'PGDR ne recherche pas encore de garage ni de dépanneur. Contactez vous-même {documented_suitability, verbatim, if established; otherwise: "un professionnel qualifié"}.',
    ),
    "T8": (
        "Ce Premier Constat est terminé. PGDR ne propose pas encore de pré-diagnostic mécanique approfondi (recherche de la cause) : cette étape n'est pas disponible aujourd'hui.",
    ),
}
# Banner lines rendered in bold (the '**'-emphasised first line of T1 / T2).
APPROVED_BANNER_BOLD_FIRST_LINE = frozenset({"T1", "T2"})

APPROVED_LABELS: dict[str, str] = {
    'operability = DO_NOT_DRIVE':
        'Ne reprenez pas la route avec ce véhicule.',
    'operability = STARTING_PREVENTED':
        "D'après la notice, le démarrage du moteur est empêché.",
    'operability = MAY_DRIVE (unused)':
        "D'après la notice, le véhicule peut rouler.",
    'operability = MAY_DRIVE_WITH_RESTRICTIONS (unused)':
        "D'après la notice, le véhicule peut rouler, avec les restrictions ci-dessous.",
    'operability = NOT_ESTABLISHED':
        "La notice ne permet pas d'établir si le véhicule peut continuer à rouler.",
    'stop_vehicle_engine_off = REQUIRED':
        'Arrêtez le véhicule dès que vous pouvez le faire en sécurité, puis coupez le contact.',
    'vehicle_immobilization = REQUIRED':
        "Laissez le véhicule à l'arrêt jusqu'à l'intervention d'un professionnel.",
    'professional_attention = REQUIRED':
        'Faites intervenir un professionnel. Délai indiqué par la notice : « {urgency_phrase} » / non précisé.',
    'practical = GARAGE_REQUIRED':
        'Le véhicule doit être vu par : « {documented_suitability} ».',
    'practical = TOWING_REQUIRED':
        'Le véhicule ne devant pas rouler, son transport vers un professionnel nécessite un dépannage (sauf intervention sur place).',
    'practical = NEITHER_REQUIRED':
        'La notice indique une action que vous pouvez réaliser vous-même (voir le texte du constructeur).',
    'max_speed / max_distance / max_duration = NOT_ESTABLISHED':
        'Vitesse maximale / distance maximale / durée maximale : non établie par la notice.',
    'exit_vehicle / move_away / environment = NOT_ESTABLISHED':
        "Quitter le véhicule / s'en éloigner / précaution liée au lieu : non établi par la notice.",
    # Owner Completion Authority, item 2 (PGDR-authored epistemic labels;
    # no automotive knowledge).
    'stop_vehicle_engine_off = NOT_ESTABLISHED':
        "Arrêt immédiat du véhicule et coupure du contact : non établi par la notice.",
    'vehicle_immobilization = NOT_ESTABLISHED':
        "Maintien du véhicule à l'arrêt : non établi par la notice.",
    'professional_attention = NOT_ESTABLISHED':
        "Intervention d'un professionnel : non établie par la notice.",
    'practical_assistance = NOT_ESTABLISHED':
        "Besoin d'un garage ou d'un dépannage : non établi par la notice.",
}

# Owner Completion Authority, item 3: the driver indicated that none of the
# offered symbols corresponds to the photo. Shown, then T8; Part 1 ends.
APPROVED_NO_IDENTIFIED_SYMBOL = (
    "Aucun voyant n'a pu être identifié parmi les voyants proposés à partir de la notice disponible. "
    "PGDR ne peut donc pas établir de Premier Constat Constructeur pour cette photo."
)

_T7_PLACEHOLDER = '{documented_suitability, verbatim, if established; otherwise: "un professionnel qualifié"}'
_T7_OTHERWISE = "un professionnel qualifié"


def banner(key: str, **values: str) -> tuple[str, ...]:
    """An approved banner, with only its declared placeholders substituted."""
    lines = APPROVED_BANNERS[key]
    if key == "T3":
        return tuple(l.replace("{document_title}", values["document_title"]).replace("{document_id}", values["document_id"]) for l in lines)
    if key == "T6":
        return tuple(l.replace("{meaning}", values["meaning"]) for l in lines)
    if key == "T7":
        return tuple(l.replace(_T7_PLACEHOLDER, values.get("documented_suitability") or _T7_OTHERWISE) for l in lines)
    return lines


def professional_label(urgency: FindingItem) -> str:
    """§7.1 professional_attention = REQUIRED: « {urgency_phrase} » when the
    urgency is established, otherwise the approved alternative "non précisé"."""
    label = APPROVED_LABELS["professional_attention = REQUIRED"]
    if urgency.basis == FindingBasis.NOT_ESTABLISHED:
        return label.replace("« {urgency_phrase} » / ", "")
    return label.replace("{urgency_phrase}", urgency.value).replace(" / non précisé", "")


def garage_label(suitability: FindingItem) -> str:
    return APPROVED_LABELS["practical = GARAGE_REQUIRED"].replace(
        "{documented_suitability}", suitability.value if suitability.basis != FindingBasis.NOT_ESTABLISHED else _T7_OTHERWISE,
    )


def raised_instructions(finding: ManufacturerFirstFinding) -> dict[str, str]:
    """The approved §7.1 label that replaces the SafetyEngine wording when an
    R-5 row RAISES the triage level (keyed by R-5 row kind)."""
    urgency = next(
        (e.urgency_phrase for e in finding.entries if e.urgency_phrase.value == WITHOUT_DELAY),
        FindingItem.not_established(),
    )
    return {
        "stop_vehicle_engine_off": APPROVED_LABELS["stop_vehicle_engine_off = REQUIRED"],
        "operability_do_not_drive": APPROVED_LABELS["operability = DO_NOT_DRIVE"],
        "professional_without_delay": professional_label(urgency),
    }
