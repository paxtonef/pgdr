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
    Part1Mapping, build_manufacturer_first_finding, compose_triage, load_part1_mapping, raised_instructions,
)
from pgdr.application.photo_first import warning_indicator_from_entry
from pgdr.errors import ConfigurationError
from pgdr.models import Consent, DiagnosticSession, InitialComplaint, PreGarageDiagnosticRequest
from pgdr.safety_engine import SafetyEngine
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
        findings, findings_status = {}, "absent"
        if repo is not None and os.environ.get("PGDR_V1_FINDINGS"):
            try:
                findings = load_v1_findings(os.environ["PGDR_V1_FINDINGS"], repo)
                findings_status = "validated"
            except ConfigurationError as exc:
                findings_status = f"refused: {exc}"
        _wiring = V1Wiring(repository=repo, dev_trial=dev, dev_vehicle=vehicle, error=error,
                           findings=findings, findings_status=findings_status)
    return _wiring


@dataclass
class Parcours:
    vehicle: dict
    consent: bool = False
    selection: list[str] = field(default_factory=list)  # entry_ids, manual order
    confirmed: bool = False
    colour: Optional[str] = None
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


def premier_constat(p: Parcours) -> dict:
    """The existing Part 1 chain on the driver's confirmed selection."""
    global _safety_engine
    from pgdr.web_app import present_first_finding  # lazy: web_app mounts this router
    if _safety_engine is None:
        _safety_engine = SafetyEngine()
    w = get_wiring()
    c = _catalogue()
    live = {e.entry_id: e for e in w.repository.entries_for_document(c.document.document_id)}
    chosen = [live[x] for x in p.selection]
    session = DiagnosticSession(request=PreGarageDiagnosticRequest(
        request_id=f"PGDR-V1-{uuid.uuid4().hex[:12]}",
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id="V1-PARCOURS", resolution_status="resolved", vehicle_identity=p.vehicle),
        initial_complaint=InitialComplaint(free_text=""),
        # The optional photo is never analysed nor kept.
        consent=Consent(media_analysis_allowed=False, report_storage_allowed=False),
    ))
    session.warning_indicators = [warning_indicator_from_entry(e, photo_evidence_id=None) for e in chosen]
    engine = _safety_engine.evaluate(session)
    finding = build_manufacturer_first_finding(
        [(e, "user_selection") for e in chosen], mapping=w.findings,
        linked_warnings={x: [lw.text for lw in c.entry(x).linked_warnings] for x in p.selection},
    )
    triage, rows = compose_triage(engine, finding, raised_instruction=raised_instructions(finding))
    return {
        "presentation": present_first_finding(finding),
        "triage": {"level": triage.level.value, "driving_assessment": triage.driving_assessment.value,
                   "engine_level": engine.level.value, "triggered_rules": list(triage.triggered_rules),
                   "r5_rows": rows},
        "classification_status": w.findings_status,
        # Verbatim linked warnings, shown inside the synthesis next to the
        # manufacturer text: a stop instruction printed in a note must never
        # appear only below a « non établi » label.
        "linked_warnings": {x: [{"number": lw.number, "text": lw.text} for lw in c.entry(x).linked_warnings]
                            for x in p.selection},
    }


