"""PGDR Web Application — minimum FastAPI adapter around existing PGDR core.

This module exposes the existing certified PGDR lifecycle online via HTTP.
It does NOT modify diagnostic semantics, scoring, evidence, or governance.
All diagnostic reasoning remains in the existing SessionController/DiagnosticLoop.

Architecture: Browser → FastAPI → SessionController → existing PGDR core
Session model: In-memory server-side sessions (requires single-process deployment)
UI language: French only
"""
from __future__ import annotations

import importlib
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pgdr.enums import (
    DrivingStatus, SessionState, TechnicalLevel,
    Urgency, VehicleLocation, VehicleState,
)
from pgdr.errors import ConfigurationError
from pgdr.models import (
    Answer, Consent, DiagnosticSession, InitialComplaint,
    PreGarageDiagnosticRequest, UserContext, VehicleIdentityContext,
)
from pgdr.adapters.peugeot_dashboard_knowledge import PeugeotDashboardKnowledgeAdapter
from pgdr.application.interpretation_validation import InterpretationValidationError
from pgdr.application.photo_first import PhotoPhase, PhotoStep, UserSelectionError
from pgdr.application.vehicle_applicability import resolve_dashboard_reference
from pgdr.domain.dashboard_knowledge import ApplicabilityStatus, DashboardReferenceSet
from pgdr.domain.media import MediaType
from pgdr.ports.dashboard_interpretation import DashboardInterpretationPort, MatchStatus
from pgdr.ports.knowledge_repository import KnowledgeRepositoryPort
from pgdr.ports.media_resolver import MediaResolutionError, MediaResolverPort, ResolvedMedia
from pgdr.readiness import check_readiness
from pgdr.session_controller import SessionController


# --- Request/Response models for HTTP API ---

class SubmitAnswerRequest(BaseModel):
    """HTTP request to submit an answer to a question."""
    question_id: str
    value: bool | str | int | float | list[str] | None


# --- In-memory session store ---
# Production deployment MUST use single-process/single-instance topology
# to preserve session continuity (Section 11.2)

_sessions: Dict[str, DiagnosticSession] = {}
_session_controller: SessionController | None = None


def _get_or_create_controller() -> SessionController:
    """Lazy SessionController initialization. Raises ConfigurationError
    (including GovernanceUnavailableError) if PGDR cannot start."""
    global _session_controller
    if _session_controller is None:
        _session_controller = SessionController(
            dashboard_interpretation_port=_get_photo_wiring().interpretation_provider,
        )
    return _session_controller


# --- FastAPI application ---

app = FastAPI(
    title="PGDR — Pré-Garage Diagnostic Runner",
    description="Outil d'aide à la structuration d'un problème véhicule avant le garage",
    version="2.0.0",
)


# --- Health/Readiness endpoint ---

@app.get("/health")
def health_check():
    """Readiness check. Returns 200 if PGDR is READY to accept diagnostic work,
    503 if NOT READY. Production requirement: GGM must be available and loadable."""
    report = check_readiness()
    if report.ready:
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "checks": report.as_dict()["checks"]},
        )
    else:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "reason": report.reason.value,
                "checks": report.as_dict()["checks"],
            },
        )


# --- Session API endpoints ---

@app.get("/api/session/{session_id}/state")
def get_session_state(session_id: str):
    """Get current session state (questions, safety triage, etc.)."""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expirée")

    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "escalated": session.state == SessionState.ESCALATED,
        "completed": session.state == SessionState.COMPLETED,
        "safety_triage": (
            {
                "level": session.safety_triage.level.value,
                "user_instruction": session.safety_triage.user_instruction,
                "emergency_services_required": session.safety_triage.emergency_services_required,
                "roadside_assistance_recommended": session.safety_triage.roadside_assistance_recommended,
            }
            if session.safety_triage
            else None
        ),
        "pending_questions": [
            {
                "question_id": q.question_id,
                "prompt": q.prompt,
                "answer_type": q.answer_type.value,
                "choices": q.choices,
                "selection_reason": q.selection_reason,
            }
            for q in session.pending_questions
        ],
    }


@app.post("/api/session/{session_id}/answer")
def submit_answer(session_id: str, req: SubmitAnswerRequest):
    """Submit an answer to the current question."""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expirée")

    if session.state == SessionState.ESCALATED and not session.pending_questions:
        raise HTTPException(status_code=400, detail="Session déjà terminée (signal de sécurité)")

    if session.state == SessionState.COMPLETED:
        raise HTTPException(status_code=400, detail="Session déjà terminée")

    if not session.pending_questions:
        raise HTTPException(status_code=400, detail="Aucune question en attente")

    # Validate question_id
    if not any(q.question_id == req.question_id for q in session.pending_questions):
        raise HTTPException(status_code=400, detail="Question invalide")

    try:
        controller = _get_or_create_controller()
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=f"PGDR indisponible : {exc}") from None

    # Submit answer through existing PGDR core
    answer = Answer(question_id=req.question_id, value=req.value)
    session = controller.submit_answer(session, answer)
    _sessions[session_id] = session

    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "completed": session.state == SessionState.COMPLETED,
        "pending_questions": [
            {
                "question_id": q.question_id,
                "prompt": q.prompt,
                "answer_type": q.answer_type.value,
                "choices": q.choices,
                "selection_reason": q.selection_reason,
            }
            for q in session.pending_questions
        ],
    }


