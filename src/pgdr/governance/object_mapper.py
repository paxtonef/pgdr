"""P8 mandate §10-13 — PGDRGGMObjectMapper: DiagnosticGovernanceCandidate
-> serialized GGM governed object, and PGDR Evidence -> EvidenceRef.

Every GGM field used below is read verbatim from ggm.model (never
invented): EpistemicStatus.UNKNOWN and AuthorityLevel.NONE are literally
the dataclass defaults for EpistemicState.status / AuthorityState.level —
"the lowest/non-authoritative canonical state" mandate §11 requires is
therefore GGM's own default, not a PGDR guess. ClaimFamily.HYPOTHETICAL is
used because that's what a PGDR hypothesis honestly is (PGDR's own
"compatible with" language never asserts fact — PGDR-HYP-003) — this is
using GGM's existing vocabulary accurately, not extending it.

RelationType is imported but never used to convert SUPPORTS/CONTRADICTS
into anything else (mandate §13) — this module maps PGDR's Evidence
direction into EvidenceRef.details["direction"], a plain string field,
specifically because EvidenceRef has no `relation_type` field of its own
(that concept belongs to GovernedRelation, a different object type this
module does not construct — P8 v1 governs candidate claims, not
relations between them).
"""
from __future__ import annotations

from typing import Any

from ggm.contract.types import EvidenceRef
from ggm.model import (
    AuthorityState,
    Classification,
    ClaimFamily,
    EpistemicState,
    EpistemicStatus,
    GovernedClaim,
    Origin,
    OriginType,
)

from pgdr.governance.port import DiagnosticGovernanceCandidate

# Free-text descriptor for EvidenceRef.type — EvidenceRef.type is a plain
# string field with no published enum of allowed values (confirmed by
# reading ggm/contract/types.py), so this is a PGDR-chosen descriptive
# label, not a GGM vocabulary term.
_PGDR_EVIDENCE_TYPE = "pgdr_analytical_evidence"


class PGDRGGMObjectMapper:
    def to_governed_claim_dict(self, candidate: DiagnosticGovernanceCandidate) -> dict[str, Any]:
        """mandate §10/§11. Never sets epistemic.status or authority.level
        beyond GGM's own dataclass defaults (UNKNOWN / NONE) — analytical_score
        is preserved as metadata (classification.confidence) only, never
        used to compute an epistemic or authority state."""
        score = candidate.analytical_score if candidate.analytical_score is not None else 0.0
        score = max(0.0, min(1.0, score))

        claim = GovernedClaim(
            id=candidate.hypothesis_id,
            content=candidate.statement,
            origin=Origin(
                origin_type=OriginType.DETERMINISTIC_SYSTEM,
                producer_id="pgdr.diagnostic_loop",
                run_id=candidate.case_id,
            ),
            classification=Classification(
                families=[ClaimFamily.HYPOTHETICAL],
                confidence=score,
            ),
            epistemic=EpistemicState(),  # defaults: status=UNKNOWN, uncertainty=UNKNOWN, contested=False
            authority=AuthorityState(),  # default: level=NONE
            # permissions / risk / lifecycle intentionally left at their
            # GGM-defined defaults (all-False permissions, R0 risk,
            # ACTIVE lifecycle) — PGDR pre-asserts none of these; DECIDE's
            # effective_permissions is what governs presentation, not
            # anything set here.
        )
        return claim.to_dict()

    def to_evidence_refs(self, evidence_items: list[tuple[str, str, str]]) -> list[EvidenceRef]:
        """mandate §12. `evidence_items` is a list of
        (evidence_id, direction, rationale) tuples — direction is passed
        through verbatim ("SUPPORTS"/"CONTRADICTS"/"NEUTRAL", PGDR's own
        pgdr.domain.enums.EvidenceDirection values), never translated into
        GGM's RelationType vocabulary (mandate §13's explicit prohibition
        on SUPPORTS->CAUSES applies to any such conversion, not only that
        specific pair)."""
        refs = []
        for evidence_id, direction, rationale in evidence_items:
            refs.append(EvidenceRef(
                type=_PGDR_EVIDENCE_TYPE,
                ref=evidence_id,
                details={"direction": direction, "rationale": rationale} if rationale else {"direction": direction},
            ))
        return refs
