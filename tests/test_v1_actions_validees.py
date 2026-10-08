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
        # No Part 1 classification here: one recording an immediate stop for this entry refuses the presentation
        # (see test_v1_exclusion_encadree).
        path = situations(notice, "action_conducteur", validated_by="Fictive Owner")
        out = []
        for presented in (True, False):
            w = wire(monkeypatch, notice, situations_path=path)
            if not presented:  # the same validated classification, without the new presentation
                st = w.situations["fx_red_fluid"]
                w.situations["fx_red_fluid"] = dataclasses.replace(st, action_validated=False, consignes=tuple(
                    dataclasses.replace(c, presented_as_action=False) for c in st.consignes))
            out.append(confirm(client, ["fx_red_fluid"]))
        a, b = out
        ta, tb = a["premier_constat"]["triage"], b["premier_constat"]["triage"]
        assert ta["level"] == tb["level"] and ta["r5_rows"] == tb["r5_rows"]
        assert ta["engine_level"] == tb["engine_level"] and ta["triggered_rules"] == tb["triggered_rules"]
        # Only the stop presented as the expected action leaves the R-5 list (no question, no answer on it).
        key = vc.stop_key("fx_red_fluid", INSTRUCTION)
        assert [u for u in tb["safety_uncertainties"] if u["key"] != key] == ta["safety_uncertainties"]
        assert key not in [s["key"] for s in a["premier_constat"]["internal"]["stops"]]
        assert key in [s["key"] for s in b["premier_constat"]["internal"]["stops"]]
        assert a["premier_constat"]["internal"]["consignes"] == b["premier_constat"]["internal"]["consignes"]
        assert situation_of(a)["consignes"][0]["label"] != situation_of(b)["consignes"][0]["label"]

    def test_draft_refused_outside_the_trial(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, dev_trial=False, situations_path=situations(notice, "action_conducteur"))
        assert w.situations == {} and w.situations_status == "refused: situations not validated"


def stop_keys(r) -> list[str]:
    return [s["key"] for s in r["premier_constat"]["presentation"]["stops"]]


class TestNoConditionQuestionForValidatedAction:
    def test_no_question_and_no_rise_whatever_the_answer(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, situations_path=situations(notice, "action_conducteur", validated_by="Fictive Owner"))
        r = confirm(client, ["fx_red_fluid"])
        key = vc.stop_key("fx_red_fluid", INSTRUCTION)
        assert key not in stop_keys(r)  # no « Consignes d'arrêt … et leur condition » entry, no question
        assert situation_of(r)["consignes"][0]["consigne"]["text"] == INSTRUCTION  # still shown, exact
        level = r["premier_constat"]["triage"]["level"]
        out = client.post(f"/api/v1/parcours/{r['parcours_id']}/condition", json={"key": key, "answer": "confirmed"})
        assert out.status_code == 409  # no answer can raise the level on this instruction
        assert any(u["kind"] == "stop.presented_as_action" and u["key"] == key and u["cause"] == "validated_action_situation"
                   for u in r["premier_constat"]["internal"]["uncertainties"])
        # The other (conditional) stop keeps its question; confirming it is unchanged behaviour.
        other = [k for k in stop_keys(r) if k != key]
        assert other
        r2 = client.post(f"/api/v1/parcours/{r['parcours_id']}/condition", json={"key": other[0], "answer": "excluded"}).json()
        assert r2["premier_constat"]["triage"]["level"] == level

    def test_draft_keeps_the_question_and_the_rise(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, situations_path=situations(notice, "action_conducteur"))
        r = confirm(client, ["fx_red_fluid"])
        key = vc.stop_key("fx_red_fluid", INSTRUCTION)
        assert key in stop_keys(r)
        out = client.post(f"/api/v1/parcours/{r['parcours_id']}/condition", json={"key": key, "answer": "confirmed"}).json()
        assert out["premier_constat"]["triage"]["level"] == "emergency_stop"
        assert f"R-5:conditional_stop_confirmed:fx_red_fluid" in out["premier_constat"]["triage"]["r5_rows"]


def test_immediate_alert_condition_travels_with_the_instruction(monkeypatch, tmp_path, client):
    grouped = fx.build(tmp_path / "grouped", with_groups=True)
    wire(monkeypatch, grouped, situations_path=fx.build_situations(grouped))
    r = confirm(client, ["fx_red_alarm_a"])  # no documented distinctive element: shown as ambiguous, no question
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    (pa,) = b["urgent"][0]["passages"]
    assert pa["text"] == fx.ALARM_STOP
    assert pa["condition"] == {"text": "If the fictive alarm light comes on while driving", "printed_page": "F-10", "pdf_page": 10}
