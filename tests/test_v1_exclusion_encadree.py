"""V1 parcours — the exclusion of a stop sentence from R-5 for a VALIDATED
« action attendue » classification is framed (FICTIVE notice only).

A stop sentence leaves the stops passed to R-5 (and the condition question)
only if: classification VALIDATED, nature action_conducteur, instruction
marked presented_as_action, no immediacy marker in the sentence, not also
cited in a linked warning carrying one, and no other validated classification
making the entry an immediate stop. Otherwise everything stays as before."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from test_v1_premier_constat import confirm, wire

CONDITION = "If the fictive light stays on"
IMMEDIATE = "Stop the fictive vehicle immediately."
PLAIN = "Stop the fictive vehicle."
PAUSE = "Stop to pause in a safe fictive place."


@pytest.fixture
def client():
    return TestClient(web.app)


def notice(tmp_path, *, instruction, warning=None, designation=None):
    m = fx.build(tmp_path / "n")
    d = fx.load(m)
    e = next(e for e in d["entries"] if e["entry_id"] == "fx_red_fluid")
    e["documented_instruction"] = instruction
    if warning is not None:
        e["linked_warnings"][0]["text"] = warning
        e["linked_warnings"][0]["inline_pictograms"] = []
    if designation is not None:
        e["manufacturer_designation"] = designation
    fx.approve_manifest(d)
    fx.save(m, d)
    return m


def situations(m, nature, instruction, warning_stop=fx.STOP_PHRASE, *, validated=True):
    entries = {"fx_red_fluid": fx.situation(nature, "the fictive brake fluid is low", intitule="Liquide fictif bas", consignes=[
        (instruction, "documented_instruction", None, None), (warning_stop, "linked_warnings", CONDITION, "linked_warnings")])}
    if validated:
        return fx.build_situations(m, entries=entries, status="VALIDE", validated_by="Fictive Owner")
    return fx.build_situations(m, entries=entries)


def answer(client, r, key, value) -> dict:
    out = client.post(f"/api/v1/parcours/{r['parcours_id']}/condition", json={"key": key, "answer": value})
    assert out.status_code == 200, out.text
    return out.json()


def keys(r, where) -> list[str]:
    pc = r["premier_constat"]
    return [s["key"] for s in (pc["internal"]["stops"] if where == "r5" else pc["presentation"]["stops"])]


def test_markers_are_one_documented_list():
    assert vc.IMMEDIACY_MARKERS == ("immediately", "at once", "straight away", "right away", "without delay")
    assert vc.has_immediacy_marker("stop the fictive car at once") and not vc.has_immediacy_marker(PAUSE)


def test_a_immediate_stop_classified_as_action_is_rejected_and_stays_in_r5(monkeypatch, tmp_path, client):
    m = notice(tmp_path, instruction=IMMEDIATE)
    w = wire(monkeypatch, m, situations_path=situations(m, "action_conducteur", IMMEDIATE))
    assert "fx_red_fluid" not in w.situations
    assert w.situations_rejected["fx_red_fluid"] == "expected action refused: immediacy marker in the stop instruction"
    r = confirm(client, ["fx_red_fluid"])
    key = vc.stop_key("fx_red_fluid", IMMEDIATE)
    assert key in keys(r, "r5") and key in keys(r, "question")
    assert any(u["kind"] == "stop.action_exclusion_refused" and u["cause"] == "immediacy_marker"
               for u in r["premier_constat"]["internal"]["uncertainties"])
    out = answer(client, r, key, "confirmed")
    assert out["premier_constat"]["triage"]["level"] == "emergency_stop"
    assert "R-5:conditional_stop_confirmed:fx_red_fluid" in out["premier_constat"]["triage"]["r5_rows"]


def test_b_linked_warning_with_marker_keeps_the_sentence_in_r5(monkeypatch, tmp_path, client):
    warning = "If the fictive light stays on, stop the fictive vehicle immediately."
    m = notice(tmp_path, instruction=PLAIN, warning=warning)
    w = wire(monkeypatch, m, situations_path=situations(m, "action_conducteur", PLAIN, "stop the fictive vehicle immediately"))
    assert "fx_red_fluid" not in w.situations
    assert "linked warning with an immediacy marker" in w.situations_rejected["fx_red_fluid"]
    r = confirm(client, ["fx_red_fluid"])
    key = vc.stop_key("fx_red_fluid", PLAIN)
    assert key in keys(r, "r5") and key in keys(r, "question")
    assert any(u["kind"] == "stop.action_exclusion_refused" and u["cause"] == "linked_warning_marker"
               for u in r["premier_constat"]["internal"]["uncertainties"])
    # The criterion itself refuses it (the phrase is cited in a linked warning carrying a marker).
    st = vc.load_situations(situations(m, "action_conducteur", PLAIN, "stop the fictive vehicle immediately"),
                            ManifestNoticeRepository(m).catalogue, dev_trial=True)
    e = ManifestNoticeRepository(m).catalogue.entry("fx_red_fluid")
    assert vc.immediacy_in_linked_warning(e, PLAIN) and st[0] == {}


def test_c_pause_without_marker_keeps_the_expected_action(monkeypatch, tmp_path, client):
    m = notice(tmp_path, instruction=PAUSE)
    w = wire(monkeypatch, m, situations_path=situations(m, "action_conducteur", PAUSE))
    st = w.situations["fx_red_fluid"]
    assert st.action_validated and st.consignes[0].presented_as_action
    r = confirm(client, ["fx_red_fluid"])
    key = vc.stop_key("fx_red_fluid", PAUSE)
    assert key not in keys(r, "r5") and key not in keys(r, "question")
    e = next(e for e in r["premier_constat"]["presentation"]["entries"] if e["entry_id"] == "fx_red_fluid")
    c = e["situation"]["consignes"][0]
    assert c["label"] == "Action attendue de votre part" and c["consigne"]["text"] == PAUSE
    level = r["premier_constat"]["triage"]["level"]
    out = client.post(f"/api/v1/parcours/{r['parcours_id']}/condition", json={"key": key, "answer": "confirmed"})
    assert out.status_code == 409
    assert confirm(client, ["fx_red_fluid"])["premier_constat"]["triage"]["level"] == level


def test_d_red_brake_entry_classified_as_action_still_triggers_saf012(monkeypatch, tmp_path, client):
    m = notice(tmp_path, instruction=PAUSE, designation="FICTIVE LOW BRAKE FLUID")
    wire(monkeypatch, m, situations_path=situations(m, "action_conducteur", PAUSE))
    t = confirm(client, ["fx_red_fluid"])["premier_constat"]["triage"]
    assert "PGDR-SAF-012" in t["triggered_rules"] and t["rule_exclusions"] == []
    assert t["engine_level"] == "do_not_drive"


def test_e_draft_keeps_the_current_behaviour(monkeypatch, tmp_path, client):
    m = notice(tmp_path, instruction=IMMEDIATE)
    w = wire(monkeypatch, m, situations_path=situations(m, "action_conducteur", IMMEDIATE, validated=False))
    assert w.situations_rejected["fx_red_fluid"] == "stop instruction not shown under its condition"
    r = confirm(client, ["fx_red_fluid"])
    key = vc.stop_key("fx_red_fluid", IMMEDIATE)
    assert key in keys(r, "r5") and key in keys(r, "question")
    assert not any(u["kind"] == "stop.action_exclusion_refused" for u in r["premier_constat"]["internal"]["uncertainties"])
    assert answer(client, r, key, "confirmed")["premier_constat"]["triage"]["level"] == "emergency_stop"


def test_other_validated_classification_making_it_an_immediate_stop_refuses_the_exclusion(monkeypatch, tmp_path, client):
    m = notice(tmp_path, instruction=PLAIN)
    w = wire(monkeypatch, m, situations_path=situations(m, "action_conducteur", PLAIN), findings_path=fx.build_findings(m))
    rec = w.findings.get((w.repository.catalogue.document.document_id, "fx_red_fluid"))
    if rec is None or "stop_vehicle_engine_off" not in rec.items:
        pytest.skip("the fictive Part 1 classification records no immediate stop for this entry")
    assert w.action_refused == {"fx_red_fluid": "immediate_alert_classification"}
    assert not w.situations["fx_red_fluid"].action_validated
    r = confirm(client, ["fx_red_fluid"])
    assert any(u["kind"] == "stop.action_exclusion_refused" and u["cause"] == "immediate_alert_classification"
               for u in r["premier_constat"]["internal"]["uncertainties"])
