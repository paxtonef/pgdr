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
| Canonical bounded/embedded GGM runtime | GGM itself does not provide one yet (confirmed by reading the pinned package - `README_HANDOFF.md` states this explicitly) | GGM-side delivery | v2.x (P8B, tracked separately below) |

## P8B specifically

Unlike the other entries above, P8B (bounded/embedded GGM runtime) is not
a "maybe someday" item - it's a known, specific, already-scoped follow-up
blocked purely on an external dependency. `GGMDiagnosticGovernanceAdapter`
already takes any `GGMConsumer` by dependency injection specifically so
this swap requires zero PGDR code changes once available - only a
different object passed to `SessionController.__init__(governance_consumer=...)`.
Candidate target: **v2.x**, as soon as GGM ships it - not v3, since it
changes no PGDR architecture, only which concrete `GGMConsumer` is
constructed.
