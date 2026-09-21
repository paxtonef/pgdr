# PGDR Production Deployment — Owner Validation Procedure

**Candidate HEAD**: `pgdr-production-deployment` branch
**Required baseline**: `7130e7fc3c1be1bd3e3fee312bfe6509598a6c50`
**Bundle**: `pgdr-production-deployment-complete.bundle`

This procedure establishes **PGDR GOVERNED LOCAL VALIDATION** in the environment
where real GGM is available. It is the required gate before production deployment.

---

## 1. Repository checkout and baseline verification

```bash
# Clone from bundle (or fetch if using existing repository)
git clone pgdr-production-deployment-complete.bundle pgdr-validation
cd pgdr-validation

# Checkout candidate branch
git checkout pgdr-production-deployment

# Verify clean state
git status --short
# Expected: clean working tree

# Verify candidate HEAD
git rev-parse HEAD
# Expected: output the candidate commit hash

# Verify baseline is reachable
git merge-base --is-ancestor 7130e7fc3c1be1bd3e3fee312bfe6509598a6c50 HEAD
echo $?
# Expected: 0 (success)
```

---

## 2. GGM wheel supply

```bash
# Supply the GGM wheel via the repository's established mechanism
# The wheel file is: vendor/ggm-1.2.0-py3-none-any.whl
# SHA-256: 7340c166918e5b9bb83008a8f5944ef0ae64b0c1995189fc3860d7a90b1baff2

# Verify wheel is present
ls -lh vendor/ggm-1.2.0-py3-none-any.whl
sha256sum vendor/ggm-1.2.0-py3-none-any.whl
# Expected: 7340c166918e5b9bb83008a8f5944ef0ae64b0c1995189fc3860d7a90b1baff2

# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install vendor/ggm-1.2.0-py3-none-any.whl
pip install fastapi 'uvicorn[standard]' httpx pytest-playwright
```

---

## 3. GGM-enabled full regression

```bash
# WITHOUT GGM wheel environment variable (should pass with 476/11/0)
pytest -q
# Expected output:
# 476 passed, 11 skipped
# (11 skipped are GGM-wheel-packaging tests)

# WITH GGM wheel environment variable (should pass with 487/0/0)
GGM_WHEEL_PATH="$(pwd)/vendor/ggm-1.2.0-py3-none-any.whl" pytest -q
# Expected output:
# 487 passed, 0 skipped
# (all tests including packaging tests should pass)

# Important: Verify skipped-because-GGM-absent count drops to 0
# The 11 tests that were skipped should now pass
```

---

## 4. Start web application with real GGM

```bash
# Start the web server
uvicorn pgdr.web_app:app --host 127.0.0.1 --port 8000

# Server should start successfully and log:
# INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 5. Readiness positive path with real GGM

In a separate terminal:

```bash
source .venv/bin/activate
curl -s http://127.0.0.1:8000/health | python3 -m json.tool

# Expected output:
# {
#   "status": "ready",
#   "checks": [
#     {
#       "name": "packaged_resources_and_configuration",
#       "required": true,
#       "status": "ok",
#       "detail": ""
#     },
#     {
#       "name": "safety_engine",
#       "required": true,
#       "status": "ok",
#       "detail": "... safety rules loaded"
#     },
#     {
#       "name": "session_controller",
#       "required": true,
#       "status": "ok",
#       "detail": ""
#     },
#     {
#       "name": "ggm_consumption",
#       "required": true,
#       "status": "ok",
#       "detail": "manifest ... materialized, kernel ggm/1.1, operations ['decide']"
#     }
#   ]
# }

# CRITICAL: ggm_consumption status must be "ok"
# If "failed", the production deployment must NOT proceed
```

---

## 6. Complete governed French browser E2E-A

**This is the FIRST required verification if Section 22.3 Case 2 applied in
the Claude Code environment.**

```bash
# Install browser automation (if not already done)
pip install pytest-playwright
playwright install chromium

# Run full-lifecycle French E2E test
pytest tests/test_browser_e2e.py::test_e2e_a_complete_french_lifecycle -v

# Expected: PASSED