@app.get("/api/session/{session_id}/report")
def get_report(session_id: str):
    """Get the final diagnostic report (only available when session is completed or escalated)."""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expirée")

    if session.state not in (SessionState.COMPLETED, SessionState.ESCALATED):
        raise HTTPException(status_code=400, detail="Rapport pas encore disponible")

    if session.result is None:
        raise HTTPException(status_code=500, detail="Résultat manquant")

    # Return the existing PGDR report structure (governed by GGM if enabled)
    return {
        "user_summary": session.result.user_summary.model_dump(mode="json"),
        "garage_preparation_report": session.result.garage_preparation_report.model_dump(mode="json"),
    }


# --- Photo-first entry (B2 completion: E1-E5) ---
#
# The dashboard photograph is the mandatory initial input. Consent for media
# analysis must accompany it; without consent PGDR does not start. No image
# leaves this process: analysis goes through the injected
# DashboardInterpretationPort, and NO external provider is authorized. When no
# provider/knowledge repository is configured the photo path reports that
# plainly instead of failing or falling back to ungoverned interpretation.

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
_MAX_IMAGE_BYTES = 15 * 1024 * 1024

CONSENT_DECLINED_MESSAGE = (
    "PGDR ne peut pas démarrer sans votre accord pour analyser la photo. "
    "Le point de départ de PGDR est la photo de votre tableau de bord : c'est elle qui permet "
    "d'identifier le voyant concerné, sans que vous ayez à décrire le problème. "
    "Votre accord porte uniquement sur l'analyse de cette photo pour ce diagnostic : "
    "il n'autorise ni l'envoi de la photo à un service extérieur, ni sa conservation, "
    "ni son utilisation à d'autres fins. Vous pouvez réessayer à tout moment en donnant votre accord."
)
PHOTO_UNAVAILABLE_MESSAGE = (
    "L'analyse de photo n'est pas disponible dans cette installation de PGDR : "
    "aucun service d'interprétation ou aucune base de références constructeur n'est configuré. "
    "Ce n'est pas une erreur de votre part et rien n'a été envoyé ni conservé."
)
VEHICLE_NOT_SUPPORTED_MESSAGE = (
    "Aucune notice constructeur disponible pour ce véhicule : PGDR ne peut pas interpréter "
    "la photo de son tableau de bord de façon fiable. Aucune interprétation n'a été tentée "
    "et la photo n'a pas été analysée."
)
REFERENCE_UNAVAILABLE_MESSAGE = (
    "La notice constructeur applicable à ce véhicule n'a pas pu être déterminée avec certitude : "
    "PGDR n'interprète pas la photo sans référence constructeur établie. La photo n'a pas été analysée."
)
VEHICLE_IDENTITY_INSUFFICIENT_MESSAGE = (
    "L'identification du véhicule reçue ne suffit pas pour choisir la notice constructeur applicable. "
    "L'identification du véhicule se fait avant PGDR, qui ne la complète pas : "
    "la photo n'a pas été analysée."
)


@dataclass
class PhotoWiring:
    """What the deployment injects for the photo path. Both default to None
    (photo analysis unavailable). NO real external vision provider exists or
    is authorized; a deterministic test provider is an integration-test
    mechanism only, never a real-world visual capability."""
    interpretation_provider: Optional[DashboardInterpretationPort] = None
    knowledge_repository: Optional[KnowledgeRepositoryPort] = None


_photo_wiring: PhotoWiring | None = None


def _get_photo_wiring() -> PhotoWiring:
    """Loaded once from PGDR_PHOTO_WIRING_FACTORY ("package.module:callable"
    returning a PhotoWiring) when set; otherwise an empty wiring."""
    global _photo_wiring
    if _photo_wiring is None:
        target = os.environ.get("PGDR_PHOTO_WIRING_FACTORY")
        if target:
            module_name, _, attr = target.partition(":")
            _photo_wiring = getattr(importlib.import_module(module_name), attr)()
        else:
            _photo_wiring = PhotoWiring()
    return _photo_wiring


