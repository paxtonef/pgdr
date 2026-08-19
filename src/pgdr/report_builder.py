"""Report Builders — Garage Preparation Report + User Summary (AMD pack 18, 19).

PGDR-AC-010: the garage report (technical, for the professional) and the
user summary (simplified, for the driver) must remain distinct objects.
PGDR-BR-012: no repair cost is ever estimated here.

P7 note: this module previously also contained the `ReportBuilder` class
(build/._build_garage_report/._build_user_summary/._determine_status).
P7's legacy reachability audit
(docs/architecture/p7_legacy_reachability_audit.md) found it had ZERO
callers anywhere — production or test — superseded entirely by
`build_from_case_state()` / `build_result_from_case_state()` below (the
sole production reporting path since P5). Removed.
"""
from __future__ import annotations

from pgdr.enums import ReportStatus, TriageLevel
from pgdr.models import GaragePreparationReport, PreGarageDiagnosticResult, SafetyTriage, UserSummary

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


# ---------------------------------------------------------------------------
# P4 mandate §22 / P4-T15 — DiagnosticCaseState consumer.
#
# Purely additive: does not touch ReportBuilder or anything above this
# line. Reuses the same GaragePreparationReport / UserSummary Pydantic
# models and the same _URGENCY_COPY table as the v0.1 pipeline so
# "OLD output ≈ NEW output" for equivalent scenarios, per the mandate's
# own success criterion. The v0.1 ReportBuilder class and this function
# are two independent producers of the same output schema — one reads
# scattered runtime objects (DiagnosticSession), the other reads the
# single-source-of-truth DiagnosticCaseState.
# ---------------------------------------------------------------------------

