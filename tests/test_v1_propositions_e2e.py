"""V1 parcours — proposed images, browser end-to-end (real uvicorn + real
Chromium) on a FICTIVE notice with the FAKE sorting transport only:
C photo -> 1 to 3 proposals -> selection -> confirmation -> notice and Premier
Constat; D proposals not recognised -> complete catalogue -> selection;
E no transport / transport failure -> explained catalogue; F no image
recognised -> existing colour fallback. Proves the wiring in a browser,
never any recognition quality."""
from __future__ import annotations

import base64
import json
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from playwright.sync_api import Page, expect

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import v1_propositions as vp
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from test_v1_browser_e2e import _ENGLISH, _UI_TEXT_JS
from test_v1_propositions import PLATE, VIN, png_with_metadata

_PORT = 8774
TOKEN = "v1-propositions-e2e-token"
RECIPIENT = "Composant de tri d'essai (faux transport)"
ORDER = ["fx_red_fluid", "fx_amber_sensor", "fx_green_lamps", "fx_white_cruise"]
SEEN: list = []  # what the fake transport received


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    notice = fx.build(tmp_path_factory.mktemp("fictive") / "notice")
    saved = (v1._wiring, os.environ.get(web.IDENTITY_HANDOFF_TOKEN_ENV), web._photo_wiring)
    v1._wiring = v1.build_wiring(ManifestNoticeRepository(notice), dev_trial=True)
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


def use(transport) -> None:
    v1._wiring.tri = transport
    SEEN.clear()


def fake(ids=None, panne=False):
    r = {"panne": True} if panne else {"texte": json.dumps({"proposed_entry_ids": ids})}
    return vp.FauxTransportTri(RECIPIENT, {}, r, observer=SEEN.append)


@pytest.fixture
def page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
    browser.close()


class Traffic:
    def __init__(self, page: Page, base: str):
        self.base, self.requests = base, []
        page.on("request", lambda r: self.requests.append((r.method, r.url, r.post_data_buffer)))

    def only_local(self):
        for method, url, _ in self.requests:
            assert url.startswith(self.base) or url.startswith("blob:") or url.startswith("data:"), url

    def photo_posts(self) -> list[bytes]:
        return [base64.b64decode(json.loads(body)["photo_base64"]) for m, url, body in self.requests
                if m == "POST" and url.endswith("/propositions")]


def no_english(page: Page) -> None:
    bad = [x for x in page.evaluate(_UI_TEXT_JS) if _ENGLISH.search(x)]
    assert bad == [], bad


def to_photo(page: Page, base: str) -> None:
    r = httpx.post(f"{base}/api/v1/vir-handoff", json={"resolution_id": "VIR-FICTIVE-PE2E", "resolution_status": "resolved",
                                                       "vehicle_identity": fx.VIR_IDENTITY},
                   headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN})
    page.goto(base + r.json()["url"])
    page.click("#vir-continue")
    page.check("#consent-box")
    page.click("#consent-continue")
    expect(page.locator("#screen-photo")).to_be_visible()


def ids(page: Page, grid: str, pressed: bool = False) -> list[str]:
    sel = f"#{grid} .tile" + ('[aria-pressed="true"]' if pressed else "")
    return page.locator(sel).evaluate_all("ts => ts.map(t => t.dataset.entryId)")


def propose(page: Page, photo: bytes) -> None:
    expect(page.locator("#propose-offer")).to_be_visible()
    expect(page.locator("#photo-propose")).to_be_disabled()           # no photo, no consent
    page.set_input_files("#photo-input", files=[{"name": "dash.png", "mimeType": "image/png", "buffer": photo}])
    expect(page.locator("#photo-propose")).to_be_disabled()           # photo, no consent yet
    expect(page.locator("#propose-consent-text")).to_contain_text("« " + RECIPIENT + " »")
    page.check("#propose-consent")
    expect(page.locator("#photo-propose")).to_be_enabled()
    expect(page.locator("#photo-continue")).to_be_visible()           # the catalogue stays reachable
    page.click("#photo-propose")


def test_c_photo_proposals_selection_notice_premier_constat(page: Page, live_server):
    use(fake(["fx_green_lamps", "fx_red_fluid"]))
    traffic = Traffic(page, live_server)
    to_photo(page, live_server)
    expect(page.locator("#consent-text")).to_have_count(1)
    propose(page, png_with_metadata())
    expect(page.locator("#screen-propositions")).to_be_visible()
    assert ids(page, "propositions-grid") == ["fx_red_fluid", "fx_green_lamps"]  # notice order, not the component's
    assert ids(page, "propositions-grid", pressed=True) == []                     # nothing chosen for the driver
    expect(page.locator("#propositions-fake")).to_have_text(vc.DRAFT_LABELS["propositions.faux"])
    expect(page.locator("#screen-propositions .draft-mention").first).to_have_text(vc.DRAFT_LABELS["draft_texts"])
    expect(page.locator("#propositions-help")).to_have_text(vc.DRAFT_LABELS["propositions.aide"])
    expect(page.locator("#propositions-continue")).to_be_disabled()
    expect(page.locator("#propositions-catalogue")).to_be_visible()
    body = page.locator("#screen-propositions").inner_text().lower()
    for word in ("%", "score", "recommand", "correspondant", "identifié"):
        assert word not in body
    no_english(page)
    for img in page.locator("#propositions-grid img").all():
        assert img.evaluate("i => i.complete && i.naturalWidth > 0")
    page.click('#propositions-grid .tile[data-entry-id="fx_green_lamps"]')
    page.click("#propositions-continue")
    expect(page.locator("#screen-confirmation")).to_be_visible()
    assert ids(page, "confirmation-grid") == ["fx_green_lamps"]
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    expect(page.locator("#premier-constat")).not_to_be_empty()
    expect(page.locator('article.restitution[data-entry-id="fx_green_lamps"] .meaning')).to_have_text(fx.GREEN_MEANING)
    # The photo crossed the wire only re-encoded by the page (pixels only), and reached the fake stripped.
    (sent,) = traffic.photo_posts()
    assert sent.startswith(b"\xff\xd8") and vp.strip_metadata(sent)[1] == "image/jpeg"
    (demande,) = SEEN
    assert demande.photo == vp.strip_metadata(sent)[0] and [c.entry_id for c in demande.candidats] == ORDER
    for marker in (PLATE.encode(), VIN.encode(), b"GPS", b"Exif", b"tEXt", b"Fictiva"):
        assert marker not in sent and marker not in demande.photo
    traffic.only_local()


