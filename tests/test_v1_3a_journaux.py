"""Bloc 3A, point 5 — PGDR's request log names a route template or a fixed
label, never a parcours identifier, a query, a photo, a token or a cookie.

Checked on the output of a REAL uvicorn process launched the way the
assembly launches PGDR (``python -m uvicorn pgdr.web_app:app
--no-access-log``), FICTIVE notice only, loopback only: success, refusal,
unknown route and an exception (the last one through a test module that adds
one failing route to the same app, since no PGDR route fails on purpose).
"""
from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

import v1_fictive_notice as fx

TOKEN = "fictive-3a-journaux-" + os.urandom(6).hex()
SECRET_COOKIE = "fictive-cookie-" + os.urandom(6).hex()
PLATE, VIN = "FICTIVE-PLATE-3A", "VF3FICTIVE3A00001"

FAILING_APP = '''
from pgdr.web_app import app

@app.get("/essai-3a/panne/{value}")
def panne(value: str):
    raise RuntimeError("message with request data " + value)
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def pgdr_server(tmp_path):
    notice = fx.build(tmp_path / "notice", applicability_established=True)
    (tmp_path / "essai_panne_3a.py").write_text(FAILING_APP, encoding="utf-8")
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PGDR_")}
    env.update({"PGDR_V1_MANIFEST": str(notice), "PGDR_IDENTITY_HANDOFF_TOKEN": TOKEN,
                "PYTHONPATH": os.pathsep.join(filter(None, [str(tmp_path), env.get("PYTHONPATH")]))})
    log = tmp_path / "pgdr.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "essai_panne_3a:app", "--host", "127.0.0.1",
                                 "--port", str(port), "--no-access-log"], env=env, stdout=out, stderr=subprocess.STDOUT,
                                cwd=tmp_path)
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(base + "/health", timeout=1).status_code in (200, 503):
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        yield base, log
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_real_launch_logs_templates_only(pgdr_server):
    base, log = pgdr_server
    cookies = {"pi_session": SECRET_COOKIE}
    with httpx.Client(base_url=base, cookies=cookies, timeout=10) as c:
        body = {"resolution_id": "VIR-FICTIVE-3A", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}
        opened = c.post("/api/v1/vir-handoff", json=body, headers={"X-PGDR-Identity-Handoff-Token": TOKEN}).json()
        pid = opened["parcours_id"]
        assert c.post(f"/api/v1/parcours/{pid}/vir-seen").status_code == 200                       # success
        assert c.get(f"/api/v1/parcours/{pid}/catalogue").status_code == 403                       # refusal: no consent
        assert c.post("/api/v1/vir-handoff", json=body, headers={"X-PGDR-Identity-Handoff-Token": "wrong"}).status_code == 403
        assert c.get(f"/v1?p={pid}&plate={PLATE}").status_code == 200
        assert c.get(f"/inconnue/{VIN}?vin={VIN}").status_code == 404                               # unknown route
        photo = base64.b64encode(fx.png((1, 2, 3))).decode()
        c.post(f"/api/v1/parcours/{pid}/propositions", json={"recipient_consent": PLATE, "photo_base64": photo})
        r = c.get(f"/essai-3a/panne/{VIN}")                                                           # exception
        assert r.status_code == 500 and VIN not in r.text
    time.sleep(0.3)
    out = log.read_text(encoding="utf-8")
    assert "POST /api/v1/parcours/{pid}/vir-seen 200" in out
    assert "GET /api/v1/parcours/{pid}/catalogue 403" in out
    assert "POST /api/v1/vir-handoff 403" in out
    assert "GET /v1 200" in out
    assert "GET (aucune route) 404" in out
    assert "GET /essai-3a/panne/{value} exception RuntimeError" in out
    assert "GET /essai-3a/panne/{value} 500" in out
    for secret in (pid, PLATE, VIN, TOKEN, SECRET_COOKIE, photo[:24], "message with request data", "Traceback"):
        assert secret not in out, secret
