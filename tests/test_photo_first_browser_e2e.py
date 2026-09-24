"""B2 photo-first completion -- REAL-BROWSER E2E (Chromium via Playwright)
against a real uvicorn server, real web app, real SessionController and real
GGM governance.

What is real: the browser, the file input and the actual image bytes it
uploads, the upload endpoint, the MediaResolverPort implementation, the
DashboardInterpretationPort call, the governed B2 chain, case state, safety
re-evaluation, GGM-governed report.
What is NOT real: the interpretation RESULT, which a deterministic provider
returns as a function of the SHA-256 of the received bytes. It is an
integration-test mechanism only -- NONE of these PASSes is a Real-World
Photo-First PASS, and no image ever leaves this process.

The vehicle identity is never entered in the browser: each flow first hands
the captured real VIR -> PI map_resolution() artifact to PGDR over HTTP (PI's
role), then opens the page on the resulting intake.

Every flow is driven to its final rendered state (report / fallback outcome)
and cross-checked against the real API / case state. One test per flow.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.sync_api import Page, expect

import photo_first_support as sup
from pgdr import web_app as web
from pgdr.domain.photo_provenance import (
    LOCATION_QUESTION_ID, PROVIDER_OBSERVATION_KIND, USER_SELECTION_OBSERVATION_KIND,
    USER_SELECTION_SOURCE_RULE_ID,
)

_PORT = 8766


@pytest.fixture(scope="module")
def provider():
    return sup.DeterministicDashboardProvider()


@pytest.fixture(scope="module")
def live_server(provider):
    saved = (web._photo_wiring, web._session_controller)
    saved_token = os.environ.get(web.IDENTITY_HANDOFF_TOKEN_ENV)
    os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = sup.HANDOFF_TOKEN
    web._photo_wiring = web.PhotoWiring(
        interpretation_provider=provider, knowledge_repository=sup.InMemoryKnowledgeRepository(),
    )
    web._session_controller = None
    web._sessions.clear()
    web._photo_intakes.clear()
    config = uvicorn.Config(web.app, host="127.0.0.1", port=_PORT, log_level="error")
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
    web._photo_wiring, web._session_controller = saved
    web._sessions.clear()
    web._photo_intakes.clear()
    if saved_token is None:
        os.environ.pop(web.IDENTITY_HANDOFF_TOKEN_ENV, None)
    else:
        os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = saved_token


@pytest.fixture()
def page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
    browser.close()


# ------------------------------------------------------------- helpers ---

def _case(session_id):
    return web._session_controller._case_states[session_id]


def _post_response(page: Page):
    return page.expect_response(lambda r: "/api/photo/" in r.url and r.request.method == "POST")


def _vir_handoff(base: str, identity: dict | None = None) -> dict:
    """PI's role: hand the VIR identity artifact to PGDR, server to server."""
    r = httpx.post(f"{base}/api/photo/identity-handoff", json=identity or sup.vir_identity(),
                   headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: sup.HANDOFF_TOKEN})
    assert r.status_code == 200, r.text
    return r.json()


def _open_on_vir_intake(page: Page, base: str, *, consent: bool) -> tuple[str, list[str]]:
    """Opens the page on an intake created from the VIR identity. Returns
    (intake id, page JS errors)."""
    handed = _vir_handoff(base)
    assert handed["status"] == "awaiting_consent"
    sid = handed["intake_id"]
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{base}/?intake={sid}")
    # photo-first: no generic upfront fields, and never the vehicle
    for gone in ("textarea#complaint", "select#location", "select#urgency", "input#vehicle-manufacturer",
                 "input#vehicle-model", "input#vehicle-generation", "input#registration-date"):
        assert page.locator(gone).count() == 0
    expect(page.locator("#consent-step")).to_be_visible()
    if consent:
        page.check("input#consent-checkbox")
    return sid, errors


def _continue_to_photo_step(page: Page, sid: str) -> str:
    """Consent granted -> photo step. PGDR has NOT started yet."""
    with _post_response(page) as info:
        page.click("button#photo-start-btn")
    assert info.value.status == 200 and info.value.json() == {"status": "awaiting_photo", "intake_id": sid}
    expect(page.locator("#photo-step")).to_be_visible()
    assert sid not in web._sessions                # no photo -> no PGDR session
    return sid


def _upload_photo(page: Page, image: bytes):
    page.set_input_files("input#photo-input", files=[{"name": "tableau_de_bord.png", "mimeType": "image/png", "buffer": image}])
    with _post_response(page) as info:
        page.click("button#photo-btn")
    assert info.value.status == 200, info.value.text()
    return info.value.json()