def test_d_proposals_not_recognised_complete_catalogue_selection(page: Page, live_server):
    use(fake(["fx_red_fluid"]))
    to_photo(page, live_server)
    propose(page, png_with_metadata())
    expect(page.locator("#screen-propositions")).to_be_visible()
    page.click("#propositions-catalogue")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    assert ids(page, "catalogue-grid") == ORDER and ids(page, "catalogue-grid", pressed=True) == []
    expect(page.locator("#catalogue-repli")).to_be_hidden()
    page.click('#catalogue-grid .tile[data-entry-id="fx_amber_sensor"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    expect(page.locator('article.restitution[data-entry-id="fx_amber_sensor"]')).to_be_visible()


def test_e_without_transport_the_catalogue_explains_and_the_photo_stays_local(page: Page, live_server):
    use(None)
    traffic = Traffic(page, live_server)
    to_photo(page, live_server)
    expect(page.locator("#propose-offer")).to_be_hidden()
    expect(page.locator("#photo-note")).to_have_text(
        "Elle reste sur votre appareil pour que vous puissiez comparer. Elle n'est ni analysée, ni envoyée, ni conservée.")
    photo = png_with_metadata()
    page.set_input_files("#photo-input", files=[{"name": "dash.png", "mimeType": "image/png", "buffer": photo}])
    page.click("#photo-continue")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    expect(page.locator("#catalogue-repli .repli-text")).to_have_text(vc.DRAFT_LABELS["propositions.repli.non_configure"])
    assert ids(page, "catalogue-grid") == ORDER
    no_english(page)
    assert traffic.photo_posts() == []
    for _, _, body in traffic.requests:
        assert not body or photo[16:40] not in body
    traffic.only_local()


@pytest.mark.parametrize("transport,repli", [("panne", "panne"), ("vide", "aucune_proposition"), ("invalide", "reponse_invalide")])
def test_e_transport_failure_gives_the_explained_catalogue(page: Page, live_server, transport, repli):
    use({"panne": fake(panne=True), "vide": fake([]), "invalide": fake(ORDER)}[transport])
    to_photo(page, live_server)
    propose(page, png_with_metadata())
    expect(page.locator("#screen-catalogue")).to_be_visible()
    expect(page.locator("#catalogue-repli .repli-text")).to_have_text(vc.DRAFT_LABELS["propositions.repli." + repli])
    assert ids(page, "catalogue-grid") == ORDER and ids(page, "catalogue-grid", pressed=True) == []


def test_e_unreadable_photo_is_not_sent_and_the_catalogue_explains(page: Page, live_server):
    use(fake(["fx_red_fluid"]))
    traffic = Traffic(page, live_server)
    to_photo(page, live_server)
    page.set_input_files("#photo-input", files=[{"name": "x.png", "mimeType": "image/png", "buffer": b"not an image"}])
    page.check("#propose-consent")
    page.click("#photo-propose")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    expect(page.locator("#catalogue-repli .repli-text")).to_have_text(vc.DRAFT_LABELS["propositions.repli.photo_refusee"])
    assert traffic.photo_posts() == [b""] and SEEN == []


def test_f_no_image_recognised_keeps_the_existing_safety_outcome(page: Page, live_server):
    use(fake(["fx_green_lamps"]))
    to_photo(page, live_server)
    propose(page, png_with_metadata())
    page.click("#propositions-catalogue")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    page.click("#none-match")
    expect(page.locator("#screen-colour")).to_be_visible()
    page.click('#colour-choices button[data-colour="rouge"]')
    expect(page.locator("#screen-fallback")).to_be_visible()
    expect(page.locator("#fallback-content")).to_have_attribute("data-screen", "red_or_uncertain")
    expect(page.locator("#fallback-content h1")).to_have_text(
        v1.load_fallback_screens()["screens"]["red_or_uncertain"]["heading"])


def test_reload_on_the_proposals_screen_shows_them_again(page: Page, live_server):
    use(fake(["fx_white_cruise"]))
    to_photo(page, live_server)
    propose(page, png_with_metadata())
    expect(page.locator("#screen-propositions")).to_be_visible()
    page.reload()
    expect(page.locator("#screen-propositions")).to_be_visible()
    assert ids(page, "propositions-grid") == ["fx_white_cruise"] and ids(page, "propositions-grid", pressed=True) == []
