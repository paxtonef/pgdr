"""P4 — application services that orchestrate the domain model.
CaseStateUpdater is the only component meant to mutate a
DiagnosticCaseState's collections (mandate §13) — this exists precisely
to avoid recreating the pre-P4 fragmentation where SessionController,
DiagnosticEngine, and ReportBuilder each independently owned a slice of
the case's knowledge.
"""
