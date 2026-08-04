"""Diagnostic Reasoning Engine — PGDR v0.1 (AMD pack 12).

PGDR-HYP-003 / policy 20.3: only "compatible with" / "system to examine"
language is allowed here — never an exact component failure claim.
"""
from __future__ import annotations

from pgdr.config_loader import load_business_rules
from pgdr.enums import ClaimStatus, Confidence, SymptomFamily
from pgdr.models import (
    ContradictionImpact, ContradictionSeverity, DiagnosticContradiction,
    DiagnosticHypothesis, DiagnosticSession, OperatingConditions,
    ReproductionProfile, ResolutionAction, VehicleEvent,
)
from pgdr.textnorm import normalize

# family -> [(system_family, description, confidence, extra_support_tags)]
# All descriptions use "compatible with" phrasing, never a definitive claim
# (PGDR-BR-006 / PGDR-HYP-003).
_HYPOTHESIS_MAP: dict[str, list[tuple[str, str, Confidence, list[str]]]] = {
    "vibration": [
        ("engine_running",
         "Les observations sont compatibles avec un problème affectant le régime moteur, "
         "les supports moteur ou l'allumage.",
         Confidence.MEDIUM, ["vibration_au_ralenti"]),
        ("tyre_or_wheel",
         "La vibration pourrait être compatible avec un défaut d'équilibrage des roues ou de pneumatique.",
         Confidence.LOW, ["vibration_en_roulant"]),
    ],
    "noise": [
        ("engine_running",
         "Le bruit rapporté est compatible avec le système d'entraînement des accessoires, "
         "la distribution ou le démarreur.",
         Confidence.MEDIUM, ["bruit_moteur"]),
        ("transmission",
         "Un bruit mécanique peut être compatible avec la transmission ou l'embrayage.",
         Confidence.LOW, ["bruit_boite"]),
        ("suspension",
         "Le bruit peut être compatible avec la suspension ou les amortisseurs.",
         Confidence.LOW, ["bruit_suspension"]),
    ],
    "warning_light": [
        ("electrical",
         "Un voyant allumé est compatible avec un défaut du réseau électronique ou d'un capteur.",
         Confidence.MEDIUM, ["voyant_allume"]),
        ("engine_running",
         "Le voyant moteur est compatible avec un défaut d'injection, d'allumage ou d'échappement.",
         Confidence.MEDIUM, ["check_engine"]),
    ],
    "braking": [
        ("braking",
         "Les symptômes décrits concernent directement le système de freinage.",
         Confidence.HIGH, ["probleme_frein"]),
    ],
    "steering": [
        ("steering",
         "Les observations concernent le système de direction et ses composants.",
         Confidence.HIGH, ["probleme_direction"]),
    ],
    "temperature_or_overheating": [
        ("temperature_or_overheating",
         "Le symptôme est compatible avec un problème du système de refroidissement.",
         Confidence.HIGH, ["surchauffe"]),
    ],
    "battery_or_charging": [
        ("battery_or_charging",
         "Les observations sont compatibles avec un problème de batterie, d'alternateur ou de charge.",
         Confidence.MEDIUM, ["batterie"]),
    ],
    "starting": [
        ("starting",
         "Le problème concerne le système de démarrage (démarreur, batterie, circuit).",
         Confidence.HIGH, ["demarrage"]),
    ],
    "fluid_leak": [
        ("fluid_leak",
         "Une fuite nécessite l'identification du liquide et de son origine par un professionnel.",
         Confidence.MEDIUM, ["fuite"]),
    ],
    "engine_running": [
        ("engine_running",
         "Les observations concernent le fonctionnement du moteur (ralenti, régime, comportement à chaud/froid).",
         Confidence.LOW, ["comportement_moteur"]),
    ],
    "power_loss": [
        ("engine_running",
         "La perte de puissance est compatible avec un défaut d'alimentation, d'admission ou d'allumage.",
         Confidence.MEDIUM, ["perte_puissance"]),
    ],
    "unknown": [
        ("unknown",
         "Les informations fournies sont insuffisantes pour formuler une hypothèse structurée.",
         Confidence.SPECULATIVE, ["symptome_non_classe"]),
    ],
}


