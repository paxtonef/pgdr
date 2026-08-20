"""P8 — PGDR x GGM Governed Consumption Integration.

This package contains ONLY PGDR-side adapter/consumption code: it imports
exclusively from `ggm.contract` and `ggm.consumption` (the public consumer
contract and consumption-resolution surfaces), never from GGM's internal
engines (InvariantEngine, ProfileResolver, TransitionEngine,
GovernanceDecisionEngine, EscalationDetector) — see
tests/test_p8_ggm_integration.py::test_p8_t01_no_internal_ggm_engine_imports,
which scans this package's source for exactly that.

No governance semantics are implemented here. This package answers "how
does PGDR talk to GGM," never "what should GGM decide."
"""