@router.post("/api/v1/parcours/{pid}/confirm")
def confirm(pid: str, req: ConfirmRequest):
    p = _get(pid)
    _require_consent(p)
    if p.phase != "confirmation" or not req.confirmed or _validated_selection(req.entry_ids) != p.selection:
        raise HTTPException(status_code=409, detail="Confirmation explicite de la sélection affichée requise.")
    p.confirmed = True
    p.phase = "restitution"
    c = _catalogue()
    return {**_state(pid, p), "document": _document(c), "premier_constat": premier_constat(p),
            "sections": [_section(pid, c.entry(x)) for x in p.selection]}


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
function quote(parent, text) { const q = make("blockquote", text); q.lang = noticeLang; parent.append(q); }
function renderConstat(pc) {
  const p = pc.presentation, root = el("premier-constat"); root.replaceChildren();
  if (p.banner.length) {
    const b = make("div"); b.id = "part1-t2"; b.append(make("strong", p.banner[0]));
    for (const line of p.banner.slice(1)) b.append(make("p", line));
    root.append(b);
  }
  if (p.entries.length) {
    const ident = sec(root, "Voyant identifié", "identified"); const ul = make("ul");
    for (const e of p.entries) {
      const li = make("li"); li.dataset.entryId = e.entry_id; li.dataset.origin = e.identified.origin;
      const d = make("span", e.identified.designation); d.lang = noticeLang;
      li.append(d, document.createTextNode(" — " + e.identified.origin_text)); ul.append(li);
    }
    ident.append(ul);
  }
  for (const e of p.entries) {
    const block = make("div", null, "finding-entry"); block.dataset.entryId = e.entry_id; root.append(block);
    const mt = sec(block, "Ce que dit le constructeur", "manufacturer-text");
    mt.append(make("p", e.manufacturer_text.label));
    for (const v of [e.manufacturer_text.documented_meaning, e.manufacturer_text.documented_instruction,
                     e.manufacturer_text.displayed_message]) if (v) quote(mt, v);
    for (const w of (pc.linked_warnings[e.entry_id] || [])) {
      const q = make("blockquote", null, "linked-warning"); q.append(make("strong", "Avertissement " + w.number + " "));
      const s = make("span", w.text); s.lang = noticeLang; q.append(s); mt.append(q);
    }
    if (e.immediate_safety.length) { const s = sec(block, "Sécurité immédiate", "immediate-safety"); for (const l of e.immediate_safety) s.append(make("p", l)); }
    sec(block, "Utilisation du véhicule", "vehicle-use").append(make("p", e.vehicle_use));
    const r = e.restrictions;
    if (r.stop_conditions.length || r.figures.length) {
      const rs = sec(block, "Restrictions / conditions d'arrêt", "restrictions");
      for (const sc of r.stop_conditions) quote(rs, sc);
      for (const f of r.figures) { quote(rs, f.figure); if (f.caution) rs.append(make("p", f.caution)); }
    }
    if (e.professional) {
      const ps = sec(block, "Intervention d'un professionnel", "professional"); ps.append(make("p", e.professional.label));
      if (e.professional.documented_suitability) quote(ps, e.professional.documented_suitability);
    }
    if (e.practical.label || e.practical.notice.length) {
      const pa = sec(block, "Assistance pratique", "practical"); pa.dataset.requirement = e.practical.requirement;
      if (e.practical.label) pa.append(make("p", e.practical.label));
      for (const line of e.practical.notice) pa.append(make("p", line));
    }
    if (e.not_established.length) {
      const ne = sec(block, "Points non établis par la notice", "not-established"); const ul = make("ul");
      for (const l of e.not_established) ul.append(make("li", l)); ne.append(ul);
      if (p.legend) ne.append(make("p", p.legend, "legend"));
    }
  }
  const src = el("part1-sources"); src.replaceChildren();
  if (p.sources.length) { const s = sec(src, "Source", "source"); for (const line of p.sources) s.append(make("p", line)); }
  el("part1-t8").textContent = p.end;
}
el("confirm").onclick = async () => {
  try {
    const s = await call("/confirm", {entry_ids: state.selection, confirmed: true}); applyState(s);
    noticeLang = s.document.language || "en";
    const doc = el("restitution-document"); doc.textContent = s.document.title + " — " + s.document.edition; doc.lang = noticeLang;
    const ln = el("language-note"); ln.textContent = s.document.language_note || ""; ln.hidden = !s.document.language_note;
    renderConstat(s.premier_constat);
    const root = el("restitution"); root.replaceChildren();
    for (const x of s.sections) {
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
      root.append(a);
    }
    show("screen-restitution");
  } catch (e) { fail(e); }
};
async function noMatch(reason) {
  try {
    const s = await call("/no-match", {reason, entry_ids: [...selected]}); applyState(s);
    const box = el("colour-choices"); box.replaceChildren();
    for (const c of s.colours) { const b = make("button", c.label); b.dataset.colour = c.key; if (s.colour === c.key) b.classList.add("primary"); b.onclick = () => chooseColour(c.key); box.append(b); }
    show("screen-colour");
  } catch (e) { fail(e); }
}
el("none-match").onclick = () => noMatch("none_match");
el("dont-know").onclick = () => noMatch("dont_know");
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