class DiagnosticEngine:
    def __init__(self) -> None:
        self.config = load_business_rules()

    def process_answers(self, session: DiagnosticSession) -> None:
        """Folds submitted answers into operating_conditions / events / reproduction_profile."""
        cond = OperatingConditions()
        for ans in session.answers:
            if ans.question_id == "Q-STATE-002" and isinstance(ans.value, str):
                val = ans.value.lower()
                if "froid" in val:
                    cond.engine_state = "cold"
                elif "chaud" in val:
                    cond.engine_state = "hot"
                elif "deux" in val:
                    cond.engine_state = "both"
            elif ans.question_id == "Q-COND-001":
                choices = ans.value if isinstance(ans.value, list) else [str(ans.value)]
                cond.vehicle_state = ", ".join(str(c) for c in choices)
            elif ans.question_id == "Q-EVT-002" and ans.value:
                session.events.append(VehicleEvent(
                    event_type="recent_maintenance",
                    description=str(ans.value),
                    relation_to_symptom="before",
                ))
        session.operating_conditions = cond

        if session.symptoms:
            primary = next((s for s in session.symptoms if s.is_primary), session.symptoms[0])
            session.reproduction_profile = ReproductionProfile(
                reproducible=primary.frequency.value in ("constant", "often", "always"),
                recurrence=primary.frequency.value,
            )

    def generate_hypotheses(self, session: DiagnosticSession) -> list[DiagnosticHypothesis]:
        hypotheses: list[DiagnosticHypothesis] = []
        primary = next((s for s in session.symptoms if s.is_primary), None)
        if primary is None:
            return hypotheses

        entries = _HYPOTHESIS_MAP.get(primary.family.value)
        if entries is None:
            entries = self._generic_entries(primary.family)
        high_safety_families = {"braking", "steering", "temperature_or_overheating"}

        for system_family, description, confidence, tags in entries:
            hypotheses.append(DiagnosticHypothesis(
                system_family=system_family,
                description=description,
                confidence=confidence,
                supporting_observations=[primary.user_description] + tags,
                missing_information=["Inspection physique par un professionnel requise pour confirmation."],
                recommended_professional_checks=[f"Examiner le système : {system_family}"],
                safety_relevance="significant" if primary.family.value in high_safety_families else "low",
                claim_status=ClaimStatus.COMPATIBLE if confidence != Confidence.SPECULATIVE else ClaimStatus.UNRESOLVED,
            ))

        max_h = self.config.get("thresholds", {}).get("max_hypotheses_garage_report", 8)
        session.hypotheses = hypotheses[:max_h]
        return session.hypotheses

    @staticmethod
    def _generic_entries(family: SymptomFamily) -> list[tuple[str, str, Confidence, list[str]]]:
        """Fallback for any SymptomFamily without a curated entry in
        _HYPOTHESIS_MAP. Ensures every recognized family still produces a
        genuine 'system to examine' hypothesis instead of silently
        degrading to 'unknown' — only complaints that match *no* keyword
        at all (true SymptomFamily.UNKNOWN) should ever reach that state."""
        if family == SymptomFamily.UNKNOWN:
            return _HYPOTHESIS_MAP["unknown"]
        return [(
            family.value,
            f"Les observations sont compatibles avec un problème concernant le système : {family.value}.",
            Confidence.LOW,
            [f"symptome_{family.value}"],
        )]

    def detect_contradictions(self, session: DiagnosticSession) -> None:
        """AMD pack 13 — flags a small set of high-signal contradictions."""
        contradictions: list[DiagnosticContradiction] = []
        text = normalize(session.request.initial_complaint.free_text)

        # "roul" catches roulé/rouler/roulé/roulant — any conjugation of "rouler" (to drive) —
        # rather than one fixed inflected form, since users phrase this many ways.
        if ("ne demarre jamais" in text or "ne demarre plus" in text) and (
            "roul" in text or "conduit" in text or "conduire" in text or "j'ai pu" in text
        ):
            contradictions.append(DiagnosticContradiction(
                fields=["starting", "vehicle_usage"],
                descriptions=[
                    "Le texte indique que le véhicule ne démarre jamais / plus.",
                    "Le texte indique également que le véhicule a roulé après l'apparition du problème.",
                ],
                severity=ContradictionSeverity.HIGH,
                impact=ContradictionImpact.HYPOTHESIS_UNCERTAINTY,
                resolution_action=ResolutionAction.ASK_CLARIFICATION,
            ))

        freqs = {s.frequency.value for s in session.symptoms}
        if "constant" in freqs and "rare" in freqs:
            contradictions.append(DiagnosticContradiction(
                fields=["frequency"],
                descriptions=[
                    "Un symptôme est décrit comme constant.",
                    "Un autre symptôme est décrit comme rare.",
                ],
                severity=ContradictionSeverity.MEDIUM,
                impact=ContradictionImpact.HYPOTHESIS_UNCERTAINTY,
                resolution_action=ResolutionAction.REDUCE_CONFIDENCE,
            ))

        session.contradictions = contradictions
