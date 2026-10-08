"""Deterministic Safety Rule Engine — PGDR v0.1.

Per AMD pack 22.4 this engine MUST be fully separated from any generative /
AI-assisted logic (pack 15.3: "an AI model must never neutralize a safety
rule"). Nothing in this file depends on an LLM; it is pure rule matching
over normalized text and structured fields loaded from safety_rules.yaml.

Matching is accent-insensitive (see pgdr.textnorm.normalize) so a rule
keyed on "fumée" still fires against "fumee", and phrase conditions support
word-order-independent matching ("keywords_all_words") so "pneu ... à
plat" still matches a rule keyed on the words "pneu" + "plat" even when
other words sit between them in the sentence.

It NEVER produces `driving_assessment: safe_to_drive` — that value does not
even exist in the DrivingAssessment enum (see enums.py docstring, and
boundary contract in AMD pack 1.3 / 11.4).

P0 fail-closed contract: constructing a SafetyEngine calls
config_loader.load_safety_rules(), which fully validates safety_rules.yaml
(schema + enum values + unique ids + non-empty conditions) before this
class ever sees it. If that validation fails, it raises
pgdr.errors.ConfigurationError and this class is simply never instantiated
— there is no code path here that converts a bad config into a degraded
but "apparently normal" triage result. Callers (session_controller.py,
cli.py) must let ConfigurationError propagate to a hard failure, never
catch it and substitute a default triage level.
"""
from __future__ import annotations

from pgdr.config_loader import load_safety_rules
from pgdr.enums import DrivingAssessment, TriageLevel, WarningBehavior, WarningColor
from pgdr.models import DiagnosticSession, SafetyTriage
from pgdr.textnorm import normalize

# Ordered lowest -> highest severity. Index is used to decide which matching
# rule wins when several rules fire at once (PGDR-BR-008 / PGDR-INV-004).
_SEVERITY_ORDER = [
    TriageLevel.MONITOR_AND_DOCUMENT,
    TriageLevel.STANDARD_APPOINTMENT,
    TriageLevel.PROMPT_INSPECTION,
    TriageLevel.LIMITED_MOVEMENT_ONLY,
    TriageLevel.DO_NOT_DRIVE,
    TriageLevel.EMERGENCY_STOP,
]


def _severity_rank(level: TriageLevel) -> int:
    # No except/fallback: _SEVERITY_ORDER enumerates every TriageLevel
    # member, so this can only raise if a new enum member is added without
    # updating the list — a real programming error that should fail loudly
    # during development, not be silently mapped to "least severe".
    return _SEVERITY_ORDER.index(level)


