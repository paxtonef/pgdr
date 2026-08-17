"""P4 — Analytical State Model. Domain-agnostic diagnostic reasoning
objects (Observation, Evidence, Hypothesis, Uncertainty, Contradiction,
Question, Answer, DiagnosticCaseState).

These are deliberately separate from pgdr.models — that module holds the
v0.1 request/response schema (still used by session_controller.py,
report_builder.py, cli.py's `run` command, and all 70 pre-P4 tests) and
is untouched by P4. This package is the new analytical-state pipeline,
built alongside it per the P4 mandate's backward-compatibility
requirement (§23): old code paths keep working unmodified.

Per §25 of the mandate, nothing in this package (or ports/, application/,
automotive/) implements epistemic status (VERIFIED/CONFIRMED), claim
authority, or any GGM/CGM concept — those are explicitly out of scope for
P4 and belong to a future phase.
"""