# Manual browser verification (complement to automated test):
# 1. Open http://127.0.0.1:8000 in a real browser
# 2. Verify page displays in French (lang="fr")
# 3. Verify disclaimer: "PGDR ne fournit jamais un diagnostic mécanique définitif"
# 4. Enter complaint: "La voiture tremble au ralenti"
# 5. Click "Démarrer l'analyse"
# 6. Answer questions until report appears
# 7. Verify report is in French
# 8. Verify report contains disclaimer about non-definitive diagnosis
# 9. Verify no English diagnostic text appears in questions or report
```

---

## 7. E2E-B and E2E-C (if feasible)

```bash
# Run boundary/error tests
pytest tests/test_browser_e2e.py::test_e2e_b_empty_complaint_validation -v
pytest tests/test_browser_e2e.py::test_e2e_b_unknown_session_error -v

# Run session isolation test
pytest tests/test_browser_e2e.py::test_e2e_c_concurrent_sessions_no_leakage -v

# Expected: all PASSED
```

---

## 8. Governed diagnostic smoke test

```bash
# CLI smoke test with GGM
python3 run_pgdr.py run \
  --vir-id VIR-VALIDATION-001 \
  --complaint "La voiture tremble au ralenti" \
  --non-interactive

# Expected:
# - Session completes without error
# - Report contains governed hypotheses (if any)
# - User summary and garage preparation report are produced
# - No GGM errors

# Verify GGM was actually called (check that governance trace exists)
# This can be verified by inspecting the session controller's governance logs
```

---

## 9. GGM wheel production supply mechanism

**What was established from the repository:**

- Wheel location: `vendor/ggm-1.2.0-py3-none-any.whl`
- SHA-256: `7340c166918e5b9bb83008a8f5944ef0ae64b0c1995189fc3860d7a90b1baff2`
- Package version: `ggm 1.2.0`
- Source commit (target): `ac99750`
- Built by PGDR from GGM P2.2 source
- No third-party runtime dependencies (stdlib only)

**What could NOT be established:**

- **Licensing terms**: No license file present in source archive
- **Distribution authorization**: Whether wheel may be publicly redistributed
- **Official GGM release process**: No canonical GGM build/release exists yet

**Production supply mechanism:**

For production deployment:

1. **If embedding in private image is authorized**: Include wheel in Docker image
   at build time via `COPY vendor/ggm-1.2.0-py3-none-any.whl /app/vendor/` and
   install during image build.

2. **If embedding is not authorized**: Supply wheel at deployment time via secure
   mechanism (e.g., mounted volume, secret store, build-time injection) and ensure
   it is available before application startup.

3. **Verify at deployment**: The `/health` endpoint MUST return `"status": "ready"`
   with `ggm_consumption.status == "ok"` before accepting traffic.

**Licensing/distribution decision required**: Confirm with GGM maintainers whether:
- The wheel may be embedded in a private deployment image
- The wheel may be redistributed (publicly or privately)
- An official GGM release process will provide canonical wheels

Until confirmed, treat the wheel as **private, non-redistributable**.

---

## 10. Validation gate criteria

Mark **PGDR GOVERNED LOCAL VALIDATION: PASS** if ALL of:

- [ ] Candidate HEAD checked out from verified bundle
- [ ] GGM wheel available and SHA-256 verified
- [ ] Regression with GGM: **487 passed, 0 skipped, 0 failed**
- [ ] Web application starts successfully with real GGM
- [ ] Readiness endpoint returns `"status": "ready"` with `ggm_consumption.status == "ok"`
- [ ] Complete governed French browser E2E-A: **PASSED**
- [ ] E2E-B boundary tests: **PASSED** (or not applicable)
- [ ] E2E-C session isolation: **PASSED**
- [ ] CLI governed diagnostic smoke test: successful
- [ ] No GGM errors in any test or smoke test

If **PASS**: Candidate is ready for production deployment planning.

If **NOT PASSED**: Document failure reason and return to implementation.

---

## Notes

- This validation procedure uses the **actual GGM wheel** and verifies **actual
  governed diagnostic output**, which could not be fully verified in the Claude
  Code environment.

- The French browser E2E (E2E-A) is the **primary end-to-end validation** of the
  complete user journey with governance active.

- Production deployment itself (external hosting, scaling, monitoring) is outside
  the scope of this local productization program and requires a separate
  deployment plan.

- All commands above were derived from the **actual implementation** in the
  `pgdr-production-deployment` branch, not invented before inspection.
