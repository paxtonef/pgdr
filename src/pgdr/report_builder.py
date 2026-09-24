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

from pgdr.enums import ClaimStatus, Confidence, Deadline, ReportStatus, TriageLevel
from pgdr.models import GaragePreparationReport, PlausibleCause, PreGarageDiagnosticResult, SafetyTriage, UserSummary

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
# PGDR Driver Diagnostic Execution Mandate v0 — Driver Diagnostic content.
#
# All of what follows is additive presentation content re-expressing
# already-computed state (safety triage, hypotheses, contradictions,
# limitations). Nothing here recomputes a decision SafetyEngine or the
# analytical engine already made — per mandate §14: presentation content
# may phrase an already-computed decision, it must not determine one.
# ---------------------------------------------------------------------------

# Mandate §4: categorical deadline, derived ONLY from TriageLevel — never
# from diagnostic confidence, hypothesis state, or evidence. Same
# presentation-boundary pattern _URGENCY_COPY above already established.
_DEADLINE_BY_TRIAGE = {
    TriageLevel.EMERGENCY_STOP.value: Deadline.IMMEDIATE,
    TriageLevel.DO_NOT_DRIVE.value: Deadline.IMMEDIATE,
    TriageLevel.LIMITED_MOVEMENT_ONLY.value: Deadline.PROMPT_PROFESSIONAL_ASSESSMENT,
    TriageLevel.PROMPT_INSPECTION.value: Deadline.PROMPT_PROFESSIONAL_ASSESSMENT,
    TriageLevel.STANDARD_APPOINTMENT.value: Deadline.SHORT_TERM_ASSESSMENT,
    TriageLevel.MONITOR_AND_DOCUMENT.value: Deadline.MONITORING,
}

# Mandate §9.A / §11: human-facing labels for internal system-family
# identifiers — covers every value _HYPOTHESIS_MAP or the generic
# SymptomFamily fallback (automotive/domain_adapter.py's
# _generic_hypothesis_entries) can produce. A missing entry falls back to
# a plain, still-non-identifier phrase (_label_for_system_family) rather
# than ever leaking a raw internal token like "engine_running" to the
# driver.
_SYSTEM_FAMILY_LABELS = {
    "starting": "le démarrage du véhicule",
    "engine_running": "le fonctionnement du moteur",
    "acceleration": "l'accélération",
    "power_loss": "une perte de puissance",
    "braking": "le système de freinage",
    "steering": "la direction",
    "suspension": "la suspension",
    "transmission": "la transmission",
    "electrical": "le système électrique",
    "battery_or_charging": "la batterie ou le système de charge",
    "temperature_or_overheating": "la température du moteur",
    "fluid_leak": "une fuite de fluide",
    "smoke": "une émission de fumée",
    "smell": "une odeur inhabituelle",
    "noise": "un bruit inhabituel",
    "vibration": "une vibration",
    "warning_light": "un voyant du tableau de bord",
    "fuel_consumption": "la consommation de carburant",
    "tyre_or_wheel": "les pneus ou les roues",
    "climate_control": "la climatisation",
    "visibility": "la visibilité",
    "body_or_structure": "la carrosserie ou la structure du véhicule",
    "charging_system_ev": "le système de charge du véhicule électrique",
    "unknown": "un problème non identifié précisément",
}


def _label_for_system_family(hypothesis_type: str) -> str:
    return _SYSTEM_FAMILY_LABELS.get(hypothesis_type, f"le système : {hypothesis_type}")


def _build_situation_explanation(triage: "SafetyTriage", active_hypotheses: list, has_warning_context: bool) -> str:
    """Mandate §9.A / §10: a coherent plain-language explanation, never a
    complaint echo, never a raw internal identifier. Preserves uncertainty
    explicitly when more than one hypothesis is active (§10 — 'evidence
    suggests primarily X, while Y remains possible')."""
    urgency_label, _ = _URGENCY_COPY.get(
        triage.level.value, _URGENCY_COPY[TriageLevel.MONITOR_AND_DOCUMENT.value]
    )
    if not active_hypotheses:
        base = f"Situation classée « {urgency_label} »."
    else:
        leading = _label_for_system_family(active_hypotheses[0].hypothesis_type)
        base = f"Situation classée « {urgency_label} ». Les éléments recueillis orientent vers {leading}."
        if len(active_hypotheses) > 1:
            base += " D'autres causes restent possibles, sans qu'aucune ne soit exclue à ce stade."
    if has_warning_context:
        base += (
            " Un voyant ou message du tableau de bord a été signalé et fait partie des éléments pris en compte."
        )
    return base