class InMemoryMediaStore:
    """Real MediaResolverPort implementation for the web layer. Bytes live in
    process memory only, and are discarded right after analysis: media-analysis
    consent does NOT authorize persistent retention. References are opaque,
    server-generated and never derived from client input."""

    def __init__(self) -> None:
        self._items: Dict[str, ResolvedMedia] = {}

    def store(self, content: bytes, content_type: str) -> str:
        if content_type not in _ALLOWED_IMAGE_TYPES:
            raise MediaResolutionError(f"unsupported media type: {content_type!r}")
        if not content:
            raise MediaResolutionError("empty upload")
        if len(content) > _MAX_IMAGE_BYTES:
            raise MediaResolutionError("upload too large")
        reference = f"media-{uuid.uuid4().hex}"
        self._items[reference] = ResolvedMedia(content=content, media_type=MediaType.IMAGE, reference=reference)
        return reference

    def resolve(self, reference: str) -> ResolvedMedia:
        try:
            return self._items[reference]
        except KeyError:
            raise MediaResolutionError(f"no stored media for reference {reference!r}") from None

    def discard(self, reference: str) -> None:
        self._items.pop(reference, None)

    def __len__(self) -> int:
        return len(self._items)


_media_store = InMemoryMediaStore()
assert isinstance(_media_store, MediaResolverPort)


@dataclass
class PhotoIntake:
    """Pre-session photo-intake state: the VIR identity artifact handed over
    by PI, the manufacturer reference it resolved to, and the driver's
    consent. It is NOT a PGDR session: PGDR starts only when the first
    dashboard photograph is submitted. Its id becomes the PGDR session id at
    that moment. Isolated per intake by construction."""
    identity: VehicleIdentityContext
    reference_set: DashboardReferenceSet
    consent_media_analysis: bool = False


_photo_intakes: Dict[str, PhotoIntake] = {}

# PI -> PGDR identity handoff credential. Unset means the handoff is closed:
# the browser can never introduce a vehicle identity of its own.
IDENTITY_HANDOFF_TOKEN_ENV = "PGDR_IDENTITY_HANDOFF_TOKEN"
IDENTITY_HANDOFF_TOKEN_HEADER = "X-PGDR-Identity-Handoff-Token"


class PhotoSessionRequest(BaseModel):
    intake_id: str = Field(max_length=64)
    consent_media_analysis: bool = False


class SymbolSelectionRequest(BaseModel):
    entry_id: Optional[str] = None


def _photo_knowledge_adapter() -> PeugeotDashboardKnowledgeAdapter:
    return PeugeotDashboardKnowledgeAdapter(repository=_get_photo_wiring().knowledge_repository)


def _resolve_reference_set(identity: VehicleIdentityContext) -> DashboardReferenceSet:
    return resolve_dashboard_reference(identity, _photo_knowledge_adapter())


def _require_handoff_credential(request: Request) -> None:
    expected = os.environ.get(IDENTITY_HANDOFF_TOKEN_ENV)
    if not expected:
        raise HTTPException(status_code=503, detail="Identity handoff is not configured on this PGDR instance.")
    supplied = request.headers.get(IDENTITY_HANDOFF_TOKEN_HEADER) or ""
    if not secrets.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Identity handoff refused.")


def _session_payload(session: DiagnosticSession) -> dict:
    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "escalated": session.state == SessionState.ESCALATED,
        "completed": session.state == SessionState.COMPLETED,
        "safety_triage": (
            {
                "level": session.safety_triage.level.value,
                "user_instruction": session.safety_triage.user_instruction,
                "emergency_services_required": session.safety_triage.emergency_services_required,
                "roadside_assistance_recommended": session.safety_triage.roadside_assistance_recommended,
            }
            if session.safety_triage else None
        ),
        "pending_questions": [
            {
                "question_id": q.question_id, "prompt": q.prompt, "answer_type": q.answer_type.value,
                "choices": q.choices, "selection_reason": q.selection_reason,
            }
            for q in session.pending_questions
        ],
    }


_SELECTION_MESSAGES = {
    MatchStatus.AMBIGUOUS_MATCH: (
        "Plusieurs voyants du constructeur ressemblent à celui de votre photo. "
        "Indiquez celui qui correspond, ou « aucun de ceux-là »."
    ),
    MatchStatus.NO_MATCH: (
        "Aucun voyant de la notice constructeur n'a été reconnu sur la photo. "
        "Vous pouvez indiquer le voyant dans la liste ci-dessous, ou « aucun de ceux-là »."
    ),
    MatchStatus.INSUFFICIENT_VISUAL_QUALITY: (
        "La photo reste inexploitable. Vous pouvez indiquer le voyant dans la liste ci-dessous, "
        "ou « aucun de ceux-là »."
    ),
}


