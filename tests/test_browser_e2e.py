"""Browser E2E tests (Section 24) — real browser against production-like build.

B2 photo-first: PGDR starts only from a consented dashboard photograph, so
these (formerly text-complaint) journeys now start from a photo. The
deterministic provider is an integration-test mechanism only (see
photo_first_support.py); the GGM / non-definitive-claim / isolation checks are
unchanged in strength.

E2E-A: complete governed French lifecycle, photo to final report
E2E-B: boundary/error cases (non-image upload, unknown session)
E2E-C: independent sessions (no state leakage)

These tests run against a real uvicorn server with a real browser engine
(Chromium via Playwright), verifying the complete French UI lifecycle
including governed diagnostic output.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import re
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.sync_api import Page, expect

import photo_first_support as sup
from pgdr.enums import SessionState
from pgdr.governance.trace import InMemoryGovernanceTraceStore
from pgdr import web_app as _web
from pgdr.web_app import app, _sessions

_PORT = 8765
_CANONICAL_GGM_VERSION = "1.0.0"
_CANONICAL_GGM_RUNTIME = "ggm/1.1"


@pytest.fixture(scope="module")
def governance_traces():
    """Observe-only tap on the real GGM adapter's trace store.

    Records every governance trace the application produces while delegating
    to the original `record` unchanged — it adds no behavior and cannot alter
    a governance outcome. Lets the browser tests prove that GGM governance
    actually executed for the sessions they drive."""
    seen: list = []
    original = InMemoryGovernanceTraceStore.record

    def tap(self, trace):
        seen.append(trace)
        return original(self, trace)

    InMemoryGovernanceTraceStore.record = tap
    try:
        yield seen
    finally:
        InMemoryGovernanceTraceStore.record = original


@pytest.fixture(scope="module")
def provider():
    return sup.DeterministicDashboardProvider()


@pytest.fixture(scope="module")
def live_server(governance_traces, provider):
    """Real uvicorn server (real HTTP, real web app, real SessionController,
    real GGM) on a background thread of this process."""
    saved = (_web._photo_wiring, _web._session_controller)
    saved_token = os.environ.get(_web.IDENTITY_HANDOFF_TOKEN_ENV)
    os.environ[_web.IDENTITY_HANDOFF_TOKEN_ENV] = sup.HANDOFF_TOKEN
    _web._photo_wiring = _web.PhotoWiring(
        interpretation_provider=provider, knowledge_repository=sup.InMemoryKnowledgeRepository(),
    )
    _web._session_controller = None
    _web._photo_intakes.clear()
    _sessions.clear()
    config = uvicorn.Config(app, host="127.0.0.1", port=_PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", _PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        server.should_exit = True
        pytest.fail("Server failed to start")

    yield f"http://127.0.0.1:{_PORT}"

    server.should_exit = True
    thread.join(timeout=5)
    _web._photo_wiring, _web._session_controller = saved
    _web._photo_intakes.clear()
    _sessions.clear()
    if saved_token is None:
        os.environ.pop(_web.IDENTITY_HANDOFF_TOKEN_ENV, None)
    else:
        os.environ[_web.IDENTITY_HANDOFF_TOKEN_ENV] = saved_token


@pytest.fixture
def page(playwright):
    """Create a new browser page for each test."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
    browser.close()


# --- Shared browser-driving helpers ---

def _open_on_vir_intake(page: Page, base_url: str) -> None:
    """PI's role (server to server): hand the captured real VIR identity
    artifact to PGDR; then the driver opens the page on that intake and
    consents. The vehicle is never entered in the browser."""
    r = httpx.post(f"{base_url}/api/photo/identity-handoff", json=sup.vir_identity(),
                   headers={_web.IDENTITY_HANDOFF_TOKEN_HEADER: sup.HANDOFF_TOKEN})
    assert r.status_code == 200 and r.json()["status"] == "awaiting_consent", r.text
    page.goto(f"{base_url}/?intake={r.json()['intake_id']}")
    page.check("input#consent-checkbox")
    page.click("button#photo-start-btn")
    expect(page.locator("#photo-step")).to_be_visible()


