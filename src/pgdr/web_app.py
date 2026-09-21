"""PGDR Web Application — minimum FastAPI adapter around existing PGDR core.

This module exposes the existing certified PGDR lifecycle online via HTTP.
It does NOT modify diagnostic semantics, scoring, evidence, or governance.
All diagnostic reasoning remains in the existing SessionController/DiagnosticLoop.

Architecture: Browser → FastAPI → SessionController → existing PGDR core
Session model: In-memory server-side sessions (requires single-process deployment)
UI language: French only
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Dict

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pgdr.enums import (
    DrivingStatus, ResolutionStatus, SessionState, TechnicalLevel,
    Urgency, VehicleLocation, VehicleState,
)
from pgdr.errors import ConfigurationError
from pgdr.models import (
    Answer, Consent, DiagnosticSession, InitialComplaint,
    PreGarageDiagnosticRequest, UserContext, VehicleIdentityContext,
)
from pgdr.readiness import check_readiness
from pgdr.session_controller import SessionController


# --- Request/Response models for HTTP API ---

class StartSessionRequest(BaseModel):
    """HTTP request to start a new diagnostic session."""
    complaint: str = Field(..., min_length=1, max_length=5000, description="Free-text vehicle problem description")
    vehicle_location: str = Field(default="home", description="Where is the vehicle")
    vehicle_state: str = Field(default="engine_off", description="Vehicle current state")
    urgency: str = Field(default="unknown", description="Perceived urgency")
    driving_status: str = Field(default="parked", description="Can user drive")
    technical_level: str = Field(default="low", description="User technical knowledge")
    vir_id: str = Field(default="WEB-VIR-UNRESOLVED", description="Vehicle identity resolution ID")


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
        _session_controller = SessionController()
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

@app.post("/api/session/start")
def start_session(req: StartSessionRequest):
    """Start a new diagnostic session. Returns session_id and initial state."""
    try:
        controller = _get_or_create_controller()
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PGDR configuration invalide : {exc}",
        ) from None

    # Create PGDR request from HTTP input
    request_id = f"PGDR-WEB-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
    pgdr_request = PreGarageDiagnosticRequest(
        request_id=request_id,
        locale="fr-FR",  # French only (Section 9)
        vehicle_identity_context=VehicleIdentityContext(
            resolution_id=req.vir_id,
            resolution_status=ResolutionStatus.PROVISIONALLY_RESOLVED,
        ),
        initial_complaint=InitialComplaint(
            free_text=req.complaint,
            current_vehicle_location=VehicleLocation(req.vehicle_location),
            vehicle_current_state=VehicleState(req.vehicle_state),
            perceived_urgency=Urgency(req.urgency),
        ),
        user_context=UserContext(
            driving_status=DrivingStatus(req.driving_status),
            technical_level=TechnicalLevel(req.technical_level),
        ),
        consent=Consent(
            media_analysis_allowed=False,
            report_storage_allowed=False,
        ),
    )

    # Start session through existing PGDR core
    session = controller.start(pgdr_request)
    session_id = session.session_id
    _sessions[session_id] = session

    # Return session state
    return {
        "session_id": session_id,
        "state": session.state.value,
        "escalated": session.state == SessionState.ESCALATED,
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

    if session.state == SessionState.ESCALATED:
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


# --- Frontend (French HTML UI) ---

@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    """Serve the French HTML UI."""
    return """<!DOCTYPE html>
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
        <p class="subtitle">Structurez votre problème véhicule avant de contacter un garage</p>

        <div class="disclaimer">
            <strong>⚠️ PGDR ne fournit jamais un diagnostic mécanique définitif</strong>
            PGDR vous aide à structurer et documenter un problème véhicule. Il ne remplace pas l'examen professionnel d'un mécanicien qualifié. Les observations produites sont des hypothèses compatibles avec les symptômes décrits, nécessitant toujours une vérification professionnelle.
        </div>

        <!-- Initial form -->
        <div id="initial-form">
            <div class="form-group">
                <label for="complaint">Décrivez le problème que vous rencontrez avec votre véhicule :</label>
                <textarea id="complaint" placeholder="Exemple : La voiture tremble au ralenti, surtout moteur chaud..." required></textarea>
            </div>

            <div class="form-group">
                <label for="location">Où se trouve actuellement le véhicule ?</label>
                <select id="location">
                    <option value="home">Domicile</option>
                    <option value="roadside">Bord de route</option>
                    <option value="parking">Parking</option>
                    <option value="work">Travail</option>
                    <option value="garage">Garage</option>
                </select>
            </div>

            <div class="form-group">
                <label for="urgency">Urgence perçue :</label>
                <select id="urgency">
                    <option value="unknown">Je ne sais pas</option>
                    <option value="low">Faible</option>
                    <option value="medium">Modérée</option>
                    <option value="high">Élevée</option>
                </select>
            </div>

            <button id="start-btn" onclick="startSession()">Démarrer l'analyse</button>
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
        let sessionId = null;
        let currentQuestion = null;

        async function startSession() {
            const complaint = document.getElementById('complaint').value.trim();
            if (!complaint) {
                showError('Veuillez décrire le problème véhicule');
                return;
            }

            showLoading();
            hideError();

            try {
                const response = await fetch('/api/session/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        complaint: complaint,
                        vehicle_location: document.getElementById('location').value,
                        urgency: document.getElementById('urgency').value,
                    }),
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Erreur lors du démarrage');
                }

                const data = await response.json();
                sessionId = data.session_id;

                document.getElementById('initial-form').classList.add('hidden');
                hideLoading();

                if (data.escalated && data.safety_triage) {
                    showSafetyAlert(data.safety_triage);
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
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
