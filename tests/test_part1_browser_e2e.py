"""PGDR Part 1 — Manufacturer First Finding, browser E2E (Execution Mandate
v0.2 FINAL §12 "E2E"): real uvicorn server + real Chromium, the real web
flow, the 11 real owner-attested Peugeot entries, and the deterministic test
provider (an integration-test mechanism only, never a visual capability).

  * oil-pressure-warning: the full §5 page and a terminal session;
  * adblue-level-state-c: the T6 figure caution and operability NOT_ESTABLISHED.
"""
from __future__ import annotations

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
from pgdr import web_app as web
from pgdr.application.part1_first_finding import APPROVED_BANNERS, APPROVED_LABELS

_PORT = 8767


@pytest.fixture(scope="module")
def provider():
    return sup.DeterministicDashboardProvider()


@pytest.fixture(scope="module")
def live_server(provider):
    saved = (web._photo_wiring, web._session_controller)
    saved_token = os.environ.get(web.IDENTITY_HANDOFF_TOKEN_ENV)
    os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = sup.HANDOFF_TOKEN
    web._photo_wiring = web.PhotoWiring(
        interpretation_provider=provider, knowledge_repository=sup.RealPeugeotKnowledgeRepository(),
    )
    web._session_controller = None
    web._sessions.clear()
    web._photo_intakes.clear()
    server = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=_PORT, log_level="error"))
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


def _photo_to_first_finding(page: Page, base: str, provider, entry_id: str, seed: int) -> tuple[str, list[str]]:
    r = httpx.post(f"{base}/api/photo/identity-handoff", json=sup.vir_identity(),
                   headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: sup.HANDOFF_TOKEN})
    sid = r.json()["intake_id"]
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{base}/?intake={sid}")
    expect(page.locator("#part1-t1")).to_contain_text(APPROVED_BANNERS["T1"][0])
    page.check("input#consent-checkbox")
    page.click("button#photo-start-btn")
    expect(page.locator("#photo-step")).to_be_visible()
    image = provider.script(sup.png_bytes(seed), sup.match(sup.REAL_ENTRIES[entry_id], "Voyant observé"))
    page.set_input_files("input#photo-input", files=[{"name": "tdb.png", "mimeType": "image/png", "buffer": image}])
    with page.expect_response(lambda resp: resp.url.endswith("/media")) as info:
        page.click("button#photo-btn")
    assert info.value.status == 200 and info.value.json()["pending_questions"] == []
    page.wait_for_selector("#manufacturer-first-finding", timeout=15000)
    return sid, errors


def _section_titles(page: Page) -> list[str]:
    return [t.strip() for t in page.locator("#manufacturer-first-finding h3").all_text_contents()]


def test_e2e_part1_oil_pressure_full_section_5_page_and_terminal_session(live_server, page, provider):
    sid, errors = _photo_to_first_finding(page, live_server, provider, "oil-pressure-warning", 701)
    root = page.locator("#manufacturer-first-finding")

    # §5 order (single entry): T2, identified, manufacturer text, immediate
    # safety, vehicle use, restrictions, professional, practical, NE, source, T8.
    assert _section_titles(page) == [
        "Voyant identifié", "Ce que dit le constructeur", "Sécurité immédiate", "Utilisation du véhicule",
        "Restrictions / conditions d'arrêt", "Intervention d'un professionnel", "Assistance pratique",
        "Points non établis par la notice", "Source",
    ]
    expect(page.locator("#part1-t2")).to_contain_text(APPROVED_BANNERS["T2"][0])
    expect(page.locator("#part1-t2")).to_contain_text(APPROVED_BANNERS["T2"][1])
    li = page.locator("#dashboard-identifications li")
    expect(li).to_have_count(1)
    assert li.first.get_attribute("data-origin") == "visual_provider_match"
    expect(li.first).to_contain_text("Engine oil pressure")
    expect(root).to_contain_text(APPROVED_BANNERS["T5"][0])
    expect(root).to_contain_text("(1) Stop the vehicle as soon as it is safe to do so and switch off the ignition.")

    safety = page.locator('[data-section="immediate-safety"] li')
    assert safety.first.text_content() == APPROVED_LABELS["stop_vehicle_engine_off = REQUIRED"]   # first (A4)
    assert page.locator('[data-section="vehicle-use"] p').text_content() == APPROVED_LABELS["operability = DO_NOT_DRIVE"]
    expect(page.locator('[data-section="practical"]')).to_have_attribute("data-requirement", "towing_required")
    expect(page.locator('[data-section="practical"]')).to_contain_text(APPROVED_LABELS["practical = TOWING_REQUIRED"])
    expect(page.locator('[data-section="not-established"]')).to_contain_text(APPROVED_BANNERS["T4"][0])
    expect(page.locator('[data-section="source"]')).to_contain_text("réf. 9999_9999_326_en-GB")
    expect(page.locator("#part1-t8")).to_have_text(APPROVED_BANNERS["T8"][0])

    text = page.locator("#report-container").text_content()
    for forbidden in ("Aucun signal critique", "hypothèses compatibles", "Synthèse pour l'automobiliste",
                      "Systèmes à examiner", "Contrôles suggérés", "Questions ouvertes", "112"):
        assert forbidden not in text, forbidden
    expect(page.locator("#question-container")).to_be_hidden()
    expect(page.locator("#safety-alert")).to_be_hidden()
    assert not page.locator("#report-container button").count()           # no "continue" affordance

    session = web._sessions[sid]
    assert session.state.value == "escalated" and session.pending_questions == []
    assert httpx.post(f"{live_server}/api/session/{sid}/answer",
                      json={"question_id": "Q-STATE-001", "value": "garage"}).status_code == 400
    assert not errors, errors


