# Pre-Garage Diagnostic Runner (PGDR) v2.0.0

A CLI that helps a driver structure a vehicle problem before contacting a
garage: it runs a deterministic safety triage first, then reasons
adaptively through `DiagnosticLoop` (question -> answer -> observation ->
evidence -> hypothesis update), then governs every candidate diagnostic
statement through GGM before producing a Garage Preparation Report (for
the mechanic) and a simplified User Summary — never a definitive
diagnosis, and never an ungoverned one.

See `LOG_DEPLOY.md` for the full deployment log and
`docs/release/PGDR_v2_RELEASE_MANIFEST.md` for what actually exists in
this version, capability by capability. The `docs/architecture/`
directory holds each phase's (P0-P8) own findings and freeze documents;
`docs/release/` holds the v2 release-freeze documents that supersede
nothing but consolidate everything.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install vendor/ggm-1.1.0-py3-none-any.whl   # pinned GGM package, not on PyPI
pip install -r requirements.txt

python3 run_pgdr.py run --vir-id VIR-001 --complaint "La voiture tremble au ralenti"
python3 run_pgdr.py readiness
python3 run_pgdr.py --version
```

## Run tests

```bash
.venv/bin/pytest tests/ -v -m "not packaging"                                          # fast, source tree only
GGM_WHEEL_PATH="$(pwd)/vendor/ggm-1.1.0-py3-none-any.whl" .venv/bin/pytest tests/ -v    # full suite incl. wheel/packaging
```

157/157 tests passing as of this release — see
`docs/release/PGDR_v2_RELEASE_MANIFEST.md` for the breakdown by
capability and `docs/release/PGDR_v2_KNOWN_LIMITATIONS.md` for what this
number does and doesn't mean.

## Architecture

```
USER (CLI) -> SessionController -> SafetyEngine (deterministic, never overridden)
                                          |
                      escalated <---------+---------> continue
                                                            |
                                                  DiagnosticCaseState
                                                            |
                                                     DiagnosticLoop
                                          (DiagnosticDomain, EvidenceMapper,
                                           HypothesisScorer, QuestionSelector)
                                                            |
                                              === GGM governance boundary ===
                                                            |
                                              GGMConsumer.evaluate() (real,
                                              pinned GGM package — commit
                                              4fda597)
                                                            |
                                                     Governed report
                                                    /                \
                                        GaragePreparationReport   UserSummary
```

Three distinct authorities, kept structurally separate: **Safety**
(`SafetyEngine`, unchanged since P0), **Analytical**
(`DiagnosticCaseState` + `DiagnosticLoop`, frozen at P7), and
**Governance** (GGM, consumed exclusively through `GGMConsumer`, never
reimplemented locally — integrated at P8). Full detail, including a
grep-based audit proving no fourth (hidden) authority exists, is in
`docs/release/PGDR_v2_ARCHITECTURE_FREEZE.md` and
`docs/release/PGDR_v2_NO_HIDDEN_AUTHORITY_AUDIT.md`.

Deterministic safety rules live in `src/pgdr/config/safety_rules.yaml` —
the safety engine never depends on an LLM (see `safety_engine.py`
docstring). The complaint parser is a rule-based placeholder for a
future LLM-backed implementation (see `complaint_parser.py` docstring) —
still true in v2, unchanged.

## Known limitations

See `docs/release/PGDR_v2_KNOWN_LIMITATIONS.md` for the full, current
list (automotive evidence coverage scope, one PROVISIONAL evidence rule,
governance-permission enforcement granularity, and more) and
`docs/release/PGDR_v2_DEFERRED_CAPABILITIES.md` for what v2 doesn't
attempt at all (Case Repository, Vehicle Health Record, cross-brand
capability reasoning, bounded/embedded GGM runtime, and others), each
with its reason and candidate target version.