def _step_response(session: DiagnosticSession, step: PhotoStep) -> dict:
    payload = _session_payload(session)
    payload["photo_phase"] = step.phase.value
    payload["retakes_used"] = step.retakes_used
    payload["retakes_remaining"] = step.retakes_remaining
    if step.phase == PhotoPhase.RETAKE_REQUESTED:
        payload["status"] = "retake_requested"
        payload["message"] = (
            "La photo n'est pas assez lisible. Reprenez-la (bonne lumière, tableau de bord net) — "
            f"il reste {step.retakes_remaining} nouvelle(s) tentative(s) avant de choisir le voyant dans la liste."
        )
    elif step.phase == PhotoPhase.SELECTION_REQUIRED:
        payload["status"] = "selection_required"
        payload["trigger"] = step.trigger.value
        payload["message"] = _SELECTION_MESSAGES[step.trigger]
        # Recognition data only: never the manufacturer's documented meaning.
        payload["options"] = [
            {
                "entry_id": e.entry_id, "designation": e.manufacturer_designation,
                "symbol_descriptor": e.symbol_descriptor, "colour": e.colour,
                "state": e.state.value if e.state else None, "displayed_message": e.displayed_message,
            }
            for e in step.offer.entries
        ]
    else:
        payload["status"] = "analysed"
    return payload


_UNAVAILABLE_REFERENCE_OUTCOMES = {
    ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT: ("vehicle_identity_insufficient", VEHICLE_IDENTITY_INSUFFICIENT_MESSAGE),
    ApplicabilityStatus.DOCUMENTATION_NOT_AVAILABLE: ("vehicle_not_supported", VEHICLE_NOT_SUPPORTED_MESSAGE),
}


@app.post("/api/photo/identity-handoff")
def receive_identity_handoff(identity: VehicleIdentityContext, request: Request):
    """PI -> PGDR: the VIR identity artifact (PI map_resolution() output) for
    a Photo-First intake. Server-to-server only (credential required): the
    vehicle identity is VIR's responsibility and never typed by the driver.
    Resolves the manufacturer reference the photo will be read against; an
    intake is created only when that reference is established."""
    _require_handoff_credential(request)
    wiring = _get_photo_wiring()
    if wiring.interpretation_provider is None or wiring.knowledge_repository is None:
        return {"status": "photo_analysis_unavailable", "message": PHOTO_UNAVAILABLE_MESSAGE}

    reference_set = _resolve_reference_set(identity)
    if reference_set.applicability_status != ApplicabilityStatus.REFERENCE_SET_AVAILABLE:
        status, message = _UNAVAILABLE_REFERENCE_OUTCOMES.get(
            reference_set.applicability_status, ("reference_unavailable", REFERENCE_UNAVAILABLE_MESSAGE),
        )
        return {
            "status": status, "message": message,
            "applicability_status": reference_set.applicability_status.value,
            "provenance_note": reference_set.provenance_note,
        }

    # No PGDR session exists yet: PGDR starts when the first photo arrives.
    intake_id = f"SESS-{uuid.uuid4().hex[:12].upper()}"
    _photo_intakes[intake_id] = PhotoIntake(identity=identity, reference_set=reference_set)
    return {"status": "awaiting_consent", "intake_id": intake_id}


@app.post("/api/photo/session")
def start_photo_session(req: PhotoSessionRequest):
    """The driver's step: consent to analysing the dashboard photo, for an
    intake whose vehicle identity was already handed over from VIR via PI.
    Without consent nothing starts."""
    intake = _photo_intakes.get(req.intake_id)
    if intake is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expirée")
    if not req.consent_media_analysis:
        return {"status": "consent_required", "message": CONSENT_DECLINED_MESSAGE}
    intake.consent_media_analysis = True
    return {"status": "awaiting_photo", "intake_id": req.intake_id}


@app.post("/api/photo/{session_id}/media")
async def submit_photo(session_id: str, request: Request):
    """The real media-ingress boundary: the raw image bytes are the request
    body (Content-Type = the image type). They are stored, resolved through
    the real MediaResolverPort, interpreted through the injected
    DashboardInterpretationPort behind the governed B2 chain, then discarded."""
    intake = _photo_intakes.get(session_id)
    if intake is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expirée")
    if not intake.consent_media_analysis:
        raise HTTPException(status_code=400, detail="La photo n'est pas attendue à ce stade.")
    controller = _get_or_create_controller()
    session = _sessions.get(session_id)
    if session is not None:
        ps = controller.photo_case_state(session)
        if ps.phase not in (PhotoPhase.AWAITING_PHOTO, PhotoPhase.RETAKE_REQUESTED):
            raise HTTPException(status_code=400, detail="La photo n'est pas attendue à ce stade.")

    content = await request.body()
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    try:
        reference = _media_store.store(content, content_type)
    except MediaResolutionError:
        raise HTTPException(
            status_code=400,
            detail="Fichier non accepté : envoyez une photo JPEG, PNG, WebP ou HEIC de moins de 15 Mo.",
        ) from None
    try:
        if session is None:
            # PGDR STARTS HERE, and only here: a consented intake plus a
            # dashboard photograph that passed transport validation.
            session = _start_photo_session(controller, session_id, intake)
            _sessions[session_id] = session
        step = controller.acquire_photo(
            session, media_reference=reference, resolver=_media_store, reference_set=intake.reference_set,
        )
    except (MediaResolutionError, InterpretationValidationError):
        raise HTTPException(status_code=502, detail="L'analyse de la photo n'a pas pu aboutir (erreur technique).") from None
    finally:
        # Consent does not authorize retention: the bytes are dropped now.
        _media_store.discard(reference)
    _sessions[session_id] = session
    return _step_response(session, step)