def _start_photo_diagnostic(page: Page, base_url: str, provider, seed: int, *factories) -> str:
    """Drive the rendered French photo-first UI: VIR intake + consent + real
    image upload. Returns the session id the server issued (read from the
    real HTTP response of the upload, which is where PGDR starts)."""
    image = provider.script(sup.png_bytes(seed), *factories)
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    _open_on_vir_intake(page, base_url)
    page.set_input_files("input#photo-input", files=[{"name": "tableau.png", "mimeType": "image/png", "buffer": image}])
    with page.expect_response(lambda r: r.url.endswith("/media")) as info:
        page.click("button#photo-btn")
    assert info.value.status == 200
    assert not errors, f"page JS errors: {errors}"
    return info.value.json()["session_id"]


def _case(session_id: str):
    """The controller-held DiagnosticCaseState (observations, Evidence,
    hypotheses, answers) for a session."""
    return _web._session_controller._case_states[session_id]


def _report_visible(page: Page) -> bool:
    return page.locator("#report-container").evaluate(
        "el => !el.classList.contains('hidden') && el.textContent.trim().length > 0"
    )


def _answer_visible_question(page: Page, pick: int, answers_log: list[str]) -> None:
    """Answer the question currently rendered in the browser through the UI
    (button click or typed text), then wait for the next question or the
    report. `pick` selects which offered choice (0 = first, 1 = second)."""
    page.wait_for_selector(".question-box", state="visible", timeout=10000)
    prompt = page.locator(".question-prompt").text_content()
    assert prompt and prompt.strip(), "empty question prompt rendered"
    choices = page.locator("#question-container .choice-btn")
    n = choices.count()
    if n:
        idx = min(pick, n - 1)
        answers_log.append(choices.nth(idx).text_content())
        choices.nth(idx).click()
    else:
        page.fill("input#text-answer", "je ne sais pas")
        answers_log.append("je ne sais pas")
        page.click("#question-container button:text('Valider')")
    page.wait_for_function(
        """(prev) => {
            const rep = document.getElementById('report-container');
            const qc = document.getElementById('question-container');
            const err = document.getElementById('error');
            if (!err.classList.contains('hidden') && err.textContent.trim()) return true;
            if (!rep.classList.contains('hidden') && rep.textContent.trim()) return true;
            const p = qc.querySelector('.question-prompt');
            return !qc.classList.contains('hidden') && p && p.textContent !== prev;
        }""",
        arg=prompt,
        timeout=15000,
    )
    assert page.locator("#error").is_hidden(), (
        f"UI error after answering: {page.locator('#error').text_content()!r}"
    )


def _drive_to_report(page: Page, pick: int = 0, max_questions: int = 20) -> list[str]:
    answers: list[str] = []
    for _ in range(max_questions):
        if _report_visible(page):
            break
        _answer_visible_question(page, pick, answers)
    else:
        pytest.fail("no report after max_questions")
    expect(page.locator("#report-container")).to_be_visible()
    return answers


def _assert_canonical_ggm_executed(governance_traces, case_id: str) -> None:
    """Prove the real canonical GGM package governed this session."""
    assert importlib.metadata.version("ggm") == _CANONICAL_GGM_VERSION
    direct_url = importlib.metadata.distribution("ggm").read_text("direct_url.json") or ""
    assert "ggm-1.0.0-py3-none-any.whl" in direct_url, (
        f"ggm not installed from the canonical wheel: {direct_url!r}"
    )
    mine = [t for t in governance_traces if t.case_id == case_id]
    assert mine, "GGM governance produced no trace for this session"
    for t in mine:
        assert t.result_channel == "GOVERNANCE_RESULT", t
        assert t.runtime_version == _CANONICAL_GGM_RUNTIME, t
        assert t.operation == "DECIDE", t