def test_e2e_part1_adblue_c_figure_caution_and_operability_not_established(live_server, page, provider):
    sid, errors = _photo_to_first_finding(page, live_server, provider, "adblue-level-state-c", 702)
    restrictions = page.locator('[data-section="restrictions"]')
    expect(restrictions.locator(".documented-figure")).to_have_text("less than 62 miles (100 km) remaining")
    expect(restrictions.locator(".figure-caution")).to_have_text(
        APPROVED_BANNERS["T6"][0].replace("{meaning}", "l'autonomie AdBlue® restante avant que le démarrage puisse être empêché"))
    assert page.locator('[data-section="vehicle-use"] p').text_content() == APPROVED_LABELS["operability = NOT_ESTABLISHED"]
    assert page.locator('[data-section="immediate-safety"]').count() == 0
    expect(page.locator('[data-section="practical"]')).to_contain_text(APPROVED_LABELS["practical = NEITHER_REQUIRED"])
    text = page.locator("#report-container").text_content()
    assert not re.search(r"\b\d+\s*km/h\b", text)
    assert web._sessions[sid].state.value == "completed" and web._sessions[sid].pending_questions == []
    assert not errors, errors


# ---- Owner Completion Authority, items 2 and 3: rendered byte-for-byte ----

NE_LABELS = {
    "stop_vehicle_engine_off": "Arrêt immédiat du véhicule et coupure du contact : non établi par la notice.",
    "vehicle_immobilization": "Maintien du véhicule à l'arrêt : non établi par la notice.",
    "professional_attention": "Intervention d'un professionnel : non établie par la notice.",
    "practical_assistance": "Besoin d'un garage ou d'un dépannage : non établi par la notice.",
}
NO_IDENTIFIED_SYMBOL = (
    "Aucun voyant n'a pu être identifié parmi les voyants proposés à partir de la notice disponible. "
    "PGDR ne peut donc pas établir de Premier Constat Constructeur pour cette photo."
)


def test_e2e_part1_the_four_not_established_labels_render_byte_for_byte(live_server, page, provider):
    # service-warning-lamp-fixed: every item NOT_ESTABLISHED -> all four labels.
    _, errors = _photo_to_first_finding(page, live_server, provider, "service-warning-lamp-fixed", 703)
    rendered = page.locator('[data-section="not-established"] li').all_text_contents()
    for label in NE_LABELS.values():
        assert label.encode("utf-8") in [r.encode("utf-8") for r in rendered], label
    assert not errors, errors


def test_e2e_part1_no_identified_symbol_renders_the_exact_text_then_t8_and_ends(live_server, page, provider):
    r = httpx.post(f"{live_server}/api/photo/identity-handoff", json=sup.vir_identity(),
                   headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: sup.HANDOFF_TOKEN})
    sid = r.json()["intake_id"]
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(f"{live_server}/?intake={sid}")
    page.check("input#consent-checkbox")
    page.click("button#photo-start-btn")
    image = provider.script(sup.png_bytes(704), sup.no_match())
    page.set_input_files("input#photo-input", files=[{"name": "tdb.png", "mimeType": "image/png", "buffer": image}])
    page.click("button#photo-btn")
    expect(page.locator("#selection-step")).to_be_visible()
    with page.expect_response(lambda resp: resp.url.endswith("/selection")) as info:
        page.click("button#symbol-none-btn")
    assert info.value.json()["pending_questions"] == []
    page.wait_for_selector("#part1-no-identification", timeout=15000)
    assert page.locator("#part1-no-identification").text_content().encode("utf-8") == NO_IDENTIFIED_SYMBOL.encode("utf-8")
    assert page.locator("#part1-t8").text_content().encode("utf-8") == APPROVED_BANNERS["T8"][0].encode("utf-8")
    ids = page.locator("#manufacturer-first-finding > *").evaluate_all("els => els.map(e => e.id)")
    assert ids == ["part1-no-identification", "part1-t8"]              # the text, then T8, nothing else
    expect(page.locator("#question-container")).to_be_hidden()
    session = web._sessions[sid]
    assert session.state.value == "completed" and session.pending_questions == [] and session.answers == []
    assert not errors, errors
