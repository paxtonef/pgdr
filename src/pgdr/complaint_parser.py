"""Complaint extraction — rule-based baseline for v0.1 (AMD pack 4, 8).

Per pack 15.2, free-text symptom extraction is listed as an "AI-assisted"
capability. For v0.1 we ship a deterministic keyword-based implementation
so the pipeline is fully testable without an LLM dependency; a future
version can swap this module for an LLM-backed one behind the same
interface (`extract()` / `extract_warning_indicators()`) without touching
the rest of the pipeline.
"""
from __future__ import annotations

import re

from pgdr.config_loader import load_taxonomy
from pgdr.enums import (
    EvidenceSource, Frequency, Reproducibility, Severity, SymptomFamily,
    WarningBehavior, WarningColor,
)
from pgdr.models import ComplaintExtraction, InitialComplaint, Symptom, WarningIndicator
from pgdr.textnorm import normalize

_TEMPORAL_PATTERNS = [
    (r"depuis (\w+)", "started_{0}"),
    (r"il y a (\w+)", "started_{0}"),
    (r"ce matin", "started_this_morning"),
    (r"hier", "started_yesterday"),
    (r"parfois", "intermittent"),
    (r"par intermittence", "intermittent"),
    (r"de temps en temps", "intermittent"),
    (r"rarement", "rare"),
    (r"souvent", "often"),
    (r"toujours", "constant"),
    (r"de plus en plus", "increasing"),
]

_SAFETY_KEYWORDS = [
    "voyant rouge", "voyant moteur", "frein", "fumée", "odeur de brûlé",
    "perte de contrôle", "direction",
]

# Families ranked by specificity/safety relevance for choosing the *primary*
# symptom when a complaint matches multiple keyword families at once.
# Lower index = higher priority. Generic/contextual families (engine_running,
# acceleration) rank last so a specific symptom (vibration, noise, a warning
# light, braking...) is never displaced by the context it occurs in.
_FAMILY_PRIORITY = [
    "braking", "steering", "temperature_or_overheating", "smoke", "smell",
    "fluid_leak", "battery_or_charging", "starting", "power_loss",
    "warning_light", "vibration", "noise", "tyre_or_wheel", "transmission",
    "suspension", "fuel_consumption", "climate_control", "visibility",
    "body_or_structure", "charging_system_ev", "electrical",
    "acceleration", "engine_running", "unknown",
]


def _family_rank(name: str) -> int:
    try:
        return _FAMILY_PRIORITY.index(name)
    except ValueError:
        return len(_FAMILY_PRIORITY)


_UNCERTAIN_TERMS = [
    "parfois", "par intermittence", "je pense", "j'ai l'impression",
    "peut-être", "quelquefois", "il me semble",
]

_VOYANT_PATTERNS = [
    (r"voyant\s+(moteur|frein|huile|batterie|airbag|abs|esp)", "voyant {0}"),
    (r"check engine", "check engine"),
]


class ComplaintParser:
    def __init__(self) -> None:
        taxonomy = load_taxonomy()
        self.keyword_map: dict[str, str] = taxonomy.get("keyword_map", {}) or {}

    def extract(self, complaint: InitialComplaint) -> tuple[ComplaintExtraction, list[Symptom]]:
        text = normalize(complaint.free_text)
        extraction = ComplaintExtraction()

        detected_families: set[str] = set()
        for keyword, family in self.keyword_map.items():
            if normalize(keyword) in text:
                detected_families.add(family)
                extraction.symptom_categories.append(family)

        for pattern, template in _TEMPORAL_PATTERNS:
            for m in re.finditer(pattern, text):
                group = m.group(1) if m.groups() else ""
                extraction.temporal_markers.append(template.format(group))

        for kw in _SAFETY_KEYWORDS:
            if normalize(kw) in text:
                extraction.explicit_safety_signals.append(kw)

        for term in _UNCERTAIN_TERMS:
            if normalize(term) in text:
                extraction.uncertain_terms.append(term)

        symptoms = self._build_symptoms(complaint, text, detected_families)
        return extraction, symptoms

    def _build_symptoms(self, complaint: InitialComplaint, text: str, families: set[str]) -> list[Symptom]:
        symptoms: list[Symptom] = []
        freq = self._detect_frequency(text)
        sev = self._detect_severity(text)

        for i, family_name in enumerate(sorted(families, key=_family_rank)):
            try:
                family = SymptomFamily(family_name)
            except ValueError:
                family = SymptomFamily.UNKNOWN
            symptoms.append(Symptom(
                family=family,
                user_description=complaint.free_text,
                normalized_description=f"Symptôme de la famille '{family.value}' détecté par correspondance de mots-clés.",
                first_occurrence=complaint.first_observed_at,
                frequency=freq,
                severity=sev,
                reproducibility=Reproducibility.UNKNOWN,
                source=EvidenceSource.USER_STATEMENT,
                is_primary=(i == 0),
            ))

        if not symptoms:
            symptoms.append(Symptom(
                family=SymptomFamily.UNKNOWN,
                user_description=complaint.free_text,
                normalized_description="Aucune famille de symptôme reconnue automatiquement.",
                first_occurrence=complaint.first_observed_at,
                source=EvidenceSource.USER_STATEMENT,
                is_primary=True,
            ))
        return symptoms

    @staticmethod
    def _detect_frequency(text: str) -> Frequency:
        if any(normalize(m) in text for m in ["toujours", "constamment", "en permanence"]):
            return Frequency.CONSTANT
        if any(normalize(m) in text for m in ["parfois", "intermittent", "de temps en temps", "par intermittence"]):
            return Frequency.INTERMITTENT
        if "rarement" in text:
            return Frequency.RARE
        if "de plus en plus" in text:
            return Frequency.INCREASING
        return Frequency.UNKNOWN

    @staticmethod
    def _detect_severity(text: str) -> Severity:
        if any(normalize(m) in text for m in ["fort", "violent", "handicapant", "ne marche plus"]):
            return Severity.STRONG
        if any(normalize(m) in text for m in ["léger", "un peu", "légèrement"]):
            return Severity.SLIGHT
        if any(normalize(m) in text for m in ["modéré", "moyen"]):
            return Severity.MODERATE
        return Severity.UNKNOWN

    def extract_warning_indicators(self, complaint: InitialComplaint) -> list[WarningIndicator]:
        """Detects mentions of dashboard warning lights directly from the free
        text so the safety engine (which reads session.warning_indicators)
        can react even when no photo/media was uploaded."""
        text = normalize(complaint.free_text)
        indicators: list[WarningIndicator] = []

        for pattern, label_template in _VOYANT_PATTERNS:
            m = re.search(pattern, text)
            if not m:
                continue
            label = label_template.format(m.group(1) if m.groups() else "")

            behavior = WarningBehavior.UNKNOWN
            if any(normalize(t) in text for t in ["clignote", "clignotant", "flashing"]):
                behavior = WarningBehavior.FLASHING
            elif any(normalize(t) in text for t in ["parfois", "intermittent", "par intermittence"]):
                behavior = WarningBehavior.INTERMITTENT
            elif any(normalize(t) in text for t in ["allumé", "constant"]):
                behavior = WarningBehavior.CONSTANT

            color = WarningColor.UNKNOWN
            if "rouge" in text:
                color = WarningColor.RED
            elif any(t in text for t in ["orange", "amber"]):
                color = WarningColor.AMBER

            indicators.append(WarningIndicator(label=label, observed_color=color, behavior=behavior))

        return indicators