_DEFINITIVE_CLAIM_PATTERNS = [
    r"\bla cause (réelle |exacte )?est\b",
    r"\bdiagnostic (est )?confirmé\b",
    r"\bpanne (est )?confirmée\b",
    r"\b(il faut|vous devez) (impérativement )?(remplacer|changer|réparer)\b",
    r"\bremplacez\b",
    r"\bchangez (la|le|les|l')\b",
    r"€|\beuros?\b|\bcoûtera\b|\bdevis de\b",
    r"\bc'est certainement\b|\bc'est sûrement\b",
]


def _assert_non_definitive(report_text: str) -> None:
    low = report_text.lower()
    for pat in _DEFINITIVE_CLAIM_PATTERNS:
        assert not re.search(pat, low), f"unsupported/definitive claim matched {pat!r}"
    assert "ne remplace pas l'examen du véhicule par un professionnel" in low
    assert "aucune réparation spécifique n'est recommandée avec certitude" in low


def _assert_first_finding_non_definitive(page_text: str) -> None:
    """PGDR Part 1: the rendered First Finding page carries the approved T2
    banner (no cause diagnosis, no replacement of a professional examination)
    and no definitive / cost claim. The legacy report disclaimer is not
    rendered on the Part 1 page; it remains in the API user_summary."""
    low = page_text.lower()
    for pat in _DEFINITIVE_CLAIM_PATTERNS:
        assert not re.search(pat, low), f"unsupported/definitive claim matched {pat!r}"
    assert "ce constat ne recherche pas la cause mécanique de la panne" in low
    assert "ne remplace pas l'examen du véhicule par un professionnel" in low


# --- E2E-A: complete governed French lifecycle from a photo ---

def test_e2e_a_complete_french_lifecycle(live_server, page: Page, governance_traces, provider):
    """E2E-A: complete governed French lifecycle, browser to final report.

    Rewritten for PGDR Part 1 (beyond the mandate v0.2 §11 step 5 list: this
    test asserted the post-photo generic questionnaire that C1 removes).
    Browser -> rendered French UI -> consent + real image bytes -> HTTP ->
    web adapter -> SessionController -> governed B2 chain -> safety triage ->
    Manufacturer First Finding -> canonical GGM governance -> governed report
    -> rendered French First Finding inspected in the browser. No question is
    asked after the photo; the photo must NOT safety-escalate and the page
    must actually render."""
    observation = "Voyant rouge de pression d'huile"

    page.goto(live_server)
    expect(page.locator("html")).to_have_attribute("lang", "fr")
    expect(page.locator("h1")).to_contain_text("PGDR")
    assert "pgdr lit le voyant de votre tableau de bord" in page.locator(".disclaimer").first.text_content().lower()

    sid = _start_photo_diagnostic(page, live_server, provider, 301, sup.match(sup.OIL, observation))

    assert page.locator("#safety-alert").is_hidden()
    assert _sessions[sid].state != SessionState.ESCALATED

    answers = _drive_to_report(page, pick=0)
    assert answers == [], f"a question followed the photo: {answers}"

    session = _sessions[sid]
    assert session.state == SessionState.COMPLETED
    assert session.answers == [] and session.pending_questions == []
    case = _case(sid)
    assert not case.answers, "no answer can exist: no question is asked in Part 1"
    assert case.observations, "no observations produced"
    assert case.evidence, "no Evidence produced"
    assert case.hypotheses, "no (internal) hypotheses produced"
    assert session.result is not None and session.result.manufacturer_first_finding is not None

    report = page.locator("#report-container")
    text = report.text_content()
    assert "Premier Constat Constructeur" in text
    assert "Ce que dit le constructeur" in text
    assert "Fault with the engine lubrication system." in text          # manufacturer text, verbatim
    assert "Synthèse pour l'automobiliste" not in text
    _assert_first_finding_non_definitive(text)

    api = page.request.get(f"{live_server}/api/session/{sid}/report").json()
    assert api["garage_preparation_report"]["customer_reported_problem"] == ""   # no complaint exists in photo-first
    assert api["garage_preparation_report"]["dashboard_identifications"][0]["description"] == observation
    _assert_non_definitive(json.dumps(api, ensure_ascii=False))

    _assert_canonical_ggm_executed(governance_traces, case.case_id)


