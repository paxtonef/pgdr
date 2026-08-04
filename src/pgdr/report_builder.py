"""Report Builders — Garage Preparation Report + User Summary (AMD pack 18, 19).

PGDR-AC-010: the garage report (technical, for the professional) and the
user summary (simplified, for the driver) must remain distinct objects.
PGDR-BR-012: no repair cost is ever estimated here.
"""
from __future__ import annotations

from pgdr.enums import ReportStatus, ResolutionStatus, TriageLevel
from pgdr.models import (
    DiagnosticSession, GaragePreparationReport, PreGarageDiagnosticResult,
    SafetyTriage, UserSummary,
)

_URGENCY_COPY = {
    TriageLevel.EMERGENCY_STOP.value: (
        "Arrêt immédiat requis",
        "Ne roulez pas. Appelez les secours ou une dépanneuse.",
    ),
    TriageLevel.DO_NOT_DRIVE.value: (
        "Ne pas conduire",
        "Le véhicule ne doit pas être déplacé par ses propres moyens.",
    ),
    TriageLevel.LIMITED_MOVEMENT_ONLY.value: (
        "Déplacement limité uniquement",
        "Ne déplacez le véhicule qu'en cas de nécessité absolue et avec précaution.",
    ),
    TriageLevel.PROMPT_INSPECTION.value: (
        "Inspection rapide recommandée",
        "Présentez le véhicule à un garage rapidement.",
    ),
    TriageLevel.STANDARD_APPOINTMENT.value: (
        "Rendez-vous standard",
        "Prenez rendez-vous pour un contrôle dans un délai raisonnable.",
    ),
    TriageLevel.MONITOR_AND_DOCUMENT.value: (
        "Surveillance",
        "Continuez à observer et documenter le symptôme jusqu'au prochain contrôle.",
    ),
}


