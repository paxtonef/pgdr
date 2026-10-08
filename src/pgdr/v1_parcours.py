"""V1 parcours (web): VIR -> consent -> optional photo -> complete manual
catalogue -> driver's own selection -> explicit confirmation -> exact
restitution of the manufacturer notice, with a colour fallback.

Boundaries, all deliberate:
  * The catalogue comes from a read-only ManifestNoticeRepository (verified
    review fingerprint and file digests). Nothing is written anywhere.
  * The photo never leaves the browser: no upload endpoint exists. It is not
    analysed, not transmitted and not kept (object URL revoked in the page).
  * No model / vision provider is called. The selection is the driver's own,
    by stable entry_id.
  * Restitution is exact: one section per chosen image, texts as stored, no
    merging, deduplication or rewording.
  * Fallback screens use the VALIDATED French translation only
    (config/v1_fallback_screens.fr.yaml, identical to
    outils/preparation_v1/config/fallback_screens.fr.yaml; named validation
    recorded in the file). An unvalidated file is refused.
  * Interface texts are French; manufacturer texts are shown as stored, in
    the notice language, never translated. Curation notes are not shown.
  * DEV TRIAL (PGDR_V1_DEV_TRIAL=1) is the only mode in which a notice whose
    applicability to the vehicle is not established may be shown, and then
    with a permanent banner on every screen.

Configuration (environment):
  PGDR_V1_MANIFEST      path to the notice manifest.yaml (outside the repo)
  PGDR_V1_DEV_TRIAL     "1" enables the development trial mode
  PGDR_V1_DEV_VEHICLE   dev trial only: JSON VIR vehicle identity used by
                        GET /v1/essai-dev (stands in for the VIR handoff)
  PGDR_V1_GROUPS        optional: VALIDATED groups of visually identical
                        images (different files). Identical files are grouped
                        automatically.
  PGDR_V1_EXPLANATIONS  optional: prepared French explanations (3 parts,
                        anchored). Draft = development trial only, marked.
  PGDR_V1_SITUATIONS    optional: situation classification per entry
                        (nature, exact justification, instructions,
                        conditions). Draft = development trial only, marked.
  PGDR_V1_FINDINGS      optional: VALIDATED structured classification of the
                        notice entries (Part 1 mapping format, header status
                        VALIDE, bound to the catalogue content fingerprint).
                        Absent, draft or mismatching = not used: every
                        structured field is « non établi ».

Premier Constat (after explicit confirmation): the EXISTING Part 1 pieces,
unmodified in behaviour -- unmodified SafetyEngine on the selected entries,
build_manufacturer_first_finding (origin "user_selection": the driver's
explicit selection replaces only the automatic identification), R-5
compose_triage (may raise, never lower) and the approved presentation
present_first_finding (APPROVED_BANNERS / APPROVED_LABELS only). No question
is asked afterwards (decisions C1/C2): the parcours ends with T8.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from importlib import resources
from typing import Dict, Literal, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from pgdr.application.part1_first_finding import (
    APPROVED_BANNERS, UNRESOLVED_VARIANT, Part1Mapping, banner, build_manufacturer_first_finding, compose_triage,
    load_part1_mapping, raised_instructions, severity_rank,
)
from pgdr.config_loader import load_safety_rules
from pgdr.application.photo_first import warning_indicator_from_entry
from pgdr.errors import ConfigurationError
from pgdr.models import (
    ConditionalStop, ConditionStatus, Consent, DiagnosticSession, FindingBasis, InitialComplaint,
    ManufacturerFirstFinding, PreGarageDiagnosticRequest,
)
from pgdr.safety_engine import SafetyEngine
from pgdr import v1_contenu as vc
from pgdr.adapters.manifest_notice_repository import (
    ManifestNoticeRepository, NoticeCatalogue, NoticeEntry, NoticeRejected, Pictogram,
)
from pgdr.domain.dashboard_knowledge import VehicleApplicabilityContext
from pgdr.models import VehicleIdentityContext

DEV_TRIAL_BANNER = "Essai de développement — Applicabilité de cette notice au véhicule non confirmée"

CONSENT_TEXT = (
    "Ce parcours affiche les images de voyants de la notice du constructeur de votre véhicule. "
    "C'est vous qui choisissez l'image ou les images qui correspondent à ce que vous voyez ; "
    "PGDR affiche ensuite le texte exact de la notice pour chacune. Ce n'est pas un diagnostic.",
    "Vous pouvez photographier votre tableau de bord pour comparer vous-même. Cette photo reste sur "
    "votre appareil : elle n'est ni analysée, ni envoyée, ni conservée.",
)

COLOURS = (
    ("rouge", "Rouge"), ("orange", "Orange / ambre"), ("jaune", "Jaune"), ("vert", "Vert"),
    ("bleu", "Bleu"), ("blanc", "Blanc"), ("gris", "Gris"), ("incertain", "Je ne sais pas / incertain"),
)
_RED_OR_UNCERTAIN = {"rouge", "incertain"}

_MAX_PARCOURS = 1000


LANGUAGE_NOTE = {"en": "Texte du constructeur reproduit dans la langue de la notice disponible (anglais)."}

COLOUR_LABELS = {"red": "rouge", "amber": "ambre", "yellow": "jaune", "green": "vert", "blue": "bleu",
                 "white": "blanc", "grey": "gris"}
STATE_LABELS = {"fixed": "fixe", "flashing": "clignotant", "unknown": "non précisé"}
FIELD_LABELS = {"manufacturer_designation": "désignation", "symbol_descriptor": "descripteur", "colour": "couleur",
                "state": "état", "displayed_message": "message affiché", "audible_signal": "signal sonore",
                "documented_meaning": "texte de la notice", "documented_instruction": "consigne"}


def load_fallback_screens() -> dict:
    """The validated French fallback copy, packaged with PGDR. Refused unless
    it carries a named validation."""
    text = resources.files("pgdr.config").joinpath("v1_fallback_screens.fr.yaml").read_text(encoding="utf-8")
    return validated_fallback(yaml.safe_load(text))


def validated_fallback(cfg: dict) -> dict:
    if cfg.get("schema_version") != 1 or set(cfg["screens"]) != {"red_or_uncertain", "other_colour"}:
        raise RuntimeError("invalid fallback screens")
    v = cfg.get("validation") or {}
    if cfg.get("status") != "VALIDE" or not v.get("validated_by") or not v.get("validated_on"):
        raise RuntimeError("fallback screens not validated")
    if cfg["shared"].get("handoff_implied") is not False or cfg["shared"].get("show_status_indicator") is not False:
        raise RuntimeError("fallback screens must not imply a handoff or a status")
    return cfg


@dataclass
class V1Wiring:
    repository: Optional[ManifestNoticeRepository] = None
    dev_trial: bool = False
    dev_vehicle: Optional[dict] = None
    error: Optional[str] = None
    findings: Part1Mapping = field(default_factory=dict)
    findings_status: str = "absent"
    findings_covered: frozenset = frozenset()   # entries a VALIDATED classification reviewed
    groups: list = field(default_factory=list)  # merged: identical files + candidate groups
    group_draft: list = field(default_factory=list)  # aligned with groups: True = uses a DRAFT candidate
    groups_status: str = "absent"
    explanations: dict = field(default_factory=dict)
    explanations_rejected: dict = field(default_factory=dict)
    explanations_status: str = "absent"
    situations: dict = field(default_factory=dict)
    situations_rejected: dict = field(default_factory=dict)
    situations_status: str = "absent"


def build_wiring(repo: Optional[ManifestNoticeRepository], *, dev_trial: bool, dev_vehicle=None, error=None,
                 findings_path=None, groups_path=None, explanations_path=None, situations_path=None) -> V1Wiring:
    """All notice content is loaded and verified ONCE here and then shared by
    every parcours of this process (no re-read, no external fetch)."""
    w = V1Wiring(repository=repo, dev_trial=dev_trial, dev_vehicle=dev_vehicle, error=error)
    if repo is None:
        return w
    c = repo.catalogue
    if findings_path:
        try:
            w.findings = load_v1_findings(findings_path, repo)
            w.findings_status = "validated"
            header = yaml.safe_load(open(findings_path, encoding="utf-8"))["header"]
            w.findings_covered = frozenset(header.get("covered_entry_ids") or [])
        except ConfigurationError as exc:
            w.findings_status = f"refused: {exc}"
    candidates, candidates_draft = [], False
    if groups_path:
        try:
            candidates, candidates_draft = vc.load_groups(groups_path, c, dev_trial=dev_trial)
            w.groups_status = "draft_dev_trial" if candidates_draft else "validated"
        except vc.ContentRejected as exc:
            w.groups_status = f"refused: {exc}"
    auto = vc.auto_groups(c)
    w.groups = vc.merge_groups(c, auto, candidates)
    w.group_draft = [candidates_draft and g not in auto for g in w.groups]
    if explanations_path:
        try:
            w.explanations, w.explanations_rejected, w.explanations_status = vc.load_explanations(
                explanations_path, c, dev_trial=dev_trial)
        except vc.ContentRejected as exc:
            w.explanations_status = f"refused: {exc}"
    if situations_path:
        try:
            w.situations, w.situations_rejected, w.situations_status = vc.load_situations(
                situations_path, c, dev_trial=dev_trial)
        except vc.ContentRejected as exc:
            w.situations_status = f"refused: {exc}"
    # Defect wording follows the notice: an explanation that does not, is not shown.
    for x, reason in vc.defect_wording_rejections(w.explanations, w.situations, c).items():
        w.explanations.pop(x, None)
        w.explanations_rejected[x] = reason
    return w


def load_v1_findings(path, repository: ManifestNoticeRepository) -> Part1Mapping:
    """A structured classification is used ONLY when validated by name and
    bound to this exact catalogue content. Anything else raises
    ConfigurationError (the caller then uses no classification at all)."""
    try:
        raw = yaml.safe_load(open(path, encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"classification unreadable: {exc}") from None
    catalogue = repository.catalogue
    header = (raw or {}).get("header") or {}
    if header.get("status") != "VALIDE":
        raise ConfigurationError("classification not validated")
    if header.get("catalogue_content_sha256") != catalogue.content_sha256:
        raise ConfigurationError("classification bound to another catalogue content")
    mapping = load_part1_mapping(path)
    if any(doc != catalogue.document.document_id for doc, _ in mapping):
        raise ConfigurationError("classification record for another document")
    # Every record must bind to a live entry (fingerprint) and every anchor
    # must be verbatim in it: checked now, never discovered mid-parcours.
    live = {e.entry_id: e for e in repository.entries_for_document(catalogue.document.document_id)}
    for _, entry_id in mapping:
        if entry_id not in live:
            raise ConfigurationError(f"classification record for unknown entry {entry_id}")
        finding = build_manufacturer_first_finding(
            [(live[entry_id], "user_selection")], mapping=mapping,
            linked_warnings={entry_id: [w.text for w in catalogue.entry(entry_id).linked_warnings]},
        )
        if finding.entries[0].audit_flags:
            raise ConfigurationError(f"classification record does not match entry {entry_id}")
    return mapping


_wiring: Optional[V1Wiring] = None


def get_wiring() -> V1Wiring:
    global _wiring
    if _wiring is None:
        dev = os.environ.get("PGDR_V1_DEV_TRIAL") == "1"
        vehicle = json.loads(os.environ["PGDR_V1_DEV_VEHICLE"]) if dev and os.environ.get("PGDR_V1_DEV_VEHICLE") else None
        path = os.environ.get("PGDR_V1_MANIFEST")
        repo, error = None, None
        if path:
            try:
                repo = ManifestNoticeRepository(path)
            except NoticeRejected as exc:
                error = str(exc)
        _wiring = build_wiring(repo, dev_trial=dev, dev_vehicle=vehicle, error=error,
                               findings_path=os.environ.get("PGDR_V1_FINDINGS"),
                               groups_path=os.environ.get("PGDR_V1_GROUPS"),
                               explanations_path=os.environ.get("PGDR_V1_EXPLANATIONS"),
                               situations_path=os.environ.get("PGDR_V1_SITUATIONS"))
    return _wiring


@dataclass
class Parcours:
    vehicle: dict
    consent: bool = False
    selection: list[str] = field(default_factory=list)  # entry_ids, manual order
    confirmed: bool = False
    colour: Optional[str] = None
    resolved: dict = field(default_factory=dict)  # group index -> entry_id chosen by the driver
    messages: dict = field(default_factory=dict)  # group index -> message typed by the driver, verbatim
    conditions: dict = field(default_factory=dict)  # consigne key -> confirmed / excluded / unknown (driver's answer)
    phase: str = "vir"  # vir -> consent -> catalogue -> confirmation -> restitution | colour -> fallback


_parcours: Dict[str, Parcours] = {}

router = APIRouter()


# --- helpers ------------------------------------------------------------------

def _catalogue() -> NoticeCatalogue:
    w = get_wiring()
    if w.repository is None:
        raise HTTPException(status_code=503, detail="Notice indisponible.")
    return w.repository.catalogue


def _get(pid: str) -> Parcours:
    p = _parcours.get(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Parcours inconnu ou expiré.")
    return p


def _require_consent(p: Parcours) -> None:
    if not p.consent:
        raise HTTPException(status_code=403, detail="Consentement requis.")


def _asset_url(pid: str, sha: str) -> str:
    return f"/api/v1/parcours/{pid}/asset/{sha}"


def _segments(pid: str, text: str, pictograms: tuple[Pictogram, ...]) -> list[dict]:
    """The exact text, split only where a pictogram is printed. Joining the
    text segments gives back the stored text unchanged."""
    out, cursor = [], 0
    for p in sorted(pictograms, key=lambda p: p.position):
        if p.position > cursor:
            out.append({"text": text[cursor:p.position]})
        out.append({"pictogram": _asset_url(pid, p.image_sha256), "pdf_page": p.pdf_page,
                    "printed_page": p.printed_page, "identified_entry_ids": list(p.identified_entry_ids)})
        cursor = max(cursor, p.position)
    if cursor < len(text):
        out.append({"text": text[cursor:]})
    return out


def _section(pid: str, e: NoticeEntry) -> dict:
    return {
        "entry_id": e.entry_id,
        "manual_order": e.manual_order,
        "image": _asset_url(pid, e.image_sha256),
        "designation": e.designation,
        "colour": COLOUR_LABELS.get(e.colour, e.colour),
        "state": STATE_LABELS.get(e.state, e.state),
        "symbol_descriptor": e.symbol_descriptor,
        "displayed_message": e.displayed_message,
        "audible_signal": e.audible_signal,
        "meaning": _segments(pid, e.documented_meaning, e.meaning_pictograms),
        "instruction": e.documented_instruction,
        "where_provided": e.where_provided is True,
        "startup_check": e.documented_startup_check,
        "page_reference": e.page_reference,
        "pdf_page": e.pdf_page,
        "warnings": [
            {"number": w.number, "text": _segments(pid, w.text, w.pictograms),
             "printed_page": w.printed_page, "pdf_page": w.pdf_page}
            for w in e.linked_warnings
        ],
        "field_sources": [
            {"field": FIELD_LABELS.get(s.field, s.field), "text": s.text, "printed_page": s.printed_page, "pdf_page": s.pdf_page}
            for s in e.field_sources
        ],
    }


def _document(c: NoticeCatalogue) -> dict:
    d = c.document
    return {"document_id": d.document_id, "title": d.document_title, "edition": d.edition,
            "language": c.language, "language_note": LANGUAGE_NOTE.get(c.language),
            "content_sha256": c.content_sha256}


def _state(pid: str, p: Parcours) -> dict:
    w = get_wiring()
    return {
        "parcours_id": pid, "phase": p.phase,
        "dev_trial_banner": DEV_TRIAL_BANNER if w.dev_trial else None,
        "vehicle": {k: p.vehicle.get(k) for k in ("manufacturer", "model", "generation")},
        "consent_text": list(CONSENT_TEXT), "consent": p.consent,
        "selection": list(p.selection), "confirmed": p.confirmed, "colour": p.colour,
        "colours": [{"key": k, "label": v} for k, v in COLOURS],
        "return_label": load_fallback_screens()["shared"]["return_button"],
    }


def _open_parcours(identity: VehicleIdentityContext) -> dict:
    w = get_wiring()
    if w.repository is None:
        return {"status": "notice_unavailable",
                "message": "La notice de ce véhicule n'est pas disponible (revue absente ou obsolète, ou fichier non conforme)."}
    if identity.resolution_status.value != "resolved":
        return {"status": "vehicle_identity_insufficient",
                "message": "L'identité du véhicule n'est pas établie par VIR."}
    vehicle = VehicleApplicabilityContext.from_pgdr_vehicle_identity_dict(identity.vehicle_identity)
    if not w.repository.matches(vehicle):
        return {"status": "vehicle_not_supported", "message": "Aucune notice disponible pour ce véhicule."}
    if not w.repository.catalogue.applicability_established and not w.dev_trial:
        return {"status": "applicability_not_confirmed",
                "message": "L'applicabilité de la notice à ce véhicule n'est pas confirmée."}
    if len(_parcours) >= _MAX_PARCOURS:
        _parcours.pop(next(iter(_parcours)))
    pid = f"V1-{uuid.uuid4().hex}"
    _parcours[pid] = Parcours(vehicle={"manufacturer": vehicle.manufacturer, "model": vehicle.model,
                                       "generation": vehicle.generation})
    return {"status": "opened", "parcours_id": pid, "url": f"/v1?p={pid}"}


# --- request bodies -----------------------------------------------------------------

class ConsentRequest(BaseModel):
    accepted: bool


class SelectionRequest(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=500)


class ConfirmRequest(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=500)
    confirmed: bool


class NoMatchRequest(BaseModel):
    reason: Literal["none_match", "dont_know"]
    # Images ticked but not validated: kept for « Revenir aux images », never confirmed.
    entry_ids: list[str] = Field(default_factory=list, max_length=500)


class ColourRequest(BaseModel):
    colour: Literal["rouge", "orange", "jaune", "vert", "bleu", "blanc", "gris", "incertain"]


# --- routes -------------------------------------------------------------------

@router.post("/api/v1/vir-handoff")
def vir_handoff(identity: VehicleIdentityContext, request: Request):
    """VIR (via PI) -> PGDR, server to server, same credential as the
    photo-first handoff. The driver never types the vehicle identity."""
    from pgdr.web_app import _require_handoff_credential
    _require_handoff_credential(request)
    return _open_parcours(identity)


@router.get("/v1/essai-dev")
def dev_trial_entry():
    """DEV TRIAL ONLY: opens a parcours from the configured dev vehicle
    identity, standing in for the VIR handoff on a local machine."""
    w = get_wiring()
    if not w.dev_trial or not w.dev_vehicle:
        raise HTTPException(status_code=404)
    out = _open_parcours(VehicleIdentityContext(resolution_id="DEV-TRIAL-SIMULATED-VIR", resolution_status="resolved",
                                                 vehicle_identity=w.dev_vehicle))
    if out["status"] != "opened":
        raise HTTPException(status_code=409, detail=out["message"])
    return RedirectResponse(out["url"], status_code=303)


@router.get("/api/v1/parcours/{pid}")
def get_parcours(pid: str):
    return _state(pid, _get(pid))


@router.post("/api/v1/parcours/{pid}/vir-seen")
def vir_seen(pid: str):
    p = _get(pid)
    if p.phase == "vir":
        p.phase = "consent"
    return _state(pid, p)


@router.post("/api/v1/parcours/{pid}/consent")
def consent(pid: str, req: ConsentRequest):
    p = _get(pid)
    if not req.accepted:
        return {**_state(pid, p), "status": "consent_required",
                "message": "Sans votre accord, le parcours ne peut pas continuer."}
    p.consent = True
    p.phase = "catalogue"
    return _state(pid, p)


@router.get("/api/v1/parcours/{pid}/catalogue")
def catalogue(pid: str):
    p = _get(pid)
    _require_consent(p)
    c = _catalogue()
    return {
        "document": _document(c),
        "entries": [{"entry_id": e.entry_id, "manual_order": e.manual_order,
                     "image": _asset_url(pid, e.image_sha256), "alt": e.designation} for e in c.entries],
        "selection": list(p.selection), "colour": p.colour,
    }


@router.get("/api/v1/parcours/{pid}/asset/{sha}")
def asset(pid: str, sha: str):
    _require_consent(_get(pid))
    w = get_wiring()
    data = w.repository.asset(sha) if w.repository else None
    if data is None:
        raise HTTPException(status_code=404)
    media = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg" if data[:3] == b"\xff\xd8\xff" else None
    if media is None:
        raise HTTPException(status_code=415)
    return Response(content=data, media_type=media, headers={"Cache-Control": "no-store"})


def _validated_selection(entry_ids: list[str]) -> list[str]:
    c = _catalogue()
    known = {e.entry_id for e in c.entries}
    if len(set(entry_ids)) != len(entry_ids) or any(x not in known for x in entry_ids):
        raise HTTPException(status_code=400, detail="Sélection invalide.")
    chosen = set(entry_ids)
    return [e.entry_id for e in c.entries if e.entry_id in chosen]


@router.post("/api/v1/parcours/{pid}/selection")
def selection(pid: str, req: SelectionRequest):
    p = _get(pid)
    _require_consent(p)
    p.selection = _validated_selection(req.entry_ids)
    p.confirmed = False
    p.phase = "confirmation"
    c = _catalogue()
    return {**_state(pid, p), "chosen": [
        {"entry_id": x, "image": _asset_url(pid, c.entry(x).image_sha256), "alt": c.entry(x).designation}
        for x in p.selection]}


_safety_engine: Optional[SafetyEngine] = None


def _level_origin(engine, triage, rows, finding) -> list[dict]:
    """Where the INTERNAL level comes from: a PGDR rule that fired, or a
    documented passage (R-5 row on a cited phrase). Never displayed, never
    used to soften an instruction."""
    names = {r["id"]: r.get("name") for r in load_safety_rules().get("rules", [])}
    out = [{"origin": "règle PGDR déclenchée", "rule": rid, "name": names.get(rid)} for rid in engine.triggered_rules]
    if not engine.triggered_rules:
        out.append({"origin": "règle PGDR par défaut (aucun signal)", "rule": "default", "name": None})
    items = {f.provenance.entry_id: f for f in finding.entries}
    for row in rows:
        _, kind, entry_id = row.split(":", 2)
        if kind == "conditional_stop_confirmed":
            cs = next(x for x in items[entry_id].conditional_stops if x.condition_status == ConditionStatus.CONFIRMED)
            out.append({"origin": "passage documenté", "rule": row, "entry_id": entry_id, "citation": cs.citation,
                        "condition": cs.condition, "condition_status": "confirmed", "printed_page": cs.printed_page})
            continue
        item = {"stop_vehicle_engine_off": "stop_vehicle_engine_off", "operability_do_not_drive": "operability",
                "professional_without_delay": "professional_attention"}[kind]
        out.append({"origin": "passage documenté", "rule": row, "entry_id": entry_id,
                    "citation": getattr(items[entry_id], item).source_phrase})
    raised = severity_rank(triage.level) > severity_rank(engine.level)
    for o in out:
        o["sets_level"] = (o["origin"] == "passage documenté") == raised
    return out


CATALOGUE_ORIGIN = "texte du constructeur, catalogue revu par le propriétaire"


def situation_fact(x: str, situation: Optional[vc.Situation], variant: str) -> Optional[dict]:
    """Structured fact on the documented situation of one indicator, for the
    SafetyEngine. Provenance only from a VALIDATED classification; a draft
    gives no fact (the engine then behaves as before)."""
    if situation is None or situation.draft:
        return None
    return {"entry_id": x, "nature": situation.nature, "provenance": "classement des situations validé",
            "variant": variant}


def attach_conditional_stops(finding: ManufacturerFirstFinding, c: NoticeCatalogue, situations: dict,
                             variant: dict, answers: dict) -> tuple[ManufacturerFirstFinding, list[dict]]:
    """Raccordement V1 -> R-5 (R-5 decides): every stop instruction of the
    reviewed manufacturer text, per entry and variant, whole sentence and
    page, with the condition a preparation pairs with it (validated or not)
    and the driver's answer (unknown by default). Already covered by a
    VALIDATED structured item (stop_vehicle_engine_off): not repeated. A
    restart procedure is never one. Also reports a validated item that
    records a restart procedure as an immediate stop (never altered)."""
    entries, limits = [], []
    for f in finding.entries:
        x = f.provenance.entry_id
        e, st = c.entry(x), situations.get(x)
        item = f.stop_vehicle_engine_off
        if item.basis == FindingBasis.DOCUMENTED and vc.consigne_is_action(e, item.source_phrase):
            limits.append({"entry_id": x, "limit": (
                "Le classement validé enregistre une procédure d'arrêt temporaire, d'attente puis de redémarrage comme "
                "arrêt immédiat (stop_vehicle_engine_off) : à corriger dans le classement (stop_conditions).")})
        stops = []
        for s_ in vc.catalogue_stops(e):
            if item.basis == FindingBasis.DOCUMENTED and item.source_phrase in s_["text"]:
                continue
            paired = vc.stop_condition(s_, st)
            cond = paired[0].condition if paired else None
            stops.append(ConditionalStop(
                key=s_["key"], source_field=s_["source_field"], citation=s_["text"], printed_page=s_["printed_page"],
                pdf_page=s_["pdf_page"], origin=CATALOGUE_ORIGIN,
                condition=cond.source_phrase if cond else None,
                condition_printed_page=cond.printed_page if cond else None,
                condition_pdf_page=cond.pdf_page if cond else None,
                condition_established=bool(paired and paired[1]),
                condition_status=ConditionStatus(vc.condition_answer(answers, s_["key"])),
                variant=variant[x]))
        entries.append(f.model_copy(update={"conditional_stops": stops}) if stops else f)
    return ManufacturerFirstFinding(entries=entries), limits


def premier_constat(p: Parcours, entry_ids: list[str], ambiguous: list[int] = (), pid: str = "",
                    messages: Optional[dict] = None) -> dict:
    """The existing Part 1 chain on the driver's confirmed selection.
    `entry_ids`: resolved entries (Premier Constat + explanation each).
    `ambiguous`: groups left indistinguishable; ALL their variants count for
    the internal level (the highest; R-5 never lowers), none is chosen."""
    global _safety_engine
    if _safety_engine is None:
        _safety_engine = SafetyEngine()
    w = get_wiring()
    c = _catalogue()
    live = {e.entry_id: e for e in w.repository.entries_for_document(c.document.document_id)}
    groups = w.groups
    variant_ids = {x for i in ambiguous for x in groups[i]} - set(entry_ids)
    eval_ids = [e.entry_id for e in c.entries if e.entry_id in set(entry_ids) | variant_ids]
    # What the driver confirmed, excluded or left unknown, kept as such.
    variant = {x: ("possible" if x in variant_ids else "selected") for x in eval_ids}
    excluded = [x for i, chosen in p.resolved.items() if chosen != AMBIGUOUS and i < len(groups)
                for x in groups[i] if x != chosen]
    chosen = [live[x] for x in eval_ids]
    session = DiagnosticSession(request=PreGarageDiagnosticRequest(
        request_id=f"PGDR-V1-{uuid.uuid4().hex[:12]}",
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id="V1-PARCOURS", resolution_status="resolved", vehicle_identity=p.vehicle),
        initial_complaint=InitialComplaint(free_text=""),
        # The optional photo is never analysed nor kept.
        consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),
    ))
    session.warning_indicators = [
        warning_indicator_from_entry(e, photo_evidence_id=None).model_copy(update={
            "situation_fact": situation_fact(e.entry_id, w.situations.get(e.entry_id), variant[e.entry_id])})
        for e in chosen]
    engine = _safety_engine.evaluate(session)
    finding = build_manufacturer_first_finding(
        # A variant left undetermined is never transmitted as the driver's confirmed selection.
        [(e, "user_selection" if variant[e.entry_id] == "selected" else UNRESOLVED_VARIANT) for e in chosen],
        mapping=w.findings, linked_warnings={x: [lw.text for lw in c.entry(x).linked_warnings] for x in eval_ids},
    )
    answers = p.conditions
    internal = [i for x in eval_ids for i in vc.internal_consignes(c.entry(x), w.situations.get(x), variant[x], answers)]
    finding, limits = attach_conditional_stops(finding, c, w.situations, variant, answers)
    # R-5: may raise the SafetyEngine level, never lower it. Its wording is
    # not displayed in V1 (internal level only).
    triage, rows = compose_triage(engine, finding, raised_instruction=raised_instructions(finding))
    by_id = {f.provenance.entry_id: f for f in finding.entries}
    # Every uncertainty of the presentation, what it touches and where it is shown (internal, never displayed).
    uncertainties: list[dict] = []

    def present(x, **where):
        out = vc.present_entry(by_id[x], c.entry(x), covered=x in w.findings_covered,
                               explanation=w.explanations.get(x), t5_label=APPROVED_BANNERS["T5"][0],
                               situation=w.situations.get(x), answers=answers)
        uncertainties.extend({**u, "entry_id": x, **where} for u in out.pop("uncertainties"))
        return out

    def title(v) -> str:
        st = w.situations.get(v.entry_id)
        return v.designation + (" — " + st.title if st is not None and st.title else "")

    entries = [present(x, variant="selected") for x in entry_ids]
    blocks = []
    for i in ambiguous:
        variants = [c.entry(x) for x in groups[i]]
        common = vc.common_texts(variants)
        if w.group_draft[i]:
            uncertainties.append(vc.uncertainty("group.draft", "technique", reason="draft_status", group=i))
        uncertainties.append(vc.uncertainty("texts.draft", "technique", reason="draft_status", group=i))
        # The undetermined variant always changes the explanation; it also touches the action and the
        # applicability of a safety instruction when a variant documents one. Always in the body.
        sits = [w.situations.get(v.entry_id) for v in variants]
        touched = ((["applicabilite_consigne"] if any(vc.urgent_passages(v, st) or vc.conditional_passages(v, st)
                                                      for v, st in zip(variants, sits)) else [])
                   + (["action"] if any(st is not None and st.consignes for st in sits) else []) + ["explication"])
        uncertainties.append(vc.uncertainty("group.variant_undetermined", touched[0], group=i,
                                            variants=list(groups[i]), points=touched))
        blocks.append({
            "group": i, "image": _asset_url(pid, variants[0].image_sha256),
            "group_draft": vc.DRAFT_LABELS["group_draft"] if w.group_draft[i] else None,
            "draft_texts": vc.DRAFT_LABELS["draft_texts"], "limit": vc.LIMIT_V1,
            # Draft status: technical, in the block's folded « Détails ».
            "group_draft_placement": "details" if w.group_draft[i] else None, "draft_texts_placement": "details",
            "details_label": vc.DRAFT_LABELS["details"],
            "message_given": None if not (messages or {}).get(i) else {
                "label": vc.DRAFT_LABELS["message_given"], "text": messages[i]},
            # Urgent instructions stay visible, each under the variant it belongs to (never transferred).
            "urgent_title": vc.DRAFT_LABELS["urgent_title"],
            "urgent": [{"only_for": vc.DRAFT_LABELS["only_for"] + title(v), "entry_id": v.entry_id, "passages": u}
                       for v in variants for u in [vc.urgent_passages(v, w.situations.get(v.entry_id))] if u],
            # What each variant's passage describes comes first (type, title, exact passage).
            "situations": [{"only_for": vc.DRAFT_LABELS["only_for"] + title(v), "entry_id": v.entry_id,
                            "situation": vc.present_situation(w.situations[v.entry_id])}
                           for v in variants if v.entry_id in w.situations],
            # Expected actions (restart procedure, documented action), with their condition and page.
            "action_title": vc.DRAFT_LABELS["action_title"], "condition_label": vc.SITUATION_LABELS["condition"],
            # Conditional stop instructions: never urgent here, never the red button; condition then whole text.
            "conditional_title": vc.DRAFT_LABELS["conditional_title"],
            "conditionals": [{"only_for": vc.DRAFT_LABELS["only_for"] + title(v), "entry_id": v.entry_id, "passages": u}
                             for v in variants for u in [vc.conditional_passages(v, w.situations.get(v.entry_id), answers)] if u],
            "condition_question": {k: vc.DRAFT_LABELS[f"condition_{k}"] for k in ("question", "confirmed", "excluded", "unknown")},
            "actions": [{"only_for": vc.DRAFT_LABELS["only_for"] + title(v), "entry_id": v.entry_id, "passages": u}
                        for v in variants for u in [vc.action_passages(v, w.situations.get(v.entry_id))] if u],
            "common_title": vc.DRAFT_LABELS["common"], "common": common,
            "no_common": None if common else vc.DRAFT_LABELS["no_common"],
            "variants": [{
                "only_for": vc.DRAFT_LABELS["only_for"] + title(v),
                "only_for_label": vc.DRAFT_LABELS["only_for"],
                "condition": {"label": vc.DRAFT_LABELS["condition"],
                              "state": STATE_LABELS.get(v.state, v.state) if v.state else vc.DRAFT_LABELS["not_documented"],
                              "displayed_message": v.displayed_message or vc.DRAFT_LABELS["not_documented"]},
                "entry": present(v.entry_id, group=i, variant=variant[v.entry_id]), "section": _section(pid, v)}
                for v in variants],
            "red_offer": vc.DRAFT_LABELS["red_offer"] if vc.red_offer(variants, by_id, w.situations) else None,
        })
    def stop_view(f, cs) -> dict:
        label = (vc.DRAFT_LABELS["stop_condition_none"] if cs.condition is None else
                 vc.DRAFT_LABELS["stop_condition_validated"] if cs.condition_established else vc.DRAFT_LABELS["stop_condition_draft"])
        return {"key": cs.key, "entry_id": f.provenance.entry_id, "only_for": vc.DRAFT_LABELS["only_for"] + title(c.entry(f.provenance.entry_id)),
                "citation": {"text": cs.citation, "printed_page": cs.printed_page, "pdf_page": cs.pdf_page},
                "condition_label": label, "condition": None if cs.condition is None else {
                    "text": cs.condition, "printed_page": cs.condition_printed_page, "pdf_page": cs.condition_pdf_page},
                "answer": cs.condition_status.value, "answer_label": vc.DRAFT_LABELS[f"condition_answer.{cs.condition_status.value}"]}

    stops = [stop_view(f, cs) for f in finding.entries for cs in f.conditional_stops]
    for f in finding.entries:
        for cs in f.conditional_stops:
            # The condition of a stop instruction touches its applicability: always in the body.
            where = {"entry_id": f.provenance.entry_id, "key": cs.key}
            if cs.condition is None:
                uncertainties.append(vc.uncertainty("stop.condition_not_established", "applicabilite_consigne", **where))
            elif not cs.condition_established:
                uncertainties.append(vc.uncertainty("stop.condition_interpretation_draft", "applicabilite_consigne", **where))
            if cs.condition_status == ConditionStatus.UNKNOWN:
                uncertainties.append(vc.uncertainty("stop.condition_unknown", "applicabilite_consigne", **where))
    if stops:
        uncertainties.append(vc.uncertainty("texts.draft", "technique", reason="draft_status", block="stops"))
    red_screen = None
    if any(b["red_offer"] for b in blocks):
        s = load_fallback_screens()["screens"]["red_or_uncertain"]
        red_screen = {"key": "red_or_uncertain", "lang": "fr", "heading": s["heading"], "paragraphs": list(s["paragraphs"])}
    return {
        "presentation": {
            "title": vc.T2_V1, "entries": entries, "ambiguous": blocks, "red_screen": red_screen,
            "condition_question": {k: vc.DRAFT_LABELS[f"condition_{k}"] for k in ("question", "confirmed", "excluded", "unknown")},
            # Stop instructions of the manufacturer text with their condition and the driver's answer; a confirmed
            # one is shown at the top of the result, without any click.
            "stops_title": vc.DRAFT_LABELS["stops_title"], "stop_question": vc.DRAFT_LABELS["stop_question"],
            "stops_confirmed_title": vc.DRAFT_LABELS["stop_confirmed_title"], "draft_texts": vc.DRAFT_LABELS["draft_texts"],
            "draft_texts_placement": "details", "details_label": vc.DRAFT_LABELS["details"],
            "stops_confirmed": [x for x in stops if x["answer"] == "confirmed"], "stops": stops,
            "sources": list(banner("T3", document_title=c.document.document_title, document_id=c.document.document_id)),
            "end": APPROVED_BANNERS["T8"][0],
        },
        "triage": {"level": triage.level.value, "driving_assessment": triage.driving_assessment.value,
                   "safety_status": triage.safety_status, "safety_uncertainties": triage.safety_uncertainties,
                   "rule_exclusions": engine.rule_exclusions,
                   "engine_level": engine.level.value, "triggered_rules": list(triage.triggered_rules),
                   "r5_rows": rows, "origin": _level_origin(engine, triage, rows, finding)},
        # Internal data carried to the result: nature of each instruction, exact condition and the driver's
        # answer, entry and variant, whole citation and page; what R-5 cannot represent is listed, never hidden.
        "internal": {"stops": [{**cs.model_dump(mode="json"), "entry_id": f.provenance.entry_id}
                               for f in finding.entries for cs in f.conditional_stops],
                     "variants": [{"entry_id": x, "status": variant[x]} for x in eval_ids]
                     + [{"entry_id": x, "status": "excluded"} for x in excluded],
                     "consignes": internal, "limits": limits, "uncertainties": uncertainties},
        "classification_status": w.findings_status,
        "explanations_status": w.explanations_status,
        "situations_status": w.situations_status,
    }


@router.post("/api/v1/parcours/{pid}/confirm")
def confirm(pid: str, req: ConfirmRequest):
    p = _get(pid)
    _require_consent(p)
    if p.phase != "confirmation" or not req.confirmed or _validated_selection(req.entry_ids) != p.selection:
        raise HTTPException(status_code=409, detail="Confirmation explicite de la sélection affichée requise.")
    p.confirmed = True
    p.resolved = {}
    p.messages = {}
    return _after_confirmation(pid, p)


def _hit_groups(p: Parcours) -> list[int]:
    groups = get_wiring().groups
    return [i for i, g in enumerate(groups) if any(x in g for x in p.selection)]


def _question(pid: str, i: int) -> dict:
    """Only the elements the notice documents to tell the variants apart,
    each choice with its source. Never chosen for the driver."""
    c = _catalogue()
    variants = [c.entry(x) for x in get_wiring().groups[i]]
    fields = vc.distinguishing_fields(variants)
    if not fields:
        # The notice speaks of a message for some variants only: ask for it, typed exactly.
        return {"group": i, "image": _asset_url(pid, variants[0].image_sha256), "kind": "message",
                "question": vc.DRAFT_LABELS["message_question"], "submit": vc.DRAFT_LABELS["message_submit"],
                "none": vc.DRAFT_LABELS["message_none"], "draft_texts": vc.DRAFT_LABELS["draft_texts"], "choices": []}
    return {"group": i, "image": _asset_url(pid, variants[0].image_sha256), "kind": "choice", "choices": [
        {"entry_id": v.entry_id,
         "elements": [{"field": f, "label": "Message affiché" if f == "displayed_message" else "État du voyant",
                       "value": v.displayed_message if f == "displayed_message" else STATE_LABELS.get(v.state, v.state),
                       "notice_value": getattr(v, f)} for f in fields],
         "source": {"designation": v.designation, "page_reference": v.page_reference, "pdf_page": v.pdf_page,
                    "text": next((s.text for s in v.field_sources if s.field in fields), v.documented_meaning)}}
        for v in variants]}


def _after_confirmation(pid: str, p: Parcours) -> dict:
    c = _catalogue()
    pending = [i for i in _hit_groups(p) if i not in p.resolved]
    w = get_wiring()
    for i in list(pending):
        variants = [c.entry(x) for x in w.groups[i]]
        if not vc.distinguishing_fields(variants) and not vc.message_question(variants, w.situations):
            # Nothing documented tells these passages apart: no question, shown as ambiguous.
            p.resolved[i] = AMBIGUOUS
            pending.remove(i)
    if pending:
        p.phase = "clarification"
        return {**_state(pid, p), "questions": [_question(pid, i) for i in pending]}
    groups = get_wiring().groups
    chosen, ambiguous = set(), []
    for x in p.selection:
        gi = next((i for i, g in enumerate(groups) if x in g), None)
        if gi is None:
            chosen.add(x)
        elif p.resolved[gi] == AMBIGUOUS:
            if gi not in ambiguous:
                ambiguous.append(gi)
        else:
            chosen.add(p.resolved[gi])
    resolved_ids = [e.entry_id for e in c.entries if e.entry_id in chosen]  # manual order
    p.phase = "restitution"
    return {**_state(pid, p), "document": _document(c),
            "premier_constat": premier_constat(p, resolved_ids, sorted(ambiguous), pid, p.messages),
            "sections": [_section(pid, c.entry(x)) for x in resolved_ids]}


AMBIGUOUS = "__ambiguous__"


class ClarifyRequest(BaseModel):
    group: int
    answer: str = Field(max_length=200)  # an entry_id of the group, "dont_know", "none" or "message"
    message: Optional[str] = Field(default=None, max_length=200)  # with "message": typed by the driver


@router.post("/api/v1/parcours/{pid}/clarify")
def clarify(pid: str, req: ClarifyRequest):
    p = _get(pid)
    _require_consent(p)
    groups = get_wiring().groups
    if p.phase != "clarification" or req.group not in _hit_groups(p) or req.group in p.resolved:
        raise HTTPException(status_code=409, detail="Aucune précision n'est attendue pour ce groupe.")
    if req.answer in ("dont_know", "none"):
        # Never chosen for the driver: the group is shown as ambiguous.
        p.resolved[req.group] = AMBIGUOUS
        return _after_confirmation(pid, p)
    if req.answer == "message":
        text = " ".join((req.message or "").split())
        if not text:
            raise HTTPException(status_code=400, detail="Message vide.")
        p.messages[req.group] = text
        # Exact documented message only; otherwise the group stays ambiguous (never guessed).
        match = vc.message_match([_catalogue().entry(x) for x in groups[req.group]], text)
        p.resolved[req.group] = match or AMBIGUOUS
        return _after_confirmation(pid, p)
    if req.answer not in groups[req.group]:
        raise HTTPException(status_code=400, detail="Choix invalide.")
    p.resolved[req.group] = req.answer
    return _after_confirmation(pid, p)


class ConditionRequest(BaseModel):
    key: str = Field(max_length=300)  # stop key « entry_id#hash » of a documented stop instruction
    answer: Literal["confirmed", "excluded", "unknown"]


@router.post("/api/v1/parcours/{pid}/condition")
def condition(pid: str, req: ConditionRequest):
    """The driver's answer on the condition of a conditional stop instruction."""
    p = _get(pid)
    _require_consent(p)
    entry_id = req.key.partition("#")[0]
    e = _catalogue().entry(entry_id)
    if p.phase != "restitution" or e is None or req.key not in {s_["key"] for s_ in vc.catalogue_stops(e)}:
        raise HTTPException(status_code=409, detail="Aucune condition n'est attendue ici.")
    p.conditions[req.key] = req.answer
    return _after_confirmation(pid, p)