def _build_plausible_causes(active_hypotheses: list) -> list["PlausibleCause"]:
    """Mandate §9.E / §11: rank reuses the existing confidence-sorted
    active_hypotheses list (unmodified) — nothing is re-derived here.
    Numerical scores are bucketed via the same _bucket_confidence already
    used by the legacy Garage-Handoff hypothesis translation (§11: 'Do NOT
    invent numerical probabilities not supported by PGDR')."""
    causes = []
    for h in active_hypotheses:
        causes.append(PlausibleCause(
            label=_label_for_system_family(h.hypothesis_type),
            description=h.description,
            confidence=_bucket_confidence(h.confidence),
            claim_status=_claim_status_for(h.confidence),
        ))
    return causes


def _build_remaining_uncertainty(unresolved_questions: list[str], limitations: list[str]) -> list[str]:
    """Mandate §9.G: deduplicated union of the Garage Handoff's own
    unresolved_questions and limitations — reused, not recomputed twice."""
    seen: set[str] = set()
    combined: list[str] = []
    for item in [*unresolved_questions, *limitations]:
        if item not in seen:
            seen.add(item)
            combined.append(item)
    return combined


def _build_next_actions(
    triage: "SafetyTriage",
    active_hypotheses: list,
    unresolved_contradictions: list,
    has_warning_context: bool,
    evidence_already_acquired: bool,
) -> list[str]:
    """Mandate §9.F: case-dependent, never a fixed generic list. Priority:
    emergency call -> the already safety-reviewed user_instruction verbatim
    -> roadside assistance if flagged -> evidence request only while still
    useful (mirrors the selector's own Tier-0 gate, so the driver is never
    asked for evidence already received) -> up to two contradiction
    clarifications -> standing evidence-preservation cautions -> a garage-
    notification reminder if any hypothesis exists."""
    actions: list[str] = []
    if triage.emergency_services_required:
        actions.append("Appelez les secours immédiatement.")
    if triage.user_instruction:
        actions.append(triage.user_instruction)
    if triage.roadside_assistance_recommended:
        actions.append("Faites appel à une assistance dépannage.")
    if has_warning_context and not evidence_already_acquired and not triage.emergency_services_required:
        actions.append(
            "Si possible et sans danger, prenez une photo du voyant ou du tableau de bord (véhicule à l'arrêt)."
        )
    for contradiction in unresolved_contradictions[:2]:
        actions.append(f"Précisez si possible : {contradiction.description}")
    actions.append("Conservez toute preuve disponible (photo, son, vidéo).")
    actions.append("Ne tentez pas de démonter ou de toucher des composants du véhicule.")
    if active_hypotheses:
        actions.append("Prévenez le garage des symptômes décrits avant le rendez-vous.")
    return actions


def _claim_status_for(confidence_score) -> "ClaimStatus":
    """Extracted from what was previously inline logic duplicated in
    _translate_hypotheses — one shared rule, used by both the Driver
    Diagnostic's plausible_causes and the legacy Garage-Handoff hypothesis
    translation below."""
    return ClaimStatus.COMPATIBLE if confidence_score and confidence_score > 0 else ClaimStatus.UNRESOLVED


def _build_professional_checks(active_hypotheses: list) -> list[str]:
    """Mandate §13: a professional check should indicate what should be
    checked AND, where more than one hypothesis is active, what competing
    hypothesis it helps discriminate against — by human-facing label, not
    raw hypothesis_type. Reuses only relationships already present in
    state.hypotheses; invents no new workshop procedure."""
    checks = []
    for h in active_hypotheses:
        others = [o for o in active_hypotheses if o.hypothesis_type != h.hypothesis_type]
        label = _label_for_system_family(h.hypothesis_type)
        if others:
            other_labels = ", ".join(_label_for_system_family(o.hypothesis_type) for o in others)
            checks.append(
                f"Examiner {label} — permet de discriminer par rapport aux hypothèses concurrentes : {other_labels}."
            )
        else:
            checks.append(f"Examiner {label} — seule hypothèse active pour ce cas.")
    return checks


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

