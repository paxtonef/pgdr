"""P4's first (and for P4, only) Domain Pack implementation. Wraps the
existing, unmodified v0.1 automotive logic (ComplaintParser,
DiagnosticEngine's `_HYPOTHESIS_MAP`, questions.yaml) behind the generic
ports defined in pgdr.ports — per the mandate: "construit à partir du
comportement actuel," not a rewrite of the automotive knowledge itself.
"""
