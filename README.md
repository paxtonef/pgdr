# Pre-Garage Diagnostic Runner (PGDR) v2.0.0

PGDR helps drivers structure vehicle problems before contacting a garage.
Available as both a CLI and a web application (French UI), it runs
deterministic safety triage first, then reasons adaptively through
`DiagnosticLoop` (question → answer → observation → evidence → hypothesis
update), then governs every candidate diagnostic statement through GGM
before producing a Garage Preparation Report (for the mechanic) and a
simplified User Summary — never a definitive diagnosis, and never an
ungoverned one.

See `LOG_DEPLOY.md` for the full deployment log and
`docs/release/PGDR_v2_RELEASE_MANIFEST.md` for what actually exists in
this version, capability by capability. The `docs/architecture/`
directory holds each phase's (P0-P8) own findings and freeze documents;
`docs/release/` holds the v2 release-freeze documents that supersede
nothing but consolidate everything.

## Quick start (CLI)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install /path/to/ggm-1.0.0-py3-none-any.whl   # canonical GGM 1.0.0 (supplied out-of-band, not on PyPI, not in this repo)
pip install -r requirements.txt

python3 run_pgdr.py run --vir-id VIR-001 --complaint "La voiture tremble au ralenti"
python3 run_pgdr.py readiness
python3 run_pgdr.py --version
```

## Web Application (French UI)

Run the web server locally:

```bash
# Install dependencies (if not already done)
pip install /path/to/ggm-1.0.0-py3-none-any.whl   # canonical GGM 1.0.0
pip install fastapi uvicorn[standard]

# Start the web server
uvicorn pgdr.web_app:app --host 127.0.0.1 --port 8000

# Access in browser
open http://127.0.0.1:8000
```

Production deployment notes:
- **GGM required**: Production readiness (`/health`) requires GGM wheel available
- **Session topology**: In-memory sessions require single-process deployment
  (single uvicorn worker, no horizontal scaling, no scale-to-zero)
- **Language**: French UI only
- **Known limitations**: Diagnostic sessions are ephemeral (lost on restart)

## Run tests

```bash
# Ordinary regression (wheel-packaging tests skip without GGM_WHEEL_PATH)
pytest tests/ -v

# GGM-enabled regression with canonical GGM 1.0.0 (verify its SHA-256 first:
# 414591587d29adf756f16e39ad03cffe0fa2328c8a41e5bbf3ba6b0aa42799a7)
GGM_WHEEL_PATH=/path/to/ggm-1.0.0-py3-none-any.whl pytest tests/ -v

# Browser E2E tests (requires Playwright)
pip install pytest-playwright
playwright install chromium
pytest tests/test_browser_e2e.py -v
```

Test suite:
- **481 passed, 11 skipped** (ordinary; the 11 skips are the GGM wheel-packaging tests)
- **492 passed, 0 skipped, 0 failed** (GGM-enabled with canonical GGM 1.0.0, incl. real-Chromium E2E)
- Counts as of the canonical-GGM adoption; they are not a frozen historical target
- Web tests verify: readiness, session lifecycle, Evidence/scoring consistency,
  French UI rendering, session isolation, safety triage preservation,
  structural governance-path verification

See `docs/release/PGDR_v2_RELEASE_MANIFEST.md` for capability breakdown.

Since the original v2 freeze, an additive, self-contained capability was
built and proved end-to-end: turning a validated dashboard-photo
interpretation of a manufacturer-official indicator into a governed,
non-causal diagnostic hypothesis (see the "Dashboard / Manufacturer-Fact
Diagnostic Relevance" entry in the release manifest, and
`docs/architecture/b2_dashboard_manufacturer_relevance_freeze.md` for
the full investigation trail). It is not yet wired into `pgdr run` and
has no real visual provider behind it — both deliberate v1 boundaries,
not omissions; see `PGDR_v2_DEFERRED_CAPABILITIES.md`.

## Architecture

```
USER (CLI or Web Browser) → SessionController → SafetyEngine (deterministic, never overridden)
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
                                                             canonical GGM 1.0.0 —
                                                             commit 5fdea20)
                                                                           |
                                                                    Governed report
                                                                   /                \
                                                       GaragePreparationReport   UserSummary
```

Web layer: `FastAPI (src/pgdr/web_app.py)` → `SessionController` (existing core, unchanged).
No diagnostic semantics modified. Web adapter preserves existing lifecycle,
governance boundary, and French module coverage.

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