class ReportBuilder:
    def build(self, session: DiagnosticSession) -> PreGarageDiagnosticResult:
        req = session.request
        triage = session.safety_triage or SafetyTriage()

        garage_report = self._build_garage_report(session, triage)
        user_summary = self._build_user_summary(session, triage)
        status = self._determine_status(session, triage)

        return PreGarageDiagnosticResult(
            request_id=req.request_id,
            status=status,
            vehicle_identity_summary={
                "resolution_id": req.vehicle_identity_context.resolution_id,
                "resolution_status": req.vehicle_identity_context.resolution_status.value,
            },
            user_complaint={
                "raw_text": req.initial_complaint.free_text,
                "structured_summary": "Voir symptom_summary dans le rapport garage.",
            },
            symptoms=session.symptoms,
            operating_conditions=session.operating_conditions,
            recent_events=session.events,
            warning_indicators=session.warning_indicators,
            evidence_summary=session.evidence,
            safety_triage=triage,
            diagnostic_hypotheses=session.hypotheses,
            contradictions=session.contradictions,
            unresolved_questions=garage_report.unresolved_questions,
            garage_preparation_report=garage_report,
            user_summary=user_summary,
            limitations=garage_report.limitations,
            trace={"transitions": session.trace},
        )

    def _build_garage_report(self, session: DiagnosticSession, triage: SafetyTriage) -> GaragePreparationReport:
        req = session.request
        limitations = [
            "Aucune inspection physique n'a été réalisée.",
            "Ce document prépare le diagnostic mais ne remplace pas l'examen du véhicule par un professionnel.",
        ]
        if req.vehicle_identity_context.resolution_status in (
            ResolutionStatus.AMBIGUOUS, ResolutionStatus.INSUFFICIENT_DATA, ResolutionStatus.CONTRADICTORY,
        ):
            limitations.append(
                "L'identité du véhicule est incertaine — le raisonnement spécifique au véhicule est limité "
                "(PGDR-BR-001 / PGDR-ID-003)."
            )
        limitations.extend(session.limitations)

        return GaragePreparationReport(
            vehicle={
                "identity_resolution_id": req.vehicle_identity_context.resolution_id,
                "resolution_status": req.vehicle_identity_context.resolution_status.value,
                **(req.vehicle_identity_context.vehicle_identity or {}),
            },
            customer_reported_problem=req.initial_complaint.free_text,  # verbatim — PGDR-BR-003
            symptom_summary=[
                {
                    "family": s.family.value,
                    "description": s.user_description,
                    "frequency": s.frequency.value,
                    "severity": s.severity.value,
                    "source": s.source.value,
                }
                for s in session.symptoms
            ],
            onset_and_evolution={
                "first_observed_at": (
                    req.initial_complaint.first_observed_at.isoformat()
                    if req.initial_complaint.first_observed_at else None
                ),
                "frequency": session.symptoms[0].frequency.value if session.symptoms else "unknown",
            },
            reproduction_conditions=(
                {
                    "reproducible": session.reproduction_profile.reproducible,
                    "recurrence": session.reproduction_profile.recurrence,
                    "engine_state": session.operating_conditions.engine_state if session.operating_conditions else "unknown",
                }
                if session.reproduction_profile else None
            ),
            warning_indicators=[
                {"label": wi.label, "color": wi.observed_color.value, "behavior": wi.behavior.value}
                for wi in session.warning_indicators
            ],
            safety_information={
                "triage_level": triage.level.value,
                "critical_signal_detected": triage.level.value in ("emergency_stop", "do_not_drive"),
                "statement": triage.user_instruction,
                "driving_assessment": triage.driving_assessment.value,
            },
            recent_vehicle_events=[
                {"type": e.event_type, "description": e.description, "relation": e.relation_to_symptom.value}
                for e in session.events
            ],
            evidence_index=[
                {"id": ev.evidence_id, "type": ev.evidence_type, "description": ev.user_description}
                for ev in session.evidence
            ],
            systems_to_examine=[
                {
                    "system_family": h.system_family,
                    "confidence": h.confidence.value,
                    "description": h.description,
                }
                for h in session.hypotheses
            ],
            suggested_professional_checks=[
                chk for h in session.hypotheses for chk in h.recommended_professional_checks
            ],
            unresolved_questions=[
                "L'origine exacte du symptôme nécessite une inspection physique.",
                "La reproduction du symptôme en atelier reste à confirmer.",
            ],
            contradictions=[
                {"fields": c.fields, "severity": c.severity.value, "impact": c.impact.value}
                for c in session.contradictions
            ],
            limitations=limitations,
        )

    def _build_user_summary(self, session: DiagnosticSession, triage: SafetyTriage) -> UserSummary:
        label, explanation = _URGENCY_COPY.get(
            triage.level.value, _URGENCY_COPY[TriageLevel.MONITOR_AND_DOCUMENT.value]
        )
        return UserSummary(
            urgency={"label": label, "explanation": explanation},
            main_observations=[s.user_description for s in session.symptoms if s.is_primary],
            next_actions=[
                "Conservez toute preuve disponible (photo, son, vidéo).",
                "Prévenez le garage des symptômes décrits avant le rendez-vous.",
                "Ne tentez pas de démonter ou de toucher des composants du véhicule.",
            ],
            disclaimer=[
                "Ce document prépare le diagnostic mais ne remplace pas l'examen du véhicule par un professionnel qualifié.",
                "Aucune réparation spécifique n'est recommandée avec certitude, et aucun coût n'est estimé.",
            ],
        )

    @staticmethod
    def _determine_status(session: DiagnosticSession, triage: SafetyTriage) -> ReportStatus:
        if triage.level.value in ("emergency_stop", "do_not_drive"):
            return ReportStatus.SAFETY_ESCALATION
        if session.contradictions:
            return ReportStatus.COMPLETED_WITH_LIMITATIONS
        if session.request.vehicle_identity_context.resolution_status in (
            ResolutionStatus.AMBIGUOUS, ResolutionStatus.INSUFFICIENT_DATA, ResolutionStatus.CONTRADICTORY,
        ):
            return ReportStatus.COMPLETED_WITH_LIMITATIONS
        return ReportStatus.COMPLETED
