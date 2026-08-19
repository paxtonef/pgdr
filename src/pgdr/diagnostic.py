"""Automotive symptom-family → hypothesis mapping — Domain Pack DATA.

P7 note: prior to P7, this module also contained the `DiagnosticEngine`
class (process_answers/generate_hypotheses/detect_contradictions
instance methods). P7's legacy reachability audit
(docs/architecture/p7_legacy_reachability_audit.md) found all three
methods unreachable from production — superseded respectively by: no
replacement (the fields they populated had no readers left once
ReportBuilder's legacy methods were also confirmed unreachable),
AutomotiveDiagnosticDomain.generate_hypotheses(), and
AutomotiveDiagnosticDomain.detect_contradictions(). They were removed.
The one genuinely production-reachable piece of that class
(`_generic_entries`, the no-curated-entry fallback) was relocated to
`automotive/domain_adapter.py` as `_generic_hypothesis_entries()`, its
sole caller — not deleted.

This module now contains only `_HYPOTHESIS_MAP` itself: automotive domain
DATA, not analytical logic (P3's boundary classification).

PGDR-HYP-003 / policy 20.3: only "compatible with" / "system to examine"
language is allowed here — never an exact component failure claim.
"""
from __future__ import annotations

from pgdr.enums import Confidence

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