def _report_visible(page: Page) -> bool:
    return page.locator("#report-container").evaluate(
        "el => !el.classList.contains('hidden') && el.textContent.trim().length > 0"
    )


def _drive_to_report(page: Page, prompts: list[str]) -> None:
    """Answer every rendered question through the UI until the report shows."""
    for _ in range(40):
        page.wait_for_function(
            "() => !document.getElementById('report-container').classList.contains('hidden')"
            " || !document.getElementById('question-container').classList.contains('hidden')",
            timeout=15000,
        )
        if _report_visible(page):
            return
        prompts.append(page.locator("#question-container .question-prompt").text_content().strip())
        choices = page.locator("#question-container .choice-btn")
        if choices.count():
            choices.nth(choices.count() - 1).click()
        else:
            page.fill("input#text-answer", "je ne sais pas")
            page.click("#question-container button:text('Valider')")
    pytest.fail("report never rendered")


# ------------------------------------------------------- flow 1: MATCH ---

def test_flow_1_consent_photo_match_to_final_report(live_server, page, provider):
    image = provider.script(sup.png_bytes(101), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
    sid, errors = _open_on_vir_intake(page, live_server, consent=True)
    _continue_to_photo_step(page, sid)

    calls_before = len(provider.calls)
    payload = _upload_photo(page, image)
    assert payload["status"] == "analysed"
    assert sid in web._sessions                     # PGDR started with the photo, under the intake id

    # actual bytes reached the real DashboardInterpretationPort through the real resolver
    assert len(provider.calls) == calls_before + 1
    assert provider.calls[-1]["sha256"] == sup.sha(image) and provider.calls[-1]["length"] == len(image)
    assert len(web._media_store) == 0  # not retained

    # PGDR Part 1 (mandate v0.2 §11 step 5, rewritten): no question at all
    # follows the photo; the page goes straight to the First Finding.
    prompts: list[str] = []
    _drive_to_report(page, prompts)
    assert prompts == []
    expect(page.locator("#question-container")).to_be_hidden()

    # final rendered state: the Manufacturer First Finding, not the legacy synthesis
    expect(page.locator("#manufacturer-first-finding")).to_be_visible()
    expect(page.locator("#report-container")).to_contain_text("Premier Constat Constructeur")
    expect(page.locator("#part1-t8")).to_be_visible()
    expect(page.locator("#report-container")).not_to_contain_text("Synthèse pour l'automobiliste")
    li = page.locator("#dashboard-identifications li")
    expect(li).to_have_count(1)
    assert li.first.get_attribute("data-origin") == "visual_provider_match"
    expect(li.first).to_contain_text("identifié sur la photo")
    expect(page.locator("#report-container")).not_to_contain_text("non vérifié")
    assert not errors, f"page JS errors: {errors}"

    # final API / case state
    state = _case(sid)
    assert [o.context["match_status"] for o in state.observations if o.kind == PROVIDER_OBSERVATION_KIND] == ["match"]
    assert any((h.domain_ref or "").startswith("b2r_dashboard:") for h in state.hypotheses)
    assert web._sessions[sid].state.value.lower() == "completed"
    assert web._sessions[sid].result is not None
    # the PGDR case consumed the VIR artifact verbatim
    assert web._sessions[sid].request.vehicle_identity_context.model_dump(mode="json") == sup.vir_identity()


# ------------------------------------------------- flow 2: consent declined ---

def test_flow_2_consent_declined_shows_bounded_message_and_pgdr_does_not_start(live_server, page, provider):
    sessions_before = set(web._sessions)
    calls_before = len(provider.calls)
    sid, _ = _open_on_vir_intake(page, live_server, consent=False)
    with _post_response(page) as info:
        page.click("button#photo-start-btn")
    assert info.value.status == 200 and info.value.json()["status"] == "consent_required"

    message = page.locator("#consent-message")
    expect(message).to_be_visible()
    expect(message).to_contain_text("PGDR ne peut pas démarrer sans votre accord")
    expect(message).to_contain_text("ne peut pas démarrer")
    assert "erreur" not in message.text_content().lower()
    expect(page.locator("#error")).to_be_hidden()          # not an error state
    expect(page.locator("#photo-step")).to_be_hidden()      # nothing to upload
    expect(page.locator("#question-container")).to_be_hidden()
    # PGDR did not start: no session, no interpretation
    assert set(web._sessions) == sessions_before
    assert len(provider.calls) == calls_before

    # ... and the driver can still give consent afterwards and proceed
    page.check("input#consent-checkbox")
    with _post_response(page) as info:
        page.click("button#photo-start-btn")
    assert info.value.json()["status"] == "awaiting_photo"
    expect(page.locator("#photo-step")).to_be_visible()
    assert sid not in web._sessions


# ------------------------------------------------ flow 3: AMBIGUOUS_MATCH ---

def test_flow_3_ambiguous_match_candidate_selection_creates_user_provenance_evidence(live_server, page, provider):
    image = provider.script(sup.png_bytes(102), sup.ambiguous([sup.ENGINE_FIXED, sup.ENGINE_FLASHING]))
    sid, _ = _open_on_vir_intake(page, live_server, consent=True)
    _continue_to_photo_step(page, sid)
    payload = _upload_photo(page, image)
    assert payload["status"] == "selection_required" and payload["trigger"] == "ambiguous_match"

    expect(page.locator("#selection-step")).to_be_visible()
    options = page.locator("#selection-options .symbol-option")
    expect(options).to_have_count(2)                          # only the preserved candidates
    assert {options.nth(i).get_attribute("data-entry-id") for i in range(2)} == {"engine-diag-fixed", "engine-diag-flashing"}
    expect(page.locator("#selection-step")).not_to_contain_text("Fault in the")   # no manufacturer meaning shown
    state = _case(sid)
    assert not [e for e in state.evidence if e.observation_ids and
                any(o.context.get("match_status") == "ambiguous_match" for o in state.observations if o.id in e.observation_ids)]

    with _post_response(page) as info:
        page.locator('#selection-options .symbol-option[data-entry-id="engine-diag-flashing"]').click()
    assert info.value.json()["status"] == "analysed"
    _drive_to_report(page, [])

    li = page.locator("#dashboard-identifications li")
    expect(li).to_have_count(1)
    assert li.first.get_attribute("data-origin") == "user_selection"
    expect(li.first).to_contain_text("indiqué par vous")
    expect(li.first).to_contain_text("non vérifié sur la photo")
    state = _case(sid)
    user_ev = [e for e in state.evidence if e.source_rule_id == USER_SELECTION_SOURCE_RULE_ID]
    assert len(user_ev) == 1
    u_obs = next(o for o in state.observations if o.kind == USER_SELECTION_OBSERVATION_KIND)
    assert u_obs.context["machine_verified"] is False and u_obs.context["triggering_match_status"] == "ambiguous_match"
    assert any((h.domain_ref or "").endswith("engine-diag-flashing:engine_running") for h in state.hypotheses)


# ------------------------------------------------------ flow 4: NO_MATCH ---

def test_flow_4_no_match_full_reference_set_fallback_creates_user_provenance_evidence(live_server, page, provider):
    image = provider.script(sup.png_bytes(103), sup.no_match())
    sid, _ = _open_on_vir_intake(page, live_server, consent=True)
    _continue_to_photo_step(page, sid)
    payload = _upload_photo(page, image)
    assert payload["status"] == "selection_required" and payload["trigger"] == "no_match"

    options = page.locator("#selection-options .symbol-option")
    expect(options).to_have_count(len(sup.ALL_ENTRIES))       # the FULL applicable set
    with _post_response(page) as info:
        page.locator('#selection-options .symbol-option[data-entry-id="oil-pressure-warning"]').click()
    assert info.value.json()["status"] == "analysed"
    _drive_to_report(page, [])

    li = page.locator("#dashboard-identifications li")
    expect(li).to_have_count(1)
    assert li.first.get_attribute("data-origin") == "user_selection"
    state = _case(sid)
    assert [o.context["match_status"] for o in state.observations if o.kind == PROVIDER_OBSERVATION_KIND] == ["no_match"]
    assert len([e for e in state.evidence if e.source_rule_id == USER_SELECTION_SOURCE_RULE_ID]) == 1
    assert any((h.domain_ref or "").endswith("oil-pressure-warning:engine_running") for h in state.hypotheses)


# ---------------------------------- flow 5: INSUFFICIENT_VISUAL_QUALITY ---

def test_flow_5_insufficient_quality_retakes_then_limit_then_fallback(live_server, page, provider):
    bad = [provider.script(sup.png_bytes(110 + i), sup.insufficient()) for i in range(3)]
    sid, _ = _open_on_vir_intake(page, live_server, consent=True)
    _continue_to_photo_step(page, sid)
    calls_before = len(provider.calls)

    first = _upload_photo(page, bad[0])
    assert first["status"] == "retake_requested" and first["retakes_used"] == 1
    expect(page.locator("#retake-step")).to_be_visible()
    expect(page.locator("#retake-message")).to_contain_text("il reste 1 nouvelle(s) tentative(s)")
    expect(page.locator("#photo-step")).to_be_visible()       # a retake is possible

    second = _upload_photo(page, bad[1])
    assert second["status"] == "retake_requested" and second["retakes_used"] == 2
    expect(page.locator("#retake-message")).to_contain_text("il reste 0 nouvelle(s) tentative(s)")

    third = _upload_photo(page, bad[2])                       # limit reached -> fallback
    assert third["status"] == "selection_required" and third["trigger"] == "insufficient_visual_quality"
    expect(page.locator("#selection-step")).to_be_visible()
    expect(page.locator("#retake-step")).to_be_hidden()
    expect(page.locator("#photo-step")).to_be_hidden()
    assert len(provider.calls) == calls_before + 3
    expect(page.locator("#selection-options .symbol-option")).to_have_count(len(sup.ALL_ENTRIES))

    with _post_response(page) as info:
        page.locator('#selection-options .symbol-option[data-entry-id="engine-diag-fixed"]').click()
    assert info.value.json()["status"] == "analysed"
    _drive_to_report(page, [])
    li = page.locator("#dashboard-identifications li")
    assert li.first.get_attribute("data-origin") == "user_selection"
    state = _case(sid)
    assert [o.context["match_status"] for o in state.observations if o.kind == PROVIDER_OBSERVATION_KIND] == \
        ["insufficient_visual_quality"] * 3
    u_obs = next(o for o in state.observations if o.kind == USER_SELECTION_OBSERVATION_KIND)
    assert u_obs.context["triggering_match_status"] == "insufficient_visual_quality"


def test_flow_5b_driver_can_decline_the_retake_and_go_straight_to_the_fallback(live_server, page, provider):
    bad = provider.script(sup.png_bytes(120), sup.insufficient())
    sid, _ = _open_on_vir_intake(page, live_server, consent=True)
    _continue_to_photo_step(page, sid)
    assert _upload_photo(page, bad)["status"] == "retake_requested"
    with _post_response(page) as info:
        page.click("button#decline-retake-btn")
    assert info.value.json()["status"] == "selection_required"
    expect(page.locator("#selection-step")).to_be_visible()


# ----------------------------------------------------- flow 6: safety ---

def test_flow_6a_photo_derived_signal_raises_safety_and_the_page_shows_the_first_finding(live_server, page, provider):
    """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2): the
    photo-derived elevation still happens, but no location question (or any
    question) is rendered -- the page shows the First Finding and ends."""
    image = provider.script(
        sup.png_bytes(130),
        sup.match(sup.OIL, "Voyant rouge de pression d'huile"),
        sup.match(sup.AIRBAG, "Voyant rouge d'airbag"),
    )
    sid, _ = _open_on_vir_intake(page, live_server, consent=True)
    _continue_to_photo_step(page, sid)
    payload = _upload_photo(page, image)
    assert payload["safety_triage"]["level"] == "prompt_inspection"

    assert payload["pending_questions"] == []

    prompts: list[str] = []
    _drive_to_report(page, prompts)
    assert prompts == []                                             # no question rendered at all
    expect(page.locator("#question-container")).to_be_hidden()
    expect(page.locator("#report-container")).to_contain_text("Premier Constat Constructeur")
    expect(page.locator("#report-container")).to_contain_text("Voyant identifié")
    expect(page.locator("#dashboard-identifications li")).to_have_count(2)
    state = _case(sid)
    assert state.safety_state.triage.level.value == "prompt_inspection"
    assert not [o for o in state.observations if o.kind == f"answer:{LOCATION_QUESTION_ID}"]
    assert web._sessions[sid].state.value.lower() == "completed"
    assert page.locator("select#location").count() == 0


def test_flow_6b_critical_photo_signal_escalates_and_the_page_shows_the_first_finding(live_server, page, provider):
    """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2 / §5): the
    escalation is kept; the legacy safety alert and the location question
    are replaced by the First Finding page (§5 order), then the session ends."""
    image = provider.script(sup.png_bytes(131), sup.match(sup.BRAKE, "Voyant rouge de frein"))
    sid, _ = _open_on_vir_intake(page, live_server, consent=True)
    _continue_to_photo_step(page, sid)
    payload = _upload_photo(page, image)
    assert payload["escalated"] is True

    assert payload["safety_triage"]["level"] == "do_not_drive" and payload["pending_questions"] == []
    page.wait_for_function("() => !document.getElementById('report-container').classList.contains('hidden')")
    expect(page.locator("#question-container")).to_be_hidden()
    expect(page.locator("#safety-alert")).to_be_hidden()
    expect(page.locator("#manufacturer-first-finding")).to_be_visible()
    expect(page.locator("#part1-t8")).to_be_visible()
    assert web._sessions[sid].state.value.lower() == "escalated"
    assert httpx.post(f"{live_server}/api/session/{sid}/answer",
                      json={"question_id": LOCATION_QUESTION_ID, "value": "bord de route"}).status_code == 400


# --------------------------------------------- flow 7: concurrent sessions ---

def test_flow_7_two_concurrent_sessions_remain_isolated(live_server, playwright, provider):
    img_a = provider.script(sup.png_bytes(140), sup.ambiguous([sup.ENGINE_FIXED, sup.ENGINE_FLASHING]))
    img_b = provider.script(sup.png_bytes(141), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
    browser = playwright.chromium.launch(headless=True)
    try:
        ctx_a, ctx_b = browser.new_context(), browser.new_context()
        page_a, page_b = ctx_a.new_page(), ctx_b.new_page()

        sid_a, _ = _open_on_vir_intake(page_a, live_server, consent=True)
        sid_b, _ = _open_on_vir_intake(page_b, live_server, consent=True)
        _continue_to_photo_step(page_a, sid_a)
        _continue_to_photo_step(page_b, sid_b)
        assert sid_a != sid_b

        # interleave: A uploads (needs fallback), B uploads (match) before A chooses
        assert _upload_photo(page_a, img_a)["status"] == "selection_required"
        assert _upload_photo(page_b, img_b)["status"] == "analysed"
        expect(page_a.locator("#selection-step")).to_be_visible()
        # PGDR Part 1 (rewritten, beyond the §11 step 5 list): B's photo
        # session ends with its First Finding -- no questions in between.
        page_b.wait_for_selector("#manufacturer-first-finding", timeout=10000)
        expect(page_b.locator("#question-container")).to_be_hidden()

        # A finishes through the fallback while B has already finished
        with _post_response(page_a) as info:
            page_a.locator('#selection-options .symbol-option[data-entry-id="engine-diag-fixed"]').click()
        assert info.value.json()["status"] == "analysed"
        _drive_to_report(page_a, [])
        _drive_to_report(page_b, [])

        li_a = page_a.locator("#dashboard-identifications li")
        li_b = page_b.locator("#dashboard-identifications li")
        assert li_a.first.get_attribute("data-origin") == "user_selection"
        assert li_b.first.get_attribute("data-origin") == "visual_provider_match"
        expect(page_a.locator("#report-container")).not_to_contain_text("identifié sur la photo")
        expect(page_b.locator("#report-container")).not_to_contain_text("indiqué par vous")

        a, b = _case(sid_a), _case(sid_b)
        assert not [o for o in b.observations if o.kind == USER_SELECTION_OBSERVATION_KIND]
        assert not [o for o in a.observations if o.context.get("match_status") == "match"]
        assert any((h.domain_ref or "").endswith("engine-diag-fixed:engine_running") for h in a.hypotheses)
        assert any((h.domain_ref or "").endswith("oil-pressure-warning:engine_running") for h in b.hypotheses)
        assert web._photo_intakes[sid_a].identity is not web._photo_intakes[sid_b].identity
        ctrl = web._session_controller
        assert ctrl.photo_case_state(web._sessions[sid_a]).offer is not None
        assert ctrl.photo_case_state(web._sessions[sid_b]).offer is None
    finally:
        browser.close()


# ------------------------------------------- flow 8: VIR identity boundary ---

def test_flow_8_without_a_vir_identity_the_page_never_asks_for_the_vehicle(live_server, page, provider):
    """No intake (or an insufficient VIR identity, which yields none): the
    page explains that identification happens before PGDR, offers no vehicle
    fields and no way to start."""
    handed = _vir_handoff(live_server, sup.vir_identity("peugeot_3008_manual_no_generation"))
    assert handed["status"] == "vehicle_identity_insufficient" and "intake_id" not in handed

    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(live_server)
    notice = page.locator("#photo-notice")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("L'identification du véhicule se fait avant PGDR")
    expect(page.locator("#consent-step")).to_be_hidden()
    expect(page.locator("#photo-step")).to_be_hidden()
    for gone in ("input#vehicle-manufacturer", "input#vehicle-model", "input#vehicle-generation",
                 "input#registration-date", "#date-step"):
        assert page.locator(gone).count() == 0
    assert not errors, f"page JS errors: {errors}"