@router.post("/api/v1/parcours/{pid}/no-match")
def no_match(pid: str, req: NoMatchRequest):
    p = _get(pid)
    _require_consent(p)
    p.selection = _validated_selection(req.entry_ids) if req.entry_ids else []
    p.confirmed = False
    p.phase = "colour"
    return {**_state(pid, p), "reason": req.reason}


@router.post("/api/v1/parcours/{pid}/colour")
def colour(pid: str, req: ColourRequest):
    p = _get(pid)
    _require_consent(p)
    if p.phase not in ("colour", "fallback"):
        raise HTTPException(status_code=409, detail="La question de couleur n'est pas posée à ce stade.")
    p.colour = req.colour
    p.phase = "fallback"
    cfg = load_fallback_screens()
    key = "red_or_uncertain" if req.colour in _RED_OR_UNCERTAIN else "other_colour"
    screen = cfg["screens"][key]
    return {**_state(pid, p), "screen": {"key": key, "lang": "fr", "heading": screen["heading"],
                                         "paragraphs": list(screen["paragraphs"])}}


@router.post("/api/v1/parcours/{pid}/return")
def return_to_images(pid: str):
    """Back to the complete catalogue in manual order. Selection and colour
    are kept; any previous confirmation is void and must be given again."""
    p = _get(pid)
    _require_consent(p)
    p.confirmed = False
    p.resolved = {}
    p.messages = {}
    p.conditions = {}
    p.phase = "catalogue"
    return _state(pid, p)


