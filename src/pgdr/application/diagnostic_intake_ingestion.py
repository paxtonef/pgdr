"""Block B2-I — Diagnostic Pipeline Integration.

Connects the already-accepted B2-D diagnostic intake to PGDR's existing
case-state machinery. This module introduces NO new diagnostic
semantics, no parallel diagnostic engine, and no new CaseState mutation
logic -- it exists only to close the last structural gap: B2-D produces
a DiagnosticIntakeResult, and something has to call the existing
CaseStateUpdater with its contents.

INVESTIGATION FINDING (mandate §4/§5, execution subsidiarity): the
lowest sufficient existing execution layer is
pgdr.application.case_state_updater.CaseStateUpdater. Its
add_observations(state, list[Observation]) and add_evidence(state,
list[Evidence]) already accept exactly DiagnosticIntakeResult's own
field shapes -- no adaptation, no new CaseState API, and no
SessionController/DiagnosticLoop change is required. This module does
not escalate to either of those higher layers.

INVESTIGATION FINDING (mandate §15, diagnostic reasoning test): existing
PGDR reasoning C. IGNORES unlinked Evidence, it does not hold it for a
later linking stage and does not reject it.
  - CaseStateUpdater.add_evidence() only recomputes hypothesis
    confidence for `{e.target_hypothesis_id for e in evidence if
    e.target_hypothesis_id}` -- since every B2-D Evidence record has
    target_hypothesis_id=None, this set is always empty and
    update_hypotheses() is never triggered by B2-D evidence.
  - CaseStateUpdater.update_hypotheses() itself only pulls
    `e for e in state.evidence if e.target_hypothesis_id == h.id` --
    None never equals a hypothesis id, so a hypothesis's
    supporting/contradicting_evidence_ids can never include B2-D
    evidence.
  - pgdr.report_builder only surfaces observations with
    kind in {"symptom", "warning_indicator"} and evidence reached via a
    hypothesis's supporting/contradicting_evidence_ids -- B2-D's
    kind="dashboard_visual_interpretation" observations and
    target_hypothesis_id=None evidence match neither path and do not
    appear in the generated report.
  - automotive/domain_adapter.py's map_evidence() only looks at
    observations with kind == "symptom", so B2-D data cannot
    accidentally trigger domain-generated evidence either.
  This is reported as the required investigation result (mandate §15)
  -- it is NOT changed by this block. B2-D evidence is durably stored
  in state.evidence (available to any FUTURE, separately-authorized
  hypothesis-linking stage) but plays no role in current scoring or
  reporting.

INVESTIGATION FINDING (mandate §16, atomicity): CaseStateUpdater
provides no cross-call transaction/rollback -- add_observations() and
add_evidence() are two independent, sequential `list.extend()` calls
with no shared undo. This module does not invent a rollback mechanism
(that would be new diagnostic-adjacent machinery beyond what was
authorized); instead it relies on the one atomicity property that
already exists for free: ingest_dashboard_interpretation() calls
build_diagnostic_intake() BEFORE either CaseStateUpdater call, so a
provider/B2-V/B2-D failure (the realistic failure mode -- both
CaseStateUpdater calls below are plain extends of already
pydantic-validated, frozen objects and are not expected to raise under
normal operation) aborts before any case-state mutation happens at all.
Once build_diagnostic_intake() has returned successfully, both
CaseStateUpdater calls are extremely low-risk no-fail operations (see
test_block_b2i_pipeline_integration.py for what is actually verified).

INVESTIGATION FINDING (mandate §16, duplicate invocation): CaseStateUpdater
has no id-based deduplication on observations or evidence (unlike
update_uncertainties(), which does dedupe by id) -- calling
ingest_dashboard_interpretation() twice with results from two separate
provider invocations WILL append twice (each provider call produces
fresh objects with fresh ids, so there is nothing to deduplicate against
in the first place -- this is not a bug introduced here, it is
CaseStateUpdater's existing, unmodified behaviour, reported per §16
rather than silently patched).
"""
from __future__ import annotations

from pgdr.application.case_state_updater import CaseStateUpdater
from pgdr.application.diagnostic_intake_from_interpretation import (
    DiagnosticIntakeResult, build_diagnostic_intake,
)
from pgdr.domain.analytical_state import DiagnosticCaseState
from pgdr.domain.dashboard_knowledge import DashboardReferenceSet
from pgdr.ports.dashboard_interpretation import DashboardInterpretationPort
from pgdr.ports.media_resolver import ResolvedMedia


def ingest_dashboard_interpretation(
    provider: DashboardInterpretationPort,
    media: ResolvedMedia,
    reference_set: DashboardReferenceSet,
    updater: CaseStateUpdater,
    state: DiagnosticCaseState,
) -> DiagnosticIntakeResult:
    """B2-I's integration entrypoint -- and, structurally, the only path
    by which a dashboard interpretation can reach PGDR case state.

        (provider, media, reference_set)
            -> build_diagnostic_intake()        [B2-D: mandatorily calls
                                                   B2-V's run_governed_interpretation()]
            -> DiagnosticIntakeResult
            -> CaseStateUpdater.add_observations()  [existing, unmodified]
            -> CaseStateUpdater.add_evidence()       [existing, unmodified]

    Takes (provider, media, reference_set) -- the same shape B2-D and
    B2-V themselves take -- never a bare DiagnosticIntakeResult or a
    bare list[DashboardInterpretationResult]. There is therefore no
    parameter through which raw provider output, or a
    DiagnosticIntakeResult assembled without crossing B2-D, could enter
    case state through this function (mandate I14/I15/I16). Returns the
    same DiagnosticIntakeResult that was inserted, for the caller's own
    confirmation/logging -- the frozen Observation/Evidence instances
    inside it are the exact objects appended to state, never copied or
    rebuilt, so nothing about them can be silently altered on the way
    in (mandate §8's "enter PGDR unchanged in substantive content").

    Contains no diagnostic reasoning of its own: no Hypothesis is
    created, no Evidence field (direction/target_hypothesis_id/weight)
    is read or altered, no match_status is reinterpreted. This function
    only calls two pre-existing CaseStateUpdater methods with B2-D's own
    output, unmodified."""
    intake = build_diagnostic_intake(provider, media, reference_set)
    if intake.observations:
        updater.add_observations(state, list(intake.observations))
    if intake.evidence:
        updater.add_evidence(state, list(intake.evidence))
    return intake