def _dashboard_identifications(state) -> list[dict]:
    """B2 photo-first: the dashboard symbols established from the photo,
    with their provenance kept explicit and distinct (never merged, never
    phrased alike). Pure translation of Observations already in state."""
    from pgdr.domain.photo_provenance import PROVIDER_OBSERVATION_KIND, USER_SELECTION_OBSERVATION_KIND

    identifications: list[dict] = []
    for o in state.observations:
        if o.kind == PROVIDER_OBSERVATION_KIND and o.context.get("match_status") == "match":
            identifications.append({
                "origin": "visual_provider_match",
                "machine_verified": True,
                "description": str(o.value),
                "reference_entry_id": o.context.get("matched_reference_entry_id"),
                "observation_id": o.id,
                "adapter_id": o.context.get("adapter_id"),
            })
        elif o.kind == USER_SELECTION_OBSERVATION_KIND and o.context.get("selected_reference_entry_id"):
            identifications.append({
                "origin": "user_selection",
                "machine_verified": False,
                "description": str(o.value),
                "reference_entry_id": o.context.get("selected_reference_entry_id"),
                "observation_id": o.id,
                "adapter_id": o.context.get("adapter_id"),
                "triggering_match_status": o.context.get("triggering_match_status"),
            })
    return identifications


def _photo_main_observations(identifications: list[dict]) -> list[str]:
    lines = []
    for i in identifications:
        if i["origin"] == "visual_provider_match":
            lines.append(f"Voyant identifié sur la photo du tableau de bord : {i['description']}.")
        else:
            lines.append(
                f"Voyant indiqué par vous dans la liste du constructeur : {i['description']} "
                f"(identification déclarative, non vérifiée sur la photo)."
            )
    return lines


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

    has_warning_context = any(o.kind == "warning_indicator" for o in state.observations)
    evidence_already_acquired = any(
        e.source_rule_id == "automotive.media_evidence_acquired" for e in state.evidence
    )

    dashboard_identifications = _dashboard_identifications(state)

    garage_report = GaragePreparationReport(
        dashboard_identifications=dashboard_identifications,
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
        suggested_professional_checks=_build_professional_checks(active_hypotheses),
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
    deadline = _DEADLINE_BY_TRIAGE.get(triage.level.value, Deadline.MONITORING)
    diagnostic_confidence = (
        _bucket_confidence(active_hypotheses[0].confidence) if active_hypotheses else None
    )

    user_summary = UserSummary(
        urgency={"label": urgency_label, "explanation": urgency_explanation},
        main_observations=([complaint_text] if complaint_text else []) + _photo_main_observations(dashboard_identifications),
        next_actions=_build_next_actions(
            triage=triage,
            active_hypotheses=active_hypotheses,
            unresolved_contradictions=state.unresolved_contradictions(),
            has_warning_context=has_warning_context,
            evidence_already_acquired=evidence_already_acquired,
        ),
        disclaimer=[
            "Ce document prépare le diagnostic mais ne remplace pas l'examen du véhicule par un professionnel qualifié.",
            "Aucune réparation spécifique n'est recommandée avec certitude, et aucun coût n'est estimé.",
        ],
        situation_explanation=_build_situation_explanation(
            triage=triage, active_hypotheses=active_hypotheses, has_warning_context=has_warning_context,
        ),
        safety_level=triage.level,
        driveability=triage.driving_assessment,
        urgency_deadline=deadline,
        diagnostic_confidence=diagnostic_confidence,
        plausible_causes=_build_plausible_causes(active_hypotheses),
        remaining_uncertainty=_build_remaining_uncertainty(unresolved, limitations),
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
            claim_status=_claim_status_for(h.confidence),
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


# ---------------------------------------------------------------------------
# PGDR Part 1 — Manufacturer First Finding (Execution Mandate v0.2 FINAL,
# §1 C7). Additive: attaches the already-built finding to the result and,
# under the new key `manufacturer_first_finding`, to the garage report.
# Every pre-existing key is unchanged; the legacy urgency content is not
# authoritative for Part 1 and never overrides the finding (D-C5).
# ---------------------------------------------------------------------------

def attach_manufacturer_first_finding(result: "PreGarageDiagnosticResult", finding) -> None:
    result.manufacturer_first_finding = finding
    if result.garage_preparation_report is not None:
        result.garage_preparation_report.manufacturer_first_finding = finding.model_dump(mode="json")