# --- E2E-B: Boundary/error cases ---

def test_e2e_b_non_image_upload_is_rejected_and_pgdr_does_not_start(live_server, page: Page, provider):
    """E2E-B: Boundary case - a non-image file is rejected, no PGDR session
    is created, and the driver can still proceed with a real photo.
    (Replaces the former empty-complaint boundary: no complaint exists.)"""
    sessions_before = set(_sessions)
    _open_on_vir_intake(page, live_server)

    page.set_input_files("input#photo-input", files=[{"name": "note.txt", "mimeType": "text/plain", "buffer": b"pas une photo"}])
    with page.expect_response(lambda r: r.url.endswith("/media")) as info:
        page.click("button#photo-btn")
    assert info.value.status == 400
    expect(page.locator("#error")).to_be_visible()
    expect(page.locator("#error")).to_contain_text("Fichier non accepté")
    assert set(_sessions) == sessions_before          # PGDR did not start
    expect(page.locator("#photo-step")).to_be_visible()  # the driver can retry with a real photo


def test_e2e_b_unknown_session_error(live_server, page: Page):
    """E2E-B: Boundary case - accessing unknown session shows error in French."""
    # Try to access a nonexistent session directly
    page.goto(f"{live_server}/api/session/INVALID-SESSION-123/state")

    # Should see 404 error page or JSON error
    content = page.content()
    assert "404" in content or "inconnue" in content.lower() or "not found" in content.lower()


# --- E2E-C: Independent sessions ---