class SafetyEngine:
    def __init__(self) -> None:
        # load_safety_rules() has already run full P0.3 semantic
        # validation (unique ids, required fields present, valid enum
        # values, non-empty conditions) — so from here on we trust the
        # structure completely. No .get(..., []) / .get(..., {}) fallback:
        # if validation was somehow bypassed, this should fail loudly
        # (KeyError) rather than silently degrade.
        cfg = load_safety_rules()
        self.rules: list[dict] = cfg["rules"]
        self.default: dict = cfg["default"]

    def evaluate(self, session: DiagnosticSession) -> SafetyTriage:
        text = self._all_text(session)
        warning_texts = self._warning_texts(session)

        triage = SafetyTriage()
        for rule in self.rules:
            cond = rule.get("conditions", {})
            texts, indicators = warning_texts, None
            if "exclude_established_situations" in cond:
                kept, excluded = self._established_exclusions(session, cond["exclude_established_situations"])
                # The driver's own words keep the rule as before: only a keyword carried by the
                # indicators' designations can be set aside by an established fact.
                if any(normalize(kw) in text for kw in cond.get("warning_keywords_any", [])):
                    excluded = []
                if excluded:
                    texts, indicators = self._texts_of(kept), kept
                    if not self._matches(cond, text, texts, session, indicators=indicators):
                        if self._matches(cond, text, warning_texts, session):
                            # Matched only through indicators established, by a structured fact with
                            # its provenance, as ordinary indications: recorded, never silent.
                            triage.rule_exclusions.append(
                                {"rule": rule["id"], "excluded": [dict(wi.situation_fact) for wi in excluded]})
                        continue
            if self._matches(cond, text, texts, session, indicators=indicators):
                self._apply(triage, rule)

        if not triage.triggered_rules:
            triage.level = TriageLevel(self.default["triage_level"])
            triage.driving_assessment = DrivingAssessment(self.default["driving_assessment"])
            triage.emergency_services_required = bool(self.default.get("emergency_services", False))
            triage.roadside_assistance_recommended = bool(self.default.get("roadside_assistance", False))
            triage.user_instruction = self.default["instruction"]
            triage.reasons.append(self.default["reason"])

        return triage

    @staticmethod
    def _apply(triage: SafetyTriage, rule: dict) -> None:
        level = TriageLevel(rule["triage_level"])
        if _severity_rank(level) >= _severity_rank(triage.level):
            triage.level = level
            triage.triggered_rules.append(rule["id"])
            triage.reasons.append(rule["reason"])
            triage.user_instruction = rule["instruction"]
            triage.driving_assessment = DrivingAssessment(rule["driving_assessment"])
            triage.emergency_services_required = bool(rule.get("emergency_services", False))
            triage.roadside_assistance_recommended = bool(rule.get("roadside_assistance", False))

    @staticmethod
    def _established_exclusions(session: DiagnosticSession, natures: list) -> tuple[list, list]:
        """Indicators whose structured situation fact establishes one of `natures`:
        a variant the driver selected (never a possible one) and a fact with a
        provenance. Without such a fact, nothing is excluded (rule unchanged)."""
        kept, excluded = [], []
        for wi in session.warning_indicators:
            f = wi.situation_fact or {}
            if f.get("nature") in natures and f.get("provenance") and f.get("variant") == "selected":
                excluded.append(wi)
            else:
                kept.append(wi)
        return kept, excluded

    @staticmethod
    def _texts_of(indicators: list) -> list[str]:
        out = []
        for wi in indicators:
            out.append(normalize(wi.label))
            if wi.associated_message:
                out.append(normalize(wi.associated_message))
        return out

    # -- matching -----------------------------------------------------

    @staticmethod
    def _all_text(session: DiagnosticSession) -> str:
        parts = [session.request.initial_complaint.free_text]
        parts += [s.user_description for s in session.symptoms]
        parts += [a.value for a in session.answers if isinstance(a.value, str)]
        return normalize(" ".join(parts))

    @staticmethod
    def _warning_texts(session: DiagnosticSession) -> list[str]:
        out = []
        for wi in session.warning_indicators:
            out.append(normalize(wi.label))
            if wi.associated_message:
                out.append(normalize(wi.associated_message))
        return out

    def _matches(self, cond: dict, text: str, warning_texts: list[str], session: DiagnosticSession,
                 indicators: list | None = None) -> bool:
        if not cond:
            return False
        indicators = session.warning_indicators if indicators is None else indicators

        if "keywords_any" in cond:
            if not any(normalize(kw) in text for kw in cond["keywords_any"]):
                return False

        if "keywords_all_words" in cond:
            # All listed words must appear somewhere in the text, in any
            # order — for phrases like "pneu ... visiblement ... à plat"
            # where the two significant words aren't adjacent.
            if not all(normalize(w) in text for w in cond["keywords_all_words"]):
                return False

        if "keywords_any_words_groups" in cond:
            # A list of word-groups; matches if ANY group has ALL of its
            # words present anywhere in the text (order-independent within
            # a group, OR across groups). Lets one rule cover several
            # non-adjacent phrasings ("pneu ... plat", "pneu ... degonfle",
            # "roue ... bouge") without duplicating whole rules.
            groups = cond["keywords_any_words_groups"]
            if not any(all(normalize(w) in text for w in group) for group in groups):
                return False

        if "keywords_any_secondary" in cond:
            if not any(normalize(kw) in text for kw in cond["keywords_any_secondary"]):
                return False

        if "warning_keywords_any" in cond:
            joined = " ".join(warning_texts)
            if not any(normalize(kw) in joined or normalize(kw) in text for kw in cond["warning_keywords_any"]):
                return False

        if "warning_behavior" in cond:
            target = cond["warning_behavior"]
            if not any(wi.behavior.value == target for wi in indicators):
                return False

        if "warning_color" in cond:
            target = cond["warning_color"]
            if not any(wi.observed_color.value == target for wi in indicators):
                return False

        return True
