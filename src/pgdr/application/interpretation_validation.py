"""Block B2-V — validation guard: no provider output may reference
manufacturer knowledge outside the DashboardReferenceSet it was given.

This is the concrete implementation of the invariant the B2-V mandate
states repeatedly (§3, §8, §14, B2V-05, B2V-14, B2V-17): "the provider
must not identify freely from its own trained knowledge... the provider
may NOT supply automotive meaning outside DashboardReferenceSet." A
Pydantic-level check inside DashboardInterpretationResult itself cannot
enforce this (the model has no access to the reference_set at
construction time), so this module provides the actual enforcement point
-- a pure function any concrete adapter (or a future orchestration layer)
runs a provider's raw output through before treating it as trustworthy.

Deliberately NOT wired into SessionController or the DiagnosticLoop in
this pass, per the mandate's own §12/§B2V-18/19/20 instruction -- this is
a standalone, directly testable capability, not yet connected to
production reasoning.

B2-V GOVERNANCE REPAIR (this pass) -- PGDR B2-V GOVERNANCE REPAIR MANDATE:
Until this pass, `validate_against_reference_set` was correct but
optional from the architecture's perspective -- a conforming
DashboardInterpretationPort caller could invoke a provider and use its
results without ever calling it. `run_governed_interpretation` below is
the governed B2-V execution boundary: the one function through which a
provider's UNTRUSTED output becomes a VALIDATED result, with no
successful return path that skips validation.

    PROVIDER OUTPUT != TRUSTED B2-V OUTPUT
    PROVIDER OUTPUT + MANDATORY VALIDATION = TRUSTED B2-V OUTPUT

A provider exception is never caught here -- it propagates unchanged, so
a provider failure can never be transformed into a fabricated NO_MATCH or
any other manufactured result (fail-closed, per B2V-24 and the repair
mandate's G10).
"""
from __future__ import annotations

from pgdr.domain.dashboard_knowledge import DashboardReferenceSet
from pgdr.ports.dashboard_interpretation import (
    DashboardInterpretationPort, DashboardInterpretationResult, MatchStatus,
)
from pgdr.ports.media_resolver import ResolvedMedia


class InterpretationValidationError(Exception):
    """Raised when a provider's output references manufacturer knowledge
    not present in the DashboardReferenceSet it was given -- fail closed,
    per B2V-24. Never silently dropped or coerced into a different
    match_status."""


def validate_against_reference_set(
    results: list[DashboardInterpretationResult], reference_set: DashboardReferenceSet,
) -> list[DashboardInterpretationResult]:
    """Confirms every positive match (MATCH) and every ambiguous
    candidate (AMBIGUOUS_MATCH) in `results` references a real
    DashboardReferenceEntry.entry_id actually present in `reference_set`.
    Returns `results` unchanged when every reference is valid. Raises
    InterpretationValidationError -- never silently filters or
    downgrades a result -- the moment any single result references an
    entry_id the reference_set does not contain, per B2V-05/B2V-17/T08."""
    known_entry_ids = {entry.entry_id for entry in reference_set.entries}

    for result in results:
        if result.match_status == MatchStatus.MATCH:
            if result.matched_reference_entry_id is None:
                raise InterpretationValidationError(
                    f"result {result.id}: match_status is MATCH but matched_reference_entry_id is None"
                )
            if result.matched_reference_entry_id not in known_entry_ids:
                raise InterpretationValidationError(
                    f"result {result.id}: matched_reference_entry_id "
                    f"{result.matched_reference_entry_id!r} is not present in the supplied "
                    f"DashboardReferenceSet (known entry_ids: {sorted(known_entry_ids)})"
                )
            if result.identification is not None:
                matched_entry = next(e for e in reference_set.entries if e.entry_id == result.matched_reference_entry_id)
                if result.identification != matched_entry.manufacturer_designation:
                    raise InterpretationValidationError(
                        f"result {result.id}: identification {result.identification!r} does not "
                        f"equal the matched entry's own manufacturer_designation "
                        f"{matched_entry.manufacturer_designation!r} -- identification must never be "
                        f"free-form provider output"
                    )

        if result.match_status == MatchStatus.AMBIGUOUS_MATCH:
            unknown = set(result.candidate_reference_entry_ids) - known_entry_ids
            if unknown:
                raise InterpretationValidationError(
                    f"result {result.id}: candidate_reference_entry_ids contains entry_id(s) not "
                    f"present in the supplied DashboardReferenceSet: {sorted(unknown)}"
                )
            if result.matched_reference_entry_id is not None:
                raise InterpretationValidationError(
                    f"result {result.id}: match_status is AMBIGUOUS_MATCH but "
                    f"matched_reference_entry_id is set -- ambiguity must never be silently resolved "
                    f"(B2V-12)"
                )

        if result.match_status in (MatchStatus.NO_MATCH, MatchStatus.INSUFFICIENT_VISUAL_QUALITY):
            if result.matched_reference_entry_id is not None or result.candidate_reference_entry_ids:
                raise InterpretationValidationError(
                    f"result {result.id}: match_status is {result.match_status.value} but a matched/"
                    f"candidate entry is set -- {result.match_status.value} must never carry a "
                    f"fabricated identification (B2V-11)"
                )

    return results


def run_governed_interpretation(
    provider: DashboardInterpretationPort,
    media: ResolvedMedia,
    reference_set: DashboardReferenceSet,
) -> list[DashboardInterpretationResult]:
    """The governed B2-V execution boundary (B2-V governance repair).

        ResolvedMedia + DashboardReferenceSet
            -> provider.interpret(...)          [UNTRUSTED results]
            -> validate_against_reference_set()  [MANDATORY]
            -> VALIDATED results

    There is exactly one return statement, and it produces the
    validator's own result -- no branch exists that returns the
    provider's output without passing it through
    validate_against_reference_set first, and
    a provider exception is never caught or swallowed here: it propagates
    to the caller unchanged, fail-closed. Does not connect
    SessionController or the DiagnosticLoop, create Observation/Evidence/
    Hypothesis, or integrate a real visual provider -- this function only
    makes the already-existing validation step mandatory."""
    return validate_against_reference_set(provider.interpret(media, reference_set), reference_set)
