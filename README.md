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

### V1 parcours (`/v1`)

VIR handoff (`POST /api/v1/vir-handoff`, same credential as the photo-first
handoff) → consent → optional photo (kept in the browser only: not analysed,
not sent, not kept) → the complete manual catalogue in manual order → the
driver's own selection by `entry_id` → explicit confirmation → exact
restitution (one section per image: image, designation, exact text and
pictograms, complete linked warnings, « selon équipement », « s'allume au
démarrage », pages). « Aucune ne correspond » / « Je ne sais pas » → colour →
the fallback screens in their VALIDATED French translation
(`src/pgdr/config/v1_fallback_screens.fr.yaml`, byte-identical to
`outils/preparation_v1/config/fallback_screens.fr.yaml`, named validation
Fred Cobral, 2026-10-07; an unvalidated file is refused). Interface texts are
French; manufacturer texts stay in the notice language, untranslated, with a
language note above the restitution. Curation notes are not shown.
No model provider is called. The notice is read by
`pgdr.adapters.manifest_notice_repository.ManifestNoticeRepository` (read-only
KnowledgeRepositoryPort): it recomputes the content fingerprint, checks every
file digest and refuses a pending/obsolete review.

Configuration: `PGDR_V1_MANIFEST` (notice manifest, outside the repo). A notice
whose applicability to the vehicle is not established is refused, except in
the local development trial (`outils/essai_dev_v1/lancer.sh`, which sets
`PGDR_V1_DEV_TRIAL=1`, a SIMULATED VIR identity, and shows a permanent banner).

After confirmation the parcours shows the existing **Premier Constat
Constructeur** (Part 1): the unmodified SafetyEngine on the selected entries,
`build_manufacturer_first_finding` with origin `user_selection` (the driver's
explicit selection replaces only the automatic identification), R-5
`compose_triage` (raises, never lowers) and `present_first_finding` (approved
banners/labels only), above the exact manufacturer passage, then T3/T8. No
question is asked afterwards (C1/C2). Structured fields come only from a
VALIDATED classification (`PGDR_V1_FINDINGS`: Part 1 mapping format, header
`status: VALIDE`, named approval, bound to the catalogue content fingerprint;
anchors may cite a linked warning with `source_field: linked_warnings`).
In V1 a structured point shows only the cited phrase (never an approved
label that adds an action); derived values (R-1/R-2) are never displayed and
only feed the internal R-5 level. Unstructured points read « Point pas encore
vérifié par PGDR… »; « La notice n'indique pas ce point. » needs a VALIDATED
classification covering the entry (`covered_entry_ids`) and is never used
when the entry has linked warnings.

Variant groups (`pgdr.v1_contenu`): identical image files are grouped
automatically; look-alike files only via a VALIDATED `PGDR_V1_GROUPS`. The
driver is asked only the documented distinguishing elements (displayed
message, fixed/flashing), each choice with its source; « Je ne sais pas » /
« Aucun de ceux-ci », or nothing distinctive documented → colour fallback.

Explanations (`PGDR_V1_EXPLANATIONS`): prepared in advance, three parts, every
sentence anchored verbatim (invalid anchor → that entry's explanation is
dropped). Draft = development trial only, marked « Explication en brouillon,
non validée »; elsewhere only with a named validation bound to the catalogue.

Persistence: the notice files are read from disk once per process and kept
verified in memory, shared by all parcours (content only); parcours state
(selection, answers, colour) is per parcours, in process memory, lost on
restart; nothing is stored in a database; the photo never leaves the browser.

Tests: `tests/test_v1_parcours.py`, `tests/test_v1_premier_constat.py` (unit +
integration) and `tests/test_v1_browser_e2e.py` (Playwright), on a FICTIVE
notice (and fictive classification) built at test time.

### Preparation package tests (`outils/preparation_v1/`)

The preparation package has its own tests and dependencies (PyYAML, pypdf,
Pillow). They are NOT part of the PGDR suite above: `pytest` only collects
`tests/` (`testpaths` in `pyproject.toml`). Run them with the package's own
installer, which creates a separate environment in `outils/preparation_v1/.venv/`
(git-ignored). Never install the package dependencies into the PGDR environment.

```bash
cd outils/preparation_v1
bash installer.sh                      # creates .venv/, installs requirements.txt, runs the 110 tests
.venv/bin/python -m unittest discover -s tests -v   # re-run the tests later
.venv/bin/python scripts/verifier_yaml.py
```

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
