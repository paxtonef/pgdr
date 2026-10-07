"""V1 parcours — browser end-to-end (real uvicorn + real Chromium) on a
FICTIVE notice: VIR -> consent -> optional local photo -> complete catalogue
-> selection -> confirmation -> exact restitution, and both colour fallbacks
with « Revenir aux images ». The photo must never leave the browser and no
provider may be reached."""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from playwright.sync_api import Page, expect

import v1_fictive_notice as fx
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

_PORT = 8771
TOKEN = "v1-e2e-handoff-token"
BANNER = "Essai de développement — Applicabilité de cette notice au véhicule non confirmée"
ORDER = ["fx_red_fluid", "fx_amber_sensor", "fx_green_lamps", "fx_white_cruise"]


def _english_screens() -> dict:
    p = Path(__file__).resolve().parents[1] / "outils" / "preparation_v1" / "config" / "fallback_screens.en.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))["screens"]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    notice = fx.build(tmp_path_factory.mktemp("fictive") / "notice")
    saved = (v1._wiring, os.environ.get(web.IDENTITY_HANDOFF_TOKEN_ENV), web._photo_wiring)
    v1._wiring = v1.V1Wiring(repository=ManifestNoticeRepository(notice), dev_trial=True)
    v1._parcours.clear()
    os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = TOKEN
    web._photo_wiring = web.PhotoWiring()  # no interpretation provider at all
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
    page = context.new_page()
    yield page
    context.close()
    browser.close()


class Traffic:
    """Every request the page makes: proves the photo is never sent and that
    nothing but the local PGDR server is contacted."""

    def __init__(self, page: Page, base: str):
        self.base, self.requests = base, []
        page.on("request", lambda r: self.requests.append((r.method, r.url, r.post_data_buffer)))

    def assert_clean(self, photo: bytes):
        assert self.requests
        for method, url, body in self.requests:
            assert url.startswith(self.base) or url.startswith("blob:"), url
            assert url.startswith("blob:") or method in ("GET", "POST"), url
            if body:
                assert photo[:16] not in body and b"multipart" not in body.lower()


def _open(page: Page, base: str) -> None:
    r = httpx.post(f"{base}/api/v1/vir-handoff",
                   json={"resolution_id": "VIR-FICTIVE-E2E", "resolution_status": "resolved",
                         "vehicle_identity": fx.VIR_IDENTITY},
                   headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN})
    assert r.json()["status"] == "opened", r.text
    page.goto(base + r.json()["url"])


def _banner(page: Page) -> None:
    expect(page.locator("#dev-banner")).to_be_visible()
    expect(page.locator("#dev-banner")).to_have_text(BANNER)


def _to_catalogue(page: Page, photo: bytes | None) -> None:
    expect(page.locator("#screen-vir")).to_be_visible()
    expect(page.locator("#vir-vehicle")).to_contain_text("Fictiva")
    _banner(page)
    page.click("#vir-continue")
    expect(page.locator("#screen-consent")).to_be_visible()
    _banner(page)
    page.click("#consent-continue")  # without ticking: refused
    expect(page.locator("#consent-message")).to_contain_text("Sans votre accord")
    expect(page.locator("#screen-consent")).to_be_visible()
    page.check("#consent-box")
    page.click("#consent-continue")
    expect(page.locator("#screen-photo")).to_be_visible()
    _banner(page)
    if photo is not None:
        page.set_input_files("#photo-input", files=[{"name": "dash.png", "mimeType": "image/png", "buffer": photo}])
        expect(page.locator("#photo-preview")).to_be_visible()
        assert page.locator("#photo-preview").get_attribute("src").startswith("blob:")
    page.click("#photo-continue")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    _banner(page)


def _tiles(page: Page) -> list[str]:
    return page.locator("#catalogue-grid .tile").evaluate_all("ts => ts.map(t => t.dataset.entryId)")


def _pressed(page: Page) -> list[str]:
    return page.locator('#catalogue-grid .tile[aria-pressed="true"]').evaluate_all("ts => ts.map(t => t.dataset.entryId)")


