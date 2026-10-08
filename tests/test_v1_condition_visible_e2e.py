"""V1 parcours — browser (real uvicorn + Chromium), FICTIVE notice only: the
condition the notice cites for an urgent instruction is visible just above it,
without any click; a validated « action attendue » instruction gets no
condition question."""
from __future__ import annotations

import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.sync_api import Page, expect

import v1_fictive_notice as fx
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

TOKEN = "v1-condition-visible-token"
_PORT = 8773


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    notice = fx.build(tmp_path_factory.mktemp("fictive-cond") / "notice", with_groups=True)
    saved = (v1._wiring, os.environ.get(web.IDENTITY_HANDOFF_TOKEN_ENV), web._photo_wiring)
    v1._wiring = v1.build_wiring(ManifestNoticeRepository(notice), dev_trial=True, situations_path=fx.build_situations(notice))
    v1._parcours.clear()
    os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = TOKEN
    web._photo_wiring = web.PhotoWiring()
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
    v1._wiring, token, web._photo_wiring = saved
    v1._parcours.clear()
    if token is None:
        os.environ.pop(web.IDENTITY_HANDOFF_TOKEN_ENV, None)
    else:
        os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = token


@pytest.fixture
def page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    yield context.new_page()
    context.close()
    browser.close()


def test_condition_visible_above_the_urgent_instruction(page: Page, live_server):
    r = httpx.post(f"{live_server}/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN},
                   json={"resolution_id": "VIR-FICTIVE-COND", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY})
    page.goto(live_server + r.json()["url"])
    page.click("#vir-continue")
    page.check("#consent-box")
    page.click("#consent-continue")
    page.click("#photo-continue")
    page.click('.tile[data-entry-id="fx_red_alarm_a"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    cond = page.locator('.urgent .urgent-variant[data-entry-id="fx_red_alarm_a"] blockquote.urgent-condition')
    expect(cond).to_be_visible()  # no click: not inside a closed « Détails »
    expect(cond).to_contain_text("If the fictive alarm light comes on while driving")
    expect(cond).to_contain_text("page de la notice F-10 (page PDF 10)")
    assert cond.evaluate("q => q.closest('details') === null")
    nxt = cond.locator("xpath=following-sibling::blockquote[1]")
    expect(nxt).to_contain_text(fx.ALARM_STOP)