@router.get("/v1", response_class=HTMLResponse)
def v1_page():
    return HTMLResponse(V1_HTML, headers={"Cache-Control": "no-store"})


V1_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PGDR — Voyants de la notice</title>
<style>
 * { box-sizing: border-box; }
 body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        line-height: 1.5; color: #222; background: #f4f4f4; }
 #dev-banner { position: sticky; top: 0; z-index: 10; background: #b00020; color: #fff; font-weight: 700;
               padding: 12px 16px; text-align: center; font-size: 1.05em; border-bottom: 4px solid #ffd600; }
 main { max-width: 960px; margin: 0 auto; padding: 16px; }
 section.screen { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px;
                  box-shadow: 0 1px 3px rgba(0,0,0,.12); }
 h1 { font-size: 1.4em; margin: 0 0 12px; } h2 { font-size: 1.2em; margin: 0 0 8px; }
 button { font: inherit; padding: 10px 16px; border-radius: 6px; border: 1px solid #555; background: #fff;
          cursor: pointer; margin: 4px 8px 4px 0; }
 button.primary { background: #1f4e79; color: #fff; border-color: #1f4e79; }
 button:disabled { opacity: .5; cursor: default; }
 .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 10px; margin: 12px 0; }
 .tile { display: flex; flex-direction: column; align-items: center; padding: 6px; margin: 0;
         border: 2px solid #ccc; background: #fafafa; }
 .tile img { max-width: 96px; max-height: 96px; }
 .tile[aria-pressed="true"] { border: 4px solid #1f4e79; background: #e3eef9; }
 .tile .n { font-size: .8em; color: #555; }
 #photo-preview { max-width: 240px; max-height: 180px; display: block; margin: 8px 0; }
 .actions { position: sticky; bottom: 0; background: #fff; padding: 8px 0; border-top: 1px solid #ddd; }
 article.restitution { border: 1px solid #ccc; border-radius: 8px; padding: 16px; margin: 16px 0; }
 article.restitution > img { max-width: 120px; }
 .exact { white-space: pre-wrap; background: #fbfbf4; border-left: 4px solid #999; padding: 8px 12px; margin: 6px 0; }
 .exact img { height: 1.4em; vertical-align: middle; margin: 0 2px; }
 span.exact { display: inline; border-left: none; padding: 0 4px; margin: 0; }
 .label { font-weight: 600; }
 .tag { display: inline-block; background: #eee; border-radius: 4px; padding: 2px 8px; margin-right: 6px; }
 .page { color: #444; font-size: .9em; }
 .fallback h1 { color: #b00020; }
 .muted { color: #555; font-size: .9em; }
 #premier-constat { border: 3px solid #1f4e79; border-radius: 8px; padding: 16px; margin-bottom: 24px; }
 #part1-t2 { background: #eef4fb; padding: 10px 12px; border-radius: 6px; margin-bottom: 12px; }
 .finding-entry { border-top: 1px solid #ccc; padding-top: 10px; margin-top: 12px; }
 .finding-entry h3 { font-size: 1em; margin: 12px 0 4px; }
 .finding-entry blockquote { margin: 4px 0; padding: 6px 10px; background: #fbfbf4; border-left: 4px solid #999; }
 .passage-title { margin-top: 8px; }
 .draft-mention { background: #fff3cd; border: 1px solid #c9a227; padding: 6px 10px; font-weight: 700; }
 .explanation { background: #f4f8fc; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
 .citation { color: #555; font-size: .9em; font-style: italic; }
 .question { border: 1px solid #ccc; border-radius: 8px; padding: 10px; margin: 10px 0; }
 .question img { max-width: 96px; display: block; }
 .question button.choice { display: block; text-align: left; width: 100%; }
 .choice-source { display: block; font-size: .85em; color: #444; }
 .ambiguous { border: 3px dashed #b26a00; border-radius: 8px; padding: 12px; margin: 14px 0; }
 .ambiguous > img { max-width: 96px; }
 .limit { font-weight: 700; }
 .variant { border-left: 4px solid #b26a00; padding-left: 10px; }
 .condition { font-weight: 600; }
 .urgent { border: 2px solid #b00020; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
 .urgent h3 { color: #b00020; }
 .expected-action { border: 2px solid #8a5a00; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
 .conditional { border: 1px solid #555; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
 .confirmed-stops { border: 3px solid #b00020; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
 .stops { border: 1px solid #555; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
 .described { background: #f7f7f7; border-radius: 6px; padding: 6px 12px; margin: 8px 0; }
 .situation { background: #f7f7f7; border-radius: 6px; padding: 6px 12px; margin: 8px 0; }
 .situation blockquote .page, .urgent blockquote .page, .expected-action blockquote .page, .conditional blockquote .page, .described blockquote .page, .stops blockquote .page, .confirmed-stops blockquote .page { display: block; font-size: .85em; color: #444; }
 .message-input { width: 100%; padding: 8px; margin: 6px 0; }
 button.red-offer { background: #b00020; color: #fff; border-color: #b00020; }
 details.details { margin: 8px 0; padding: 4px 10px; border: 1px solid #ccc; border-radius: 6px; background: #fafafa; }
 details.details > summary { cursor: pointer; color: #1f4e79; font-weight: 600; }
 .end { margin-top: 16px; padding: 12px; background: #f0f0f0; border-radius: 6px; font-weight: 600; }
 [hidden] { display: none !important; }
</style>
</head>
<body>
<div id="dev-banner" role="alert" hidden></div>
<main>
 <section class="screen" id="screen-error" hidden><h1>Parcours indisponible</h1><p id="error-text"></p></section>

 <section class="screen" id="screen-vir" hidden>
  <h1>Votre véhicule</h1>
  <p>Véhicule identifié par VIR : <strong id="vir-vehicle"></strong></p>
  <button class="primary" id="vir-continue">Continuer</button>
 </section>

 <section class="screen" id="screen-consent" hidden>
  <h1>Avant de commencer</h1>
  <div id="consent-text"></div>
  <label><input type="checkbox" id="consent-box"> J'ai compris et je souhaite continuer.</label><br>
  <button class="primary" id="consent-continue">Continuer</button>
  <p id="consent-message" class="muted"></p>
 </section>

 <section class="screen" id="screen-photo" hidden>
  <h1>Photo du tableau de bord (facultative)</h1>
  <p>Elle reste sur votre appareil pour que vous puissiez comparer. Elle n'est ni analysée, ni envoyée, ni conservée.</p>
  <input type="file" id="photo-input" accept="image/*" capture="environment">
  <img id="photo-preview" alt="Votre photo (sur cet appareil uniquement)" hidden>
  <button id="photo-remove" hidden>Retirer la photo</button><br>
  <button class="primary" id="photo-continue">Voir les images de la notice</button>
 </section>

 <section class="screen" id="screen-catalogue" hidden>
  <h1>Images de la notice</h1>
  <p class="muted">Toutes les images de la notice, dans l'ordre de la notice. Touchez celle ou celles qui correspondent à ce que vous voyez.</p>
  <img id="photo-compare" alt="Votre photo (sur cet appareil uniquement)" hidden style="max-width:200px">
  <div class="grid" id="catalogue-grid"></div>
  <div class="actions">
   <button class="primary" id="selection-continue" disabled>Valider ma sélection (<span id="selection-count">0</span>)</button>
   <button id="none-match">Aucune ne correspond</button>
   <button id="dont-know">Je ne sais pas</button>
  </div>
 </section>

 <section class="screen" id="screen-confirmation" hidden>
  <h1>Confirmez votre sélection</h1>
  <p>Vous avez choisi ces images :</p>
  <div class="grid" id="confirmation-grid"></div>
  <button class="primary" id="confirm">Je confirme : ces images correspondent à ce que je vois</button>
  <button class="return">Revenir aux images de la notice</button>
 </section>

 <section class="screen" id="screen-clarification" hidden>
  <h1>Précisez ce que vous voyez</h1>
  <p>La même image correspond à plusieurs passages de la notice. Choisissez ce que vous constatez, tel que la notice le décrit.</p>
  <div id="clarification-questions"></div>
  <button class="return">Revenir aux images de la notice</button>
 </section>

 <section class="screen" id="screen-restitution" hidden>
  <div id="premier-constat"></div>
  <h2 class="passage-title">Ce que dit la notice</h2>
  <p class="muted">Notice : <span id="restitution-document"></span></p>
  <p id="language-note" hidden></p>
  <p class="muted">Ces extraits de la notice ne constituent pas une autorisation de rouler.</p>
  <div id="restitution"></div>
  <div id="part1-sources"></div>
  <div id="part1-t8" class="end"></div>
  <button class="return">Revenir aux images de la notice</button>
 </section>

 <section class="screen" id="screen-colour" hidden>
  <h1>De quelle couleur est le voyant ?</h1>
  <div id="colour-choices"></div>
  <button class="return">Revenir aux images de la notice</button>
 </section>

 <section class="screen fallback" id="screen-fallback" hidden>
  <div id="fallback-content" lang="fr"></div>
  <button class="return">Revenir aux images de la notice</button>
 </section>
</main>
<script>
"use strict";
const pid = new URLSearchParams(location.search).get("p");
const api = "/api/v1/parcours/" + encodeURIComponent(pid || "");
let state = null, selected = new Set(), photoUrl = null, noticeLang = "en";

function el(id) { return document.getElementById(id); }
function make(tag, text, cls) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; }
function show(id) { document.querySelectorAll("section.screen").forEach(s => s.hidden = (s.id !== id)); window.scrollTo(0, 0); }
async function call(path, body) {
  const r = await fetch(api + path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!r.ok) { let d = ""; try { d = (await r.json()).detail; } catch (e) {} throw new Error(d || ("Erreur " + r.status)); }
  return r.json();
}
function fail(e) { el("error-text").textContent = e.message; show("screen-error"); }
function applyState(s) {
  state = s;
  const b = el("dev-banner");
  if (s.dev_trial_banner) { b.textContent = s.dev_trial_banner; b.hidden = false; } else { b.hidden = true; }
}
function dropPhoto() {
  if (photoUrl) { URL.revokeObjectURL(photoUrl); photoUrl = null; }
  for (const id of ["photo-preview", "photo-compare"]) { el(id).removeAttribute("src"); el(id).hidden = true; }
  el("photo-input").value = ""; el("photo-remove").hidden = true;
}
window.addEventListener("pagehide", dropPhoto);

async function start() {
  if (!pid) { fail(new Error("Ouvrez ce parcours depuis le lien reçu après l'identification de votre véhicule.")); return; }
  try { applyState(await call("")); } catch (e) { fail(e); return; }
  const v = state.vehicle;
  el("vir-vehicle").textContent = [v.manufacturer, v.model, v.generation].filter(Boolean).join(" · ");
  const ct = el("consent-text"); ct.replaceChildren(...state.consent_text.map(t => make("p", t)));
  selected = new Set(state.selection);
  if (state.phase === "vir") show("screen-vir");
  else if (!state.consent) show("screen-consent");
  else await openCatalogue();
}

el("vir-continue").onclick = async () => { try { applyState(await call("/vir-seen", {})); show("screen-consent"); } catch (e) { fail(e); } };
el("consent-continue").onclick = async () => {
  try {
    const s = await call("/consent", {accepted: el("consent-box").checked});
    applyState(s);
    if (!s.consent) { el("consent-message").textContent = s.message; return; }
    show("screen-photo");
  } catch (e) { fail(e); }
};
el("photo-input").onchange = () => {
  const f = el("photo-input").files[0];
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photoUrl = f ? URL.createObjectURL(f) : null;   // local object URL: the file is never sent
  for (const id of ["photo-preview", "photo-compare"]) { if (photoUrl) el(id).src = photoUrl; el(id).hidden = !photoUrl; }
  el("photo-remove").hidden = !photoUrl;
};
el("photo-remove").onclick = dropPhoto;
el("photo-continue").onclick = () => openCatalogue().catch(fail);

function updateCount() {
  el("selection-count").textContent = String(selected.size);
  el("selection-continue").disabled = selected.size === 0;
}
async function openCatalogue() {
  const c = await call("/catalogue");
  noticeLang = c.document.language || "en";
  selected = new Set(c.selection);
  const grid = el("catalogue-grid"); grid.replaceChildren();
  for (const e of c.entries) {
    const t = make("button", null, "tile");
    t.type = "button"; t.dataset.entryId = e.entry_id;
    t.setAttribute("aria-pressed", selected.has(e.entry_id) ? "true" : "false");
    const img = make("img"); img.src = e.image; img.alt = e.alt; img.lang = noticeLang; t.append(img, make("span", "n° " + (e.manual_order + 1), "n"));
    t.onclick = () => {
      if (selected.has(e.entry_id)) selected.delete(e.entry_id); else selected.add(e.entry_id);
      t.setAttribute("aria-pressed", selected.has(e.entry_id) ? "true" : "false"); updateCount();
    };
    grid.append(t);
  }
  updateCount(); show("screen-catalogue");
}
el("selection-continue").onclick = async () => {
  try {
    const s = await call("/selection", {entry_ids: [...selected]}); applyState(s);
    const g = el("confirmation-grid"); g.replaceChildren();
    for (const c of s.chosen) { const d = make("div", null, "tile"); d.dataset.entryId = c.entry_id; const i = make("img"); i.src = c.image; i.alt = c.alt; i.lang = noticeLang; d.append(i); g.append(d); }
    show("screen-confirmation");
  } catch (e) { fail(e); }
};
function exact(segments, tag) {
  const n = make(tag || "div", null, "exact");
  for (const s of segments) {
    if (s.text !== undefined) n.append(document.createTextNode(s.text));
    else { const i = make("img"); i.src = s.pictogram; i.alt = "[pictogramme imprimé, p. " + s.printed_page + "]"; n.append(i); }
  }
  n.lang = noticeLang; return n;
}
function field(article, label, value) {
  if (value == null) return;
  const p = make("div"); p.append(make("span", label + " : ", "label"));
  const v = make("span", value, "exact"); p.append(v); article.append(p);
}
function manufacturer(article, label, value) {   // manufacturer text: notice language, untranslated
  if (value == null) return;
  const p = make("div"); p.append(make("span", label + " : ", "label"));
  const v = make("span", value, "exact"); v.lang = noticeLang; p.append(v); article.append(p);
}
// Premier Constat: every string comes from the server (approved banners and
// labels, or verbatim manufacturer text); nothing is composed here.
function sec(parent, title, cls) { const s = make("div", null, cls); s.append(make("h3", title)); parent.append(s); return s; }
// Folded « Détails »: purely technical uncertainties only (the server decides the placement).
function detailsBox(label) { const d = make("details", null, "details"); d.append(make("summary", label)); return d; }
function flush(parent, d) { if (d.children.length > 1) parent.append(d); }
function quote(parent, text) { const q = make("blockquote", text); q.lang = noticeLang; parent.append(q); }
function renderEntry(e, block, headingLabel) {
    const h = make("p", null, "selected"); h.append(make("strong", headingLabel));
    const d = make("span", e.designation); d.lang = noticeLang; h.append(d); block.append(h);
    const det = detailsBox(e.details_label);
    if (e.explanation) {
      const ex = make("div", null, "explanation");
      if (e.explanation.mention) (e.explanation.mention_placement === "details" ? det : ex).append(make("p", e.explanation.mention, "draft-mention"));
      for (const part of e.explanation.parts) {
        const s = sec(ex, part.title, "part-" + part.key);
        for (const sen of part.sentences) {
          const pp = make("p", sen.text); const c = make("span", " « " + sen.citation + " »", "citation"); c.lang = noticeLang;
          pp.append(c); s.append(pp);
        }
      }
      block.append(ex);
    }
    if (e.situation) renderSituation(e.situation, block, det);
    for (const pt of e.points) {
      const s = sec(pt.placement === "details" ? det : block, pt.title, "point point-" + pt.key);
      if (pt.label) s.append(make("p", pt.label, "point-label"));
      for (const q of pt.quotes) quote(s, q);
    }
    if (e.stop_conditions.length) { const rs = sec(block, "Restrictions / conditions d'arrêt", "restrictions"); for (const sc of e.stop_conditions) quote(rs, sc); }
    const mt = sec(block, "Ce que dit le constructeur", "manufacturer-text");
    mt.append(make("p", e.manufacturer_text.label));
    for (const v of [e.manufacturer_text.documented_meaning, e.manufacturer_text.documented_instruction,
                     e.manufacturer_text.displayed_message]) if (v) quote(mt, v);
    for (const w of e.manufacturer_text.linked_warnings) {
      const q = make("blockquote", null, "linked-warning"); q.append(make("strong", "Avertissement " + w.number + " "));
      const s = make("span", w.text); s.lang = noticeLang; q.append(s); mt.append(q);
    }
    flush(block, det);
}
function cite(parent, a, cls) {
    const q = make("blockquote", null, cls); const t = make("span", a.text); t.lang = noticeLang; q.append(t);
    q.append(make("span", " — page de la notice " + a.printed_page + " (page PDF " + a.pdf_page + ")", "page"));
    parent.append(q);
}
function renderSituation(st, block, det) {
    const s = sec(block, "Type de situation : " + st.label, "situation situation-" + st.nature);
    if (st.mention) { const m = make("p", st.mention, "draft-mention"); if (st.mention_placement === "details") det.append(m); else s.insertBefore(m, s.firstChild); }
    s.dataset.nature = st.nature;
    if (st.title) s.append(make("p", st.title, "situation-title"));
    s.append(make("p", "Passage qui le justifie :", "label")); cite(s, st.justification, "justification");
    for (const c of st.conditions) { const t = c.placement === "details" ? det : s; t.append(make("p", "Conditions d'application :", "label")); cite(t, c, "condition-quote"); }
    for (const c of st.consignes) {
      s.append(make("p", (c.label || "Consigne du constructeur") + (c.conditional ? "" : " :"),
                    c.action ? "label action-label" : c.conditional ? "label conditional-label" : "label"));
      if (c.condition) cite(s, c.condition, "consigne-condition");
      cite(s, c.consigne, "consigne");
      if (c.conditional && c.key && condQ) conditionQuestion(s, c, condQ);
    }
    if (st.no_consigne) s.append(make("p", st.no_consigne, "no-consigne"));
}
function conditionQuestion(parent, pa, q) {
    const box = make("div", null, "condition-question"); box.dataset.key = pa.key; box.dataset.answer = pa.answer;
    box.append(make("p", q.question, "label"));
    for (const k of ["confirmed", "excluded", "unknown"]) {
      const b = make("button", q[k], "condition-" + k); if (pa.answer === k) b.classList.add("primary");
      b.onclick = async () => { try { outcome(await call("/condition", {key: pa.key, answer: k})); } catch (e) { fail(e); } };
      box.append(b);
    }
    box.append(make("p", pa.answer_label, "condition-answer")); parent.append(box);
}
function renderAmbiguous(b, root, redScreen) {
    const box = make("div", null, "ambiguous"); box.dataset.group = b.group; root.append(box);
    const img = make("img"); img.src = b.image; img.alt = ""; box.append(img);
    const det = detailsBox(b.details_label);
    if (b.group_draft) (b.group_draft_placement === "details" ? det : box).append(make("p", b.group_draft, "draft-mention group-draft"));
    (b.draft_texts_placement === "details" ? det : box).append(make("p", b.draft_texts, "draft-mention"));
    box.append(make("p", b.limit, "limit"));
    if (b.message_given) {
      const m = make("p", b.message_given.label, "message-given"); m.append(make("strong", "« " + b.message_given.text + " »")); box.append(m);
    }
    if (b.situations.length) {
      const ss = sec(box, "Ce que décrit la notice pour chaque possibilité", "described");
      for (const x of b.situations) {
        const d = make("div", null, "described-variant"); d.dataset.entryId = x.entry_id; ss.append(d);
        d.append(make("p", x.only_for, "label"));
        d.append(make("p", "Type de situation : " + x.situation.label, "described-type nature-" + x.situation.nature));
        cite(d, x.situation.justification, "described-quote");
      }
    }
    if (b.urgent.length) {
      // Urgent instructions of the variants not excluded, each under its own variant.
      const us = sec(box, b.urgent_title, "urgent");
      for (const u of b.urgent) {
        const d = make("div", null, "urgent-variant"); d.dataset.entryId = u.entry_id; us.append(d);
        const h = make("p", u.only_for, "label"); d.append(h);
        for (const pa of u.passages) cite(d, {text: pa.text, printed_page: pa.printed_page, pdf_page: pa.pdf_page});
      }
    }
    if (b.actions.length) {
      const as = sec(box, b.action_title, "expected-action");
      for (const u of b.actions) {
        const d = make("div", null, "action-variant"); d.dataset.entryId = u.entry_id; as.append(d);
        d.append(make("p", u.only_for, "label"));
        for (const pa of u.passages) {
          if (pa.condition) { d.append(make("p", b.condition_label + " :", "label")); cite(d, pa.condition, "action-condition"); }
          cite(d, {text: pa.text, printed_page: pa.printed_page, pdf_page: pa.pdf_page}, "action-quote");
        }
      }
    }
    if (b.conditionals.length) {
      const cs2 = sec(box, b.conditional_title, "conditional");
      for (const u of b.conditionals) {
        const d = make("div", null, "conditional-variant"); d.dataset.entryId = u.entry_id; cs2.append(d);
        d.append(make("p", u.only_for, "label"));
        for (const pa of u.passages) {
          d.append(make("p", b.condition_label + " :", "label")); cite(d, pa.condition, "conditional-condition");
          cite(d, {text: pa.text, printed_page: pa.printed_page, pdf_page: pa.pdf_page}, "conditional-quote");
          conditionQuestion(d, pa, b.condition_question);
        }
      }
    }
    const cs = sec(box, b.common_title, "common");
    if (b.no_common) cs.append(make("p", b.no_common, "no-common"));
    for (const c of b.common) {
      quote(cs, c.text);
      cs.append(make("p", c.sources.map(s => "n° " + (s.manual_order + 1) + " — " + s.field + ", page de la notice "
                                        + s.printed_page + " (page PDF " + s.pdf_page + ")").join(" ; "), "page"));
    }
    for (const v of b.variants) {
      const vb = make("div", null, "variant finding-entry"); vb.dataset.entryId = v.entry.entry_id; box.append(vb);
      const cond = make("p", v.condition.label + " : état du voyant « " + v.condition.state + " » · message affiché « "
                        + v.condition.displayed_message + " »", "condition");
      renderEntry(v.entry, vb, v.only_for_label);
      vb.insertBefore(cond, vb.children[1] || null);
      vb.append(buildArticle(v.section));
    }
    if (b.red_offer) {
      const btn = make("button", b.red_offer, "red-offer");
      btn.onclick = () => showScreen(redScreen); box.append(btn);
    }
    flush(box, det);
}
let condQ = null;
function renderConstat(pc) {
  const p = pc.presentation, root = el("premier-constat"); root.replaceChildren();
  condQ = p.condition_question;
  root.append(make("h1", p.title));
  if (p.stops_confirmed.length) {
    const cb = sec(root, p.stops_confirmed_title, "confirmed-stops");
    const cdet = detailsBox(p.details_label);
    (p.draft_texts_placement === "details" ? cdet : cb).append(make("p", p.draft_texts, "draft-mention"));
    for (const x of p.stops_confirmed) {
      const d = make("div", null, "confirmed-stop"); d.dataset.key = x.key; cb.append(d);
      d.append(make("p", x.only_for, "label"));
      d.append(make("p", x.condition_label, "label")); if (x.condition) cite(d, x.condition, "confirmed-condition");
      cite(d, x.citation, "confirmed-citation"); d.append(make("p", x.answer_label, "condition-answer"));
    }
    flush(cb, cdet);
  }
  for (const e of p.entries) {
    const block = make("div", null, "finding-entry"); block.dataset.entryId = e.entry_id; root.append(block);
    renderEntry(e, block, e.selected_label + " : ");
  }
  for (const b of p.ambiguous) renderAmbiguous(b, root, p.red_screen);
  if (p.stops.length) {
    const sb = sec(root, p.stops_title, "stops");
    const sdet = detailsBox(p.details_label);
    (p.draft_texts_placement === "details" ? sdet : sb).append(make("p", p.draft_texts, "draft-mention"));
    for (const x of p.stops) {
      const d = make("div", null, "stop-item"); d.dataset.key = x.key; d.dataset.answer = x.answer; sb.append(d);
      d.append(make("p", x.only_for, "label"));
      d.append(make("p", x.condition_label, "label")); if (x.condition) cite(d, x.condition, "stop-condition");
      cite(d, x.citation, "stop-citation");
      conditionQuestion(d, x, {...condQ, question: p.stop_question});
    }
    flush(sb, sdet);
  }
  const src = el("part1-sources"); src.replaceChildren();
  if (p.sources.length) { const s = sec(src, "Source", "source"); for (const line of p.sources) s.append(make("p", line)); }
  el("part1-t8").textContent = p.end;
}
function renderQuestions(s) {
  const root = el("clarification-questions"); root.replaceChildren();
  for (const q of s.questions) {
    const box = make("div", null, "question"); box.dataset.group = q.group;
    const img = make("img"); img.src = q.image; img.alt = ""; box.append(img);
    if (q.kind === "message") {
      box.dataset.kind = "message";
      box.append(make("p", q.draft_texts, "draft-mention"));
      const lab = make("label", q.question); const inp = make("input"); inp.type = "text"; inp.maxLength = 200;
      inp.className = "message-input"; lab.append(document.createElement("br"), inp); box.append(lab);
      const ok = make("button", q.submit, "message-submit");
      ok.onclick = () => { if (inp.value.trim()) clarify(q.group, "message", inp.value); };
      const no = make("button", q.none, "message-none"); no.onclick = () => clarify(q.group, "dont_know");
      box.append(ok, no); root.append(box); continue;
    }
    for (const c of q.choices) {
      const b = make("button", null, "choice"); b.dataset.entryId = c.entry_id;
      b.append(make("span", c.elements.map(x => x.label + " : " + x.value).join(" · "), "choice-label"));
      const src = make("span", " — page de la notice " + c.source.page_reference + " (page PDF " + c.source.pdf_page + ") : ", "choice-source");
      const t = make("span", "« " + c.source.text + " »"); t.lang = noticeLang; src.append(t); b.append(src);
      b.onclick = () => clarify(q.group, c.entry_id); box.append(b);
    }
    const dk = make("button", "Je ne sais pas"); dk.className = "dont-know-variant"; dk.onclick = () => clarify(q.group, "dont_know");
    const nn = make("button", "Aucun de ceux-ci"); nn.className = "none-variant"; nn.onclick = () => clarify(q.group, "none");
    box.append(dk, nn); root.append(box);
  }
  show("screen-clarification");
}
async function clarify(group, answer, message) {
  try { outcome(await call("/clarify", message === undefined ? {group, answer} : {group, answer, message})); } catch (e) { fail(e); }
}
function showColour(s) {
  const box = el("colour-choices"); box.replaceChildren();
  for (const c of s.colours) { const b = make("button", c.label); b.dataset.colour = c.key; if (s.colour === c.key) b.classList.add("primary"); b.onclick = () => chooseColour(c.key); box.append(b); }
  show("screen-colour");
}
function outcome(s) {
  applyState(s);
  if (s.phase === "clarification") return renderQuestions(s);
  if (s.phase === "colour") return showColour(s);
  renderRestitution(s);
}
el("confirm").onclick = async () => {
  try { outcome(await call("/confirm", {entry_ids: state.selection, confirmed: true})); } catch (e) { fail(e); }
};
function buildArticle(x) {
      const a = make("article", null, "restitution"); a.dataset.entryId = x.entry_id;
      const img = make("img"); img.src = x.image; img.alt = x.designation; a.append(img);
      const h = make("h2", x.designation); h.lang = noticeLang; a.append(h);
      const tags = make("p");
      if (x.where_provided) tags.append(make("span", "selon équipement", "tag where-provided"));
      if (x.startup_check) tags.append(make("span", "s'allume au démarrage", "tag startup-check"));
      a.append(tags);
      a.append(make("p", "Page de la notice : " + x.page_reference + " (page PDF " + x.pdf_page + ")", "page"));
      field(a, "Couleur", x.colour); field(a, "État", x.state); manufacturer(a, "Descripteur", x.symbol_descriptor);
      a.append(make("div", "Texte de la notice :", "label")); const m = exact(x.meaning); m.classList.add("meaning"); a.append(m);
      manufacturer(a, "Consigne", x.instruction);
      manufacturer(a, "Message affiché", x.displayed_message); manufacturer(a, "Signal sonore", x.audible_signal);
      if (x.startup_check) { const sc = make("div"); sc.className = "startup-text"; sc.append(make("span", "Au démarrage : ", "label"));
        const t = make("span", x.startup_check, "exact"); t.lang = noticeLang; sc.append(t); a.append(sc); }
      for (const fs of x.field_sources) {
        const q = make("p", "Source du champ « " + fs.field + " » : page de la notice " + fs.printed_page + " (page PDF " + fs.pdf_page + ") — ", "page");
        const t = make("span", fs.text); t.lang = noticeLang; q.append(t); a.append(q);
      }
      if (x.warnings.length) {
        a.append(make("h3", "Avertissements liés"));
        for (const w of x.warnings) {
          const wd = make("div", null, "warning"); wd.append(make("span", "Avertissement " + w.number + " ", "label"));
          wd.append(exact(w.text)); wd.append(make("p", "Page de la notice : " + w.printed_page + " (page PDF " + w.pdf_page + ")", "page"));
          a.append(wd);
        }
      }
      return a;
}
function renderRestitution(s) {
    noticeLang = s.document.language || "en";
    const doc = el("restitution-document"); doc.textContent = s.document.title + " — " + s.document.edition; doc.lang = noticeLang;
    const ln = el("language-note"); ln.textContent = s.document.language_note || ""; ln.hidden = !s.document.language_note;
    renderConstat(s.premier_constat);
    const root = el("restitution"); root.replaceChildren();
    for (const x of s.sections) root.append(buildArticle(x));
    show("screen-restitution");
}
async function noMatch(reason) {
  try {
    const s = await call("/no-match", {reason, entry_ids: [...selected]}); applyState(s);
    showColour(s);
  } catch (e) { fail(e); }
}
el("none-match").onclick = () => noMatch("none_match");
el("dont-know").onclick = () => noMatch("dont_know");
function showScreen(screen) {
    const box = el("fallback-content"); box.replaceChildren(make("h1", screen.heading));
    box.dataset.screen = screen.key;
    for (const p of screen.paragraphs) box.append(make("p", p));
    show("screen-fallback");
}
async function chooseColour(key) {
  try {
    const s = await call("/colour", {colour: key}); applyState(s);
    const box = el("fallback-content"); box.replaceChildren(make("h1", s.screen.heading));
    box.dataset.screen = s.screen.key;
    for (const p of s.screen.paragraphs) box.append(make("p", p));
    show("screen-fallback");
  } catch (e) { fail(e); }
}
document.querySelectorAll("button.return").forEach(b => b.onclick = async () => {
  try { applyState(await call("/return", {})); await openCatalogue(); } catch (e) { fail(e); }
});
start();
</script>
</body>
</html>
"""
