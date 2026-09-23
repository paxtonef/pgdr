"""B2 photo-first completion: pure helpers for the E5 fallback and for the
E4 safety-signal projection. No I/O, no state mutation.

  * fallback_trigger()/fallback_offer(): which fallback (if any) a validated
    B2-D intake requires, and what the driver may choose from -- separately
    for AMBIGUOUS_MATCH, NO_MATCH and INSUFFICIENT_VISUAL_QUALITY (never
    collapsed into one generic fallback).
  * build_user_selection_intake(): the driver's selection of a manufacturer
    symbol, as an Observation/Evidence pair carrying a provenance that is
    structurally distinct from a machine visual MATCH (source_type USER,
    adapter_id USER_SELECTION_ADAPTER_ID, machine_verified False, its own
    source_rule_id). It is a user statement, never a machine-verified
    visual recognition.
  * warning_indicator_from_entry(): the projection of a governed manufacturer
    reference entry (validated MATCH, or a user-selected entry) onto the
    EXISTING WarningIndicator shape SafetyEngine already evaluates. No new
    safety rule is created here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgdr.application.diagnostic_intake_from_interpretation import DiagnosticIntakeResult
from pgdr.domain.dashboard_knowledge import DashboardReferenceEntry, DashboardReferenceSet, IndicatorState
from pgdr.domain.enums import EvidenceDirection, ObservationSource
from pgdr.domain.evidence import Evidence
from pgdr.domain.observation import Observation
from pgdr.domain.photo_provenance import (
    PROVIDER_OBSERVATION_KIND, USER_SELECTION_ADAPTER_ID, USER_SELECTION_OBSERVATION_KIND,
    USER_SELECTION_SOURCE_RULE_ID,
)
from pgdr.enums import WarningBehavior, WarningColor
from pgdr.models import WarningIndicator
from pgdr.ports.dashboard_interpretation import MatchStatus


class UserSelectionError(ValueError):
    """The driver's selection is not one of the entries that were offered
    (fails closed -- never silently accepted)."""


@dataclass(frozen=True)
class FallbackOffer:
    trigger: MatchStatus
    entries: tuple[DashboardReferenceEntry, ...]
    trigger_observation_ids: tuple[str, ...] = field(default_factory=tuple)
    trigger_result_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def offered_entry_ids(self) -> frozenset[str]:
        return frozenset(e.entry_id for e in self.entries)


# When a single image yields several validated results and none is a MATCH,
# the fallback follows the most actionable status present: an ambiguity
# (preserved candidates) is more specific than a no-match, which is more
# specific than an unusable image.
_TRIGGER_PRECEDENCE = (
    MatchStatus.AMBIGUOUS_MATCH, MatchStatus.NO_MATCH, MatchStatus.INSUFFICIENT_VISUAL_QUALITY,
)


def _provider_observations(intake: DiagnosticIntakeResult) -> list[Observation]:
    return [o for o in intake.observations if o.kind == PROVIDER_OBSERVATION_KIND]


def fallback_trigger(intake: DiagnosticIntakeResult) -> MatchStatus | None:
    """None when the intake contains at least one MATCH (no fallback is
    needed: the governed path proceeds with the matches). Otherwise the
    single status that drives the fallback. An intake with no observation
    at all (a provider that returned nothing) is treated as NO_MATCH --
    the driver is offered the applicable symbols; nothing is fabricated."""
    if intake.matched_reference_entries:
        return None
    statuses = {o.context.get("match_status") for o in _provider_observations(intake)}
    for status in _TRIGGER_PRECEDENCE:
        if status.value in statuses:
            return status
    return MatchStatus.NO_MATCH


def fallback_offer(
    trigger: MatchStatus, intake: DiagnosticIntakeResult, reference_set: DashboardReferenceSet,
) -> FallbackOffer:
    """AMBIGUOUS_MATCH: only the provider's preserved candidates.
    NO_MATCH / INSUFFICIENT_VISUAL_QUALITY (after retakes): the full
    applicable reference set. The offered list carries designation /
    descriptor / colour / state / message for RECOGNITION -- the caller
    presents those, never documented_meaning or documented_instruction."""
    observations = [
        o for o in _provider_observations(intake) if o.context.get("match_status") == trigger.value
    ]
    obs_ids = tuple(o.id for o in observations)
    result_ids = tuple(o.context.get("interpretation_result_id") for o in observations)
    if trigger == MatchStatus.AMBIGUOUS_MATCH:
        candidate_ids: list[str] = []
        for o in observations:
            for cid in o.context.get("candidate_reference_entry_ids", []):
                if cid not in candidate_ids:
                    candidate_ids.append(cid)
        entries = tuple(e for e in reference_set.entries if e.entry_id in candidate_ids)
    else:
        entries = tuple(reference_set.entries)
    return FallbackOffer(
        trigger=trigger, entries=entries, trigger_observation_ids=obs_ids, trigger_result_ids=result_ids,
    )


def build_user_selection_intake(
    offer: FallbackOffer, *, media_reference: str, selected_entry_id: str | None,
) -> DiagnosticIntakeResult:
    """The driver's selection (or "none of these") as a USER-provenance
    Observation, plus -- only for a real selection -- NEUTRAL Evidence
    with its own source_rule_id and a rationale stating the identification
    was made by the driver and not visually verified. The selected entry
    is the exact frozen reference entry that was offered (same instance),
    transported for downstream B2-R relevance exactly like a B2-C match."""
    entry: DashboardReferenceEntry | None = None
    if selected_entry_id is not None:
        entry = next((e for e in offer.entries if e.entry_id == selected_entry_id), None)
        if entry is None:
            raise UserSelectionError(
                f"entry_id {selected_entry_id!r} was not among the offered entries"
            )

    context = {
        "selection_provenance": "USER_MANUFACTURER_SYMBOL_SELECTION",
        "adapter_id": USER_SELECTION_ADAPTER_ID,
        "machine_verified": False,
        "triggering_match_status": offer.trigger.value,
        "triggering_observation_ids": list(offer.trigger_observation_ids),
        "triggering_interpretation_result_ids": list(offer.trigger_result_ids),
        "offered_reference_entry_ids": sorted(offer.offered_entry_ids),
        "selected_reference_entry_id": selected_entry_id,
        "media_reference": media_reference,
    }
    observation = Observation(
        kind=USER_SELECTION_OBSERVATION_KIND,
        value=entry.manufacturer_designation if entry is not None else "none_of_the_offered_symbols",
        source_type=ObservationSource.USER,
        source_ref=media_reference,
        context=context,
    )
    if entry is None:
        return DiagnosticIntakeResult(observations=[observation])

    document = entry.applicability
    rationale = (
        f"Symbole du tableau de bord indiqué par le conducteur dans la liste des références constructeur "
        f"('{entry.manufacturer_designation}', entry_id={entry.entry_id}, document "
        f"{document.manufacturer} {document.document_id}) : identification déclarative du conducteur, "
        f"non vérifiée visuellement sur la photo."
    )
    evidence = Evidence(
        observation_ids=[observation.id],
        direction=EvidenceDirection.NEUTRAL,
        target_hypothesis_id=None,
        weight=None,
        rationale=rationale,
        source_rule_id=USER_SELECTION_SOURCE_RULE_ID,
    )
    return DiagnosticIntakeResult(
        observations=[observation], evidence=[evidence], matched_reference_entries={observation.id: entry},
    )


_COLOUR_MAP = {
    "red": WarningColor.RED, "orange": WarningColor.AMBER, "amber": WarningColor.AMBER,
    "yellow": WarningColor.AMBER, "green": WarningColor.GREEN, "blue": WarningColor.BLUE,
    "white": WarningColor.WHITE,
}
_BEHAVIOR_MAP = {IndicatorState.FIXED: WarningBehavior.CONSTANT, IndicatorState.FLASHING: WarningBehavior.FLASHING}


def warning_indicator_from_entry(entry: DashboardReferenceEntry, *, photo_evidence_id: str | None) -> WarningIndicator:
    """Projection of a governed reference entry onto the existing
    WarningIndicator shape (label / colour / behaviour / message) that the
    unmodified SafetyEngine already evaluates. Unknown colour/state stay
    UNKNOWN -- never inferred."""
    return WarningIndicator(
        label=entry.manufacturer_designation,
        observed_color=_COLOUR_MAP.get((entry.colour or "").lower(), WarningColor.UNKNOWN),
        behavior=_BEHAVIOR_MAP.get(entry.state, WarningBehavior.UNKNOWN) if entry.state else WarningBehavior.UNKNOWN,
        associated_message=entry.displayed_message,
        photo_evidence_id=photo_evidence_id,
    )


# ---------------------------------------------------------------------------
# Per-case photo acquisition state (held by SessionController, keyed by
# session id -- isolated per session by construction).
# ---------------------------------------------------------------------------

from enum import Enum  # noqa: E402


class PhotoPhase(str, Enum):
    AWAITING_PHOTO = "awaiting_photo"
    RETAKE_REQUESTED = "retake_requested"
    SELECTION_REQUIRED = "selection_required"
    COMPLETED = "completed"


@dataclass
class PhotoCaseState:
    media_reference: str | None = None
    phase: PhotoPhase = PhotoPhase.AWAITING_PHOTO
    retakes_used: int = 0
    trigger: MatchStatus | None = None
    offer: FallbackOffer | None = None
    reference_set: DashboardReferenceSet | None = None
    last_intake: DiagnosticIntakeResult | None = None
    location_clarification_asked: bool = False


@dataclass(frozen=True)
class PhotoStep:
    """What the driver-facing layer must do next, after a photo attempt or
    a fallback decision."""
    phase: PhotoPhase
    trigger: MatchStatus | None = None
    offer: FallbackOffer | None = None
    retakes_used: int = 0
    retakes_remaining: int = 0