def build_from_case_state(state) -> tuple["UserSummary", "GaragePreparationReport"]:
    """Builds (UserSummary, GaragePreparationReport) from a
    DiagnosticCaseState. Import is deferred inside the function body to
    avoid a module-level dependency from report_builder.py onto the P4
    domain package for callers who only use the pre-P4 `ReportBuilder`
    class."""
    from pgdr.domain.analytical_state import DiagnosticCaseState  # noqa: F401 (type documentation only)

    triage = state.safety_state.triage if state.safety_state else SafetyTriage()

    raw_complaint_obs = next((o for o in state.observations if o.kind == "raw_complaint"), None)
    complaint_text = str(raw_complaint_obs.value) if raw_complaint_obs else ""

    active_hypotheses = sorted(
        (h for h in state.hypotheses if h.active),
        key=lambda h: (h.confidence if h.confidence is not None else 0.0),
        reverse=True,
    )

    limitations = [
        "Aucune inspection physique n'a été réalisée.",
        "Ce document prépare le diagnostic mais ne remplace pas l'examen du véhicule par un professionnel.",
    ]
    if state.identity_context is not None and state.identity_context.ambiguity:
        limitations.append(
            "L'identité du véhicule est incertaine — le raisonnement spécifique au véhicule est limité "
            "(PGDR-BR-001 / PGDR-ID-003)."
        )

    unresolved = [c.description for c in state.unresolved_contradictions()]
    if not unresolved:
        unresolved = [
            "L'origine exacte du symptôme nécessite une inspection physique.",
            "La reproduction du symptôme en atelier reste à confirmer.",
        ]

    garage_report = GaragePreparationReport(
        vehicle={
            "identity_resolution_id": state.identity_context.identity_ref if state.identity_context else None,
            **(state.identity_context.attributes if state.identity_context else {}),
        },
        customer_reported_problem=complaint_text,
        symptom_summary=[
            {"kind": o.kind, "value": o.value, **o.context}
            for o in state.observations if o.kind == "symptom"
        ],
        warning_indicators=[
            {"label": o.value, **o.context}
            for o in state.observations if o.kind == "warning_indicator"
        ],
        safety_information={
            "triage_level": triage.level.value,
            "critical_signal_detected": triage.level.value in ("emergency_stop", "do_not_drive"),
            "statement": triage.user_instruction,
            "driving_assessment": triage.driving_assessment.value,
        },
        systems_to_examine=[
            {
                "system_family": h.hypothesis_type,
                "confidence": round(h.confidence, 3) if h.confidence is not None else None,
                "description": h.description,
            }
            for h in active_hypotheses
        ],
        suggested_professional_checks=[f"Examiner le système : {h.hypothesis_type}" for h in active_hypotheses],
        unresolved_questions=unresolved,
        contradictions=[
            {"id": c.id, "description": c.description, "resolved": c.resolved}
            for c in state.contradictions
        ],
        limitations=limitations,
    )

    urgency_label, urgency_explanation = _URGENCY_COPY.get(
        triage.level.value, _URGENCY_COPY[TriageLevel.MONITOR_AND_DOCUMENT.value]
    )
    user_summary = UserSummary(
        urgency={"label": urgency_label, "explanation": urgency_explanation},
        main_observations=[complaint_text] if complaint_text else [],
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
    return user_summary, garage_report


# ---------------------------------------------------------------------------
# P5 mandate §17/§4 — production result assembly from DiagnosticCaseState.
#
# Purely additive (appended after build_from_case_state, same section).
# This is what makes DiagnosticCaseState able to produce the FULL
# PreGarageDiagnosticResult the CLI and all pre-P5 tests expect — not just
# the two report objects P4's build_from_case_state already produced.
#
# Translation, not reasoning: this function recalculates nothing. It maps
# already-computed analytical state (hypotheses, their already-computed
# confidence, already-detected contradictions, the already-computed
# safety triage) into the legacy output schema. Per mandate §17: "Le
# reporting présente l'état. Il ne raisonne pas."
# ---------------------------------------------------------------------------

def _bucket_confidence(score) -> "Confidence":
    """P5 mandate §12 — the analytical_score is NOT a scientific
    probability; this bucketing exists only so the legacy
    pgdr.models.DiagnosticHypothesis.confidence field (typed as the
    Confidence enum) can still be populated for backward compatibility.
    The underlying float score is preserved verbatim in
    DiagnosticCaseState — nothing is lost, only re-expressed for the old
    schema."""
    from pgdr.enums import Confidence

    if score is None:
        return Confidence.SPECULATIVE
    if score >= 0.7:
        return Confidence.HIGH
    if score >= 0.4:
        return Confidence.MEDIUM
    if score > 0.0:
        return Confidence.LOW
    return Confidence.SPECULATIVE


def _translate_hypotheses(state) -> list:
    """New pgdr.domain.hypothesis.DiagnosticHypothesis (mutable
    analytical_score) -> old pgdr.models.DiagnosticHypothesis (fixed
    Confidence enum + supporting_observations text), for legacy schema
    compatibility."""
    from pgdr.enums import ClaimStatus
    from pgdr.models import DiagnosticHypothesis as LegacyHypothesis

    evidence_by_id = {e.id: e for e in state.evidence}
    translated = []
    for h in state.hypotheses:
        if not h.active:
            continue
        supporting = [
            evidence_by_id[eid].rationale or f"Supporté par {evidence_by_id[eid].id}"
            for eid in h.supporting_evidence_ids if eid in evidence_by_id
        ]
        contradicting = [
            evidence_by_id[eid].rationale or f"Contredit par {evidence_by_id[eid].id}"
            for eid in h.contradicting_evidence_ids if eid in evidence_by_id
        ]
        translated.append(LegacyHypothesis(
            hypothesis_id=h.id,
            system_family=h.hypothesis_type,
            description=h.description,
            confidence=_bucket_confidence(h.confidence),
            supporting_observations=supporting or [h.description],
            contradicting_observations=contradicting,
            missing_information=["Inspection physique par un professionnel requise pour confirmation."],
            recommended_professional_checks=[f"Examiner le système : {h.hypothesis_type}"],
            safety_relevance="unknown",
            claim_status=ClaimStatus.COMPATIBLE if h.confidence and h.confidence > 0 else ClaimStatus.UNRESOLVED,
        ))
    return translated


def _translate_contradictions(state) -> list:
    from pgdr.enums import ContradictionImpact, ContradictionSeverity, ResolutionAction
    from pgdr.models import DiagnosticContradiction as LegacyContradiction

    translated = []
    for c in state.contradictions:
        translated.append(LegacyContradiction(
            contradiction_id=c.id,
            fields=[],
            descriptions=[c.description],
            severity=ContradictionSeverity.MEDIUM,
            impact=(
                ContradictionImpact.NO_MATERIAL_IMPACT if c.resolved
                else ContradictionImpact.HYPOTHESIS_UNCERTAINTY
            ),
            resolution_action=(
                ResolutionAction.RETAIN_BOTH if not c.resolved else ResolutionAction.REDUCE_CONFIDENCE
            ),
        ))
    return translated


def _determine_status_from_case_state(state) -> "ReportStatus":
    triage = state.safety_state.triage if state.safety_state else None
    if triage and triage.level.value in ("emergency_stop", "do_not_drive"):
        return ReportStatus.SAFETY_ESCALATION
    if state.unresolved_contradictions():
        return ReportStatus.COMPLETED_WITH_LIMITATIONS
    if state.identity_context is not None and state.identity_context.ambiguity:
        return ReportStatus.COMPLETED_WITH_LIMITATIONS
    return ReportStatus.COMPLETED


def build_result_from_case_state(request_id: str, state) -> "PreGarageDiagnosticResult":
    """The P5 production path: DiagnosticCaseState -> full
    PreGarageDiagnosticResult, matching the schema SessionController /
    the CLI / all pre-P5 tests already expect."""
    user_summary, garage_report = build_from_case_state(state)
    triage = state.safety_state.triage if state.safety_state else SafetyTriage()

    return PreGarageDiagnosticResult(
        request_id=request_id,
        status=_determine_status_from_case_state(state),
        vehicle_identity_summary={
            "resolution_id": state.identity_context.identity_ref if state.identity_context else None,
            "status": (
                state.identity_context.attributes.get("resolution_status")
                if state.identity_context else None
            ),
        },
        user_complaint={
            "raw_text": garage_report.customer_reported_problem,
            "structured_summary": "Voir symptom_summary dans le rapport garage.",
        },
        symptoms=[],  # legacy Symptom objects are populated by SessionController directly (unchanged path, see P5 findings)
        operating_conditions=None,
        recent_events=[],
        warning_indicators=[],
        evidence_summary=[],
        safety_triage=triage,
        diagnostic_hypotheses=_translate_hypotheses(state),
        contradictions=_translate_contradictions(state),
        unresolved_questions=garage_report.unresolved_questions,
        garage_preparation_report=garage_report,
        user_summary=user_summary,
        limitations=garage_report.limitations,
        trace={"case_id": state.case_id, "iteration": state.iteration},
    )