def _start_photo_session(controller: SessionController, session_id: str, intake: PhotoIntake) -> DiagnosticSession:
    request_id = f"PGDR-WEB-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
    pgdr_request = PreGarageDiagnosticRequest(
        request_id=request_id,
        locale="fr-FR",
        vehicle_identity_context=intake.identity,  # the VIR artifact, verbatim (PGDR-ID-001/002)
        initial_complaint=InitialComplaint(free_text=""),
        consent=Consent(media_analysis_allowed=intake.consent_media_analysis, report_storage_allowed=False),
    )
    return controller.start_photo_case(pgdr_request, session_id=session_id)


@app.post("/api/photo/{session_id}/decline-retake")
def decline_retake(session_id: str):
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expirée")
    controller = _get_or_create_controller()
    try:
        step = controller.decline_retake(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail="Aucune nouvelle photo n'est demandée.") from exc
    return _step_response(session, step)


@app.post("/api/photo/{session_id}/selection")
def submit_symbol_selection(session_id: str, req: SymbolSelectionRequest):
    """E5: the driver's own selection from the manufacturer symbol list.
    Recorded with USER provenance -- never as a machine-verified match."""
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session inconnue ou expirée")
    controller = _get_or_create_controller()
    try:
        step = controller.record_user_symbol_selection(session, entry_id=req.entry_id)
    except UserSelectionError:
        raise HTTPException(status_code=400, detail="Ce voyant ne figure pas dans la liste proposée.") from None
    except RuntimeError:
        raise HTTPException(status_code=400, detail="Aucun choix de voyant n'est attendu.") from None
    _sessions[session_id] = session
    return _step_response(session, step)


# --- Frontend (French HTML UI): the ONLY page. The dashboard photograph is the
# mandatory initial input; there is no text-first entry into PGDR. ---

