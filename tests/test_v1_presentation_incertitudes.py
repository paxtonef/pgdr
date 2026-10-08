"""V1 restitution — presentation rule on a FICTIVE notice: explain the situation
first, give the action actually established, then signal only the useful
uncertainty. An uncertainty stays in the body when its resolution can change
the explanation, the action or the applicability of a safety instruction; only
a purely technical one goes to the folded « Détails », with its reason. Each
uncertainty is traced in the internal result (API), never displayed. The
internal level is not touched by the presentation."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import web_app as web
from test_v1_premier_constat import confirm, entry, wire


@pytest.fixture
def grouped(tmp_path):
    return fx.build(tmp_path / "grouped", with_groups=True)


@pytest.fixture
def client():
    return TestClient(web.app)


def full(monkeypatch, manifest, **kw):
    return wire(monkeypatch, manifest, explanations_path=fx.build_explanations(manifest),
                situations_path=fx.build_situations(manifest), **kw)


def restitution(client, ids, answer="dont_know", message=None) -> dict:
    r = confirm(client, ids)
    while r["phase"] == "clarification":
        body = {"group": r["questions"][0]["group"], "answer": answer, **({"message": message} if message else {})}
        r = {**client.post(f"/api/v1/parcours/{r['pid']}/clarify", json=body).json(), "pid": r["pid"]}
    assert r["phase"] == "restitution"
    return r


def uncertainties(r, **where) -> list[dict]:
    us = r["premier_constat"]["internal"]["uncertainties"]
    return [u for u in us if all(u.get(k) == v for k, v in where.items())]


def test_informative_light_no_instruction_block_no_technical_uncertainty_in_body(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_green_lamps"])
    e = entry(r, "fx_green_lamps")
    # No established action: every structured point goes to « Détails » (the block is without object).
    assert {p["placement"] for p in e["points"]} == {"details"} and all(not p["quotes"] for p in e["points"])
    assert e["explanation"]["mention_placement"] == "details" and e["situation"]["mention_placement"] == "details"
    assert e["situation"]["no_consigne"] == vc.SITUATION_LABELS["no_consigne"]
    p = r["premier_constat"]["presentation"]
    assert p["stops"] == [] and p["stops_confirmed"] == [] and p["red_screen"] is None
    body = [u for u in uncertainties(r, entry_id="fx_green_lamps") if u["placement"] == "corps"]
    assert [u["kind"] for u in body] == ["explanation.inconnu"] and body[0]["point"] == "explication"
    tech = uncertainties(r, entry_id="fx_green_lamps", point="technique")
    assert {u["kind"] for u in tech} == {"explanation.draft", "situation.draft", "point.stop", "point.operability",
                                         "point.professional", "point.practical"}
    assert all(u["placement"] == "details" and u["reason"] in vc.DETAILS_REASONS and u["reason_text"] for u in tech)


def test_two_lighting_functions_uncertainty_shown_no_safety_screen(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_green_side_lights"])
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    assert b["limit"] == vc.LIMIT_V1 and b["red_offer"] is None and b["urgent"] == [] and b["conditionals"] == []
    assert r["premier_constat"]["presentation"]["red_screen"] is None
    assert [v["entry"]["entry_id"] for v in b["variants"]] == ["fx_green_side_lights", "fx_green_follow_me"]
    (u,) = uncertainties(r, kind="group.variant_undetermined")
    assert u["point"] == "explication" and u["placement"] == "corps" and u["points"] == ["explication"]
    assert u["variants"] == ["fx_green_side_lights", "fx_green_follow_me"]
    assert b["draft_texts_placement"] == "details"


def test_brake_group_stop_stays_visible_variant_uncertainty_shown(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_red_pb_failure"])
    p = r["premier_constat"]["presentation"]
    (b,) = p["ambiguous"]
    # The stop instruction stays visible, whole, under its own variant only (never merged nor transferred).
    assert [u["entry_id"] for u in b["urgent"]] == ["fx_red_pb_fluid"]
    assert b["urgent"][0]["passages"][0]["text"] == fx.PB_FLUID_WARNING
    consignes = {v["entry"]["entry_id"]: [c["consigne"]["text"] for c in v["entry"]["situation"]["consignes"]] for v in b["variants"]}
    assert consignes == {"fx_red_pb_failure": ["Contact a fictive workshop."],
                         "fx_red_pb_fluid": ["stop the fictive vehicle immediately and contact a fictive workshop"],
                         "fx_red_pb_applied": []}
    (u,) = uncertainties(r, kind="group.variant_undetermined")
    assert u["point"] == "applicabilite_consigne" and u["placement"] == "corps"
    assert u["points"] == ["applicabilite_consigne", "action", "explication"]
    # The stop of the stops block: its condition touches its applicability, in the body.
    stop = [s for s in p["stops"] if s["entry_id"] == "fx_red_pb_fluid"]
    assert stop and all(s["answer"] == "unknown" for s in stop)
    for kind in ("stop.condition_interpretation_draft", "stop.condition_unknown"):
        assert [x["placement"] for x in uncertainties(r, kind=kind, entry_id="fx_red_pb_fluid")] == ["corps"]
    assert b["red_offer"] is not None  # offered, never automatic


def test_unknown_condition_shown(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_red_steer_a"])
    us = uncertainties(r, kind="consigne.condition_unknown", entry_id="fx_red_steer_a")
    assert us and {(u["point"], u["placement"]) for u in us} == {("applicabilite_consigne", "corps")}
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    assert b["conditionals"][0]["passages"][0]["answer"] == "unknown"


def test_unvalidated_condition_without_dependent_instruction_in_details_with_reason(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_amber_code_b"], answer="none")
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    v = next(v for v in b["variants"] if v["entry"]["entry_id"] == "fx_amber_code_b")
    assert [c["placement"] for c in v["entry"]["situation"]["conditions"]] == ["details"]
    assert v["entry"]["situation"]["consignes"] == []
    (u,) = uncertainties(r, kind="situation.condition", entry_id="fx_amber_code_b")
    assert u["point"] == "technique" and u["placement"] == "details" and u["reason"] == "condition_without_consigne"
    assert u["reason_text"] == vc.DETAILS_REASONS["condition_without_consigne"]


def test_condition_with_dependent_instruction_stays_in_body():
    a = vc.Anchor("documented_meaning", "if X", "F-1", 1)
    st = vc.Situation("anomalie_defaut", a, (vc.Consigne(vc.Anchor("documented_meaning", "do Y", "F-1", 1), a),), (a,),
                      None, True)
    assert vc.situation_uncertainties(st, "fx")[1] == {"kind": "situation.condition", "point": "applicabilite_consigne",
                                                       "placement": "corps", "condition": "if X"}


def test_doubt_is_shown():
    assert vc.uncertainty("x", "technique")["placement"] == "corps"  # technical without a known reason: shown
    assert vc.uncertainty("x", "technique", reason="draft_status")["placement"] == "details"
    for point in ("explication", "action", "applicabilite_consigne"):
        assert vc.uncertainty("x", point, reason="draft_status")["placement"] == "corps"
    with pytest.raises(ValueError):
        vc.uncertainty("x", "gravite")


CASES = [["fx_green_lamps"], ["fx_red_fluid"], ["fx_blue_mode_x"], ["fx_red_pb_failure"], ["fx_amber_tyre_low"],
         ["fx_red_steer_a"], ["fx_blue_frost"], ["fx_amber_code_b"], ["fx_red_alarm_b"], ["fx_red_fluid", "fx_green_lamps"],
         ["fx_green_side_lights"], ["fx_amber_pressure"]]


@pytest.mark.parametrize("ids", CASES, ids=lambda x: "+".join(x))
def test_every_uncertainty_traced_never_displayed(monkeypatch, grouped, client, ids):
    full(monkeypatch, grouped, findings_path=fx.build_findings(grouped))
    r = restitution(client, ids)
    for u in r["premier_constat"]["internal"]["uncertainties"]:
        assert u["point"] in vc.UNCERTAINTY_POINTS
        if u["placement"] == "details":
            assert u["point"] == "technique" and u["reason"] in vc.DETAILS_REASONS
        else:
            assert u["placement"] == "corps" and "reason" not in u
    text = json.dumps(r["premier_constat"]["presentation"], ensure_ascii=False)
    assert '"uncertainties"' not in text and "reason_text" not in text
    assert not [f for f in vc.FORBIDDEN if f in text.lower()]  # never a general permission to drive


def test_no_instruction_sentence_kept(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_blue_frost"])
    assert entry(r, "fx_blue_frost")["situation"]["no_consigne"] == (
        "Aucune consigne n'est citée dans ce passage ; cela ne prouve pas l'absence de risque.")


# Internal level recorded BEFORE the presentation change (same fictive notice, same selections).
LEVELS_BEFORE = {
    (False, "fx_green_lamps"): ("monitor_and_document", []),
    (False, "fx_red_pb_failure"): ("do_not_drive", []),
    (False, "fx_red_steer_a"): ("monitor_and_document", []),
    (True, "fx_red_fluid"): ("emergency_stop", ["R-5:stop_vehicle_engine_off:fx_red_fluid"]),
    (True, "fx_red_alarm_b"): ("emergency_stop", ["R-5:stop_vehicle_engine_off:fx_red_alarm_a"]),
    (True, "fx_red_pb_failure"): ("do_not_drive", []),
    (True, "fx_amber_tyre_low"): ("monitor_and_document", []),
}


@pytest.mark.parametrize("findings,x", list(LEVELS_BEFORE), ids=lambda v: str(v))
def test_internal_level_identical_before_and_after(monkeypatch, grouped, client, findings, x):
    full(monkeypatch, grouped, **({"findings_path": fx.build_findings(grouped)} if findings else {}))
    t = restitution(client, [x])["premier_constat"]["triage"]
    assert (t["level"], t["r5_rows"]) == LEVELS_BEFORE[(findings, x)]
