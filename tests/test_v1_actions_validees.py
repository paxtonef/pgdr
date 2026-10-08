"""V1 parcours — a stop instruction of a VALIDATED « action attendue »
(action_conducteur) classification, shown under « Action attendue de votre
part », on a FICTIVE notice only. The exact text is never changed; a draft
keeps the current behaviour; an immediate alert stays urgent; the internal
level (SafetyEngine, R-5) is not changed by this presentation."""
from __future__ import annotations

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

TOKEN = "v1-actions-validees-token"
INSTRUCTION = "Stop the fictive vehicle."
CONDITION = "If the fictive light stays on"


def consignes():
    return [(INSTRUCTION, "documented_instruction", None, None),
            (fx.STOP_PHRASE, "linked_warnings", CONDITION, "linked_warnings")]


def situations(manifest, nature, **kw):
    entries = {"fx_red_fluid": fx.situation(nature, "the fictive brake fluid is low", consignes=consignes(),
                                            intitule="Liquide fictif bas")}
    if kw.get("validated_by"):
        kw["status"] = "VALIDE"
    return fx.build_situations(manifest, entries=entries, **kw)


@pytest.fixture
def notice(tmp_path):
    return fx.build(tmp_path / "notice")


@pytest.fixture
def client():
    return TestClient(web.app)


def wire(monkeypatch, manifest, **paths):
    w = v1.build_wiring(ManifestNoticeRepository(manifest), dev_trial=paths.pop("dev_trial", True), **paths)
    monkeypatch.setattr(v1, "_wiring", w)
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    return w


def confirm(client, ids) -> dict:
    r = client.post("/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}, json={
        "resolution_id": "VIR-FICTIVE", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}).json()
    pid = r["parcours_id"]
    client.post(f"/api/v1/parcours/{pid}/vir-seen")
    client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True})
    client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids})
    out = client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True})
    assert out.status_code == 200, out.text
    return out.json()


def situation_of(r) -> dict:
    e = next(e for e in r["premier_constat"]["presentation"]["entries"] if e["entry_id"] == "fx_red_fluid")
    return e["situation"]


class TestValidatedAction:
    def test_stop_instruction_shown_as_expected_action_exact_text(self, monkeypatch, notice, client):
        w = wire(monkeypatch, notice, situations_path=situations(notice, "action_conducteur", validated_by="Fictive Owner"))
        st = w.situations["fx_red_fluid"]
        assert w.situations_status == "validated" and st.action_validated
        first, second = st.consignes
        assert first.presented_as_action and not first.action and not first.conditional
        assert not second.presented_as_action and second.conditional  # conditional one: unchanged
        e = w.repository.catalogue.entry("fx_red_fluid")
        assert vc.action_passages(e, st) == [{"field": "Consigne", "text": INSTRUCTION, "printed_page": "F-1", "pdf_page": 1,
                                              "condition": None}]
        assert vc.urgent_passages(e, st) == []
        s = situation_of(confirm(client, ["fx_red_fluid"]))
        c = s["consignes"][0]
        assert c["label"] == vc.SITUATION_LABELS["action"] == "Action attendue de votre part"
        assert c["consigne"]["text"] == INSTRUCTION and c["action"] is True
        assert s["consignes"][1]["label"] == vc.SITUATION_LABELS["conditional"]
        text = json.dumps(s, ensure_ascii=False).lower()
        assert "facultati" not in text and "conseill" not in text

    def test_draft_keeps_current_behaviour(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, situations_path=situations(notice, "action_conducteur"))
        assert w.situations_status == "draft_dev_trial"
        assert "fx_red_fluid" not in w.situations
        assert w.situations_rejected["fx_red_fluid"] == "stop instruction not shown under its condition"

    def test_immediate_alert_stays_urgent(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, situations_path=situations(notice, "alerte_consigne_immediate", validated_by="Fictive Owner"))
        st = w.situations["fx_red_fluid"]
        assert not st.action_validated and not any(c.presented_as_action for c in st.consignes)
        e = w.repository.catalogue.entry("fx_red_fluid")
        assert any(INSTRUCTION in u["text"] for u in vc.urgent_passages(e, st))
        assert vc.action_passages(e, st) == []
        assert vc.present_situation(st)["consignes"][0]["label"] == vc.SITUATION_LABELS["consigne"]

    def test_internal_level_identical_with_and_without_the_presentation(self, monkeypatch, notice, client):
        path = situations(notice, "action_conducteur", validated_by="Fictive Owner")
        findings = fx.build_findings(notice)
        out = []
        for presented in (True, False):
            w = wire(monkeypatch, notice, situations_path=path, findings_path=findings)
            if not presented:  # the same validated classification, without the new presentation
                st = w.situations["fx_red_fluid"]
                w.situations["fx_red_fluid"] = dataclasses.replace(st, action_validated=False, consignes=tuple(
                    dataclasses.replace(c, presented_as_action=False) for c in st.consignes))
            out.append(confirm(client, ["fx_red_fluid"]))
        a, b = out
        assert a["premier_constat"]["triage"] == b["premier_constat"]["triage"]
        assert a["premier_constat"]["triage"]["level"] == "emergency_stop"
        strip = lambda r: json.loads(json.dumps(r["premier_constat"].get("internal")).replace(r["parcours_id"], "PID"))
        assert strip(a) == strip(b)
        assert situation_of(a)["consignes"][0]["label"] != situation_of(b)["consignes"][0]["label"]

    def test_draft_refused_outside_the_trial(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, dev_trial=False, situations_path=situations(notice, "action_conducteur"))
        assert w.situations == {} and w.situations_status == "refused: situations not validated"