_PHOTO_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PGDR — Pré-Garage Diagnostic Runner</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 2em;
        }
        h2 {
            color: #34495e;
            margin: 25px 0 15px 0;
            font-size: 1.3em;
        }
        .subtitle {
            color: #7f8c8d;
            margin-bottom: 25px;
        }
        .disclaimer {
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin-bottom: 25px;
            font-size: 0.95em;
        }
        .disclaimer strong {
            display: block;
            margin-bottom: 8px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #2c3e50;
        }
        input[type="text"],
        textarea,
        select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1em;
            font-family: inherit;
        }
        textarea {
            min-height: 120px;
            resize: vertical;
        }
        button {
            background: #3498db;
            color: white;
            border: none;
            padding: 12px 30px;
            font-size: 1em;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
        }
        button:hover {
            background: #2980b9;
        }
        button:disabled {
            background: #95a5a6;
            cursor: not-allowed;
        }
        .question-box {
            background: #ecf0f1;
            padding: 20px;
            border-radius: 6px;
            margin-bottom: 20px;
        }
        .question-prompt {
            font-size: 1.1em;
            font-weight: 600;
            margin-bottom: 15px;
            color: #2c3e50;
        }
        .question-reason {
            font-size: 0.9em;
            color: #7f8c8d;
            margin-bottom: 15px;
            font-style: italic;
        }
        .choices {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .choice-btn {
            background: white;
            border: 2px solid #3498db;
            color: #3498db;
            padding: 12px;
            text-align: left;
            border-radius: 4px;
            cursor: pointer;
            font-size: 1em;
            transition: all 0.2s;
        }
        .choice-btn:hover {
            background: #3498db;
            color: white;
        }
        .safety-alert {
            background: #f8d7da;
            border-left: 4px solid #dc3545;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 4px;
        }
        .safety-alert h2 {
            color: #721c24;
            margin-top: 0;
        }
        .safety-instruction {
            font-size: 1.1em;
            font-weight: 600;
            margin: 15px 0;
        }
        .report-section {
            margin-bottom: 25px;
        }
        .report-section h3 {
            color: #2c3e50;
            margin-bottom: 10px;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }
        .report-section ul {
            list-style-position: inside;
            padding-left: 0;
        }
        .report-section li {
            margin: 8px 0;
        }
        .report-disclaimer {
            background: #e8f4f8;
            border-left: 4px solid #17a2b8;
            padding: 15px;
            margin-top: 20px;
            font-size: 0.9em;
        }
        .hidden {
            display: none;
        }
        .loading {
            text-align: center;
            padding: 20px;
            color: #7f8c8d;
        }
        .error {
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>PGDR — Pré-Garage Diagnostic Runner</h1>
        <p class="subtitle">Photographiez le tableau de bord : PGDR prépare la suite</p>

        <div class="disclaimer">
            <strong>⚠️ PGDR ne fournit jamais un diagnostic mécanique définitif</strong>
            PGDR vous aide à structurer et documenter un problème véhicule. Il ne remplace pas l'examen professionnel d'un mécanicien qualifié. Les observations produites sont des hypothèses compatibles avec les symptômes décrits, nécessitant toujours une vérification professionnelle.
        </div>

        <!-- Photo-first entry -->
        <div id="photo-flow">
            <div id="consent-step">
                <p><strong>Étape 1 — Votre accord</strong></p>
                <p class="question-reason">Votre véhicule a déjà été identifié : la photo de votre tableau de bord
                    sera lue avec la notice de son constructeur. Vous n'avez pas à décrire de problème.</p>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="consent-checkbox">
                        J'autorise PGDR à analyser la photo que je fournis, pour ce diagnostic uniquement.
                        Cet accord n'autorise ni l'envoi de la photo à un service extérieur, ni sa conservation,
                        ni son utilisation à d'autres fins.
                    </label>
                </div>
                <button id="photo-start-btn" onclick="startPhotoSession()">Continuer</button>
            </div>

            <div id="consent-message" class="disclaimer hidden"></div>
            <div id="photo-notice" class="disclaimer hidden"></div>

            <div id="photo-step" class="hidden">
                <p><strong>Étape 2 — La photo de votre tableau de bord</strong></p>
                <p class="question-reason">Photographiez le tableau de bord avec le ou les voyants allumés.</p>
                <div class="form-group">
                    <input type="file" id="photo-input" accept="image/*" capture="environment">
                </div>
                <button id="photo-btn" onclick="submitPhoto()">Envoyer la photo pour analyse</button>
            </div>

            <div id="retake-step" class="hidden">
                <p id="retake-message"></p>
                <button id="decline-retake-btn" class="choice-btn" onclick="declineRetake()">
                    Je ne peux pas reprendre la photo — choisir le voyant dans la liste</button>
            </div>

            <div id="selection-step" class="hidden">
                <p id="selection-message"></p>
                <div id="selection-options" class="choices"></div>
                <div class="choices"><button id="symbol-none-btn" class="choice-btn" onclick="submitSelection(null)">Aucun de ceux-là</button></div>
            </div>
        </div>

        <!-- Loading state -->
        <div id="loading" class="loading hidden">
            <p>Analyse en cours...</p>
        </div>

        <!-- Error display -->
        <div id="error" class="error hidden"></div>

        <!-- Safety escalation -->
        <div id="safety-alert" class="safety-alert hidden"></div>

        <!-- Question display -->
        <div id="question-container" class="hidden"></div>

        <!-- Report display -->
        <div id="report-container" class="hidden"></div>
    </div>

    <script>
        // The intake is created upstream, from the VIR vehicle identity handed
        // over by PI; this page never asks for the vehicle.
        let sessionId = new URLSearchParams(window.location.search).get('intake');
        let currentQuestion = null;

        function showSafetyAlert(triage) {
            const alertDiv = document.getElementById('safety-alert');
            let html = '<h2>⚠️ Signal de sécurité détecté</h2>';
            html += `<p><strong>Niveau :</strong> ${triage.level}</p>`;
            if (triage.user_instruction) {
                html += `<p class="safety-instruction">${triage.user_instruction}</p>`;
            }
            if (triage.emergency_services_required) {
                html += '<p style="color: #dc3545; font-weight: bold;">→ APPELEZ LES SECOURS</p>';
            }
            if (triage.roadside_assistance_recommended) {
                html += '<p style="color: #ffc107; font-weight: bold;">→ Assistance dépannage recommandée</p>';
            }
            alertDiv.innerHTML = html;
            alertDiv.classList.remove('hidden');
        }

        function showQuestion(question) {
            currentQuestion = question;
            const container = document.getElementById('question-container');

            let html = '<div class="question-box">';
            html += `<div class="question-prompt">${question.prompt}</div>`;
            if (question.selection_reason) {
                html += `<div class="question-reason">${question.selection_reason}</div>`;
            }

            if (question.answer_type === 'yes_no') {
                html += '<div class="choices">';
                html += '<button class="choice-btn" onclick="submitAnswer(true)">Oui</button>';
                html += '<button class="choice-btn" onclick="submitAnswer(false)">Non</button>';
                html += '</div>';
            } else if (question.answer_type === 'single_choice' && question.choices) {
                html += '<div class="choices">';
                for (const choice of question.choices) {
                    html += `<button class="choice-btn" onclick="submitAnswer('${escapeHtml(choice)}')">${escapeHtml(choice)}</button>`;
                }
                html += '</div>';
            } else {
                html += '<input type="text" id="text-answer" placeholder="Votre réponse">';
                html += '<br><br><button onclick="submitTextAnswer()">Valider</button>';
            }

            html += '</div>';
            container.innerHTML = html;
            container.classList.remove('hidden');
        }

        async function submitAnswer(value) {
            if (!sessionId || !currentQuestion) return;

            showLoading();
            document.getElementById('question-container').classList.add('hidden');
            hideError();

            try {
                const response = await fetch(`/api/session/${sessionId}/answer`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        question_id: currentQuestion.question_id,
                        value: value,
                    }),
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Erreur lors de la soumission');
                }

                const data = await response.json();
                hideLoading();

                if (data.completed) {
                    await loadReport();
                } else if (data.pending_questions && data.pending_questions.length > 0) {
                    showQuestion(data.pending_questions[0]);
                } else {
                    await loadReport();
                }
            } catch (error) {
                hideLoading();
                showError(error.message);
            }
        }

        async function submitTextAnswer() {
            const value = document.getElementById('text-answer').value.trim();
            if (!value) {
                showError('Veuillez saisir une réponse');
                return;
            }
            await submitAnswer(value);
        }

        async function loadReport() {
            if (!sessionId) return;

            showLoading();
            hideError();

            try {
                const response = await fetch(`/api/session/${sessionId}/report`);
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Erreur lors du chargement du rapport');
                }

                const data = await response.json();
                hideLoading();
                showReport(data);
            } catch (error) {
                hideLoading();
                showError(error.message);
            }
        }

        function showReport(data) {
            const container = document.getElementById('report-container');
            const us = data.user_summary;
            const gpr = data.garage_preparation_report;

            let html = "<h2>📋 Synthèse pour l'automobiliste</h2>";
            html += '<div class="report-section">';
            if (us.urgency && us.urgency.label) {
                html += `<h3>Urgence</h3>`;
                html += `<p><strong>${us.urgency.label}</strong></p>`;
                if (us.urgency.explanation) {
                    html += `<p>${us.urgency.explanation}</p>`;
                }
            }
            if (us.main_observations && us.main_observations.length > 0) {
                html += '<h3>Observations principales</h3><ul>';
                for (const obs of us.main_observations) {
                    html += `<li>${obs}</li>`;
                }
                html += '</ul>';
            }
            if (us.next_actions && us.next_actions.length > 0) {
                html += '<h3>Actions recommandées</h3><ul>';
                for (const action of us.next_actions) {
                    html += `<li>${action}</li>`;
                }
                html += '</ul>';
            }
            html += '</div>';

            html += '<h2>🔧 Rapport de préparation garage</h2>';
            html += '<div class="report-section">';
            html += `<p><strong>Problème signalé :</strong> ${gpr.customer_reported_problem}</p>`;

            if (gpr.systems_to_examine && gpr.systems_to_examine.length > 0) {
                html += '<h3>Systèmes à examiner</h3><ul>';
                for (const sys of gpr.systems_to_examine) {
                    html += `<li>${sys.system_family} (confiance : ${sys.confidence})</li>`;
                }
                html += '</ul>';
            }

            if (gpr.suggested_professional_checks && gpr.suggested_professional_checks.length > 0) {
                html += '<h3>Contrôles suggérés</h3><ul>';
                for (const check of gpr.suggested_professional_checks) {
                    html += `<li>${check}</li>`;
                }
                html += '</ul>';
            }

            if (gpr.unresolved_questions && gpr.unresolved_questions.length > 0) {
                html += '<h3>Questions ouvertes</h3><ul>';
                for (const q of gpr.unresolved_questions) {
                    html += `<li>${q}</li>`;
                }
                html += '</ul>';
            }

            html += '</div>';

            if (us.disclaimer && us.disclaimer.length > 0) {
                html += '<div class="report-disclaimer">';
                html += '<strong>Important :</strong> ' + us.disclaimer.join(' ');
                html += '</div>';
            }

            container.innerHTML = html;
            container.classList.remove('hidden');
        }

        function showLoading() {
            document.getElementById('loading').classList.remove('hidden');
        }

        function hideLoading() {
            document.getElementById('loading').classList.add('hidden');
        }

        function showError(message) {
            const errorDiv = document.getElementById('error');
            errorDiv.textContent = message;
            errorDiv.classList.remove('hidden');
        }

        function hideError() {
            document.getElementById('error').classList.add('hidden');
        }

        function escapeHtml(unsafe) {
            return unsafe
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        function show(id) { document.getElementById(id).classList.remove('hidden'); }
        function hide(id) { document.getElementById(id).classList.add('hidden'); }
        function hidePhotoSteps() {
            ['consent-step','photo-step','retake-step','selection-step'].forEach(hide);
        }
        function photoNotice(message) {
            const n = document.getElementById('photo-notice');
            n.textContent = message;
            n.classList.remove('hidden');
        }

        async function photoPost(url, body, headers) {
            const response = await fetch(url, {method: 'POST', headers: headers || {'Content-Type': 'application/json'}, body: body});
            const data = await response.json();
            if (!response.ok) { throw new Error(data.detail || 'Erreur'); }
            return data;
        }

        async function startPhotoSession() {
            hideError(); hide('consent-message'); hide('photo-notice');
            showLoading();
            try {
                const data = await photoPost('/api/photo/session', JSON.stringify({
                    intake_id: sessionId,
                    consent_media_analysis: document.getElementById('consent-checkbox').checked,
                }));
                hideLoading();
                handlePhotoStatus(data);
            } catch (error) { hideLoading(); showError(error.message); }
        }

        function handlePhotoStatus(data) {
            if (data.intake_id) { sessionId = data.intake_id; }
            if (data.session_id) { sessionId = data.session_id; }
            hide('photo-step'); hide('retake-step'); hide('selection-step');
            if (data.status === 'consent_required') {
                const c = document.getElementById('consent-message');
                c.textContent = data.message; c.classList.remove('hidden');
            } else if (data.status === 'awaiting_photo') {
                hide('consent-step'); hide('photo-notice'); show('photo-step');
            } else if (data.status === 'retake_requested') {
                document.getElementById('retake-message').textContent = data.message;
                show('photo-step'); show('retake-step');
                document.getElementById('photo-input').value = '';
            } else if (data.status === 'selection_required') {
                showSelection(data);
            } else if (data.status === 'analysed') {
                hidePhotoSteps(); hide('photo-notice');
                document.getElementById('photo-flow').classList.add('hidden');
                if (data.escalated && data.safety_triage) { showSafetyAlert(data.safety_triage); }
                if (data.pending_questions && data.pending_questions.length > 0) {
                    showQuestion(data.pending_questions[0]);
                } else {
                    loadReport();
                }
            }
        }

        async function submitPhoto() {
            hideError();
            const file = document.getElementById('photo-input').files[0];
            if (!file) { showError('Veuillez choisir ou prendre une photo du tableau de bord'); return; }
            showLoading();
            try {
                const data = await photoPost(`/api/photo/${sessionId}/media`, file, {'Content-Type': file.type});
                hideLoading(); handlePhotoStatus(data);
            } catch (error) { hideLoading(); showError(error.message); }
        }

        async function declineRetake() {
            hideError(); showLoading();
            try {
                const data = await photoPost(`/api/photo/${sessionId}/decline-retake`, '{}');
                hideLoading(); handlePhotoStatus(data);
            } catch (error) { hideLoading(); showError(error.message); }
        }

        function showSelection(data) {
            hide('photo-step'); hide('retake-step');
            document.getElementById('selection-message').textContent = data.message;
            const box = document.getElementById('selection-options');
            box.innerHTML = '';
            for (const o of data.options) {
                const label = [o.designation, o.symbol_descriptor, o.colour, o.state, o.displayed_message]
                    .filter(Boolean).join(' — ');
                const b = document.createElement('button');
                b.className = 'choice-btn symbol-option';
                b.setAttribute('data-entry-id', o.entry_id);
                b.textContent = label;
                b.onclick = () => submitSelection(o.entry_id);
                box.appendChild(b);
            }
            show('selection-step');
        }

        async function submitSelection(entryId) {
            hideError(); showLoading();
            try {
                const data = await photoPost(`/api/photo/${sessionId}/selection`, JSON.stringify({entry_id: entryId}));
                hideLoading(); hide('selection-step'); handlePhotoStatus(data);
            } catch (error) { hideLoading(); showError(error.message); }
        }

        const _baseShowReport = showReport;
        showReport = function(data) {
            _baseShowReport(data);
            const ids = (data.garage_preparation_report && data.garage_preparation_report.dashboard_identifications) || [];
            if (ids.length === 0) { return; }
            let html = '<div class="report-section" id="dashboard-identifications"><h3>Voyants du tableau de bord</h3><ul>';
            for (const i of ids) {
                const origin = i.origin === 'user_selection'
                    ? 'indiqué par vous dans la liste du constructeur (non vérifié sur la photo)'
                    : 'identifié sur la photo et rapproché de la notice du constructeur';
                html += `<li data-origin="${escapeHtml(i.origin)}">${escapeHtml(i.description)} — ${origin}</li>`;
            }
            html += '</ul></div>';
            document.getElementById('report-container').insertAdjacentHTML('beforeend', html);
        };

        if (!sessionId) {
            hide('consent-step');
            photoNotice("Aucun véhicule identifié pour ce diagnostic. L'identification du véhicule se fait "
                        + "avant PGDR : ouvrez PGDR depuis le lien reçu après l'identification de votre véhicule.");
        }
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def serve_photo_first_frontend():
    """Primary entry point: the dashboard photograph is the mandatory
    initial input. No complaint text, location or urgency is asked up front."""
    return _PHOTO_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
