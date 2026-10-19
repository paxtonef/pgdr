"""Bloc 3A, point 7 — the fake sorting transport is a verification tool,
never a production component.

From the environment it is activated only for a signalled trial
(PGDR_V1_ESSAI_TRI=1), and then every screen carries a permanent banner
saying so. Without that declaration -- and with any other value, since no
real component is authorised -- there is no sorting: the complete catalogue
in the notice order, with its explanation. In-process tests may still hand
the fake to build_wiring directly. FICTIVE notice only.
"""
from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import v1_propositions as vp
from pgdr import web_app as web

TOKEN = "v1-3a-tri-token"
RECIPIENT = "Composant de tri d'essai (faux transport)"


@pytest.fixture
def fake_file(tmp_path) -> str:
    p = tmp_path / "faux.json"
    p.write_text(json.dumps({"nature": vp.FAUX_NATURE, "destinataire": RECIPIENT, "reponses": {},
                             "defaut": {"texte": json.dumps({"proposed_entry_ids": []})}}), encoding="utf-8")
    return str(p)


def from_environment(monkeypatch, tmp_path, **env):
    monkeypatch.setattr(v1, "_wiring", None)
    monkeypatch.setattr(v1, "_parcours", {})
    for name in ("PGDR_V1_TRI", "PGDR_V1_TRI_FAUX", "PGDR_V1_ESSAI_TRI", "PGDR_V1_DEV_TRIAL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PGDR_V1_MANIFEST", str(fx.build(tmp_path / "notice", applicability_established=True)))
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return v1.get_wiring()


def started(client) -> str:
    body = {"resolution_id": "VIR-FICTIVE-3A", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}
    pid = client.post("/api/v1/vir-handoff", json=body, headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}).json()["parcours_id"]
    client.post(f"/api/v1/parcours/{pid}/vir-seen")
    client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True})
    return pid


def test_fake_from_the_environment_needs_a_signalled_trial(fake_file):
    t, status = vp.charger_transport("faux", fake_file)
    assert t is None and status == "refused: faux transport hors essai signalé (PGDR_V1_ESSAI_TRI=1)"
    t, status = vp.charger_transport("faux", fake_file, essai=True)
    assert status == "faux" and t.faux is True


@pytest.mark.parametrize("mode", ["reel", "vision", "openai"])
def test_no_real_component_even_in_a_trial(mode, fake_file):
    assert vp.charger_transport(mode, fake_file, essai=True) == (None, "refused: composant réel non autorisé")


def test_without_the_trial_the_catalogue_is_shown_with_its_explanation(monkeypatch, tmp_path, fake_file):
    w = from_environment(monkeypatch, tmp_path, PGDR_V1_TRI="faux", PGDR_V1_TRI_FAUX=fake_file)
    assert w.tri is None and w.tri_status.startswith("refused: faux transport hors essai signalé")
    client = TestClient(web.app)
    pid = started(client)
    state = client.get(f"/api/v1/parcours/{pid}").json()
    assert state["propositions"] == {"available": False} and state["tri_trial_banner"] is None
    r = client.post(f"/api/v1/parcours/{pid}/propositions",
                    json={"recipient_consent": RECIPIENT, "photo_base64": base64.b64encode(fx.png((1, 2, 3))).decode()}).json()
    assert r["phase"] == "catalogue" and r["proposed"] is None and r["repli"]["key"] == "non_configure"
    c = client.get(f"/api/v1/parcours/{pid}/catalogue").json()
    assert len(c["entries"]) == len(fx.load(tmp_path / "notice" / "manifest.yaml")["entries"])
    assert c["repli"]["explanation"] == vc.DRAFT_LABELS["propositions.repli.non_configure"]


def test_signalled_trial_shows_a_permanent_banner_on_every_screen(monkeypatch, tmp_path, fake_file):
    w = from_environment(monkeypatch, tmp_path, PGDR_V1_TRI="faux", PGDR_V1_TRI_FAUX=fake_file, PGDR_V1_ESSAI_TRI="1")
    assert w.tri is not None and w.tri.faux and w.tri_status == "faux"
    client = TestClient(web.app)
    pid = started(client)
    for r in (client.get(f"/api/v1/parcours/{pid}"), client.post(f"/api/v1/parcours/{pid}/return")):
        assert r.json()["tri_trial_banner"] == v1.TRI_TRIAL_BANNER
    page = client.get("/v1").text
    assert "s.tri_trial_banner" in page   # the page shows it in its permanent banner


def test_absent_configuration_has_no_banner_and_no_sorting(monkeypatch, tmp_path):
    w = from_environment(monkeypatch, tmp_path)
    assert w.tri is None and w.tri_status == "absent"
    client = TestClient(web.app)
    pid = started(client)
    assert client.get(f"/api/v1/parcours/{pid}").json()["tri_trial_banner"] is None