def test_v1_complete_parcours_two_images_one_red(page: Page, live_server):
    photo = fx.png((12, 34, 56), 16)
    traffic = Traffic(page, live_server)
    _open(page, live_server)
    _to_catalogue(page, photo)
    assert _tiles(page) == ORDER  # complete, manual order
    expect(page.locator("#photo-compare")).to_be_visible()
    for img in page.locator("#catalogue-grid img").all():
        assert img.evaluate("i => i.complete && i.naturalWidth > 0")
    expect(page.locator("#selection-continue")).to_be_disabled()
    page.click('.tile[data-entry-id="fx_green_lamps"]')
    page.click('.tile[data-entry-id="fx_red_fluid"]')
    expect(page.locator("#selection-count")).to_have_text("2")
    page.click("#selection-continue")
    expect(page.locator("#screen-confirmation")).to_be_visible()
    _banner(page)
    assert page.locator("#confirmation-grid .tile").evaluate_all("ts => ts.map(t => t.dataset.entryId)") == [
        "fx_red_fluid", "fx_green_lamps"]
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    _banner(page)

    sections = page.locator("article.restitution")
    expect(sections).to_have_count(2)
    red, green = sections.nth(0), sections.nth(1)
    assert red.get_attribute("data-entry-id") == "fx_red_fluid"
    expect(red.locator("h2")).to_have_text("FICTIVE LOW FLUID")
    assert red.locator(".meaning").text_content() == fx.RED_MEANING
    expect(red.locator(".meaning img")).to_have_count(1)
    expect(red.locator(".where-provided")).to_have_text("selon équipement")
    expect(red.locator(".startup-check")).to_have_text("s'allume au démarrage")
    expect(red.locator(".startup-text")).to_contain_text(fx.RED_STARTUP)
    expect(red.locator(".warning")).to_have_count(1)
    assert red.locator(".warning .exact").text_content() == fx.SHARED_WARNING
    expect(red.locator(".warning")).to_contain_text("Avertissement 7)")
    expect(red.locator(".warning")).to_contain_text("Page de la notice : F-2 (page PDF 2)")
    expect(red).to_contain_text("Page de la notice : F-1 (page PDF 1)")
    expect(red).to_contain_text("Stop the fictive vehicle.")
    assert green.get_attribute("data-entry-id") == "fx_green_lamps"
    assert green.locator(".meaning").text_content() == fx.GREEN_MEANING
    expect(green.locator(".where-provided")).to_have_count(0)
    expect(green.locator(".startup-check")).to_have_count(0)
    expect(green.locator(".warning")).to_have_count(0)
    expect(green).to_contain_text("Page de la notice : F-2 (page PDF 2)")

    traffic.assert_clean(photo)


def test_v1_fallback_red_then_other_colour_with_return(page: Page, live_server):
    photo = fx.png((90, 10, 10), 16)
    traffic = Traffic(page, live_server)
    screens = _english_screens()
    _open(page, live_server)
    _to_catalogue(page, photo)
    page.click('.tile[data-entry-id="fx_white_cruise"]')

    # 1. « Aucune ne correspond » -> rouge -> red-or-uncertain screen (validated English).
    page.click("#none-match")
    expect(page.locator("#screen-colour")).to_be_visible()
    _banner(page)
    page.click('#colour-choices button[data-colour="rouge"]')
    expect(page.locator("#screen-fallback")).to_be_visible()
    _banner(page)
    expect(page.locator("#fallback-content h1")).to_have_text(screens["red_or_uncertain"]["heading"])
    assert page.locator("#fallback-content p").all_text_contents() == screens["red_or_uncertain"]["paragraphs"]
    assert page.locator("#fallback-content").get_attribute("lang") == "en"

    # « Revenir aux images »: manual order, selection kept.
    page.click("#screen-fallback button.return")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    assert _tiles(page) == ORDER
    assert _pressed(page) == ["fx_white_cruise"]

    # 2. « Je ne sais pas » -> colour kept (rouge highlighted) -> vert -> other-colour screen.
    page.click("#dont-know")
    expect(page.locator('#colour-choices button[data-colour="rouge"]')).to_have_class("primary")
    page.click('#colour-choices button[data-colour="vert"]')
    expect(page.locator("#fallback-content h1")).to_have_text(screens["other_colour"]["heading"])
    assert page.locator("#fallback-content p").all_text_contents() == screens["other_colour"]["paragraphs"]

    # Back again: selection still kept; a NEW confirmation is required before any restitution.
    page.click("#screen-fallback button.return")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    assert _pressed(page) == ["fx_white_cruise"]
    page.click("#selection-continue")
    expect(page.locator("#screen-confirmation")).to_be_visible()
    expect(page.locator("#screen-restitution")).to_be_hidden()
    page.click("#confirm")
    expect(page.locator("article.restitution")).to_have_count(1)
    expect(page.locator("article.restitution .where-provided")).to_have_text("selon équipement")

    body = page.locator("body").inner_text().lower()
    for phrase in ("vous pouvez rouler", "you may continue driving", "safe to drive", "a été contacté",
                   "has been contacted", "we have contacted"):
        assert phrase not in body
    traffic.assert_clean(photo)
