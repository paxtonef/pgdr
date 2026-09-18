"""Block B2-D — Diagnostic Intake from Validated Visual Interpretation.

Connects the already-governed output of B2-V to PGDR's diagnostic input
semantics: the boundary at which a VALIDATED DashboardInterpretationResult
(never raw provider output) becomes PGDR-native Observation/Evidence.

    VALIDATED B2-V OUTPUT -> B2-D -> PGDR DIAGNOSTIC INPUT

This module does not perform diagnostic reasoning. It creates no
Hypothesis, determines no severity or driveability, and recommends no
repair or action -- those remain downstream PGDR responsibilities. It
does not integrate a real visual provider, and it is not wired into
SessionController or the DiagnosticLoop (a separate acceptance decision,
per the B2-D mandate's own §12).

Reuses pgdr.domain.observation.Observation and pgdr.domain.evidence.Evidence
unchanged -- no parallel Observation/Evidence model is introduced. The
existing models already have everything B2-D needs: Observation.context
is a free-form dict (carries match_status, confidences, candidate ids,
and interpretation/media provenance without requiring new fields), and
Evidence's target_hypothesis_id/weight are already optional (so a NEUTRAL,
unlinked-to-any-hypothesis Evidence record -- exactly what B2-D produces
-- is representable without fabricating hypothesis targeting or
certainty B2-D has no authority to assert).

B2-D is deliberately a SEPARATE channel from Q-EVI-002 (the existing
supplementary-photo answer path in pgdr.automotive.evidence_mapper,
MEDIA_EVIDENCE_SOURCE_RULE_ID = "automotive.media_evidence_acquired").
That path is answer-driven (DiagnosticQuestion/DiagnosticAnswer, routed
through CaseStateUpdater/AutomotiveEvidenceMapper) and remains completely
untouched by this module. B2-D uses its own distinct source_rule_id
(B2D_SOURCE_RULE_ID below) precisely so the two paths are never
conflated, per the B2-D mandate's own §7.

MATCH semantics -- the only match_status that produces Evidence:
Evidence.rationale and Observation.context preserve the matched entry's
identity (entry_id, manufacturer_designation) and its document
provenance (manufacturer, document_id, source_authority), never the
matched entry's own documented_meaning/documented_instruction -- copying
manufacturer MEANING (as opposed to manufacturer REFERENCE IDENTITY)
into a rationale would start to look like B2-D asserting or restating
automotive meaning itself, which is downstream reasoning's job, not
B2-D's (§4's "invent manufacturer meaning" prohibition read
conservatively).

AMBIGUOUS_MATCH / NO_MATCH / INSUFFICIENT_VISUAL_QUALITY: per §5, these
are represented as an Observation only (visual event preserved for
traceability, including any AMBIGUOUS_MATCH candidates, without
fabricating certainty) and produce NO Evidence at all -- the
conservative reading of "AMBIGUOUS_MATCH must not be silently converted
to MATCH" and "NO_MATCH/INSUFFICIENT_VISUAL_QUALITY must not create
manufacturer-identified Evidence": since none of these three states name
a resolved manufacturer reference, there is nothing evidentiary yet to
record as Evidence, only an observed event.

BLOCK B2-C EXTENSION (this pass) -- EXACT MANUFACTURER REFERENCE CONTEXT
TRANSPORT: DiagnosticIntakeResult gains `matched_reference_entries`, a
dict[observation_id, DashboardReferenceEntry] carrying, for every MATCH
result only, the EXACT (same-instance, frozen) DashboardReferenceEntry
that was looked up from the SAME in-memory reference_set already passed
to B2-V/B2-D -- never a re-query, never a reconstruction from selected
fields, never a copy. This makes documented_meaning, documented_
instruction, and the full ManufacturerDocumentReference (via
entry.applicability: document_id, source_authority, lifecycle_status,
freshness_status) available to whatever future, separately-authorized
capability performs diagnostic relevance determination -- without B2-D
itself reading, interpreting, or asserting any of that content (transport
is not semantic ownership, per this block's own §10). AMBIGUOUS_MATCH/
NO_MATCH/INSUFFICIENT_VISUAL_QUALITY observations simply have no entry
in this dict -- consistent with, and not a new form of, their existing
"no matched entry" semantics. The SAME entry object already looked up
for MATCH Evidence's rationale text is reused here (see
_matched_entry_for_result), never looked up a second, independent time
-- so the transported object and the object the rationale text describes
are provably identical, not merely equal.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pgdr.application.interpretation_validation import run_governed_interpretation
from pgdr.domain.dashboard_knowledge import DashboardReferenceEntry, DashboardReferenceSet
from pgdr.domain.enums import EvidenceDirection, ObservationSource
from pgdr.domain.evidence import Evidence
from pgdr.domain.observation import Observation
from pgdr.enums import Confidence
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationPort, DashboardInterpretationResult, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia

# Deliberately distinct from
# pgdr.automotive.evidence_mapper.MEDIA_EVIDENCE_SOURCE_RULE_ID
# ("automotive.media_evidence_acquired") -- the Q-EVI-002 answer-driven
# path and this primary-media/B2-V/B2-D path must never be conflated
# (mandate §7).
B2D_SOURCE_RULE_ID = "pgdr.b2d.dashboard_interpretation_intake"


class DiagnosticIntakeResult(BaseModel):
    """Plain paired container for B2-D's output -- NOT a new domain
    model competing with Observation/Evidence (both are reused exactly
    as defined elsewhere in PGDR); this only groups the two lists this
    conversion produces, in a shape directly compatible with
    pgdr.application.case_state_updater.CaseStateUpdater.add_observations
    / .add_evidence, should a future, separate acceptance decision wire
    B2-D into SessionController/DiagnosticLoop (not done in this block,
    per §12).

    matched_reference_entries (Block B2-C): dict[Observation.id,
    DashboardReferenceEntry] -- the exact, canonical, frozen B2-K entry
    for every MATCH observation, keyed by that observation's own id (not
    a new wrapper type -- a plain dict over an existing domain type, per
    B2-C's own §5/§7 prohibition on inventing a carrier). Absent key =
    no matched entry, which already means the same thing it always has
    for AMBIGUOUS_MATCH/NO_MATCH/INSUFFICIENT_VISUAL_QUALITY."""
    model_config = ConfigDict(frozen=True)

    observations: list[Observation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    matched_reference_entries: dict[str, DashboardReferenceEntry] = Field(default_factory=dict)


def _observation_context(
    result: DashboardInterpretationResult, reference_set: DashboardReferenceSet,
) -> dict[str, object]:
    """Everything about the validated interpretation result worth
    preserving for traceability (§8), independent of match_status."""
    return {
        "interpretation_result_id": result.id,
        "match_status": result.match_status.value,
        "observation_confidence": result.observation_confidence.value,
        "match_confidence": result.match_confidence.value if result.match_confidence else None,
        "matched_reference_entry_id": result.matched_reference_entry_id,
        "candidate_reference_entry_ids": list(result.candidate_reference_entry_ids),
        "media_reference": result.provenance.media_reference,
        "adapter_id": result.provenance.adapter_id,
        "interpreted_at": result.provenance.interpreted_at.isoformat(),
        "vehicle_applicability": reference_set.vehicle_applicability.model_dump(mode="json"),
    }


def _observation_from_result(
    result: DashboardInterpretationResult, reference_set: DashboardReferenceSet,
) -> Observation:
    """Every validated result -- regardless of match_status -- becomes an
    Observation. This is the visual event itself (what was observed, and
    what the governed B2-V boundary determined about it), never a
    diagnostic conclusion."""
    return Observation(
        kind="dashboard_visual_interpretation",
        value=result.observation,
        source_type=ObservationSource.PROVIDER,
        source_ref=result.provenance.media_reference,
        context=_observation_context(result, reference_set),
    )


def _matched_entry_for_result(
    result: DashboardInterpretationResult, reference_set: DashboardReferenceSet,
) -> DashboardReferenceEntry:
    """Block B2-C: the single lookup point for a MATCH result's exact
    DashboardReferenceEntry -- against the SAME in-memory reference_set
    already supplied to B2-V/B2-D (never a repository re-query; B2-C's
    own §6/§15/§16 forbid both). Called exactly once per MATCH result;
    its return value is reused for both the Evidence rationale (below)
    and DiagnosticIntakeResult.matched_reference_entries, so both refer
    to the identical object instance, never two independently-fetched
    copies."""
    return next(entry for entry in reference_set.entries if entry.entry_id == result.matched_reference_entry_id)


def _evidence_from_match(
    result: DashboardInterpretationResult, observation: Observation, matched_entry: DashboardReferenceEntry,
) -> Evidence:
    """Only called for match_status == MATCH (see the module docstring
    for why AMBIGUOUS_MATCH/NO_MATCH/INSUFFICIENT_VISUAL_QUALITY produce
    no Evidence). Preserves the matched entry's identity and document
    provenance in the rationale text -- never its documented_meaning/
    documented_instruction (that lookup belongs to whoever performs
    actual diagnostic reasoning downstream, not to B2-D). The full
    canonical object itself -- meaning included -- is separately
    transported via DiagnosticIntakeResult.matched_reference_entries
    (Block B2-C); this rationale text is a human-readable summary, not
    the structured transport mechanism."""
    document = matched_entry.applicability
    rationale = (
        f"Interprétation visuelle du tableau de bord (média {result.provenance.media_reference}), "
        f"validée par la frontière d'exécution gouvernée B2-V : correspondance avec la référence "
        f"constructeur '{matched_entry.manufacturer_designation}' (entry_id={matched_entry.entry_id}, "
        f"document {document.manufacturer} {document.document_id}). Aucune hypothèse, sévérité, "
        f"aptitude à circuler ou recommandation de réparation n'est déterminée à ce stade."
    )
    return Evidence(
        observation_ids=[observation.id],
        direction=EvidenceDirection.NEUTRAL,
        target_hypothesis_id=None,
        weight=None,
        rationale=rationale,
        source_rule_id=B2D_SOURCE_RULE_ID,
    )


def _diagnostic_intake_from_validated_results(
    validated_results: list[DashboardInterpretationResult], reference_set: DashboardReferenceSet,
) -> DiagnosticIntakeResult:
    """The actual B2-D conversion logic. Private (leading underscore):
    not part of B2-D's public contract, so tests exercising it directly
    are exercising an internal helper, not using it as a way to skip
    governed validation -- the only sanctioned public entrypoint is
    build_diagnostic_intake() below, which is the sole path that accepts
    a provider and therefore the sole path capable of invoking one."""
    observations: list[Observation] = []
    evidence: list[Evidence] = []
    matched_reference_entries: dict[str, DashboardReferenceEntry] = {}
    for result in validated_results:
        observation = _observation_from_result(result, reference_set)
        observations.append(observation)
        if result.match_status == MatchStatus.MATCH:
            matched_entry = _matched_entry_for_result(result, reference_set)
            evidence.append(_evidence_from_match(result, observation, matched_entry))
            matched_reference_entries[observation.id] = matched_entry
        # AMBIGUOUS_MATCH / NO_MATCH / INSUFFICIENT_VISUAL_QUALITY:
        # Observation only -- see module docstring. No entry in
        # matched_reference_entries either (B2-C §8/C13/C14).
    return DiagnosticIntakeResult(
        observations=observations, evidence=evidence, matched_reference_entries=matched_reference_entries,
    )


def build_diagnostic_intake(
    provider: DashboardInterpretationPort,
    media: ResolvedMedia,
    reference_set: DashboardReferenceSet,
) -> DiagnosticIntakeResult:
    """The B2-D execution boundary and its only public entrypoint.

        ResolvedMedia + DashboardReferenceSet
            -> provider.interpret(...)            [B2-V, UNTRUSTED]
            -> run_governed_interpretation()        [MANDATORY validation]
            -> VALIDATED DashboardInterpretationResult(s)
            -> B2-D conversion                      [this module]
            -> DiagnosticIntakeResult (Observation/Evidence)

    Takes the same (provider, media, reference_set) shape as
    run_governed_interpretation itself -- never a bare
    list[DashboardInterpretationResult] -- so there is no parameter
    through which already-unvalidated provider output could be passed
    in and reach the conversion step without crossing the governed B2-V
    boundary first. Raw DashboardInterpretationPort output is not an
    authorized B2-D input (mandate §2); this signature makes that
    structurally true rather than merely documented."""
    validated_results = run_governed_interpretation(provider, media, reference_set)
    return _diagnostic_intake_from_validated_results(validated_results, reference_set)