def test_e2e_c_concurrent_sessions_no_leakage(live_server, playwright, governance_traces, provider):
    """E2E-C: two independent browser contexts, interleaved, fully isolated.

    Rewritten for PGDR Part 1 (beyond the mandate v0.2 §11 step 5 list: this
    test drove the post-photo generic questionnaire that C1 removes). Two
    users with different photos reach their own First Finding through the
    real UI. Verifies different session ids, independent diagnostic state /
    Evidence / hypotheses / reports, no leakage in either direction, and both
    sessions completing with no question asked."""
    # Two distinct photos -> two distinct governed interpretations.
    complaint_1 = "Voyant rouge de pression d'huile allumé"          # (kept as the per-session marker text)
    complaint_2 = "Voyant orange clignotant du moteur"

    browser = playwright.chromium.launch(headless=True)
    ctx_1 = browser.new_context()
    ctx_2 = browser.new_context()
    page_1 = ctx_1.new_page()
    page_2 = ctx_2.new_page()
    try:
        sid_1 = _start_photo_diagnostic(page_1, live_server, provider, 311, sup.match(sup.OIL, complaint_1))
        sid_2 = _start_photo_diagnostic(page_2, live_server, provider, 312, sup.match(sup.ENGINE_FLASHING, complaint_2))
        assert sid_1 != sid_2
        s1, s2 = _sessions[sid_1], _sessions[sid_2]
        assert s1 is not s2
        assert page_1.locator("#safety-alert").is_hidden()
        assert page_2.locator("#safety-alert").is_hidden()

        # Both reach their First Finding with no question asked.
        for pg in (page_1, page_2):
            pg.wait_for_selector("#manufacturer-first-finding", timeout=15000)
            expect(pg.locator("#question-container")).to_be_hidden()
        s1, s2 = _sessions[sid_1], _sessions[sid_2]
        assert s1.state == SessionState.COMPLETED
        assert s2.state == SessionState.COMPLETED
        assert s1.answers == [] and s2.answers == []

        # Independent request state (no complaint exists in photo-first).
        assert s1.request.request_id != s2.request.request_id
        assert s1.request.initial_complaint.free_text == "" == s2.request.initial_complaint.free_text

        # Independent diagnostic state (case state: observations, Evidence,
        # hypotheses, answers) — no shared objects between the sessions.
        c1, c2 = _case(sid_1), _case(sid_2)
        assert c1 is not c2 and c1.case_id != c2.case_id
        for attr in ("observations", "evidence", "hypotheses", "answers", "questions"):
            l1, l2 = getattr(c1, attr), getattr(c2, attr)
            assert l1 is not l2
            assert not ({id(x) for x in l1} & {id(x) for x in l2}), f"shared {attr} objects"
        for attr in ("answers", "symptoms", "trace", "questions_asked"):
            l1, l2 = getattr(s1, attr), getattr(s2, attr)
            assert l1 is not l2
            assert not ({id(x) for x in l1} & {id(x) for x in l2}), f"shared {attr} objects"
        assert c1.evidence and c2.evidence and c1.hypotheses and c2.hypotheses
        assert c1.observations and c2.observations

        # No Evidence / observation / hypothesis / report content leakage,
        # either direction.
        def dump(objs):
            return json.dumps([o.model_dump(mode="json") for o in objs], ensure_ascii=False).lower()

        own_1 = dump(c1.observations) + dump(c1.evidence) + dump(c1.hypotheses)
        own_2 = dump(c2.observations) + dump(c2.evidence) + dump(c2.hypotheses)
        assert complaint_2.lower() not in own_1
        assert complaint_1.lower() not in own_2
        assert c1.case_id not in own_2 and c2.case_id not in own_1
        rep_1 = s1.result.garage_preparation_report.model_dump_json().lower()
        rep_2 = s2.result.garage_preparation_report.model_dump_json().lower()
        assert complaint_1.lower() in rep_1 and complaint_2.lower() not in rep_1
        assert complaint_2.lower() in rep_2 and complaint_1.lower() not in rep_2
        assert "oil-pressure-warning" in own_1 and "engine-diag-flashing" not in own_1
        assert "engine-diag-flashing" in own_2 and "oil-pressure-warning" not in own_2

        # Rendered UI: each browser shows only its own First Finding.
        text_1 = page_1.locator("#report-container").text_content()
        text_2 = page_2.locator("#report-container").text_content()
        meaning_1 = "Fault with the engine lubrication system."
        meaning_2 = "Fault in the engine management system."
        assert meaning_1 in text_1 and meaning_2 not in text_1
        assert meaning_2 in text_2 and meaning_1 not in text_2
        _assert_first_finding_non_definitive(text_1)
        _assert_first_finding_non_definitive(text_2)

        # Server API keeps them separate and each remains operable/readable.
        st_1 = page_1.request.get(f"{live_server}/api/session/{sid_1}/state").json()
        st_2 = page_2.request.get(f"{live_server}/api/session/{sid_2}/state").json()
        assert st_1["session_id"] == sid_1 and st_2["session_id"] == sid_2
        assert st_1["completed"] and st_2["completed"]
        rep_api_1 = page_1.request.get(f"{live_server}/api/session/{sid_1}/report").json()
        rep_api_2 = page_2.request.get(f"{live_server}/api/session/{sid_2}/report").json()
        assert rep_api_1["garage_preparation_report"]["dashboard_identifications"][0]["description"] == complaint_1
        assert rep_api_2["garage_preparation_report"]["dashboard_identifications"][0]["description"] == complaint_2
        assert rep_api_1["garage_preparation_report"]["report_id"] != rep_api_2["garage_preparation_report"]["report_id"]

        # Governance traces are per-session and both used canonical GGM.
        _assert_canonical_ggm_executed(governance_traces, c1.case_id)
        _assert_canonical_ggm_executed(governance_traces, c2.case_id)
    finally:
        ctx_1.close()
        ctx_2.close()
        browser.close()


# --- Supplemental: verify French accents render correctly end-to-end ---

def test_e2e_french_accents_display(live_server, page: Page):
    """Verify French accented characters display correctly in the browser
    (photo-first page + the script-rendered notice shown without a VIR
    identity)."""
    page.goto(live_server)
    content = page.content()
    french_chars = ["é", "è", "à", "ê", "ç"]
    assert [c for c in french_chars if c in content], "No French accented characters found in rendered page"

    notice = page.locator("#photo-notice")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Aucun véhicule identifié pour ce diagnostic")
    expect(notice).to_contain_text("après l'identification de votre véhicule")
