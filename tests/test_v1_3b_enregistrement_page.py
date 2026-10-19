"""Bloc 3B, point 3 — the /v1 page shows the product's record status of a
confirmed result, and lets the driver retry the record alone.

Served by the product (PI), the restitution answered after an explicit
confirmation may carry ``product_record`` -- the product's own status of its
record in CPL, with the product's own texts: "recorded" only once written,
"not_recorded" with a retry. The page shows the manufacturer's texts in both
cases; a retry posts ``/record`` alone (no confirmation, no selection, no
photo, no sorting sent again). Served by PGDR alone, nothing is said about a
record. Real uvicorn, real Chromium, a FICTIVE notice; the product's answers
are stood in for by Playwright routes (PI's own behaviour is tested in PI).
"""
from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

import v1_fictive_notice as fx
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

TOKEN = "v1-3b-enregistrement-token"
NOT_RECORDED = {"status": "not_recorded", "message": "Résultat non enregistré (texte du produit, fictif).",
                "retry": True, "retry_label": "Réessayer l'enregistrement"}
RECORDED = {"status": "recorded", "message": "Résultat enregistré (texte du produit, fictif).", "retry": False}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def notice(tmp_path_factory):
    return fx.build(tmp_path_factory.mktemp("fictive") / "notice", applicability_established=True)


@pytest.fixture
def base(notice, monkeypatch):
    monkeypatch.setattr(v1, "_wiring", v1.build_wiring(ManifestNoticeRepository(notice), dev_trial=False))
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture
def page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    yield context.new_page()
    context.close()
    browser.close()


def to_confirmation(page, base: str) -> None:
    r = httpx.post(f"{base}/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN},
                   json={"resolution_id": "VIR-FICTIVE-3B", "resolution_status": "resolved",
                         "vehicle_identity": fx.VIR_IDENTITY})
    page.goto(f"{base}/v1?p={r.json()['parcours_id']}")
    page.click("#vir-continue")
    page.check("#consent-box")
    page.click("#consent-continue")
    page.click("#photo-continue")
    page.click('#catalogue-grid .tile[data-entry-id="fx_green_lamps"]')
    page.click("#selection-continue")


def test_not_recorded_shows_the_texts_and_retries_the_record_alone(page, base):
    sent: list[tuple[str, str]] = []
    page.on("request", lambda r: sent.append((r.method, r.url.rsplit("/", 1)[1])) if "/api/v1/parcours/" in r.url else None)
    record_answers = [{"detail": "Service indisponible (fictif)."}, {"product_record": RECORDED}]

    def confirm(route):
        answer = route.fetch()
        body = answer.json()
        assert "product_record" not in body          # PGDR itself never speaks of a record
        route.fulfill(response=answer, json={**body, "product_record": NOT_RECORDED})

    def record(route):
        body = record_answers.pop(0)
        route.fulfill(status=200 if "product_record" in body else 503, json=body)

    page.route("**/api/v1/parcours/*/confirm", confirm)
    page.route("**/api/v1/parcours/*/record", record)
    to_confirmation(page, base)
    page.click("#confirm")
    page.wait_for_selector("#screen-restitution:not([hidden])")

    box = page.locator("#product-record")
    assert page.locator('article.restitution[data-entry-id="fx_green_lamps"]').count() == 1
    assert fx.GREEN_MEANING in page.locator("#restitution").inner_text()
    assert box.is_visible() and box.get_attribute("role") == "alert"
    assert box.get_attribute("data-status") == "not_recorded"
    assert "Résultat non enregistré" in box.inner_text()

    page.click("#record-retry")                     # the product fails again: still not recorded, retry offered
    page.wait_for_function("document.querySelector('#product-record p').textContent.includes('Service indisponible')")
    assert "Service indisponible (fictif)." in box.inner_text() and box.get_attribute("data-status") == "not_recorded"
    assert page.locator("#record-retry").is_enabled()

    page.click("#record-retry")
    page.wait_for_selector('#product-record[data-status="recorded"]')
    assert "Résultat enregistré" in box.inner_text() and box.get_attribute("role") == "status"
    assert page.locator("#record-retry").count() == 0
    assert page.locator('article.restitution[data-entry-id="fx_green_lamps"]').count() == 1
    posts = [p for m, p in sent if m == "POST"]
    assert posts.count("confirm") == 1 and posts.count("record") == 2
    assert not {"selection", "propositions", "consent", "vir-seen"} & set(posts[posts.index("confirm"):])


def test_served_by_pgdr_alone_nothing_is_said_about_a_record(page, base):
    to_confirmation(page, base)
    page.click("#confirm")
    page.wait_for_selector("#screen-restitution:not([hidden])")
    assert page.locator('article.restitution[data-entry-id="fx_green_lamps"]').count() == 1
    assert page.locator("#product-record").is_hidden()
    assert "enregistr" not in page.locator("#screen-restitution").inner_text().lower()
