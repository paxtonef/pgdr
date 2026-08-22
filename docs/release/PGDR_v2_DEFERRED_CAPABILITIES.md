# PGDR v2 Deferred Capabilities Register

Capabilities that do not exist in v2 at all - not implemented, not
partially implemented. Distinct from `PGDR_v2_KNOWN_LIMITATIONS.md`,
which covers things v2 *does* do, with bounded coverage. Nothing here is
a bug; each entry was deliberately not attempted, per the phase mandate
that introduced or could have introduced it.

| Capability | Reason deferred | Dependency | Candidate target |
|---|---|---|---|
| Case Repository / persistent diagnostic history | Explicitly out of scope for every phase P4-P8; no PGDR component reads or writes case history across sessions today | none | v3 |
| Vehicle Health Record | Same - never attempted | Case Repository | v3 |
| Garage feedback ingestion (post-repair outcome loop) | Never attempted; would require a new external input channel PGDR has no model for | Case Repository | v3 |
| Cross-brand / cross-manufacturer capability knowledge | P6 mandate explicitly deferred this ("DEFER TO CAPABILITY MODEL"); `configuration_requirements` mechanism exists but no capability taxonomy is built on top of it | Capability Model (undesigned) | UNDECIDED |
| Historical case similarity / large-scale diagnostic knowledge accumulation | Never attempted; no learning mechanism exists anywhere in PGDR - every hypothesis/evidence relation is either hand-authored (`_HYPOTHESIS_MAP`) or explicitly PROVISIONAL | Case Repository | v3 |
| Additional automotive evidence mappings beyond the 2 currently MAPPED questions | P6's own explicit target was 100% KNOWN STATUS, not 100% MAPPED - 8 of 10 questions remain NEUTRAL/UNMAPPED by design, pending validated sources | none - additive work, can happen incrementally | v2.x |
| Real external diagnostic providers (e.g. OBD-II telemetry, manufacturer APIs) | Never attempted; PGDR's `ComplaintParser` only processes free-text complaints | none | v3 |
| Remote GGM service mode | P8's Axis 3 declares `shared_service_allowed=False` deliberately (see `p8_consumption_profile.md`) - PGDR is standalone-only today | Deployment Profile change + GGM-side remote service | UNDECIDED |
| ~~Canonical bounded/embedded GGM runtime~~ **DELIVERED** | GGM P2.2 shipped `RuntimeMaterializer` / `MaterializedGGMRuntime`; PGDR migrated to consume it (see `PGDR_v2_DEPENDENCY_FREEZE.md`) | ~~GGM-side delivery~~ done | ~~v2.x (P8B)~~ delivered |

## P8B specifically — DELIVERED, prediction below was WRONG on scope

P8B (bounded/embedded GGM runtime) was tracked as a known, specific,
already-scoped follow-up blocked purely on an external dependency. That
dependency has been delivered (GGM P2.2, `RuntimeMaterializer`), and
PGDR has migrated to it.

CORRECTION: the original prediction below claimed this swap would
require "zero PGDR code changes... only a different object passed to
`governance_consumer`." That was wrong. `RuntimeMaterializer` requires
an explicit `resolve -> materialize` call PGDR did not previously make;
the migration modified `session_controller.py`,
`governance/consumption_profile.py`, and `readiness.py`. The
`GGMConsumer` Protocol injection seam (`governance_consumer` parameter)
itself was correctly identified as stable and was NOT what needed to
change — but calling code around it did.

Original (superseded) prediction, kept for record:
"`GGMDiagnosticGovernanceAdapter` already takes any `GGMConsumer` by
dependency injection specifically so this swap requires zero PGDR code
changes once available - only a different object passed to
`SessionController.__init__(governance_consumer=...)`."
