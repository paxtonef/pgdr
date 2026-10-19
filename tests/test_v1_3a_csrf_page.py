"""Bloc 3A, point 4 — PGDR's /v1 page sends the CSRF token of the product
that serves it.

When the product (PI) serves the page, it places its own session-bound CSRF
token in ``<meta name="csrf-token">``; the page then sends it as
``X-CSRF-Token`` on every write request, and only on those. Served by PGDR
alone, the page has no such meta and sends no such header. Real uvicorn and
real Chromium, a FICTIVE notice; a small wrapper stands in for PI's page
relay (meta injection) and records the headers of each request.
"""
from __future__ import annotations

import os
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

TOKEN = "v1-3a-csrf-page-token"
CSRF = "0123456789abcdef" * 4
SEEN: list[tuple[str, str, str | None]] = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Relay:
    """With `inject`, adds the product's meta to the page like PI does; records (method, path, X-CSRF-Token)."""

    def __init__(self, inject: bool):
        self.inject = inject

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await web.app(scope, receive, send)
        headers = dict(scope["headers"])
        SEEN.append((scope["method"], scope["path"], (headers.get(b"x-csrf-token") or b"").decode() or None))
        if not (self.inject and scope["path"] == "/v1"):
            return await web.app(scope, receive, send)
        html = v1.V1_HTML.replace("<head>", f'<head>\n<meta name="csrf-token" content="{CSRF}">', 1)
        body = html.encode("utf-8")
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


@pytest.fixture(scope="module")
def notice(tmp_path_factory):
    return fx.build(tmp_path_factory.mktemp("fictive") / "notice", applicability_established=True)


@pytest.fixture
def served(notice, monkeypatch):
    def start(inject: bool) -> str:
        monkeypatch.setattr(v1, "_wiring", v1.build_wiring(ManifestNoticeRepository(notice), dev_trial=False))
        monkeypatch.setattr(v1, "_parcours", {})
        monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(Relay(inject), host="127.0.0.1", port=port, log_level="error"))
        threading.Thread(target=server.run, daemon=True).start()
        servers.append(server)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        return f"http://127.0.0.1:{port}"

    servers: list = []
    SEEN.clear()
    yield start
    for s in servers:
        s.should_exit = True


@pytest.fixture
def page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    yield context.new_page()
    context.close()
    browser.close()


def walk_to_catalogue(page, base: str) -> None:
    r = httpx.post(f"{base}/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN},
                   json={"resolution_id": "VIR-FICTIVE-3A", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY})
    page.goto(f"{base}/v1?p={r.json()['parcours_id']}")
    page.click("#vir-continue")
    page.check("#consent-box")
    page.click("#consent-continue")
    page.click("#photo-continue")
    page.wait_for_selector("#screen-catalogue:not([hidden])")


def test_page_served_by_the_product_sends_its_token_on_writes_only(page, served):
    walk_to_catalogue(page, served(inject=True))
    writes = [(m, p, t) for m, p, t in SEEN if m == "POST" and p.startswith("/api/v1/parcours/")]
    reads = [(m, p, t) for m, p, t in SEEN if m == "GET" and p.startswith("/api/v1/parcours/")]
    assert {p.rsplit("/", 1)[1] for _, p, _ in writes} >= {"vir-seen", "consent"}
    assert all(t == CSRF for _, _, t in writes), writes
    assert reads and all(t is None for _, _, t in reads), reads


def test_page_served_by_pgdr_alone_sends_no_token(page, served):
    walk_to_catalogue(page, served(inject=False))
    writes = [t for m, p, t in SEEN if m == "POST" and p.startswith("/api/v1/parcours/")]
    assert writes and all(t is None for t in writes)
