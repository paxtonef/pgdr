# PGDR ↔ GGM P2.2 Migration — Closure Verification

**Status: CLOSED**

| Gate | Result | Evidence |
|---|---|---|
| Source Migration Gate | **PASS** | `consumption_profile.py`, `session_controller.py`, `readiness.py` migrated to `DECIDE`-only + `RuntimeMaterializer`; full suite green against real GGM P2.2 source |
| Runtime Materialization | **PASS** | End-to-end smoke test: real `SessionController()`, full diagnostic session driven to completion through `runtime.consumer.evaluate()` |
| DECIDE-only consumption | **PASS** | `manifest.operations_enabled == {"DECIDE"}` confirmed live; `test_p8_t02_t03_t04` updated and passing |
| Fail-closed | **PASS** | `test_p8_t27_t28`, `test_rc05` — both patch `materialize_pgdr_runtime_or_raise` (the real call site) and confirm `GovernanceUnavailableError` propagates from both `SessionController` construction and `readiness.check_readiness()` |
| Packaging Identity Gate | **PASS** | `ggm-1.2.0-py3-none-any.whl` built from the verified P2.2 source; identity recorded in `vendor/GGM_PACKAGING_IDENTITY.md` (package version, target commit, wheel SHA-256, provenance caveats) |
| Fresh wheel test | **163/163 PASS, 0 skipped** | `GGM_WHEEL_PATH=vendor/ggm-1.2.0-py3-none-any.whl python -m pytest tests/ -q` — real wheel build, real fresh venv, real `pgdr` console-script, full negative-config matrix |
| Dependency Freeze | **PASS** | `pyproject.toml` (`ggm>=1.2.0`), `docs/release/PGDR_v2_DEPENDENCY_FREEZE.md` fully rewritten for P2.2 architecture (DECIDE-only, `RuntimeMaterializer`, public-contract-not-internal-machinery pinning model) |
| Release Documentation | **PASS** | All P8B "deferred / waiting on GGM / zero-code-change" language corrected across `PGDR_v2_RELEASE_MANIFEST.md`, `PGDR_v2_DEFERRED_CAPABILITIES.md`, `PGDR_v2_KNOWN_LIMITATIONS.md` (release-facing docs, updated to current state) and `p8_findings.md`, `p8_ggm_integration.md` (architecture docs, historical framing preserved with delivery annotations) |

## Final identity record

```
GGM package:          1.2.0
Target source commit: ac99750 (supplied — not independently git-verifiable
                       from the source archive; see
                       vendor/GGM_PACKAGING_IDENTITY.md)
Source archive SHA-256: 8cf69f925dc9d97c987807a1e4452a3eeb97c119a96f8b26757844b8875b1b93
Wheel SHA-256:         7340c166918e5b9bb83008a8f5944ef0ae64b0c1995189fc3860d7a90b1baff2
Contract version:      1.3
Resolver version:      1.3
Kernel/runtime version: ggm/1.1
PGDR operations declared: DECIDE (only)
```

## What was corrected, not just updated

Two documents (`p8_findings.md`, `PGDR_v2_DEFERRED_CAPABILITIES.md`) had
made a specific prediction — that the eventual bounded-runtime swap would
require "zero PGDR code changes, only a different `governance_consumer`
object." That prediction did not hold: `RuntimeMaterializer` requires an
explicit `resolve -> materialize` call PGDR did not previously make, and
the actual migration modified `session_controller.py`,
`governance/consumption_profile.py`, and `readiness.py`. Both documents
now state this explicitly rather than silently updating the status flag,
per the project's own standard of reporting discrepancies rather than
smoothing over them.

## Verification commands (reproducible)

```bash
GGM_WHEEL_PATH=vendor/ggm-1.2.0-py3-none-any.whl python -m pytest tests/ -q
# expect: 163 passed, 0 skipped

grep -rn "ggm-1.1.0\|ggm>=1.1.0\|4fda5974312f1949771fc4993ced4c98fe0d1ac0\|contract v1.2\|once GGM ships\|P8B.*WAITING" \
  --include="*.md" --include="*.yml" --include="*.yaml" --include="*.toml" .
# expect: only vendor/GGM_PACKAGING_IDENTITY.md's intentional historical mentions
```

## Remaining known limitation (not a gate failure)

Source commit `ac99750` remains a **supplied**, not independently
git-verified, identity — the distributed source archive contains no
`.git` metadata. This is documented consistently across
`vendor/GGM_PACKAGING_IDENTITY.md` and `docs/release/PGDR_v2_DEPENDENCY_FREEZE.md`
rather than treated as resolved. If GGM's upstream project later
publishes an official release, that release's identity should supersede
this one.
