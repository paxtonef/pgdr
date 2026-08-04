# Pre-Garage Diagnostic Runner (PGDR) v0.1

A CLI that helps a driver structure a vehicle problem before contacting a
garage: it runs a deterministic safety triage first, then asks adaptive
follow-up questions, then produces a Garage Preparation Report (for the
mechanic) and a simplified Driver Summary — never a definitive diagnosis.

See `LOG_DEPLOY.md` for the full deployment log, test results, and the
history of bugs found via live scenario testing.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 run_pgdr.py run --vir-id VIR-001 --complaint "La voiture tremble au ralenti"
```

## Run tests

```bash
.venv/bin/pytest tests/ -v
```

24/24 tests passing as of this version, covering the AMD spec's acceptance
scenarios plus regressions found during live testing (accent-insensitivity,
word-order-independent safety phrase matching, missing hypothesis families,
and several safety rules — sudden steering stiffness, EV battery thermal
events, major unknown fluid leaks — required by the spec but not yet wired
up in earlier drafts).

## Architecture

```
User (CLI) -> SessionController -> ComplaintParser -> SafetyEngine (deterministic)
                                                            |
                                        escalated <---------+---------> continue
                                                                            |
                                                                  DiagnosticEngine
                                                                  (system-family hypotheses)
                                                                            |
                                                                     ReportBuilder
                                                                  /                \
                                                       GaragePreparationReport   UserSummary
```

Deterministic safety rules live in `src/pgdr/config/safety_rules.yaml` — the
safety engine never depends on an LLM (see `safety_engine.py` docstring).
The complaint parser is a rule-based v0.1 placeholder for a future
LLM-backed implementation (see `complaint_parser.py` docstring).

## Known limitations (v0.1)

- English-language safety-phrase coverage is partial (only the
  highest-severity rules have English variants so far).
- No PDF export, no persistent session storage, no VIR HTTP client yet —
  all deferred per the v0.1 scope in the original spec.
