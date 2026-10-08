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
    # Established operating indication, nothing critical: the caution sentence is kept, folded in « Détails ».
    assert e["situation"]["no_consigne"] == vc.SITUATION_LABELS["no_consigne"]
    assert e["situation"]["no_consigne_placement"] == "details"
    p = r["premier_constat"]["presentation"]
    assert p["stops"] == [] and p["stops_confirmed"] == [] and p["red_screen"] is None
    body = [u for u in uncertainties(r, entry_id="fx_green_lamps") if u["placement"] == "corps"]
    assert [u["kind"] for u in body] == ["explanation.inconnu"] and body[0]["point"] == "explication"
    tech = uncertainties(r, entry_id="fx_green_lamps", point="technique")
    assert {u["kind"] for u in tech} == {"explanation.draft", "situation.draft", "situation.no_consigne", "point.stop",
                                         "point.operability", "point.professional", "point.practical"}
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


# --- group block: prepared explanations of the variants first; caution sentence placement --------

BELT_EXPLANATIONS = {
    "fx_red_belt_fixed": {
        "indique": [{"texte": "Le voyant fictif reste allumé tant que la ceinture fictive est ouverte.",
                     "source_field": "documented_meaning", "source_phrase": "while the fictive belt is open"}],
        "maintenant": [{"texte": "Bouclez la ceinture fictive.", "source_field": "documented_meaning",
                        "source_phrase": "the fictive belt is open"}],
        "inconnu": [{"texte": "Le passage fictif ne précise rien d'autre.", "source_field": "documented_meaning",
                     "source_phrase": fx.BELT_MEANING_FIXED}]},
    "fx_red_belt_flashing": {
        "indique": [{"texte": "Le voyant fictif clignote quand le véhicule fictif roule ceinture ouverte.",
                     "source_field": "documented_meaning", "source_phrase": "while the fictive vehicle moves with the belt open"}],
        "maintenant": [{"texte": "Bouclez la ceinture fictive.", "source_field": "documented_meaning",
                        "source_phrase": "the belt open"}],
        "inconnu": [{"texte": "Le passage fictif ne précise rien d'autre.", "source_field": "documented_meaning",
                     "source_phrase": fx.BELT_MEANING_FLASHING}]},
}
SIDE_LIGHTS_EXPLANATION = {
    "indique": [{"texte": "Ce voyant fictif indique que les feux de position fictifs sont allumés.",
                 "source_field": "documented_meaning", "source_phrase": "the fictive side lights are on"}],
    "maintenant": [{"texte": "Le passage fictif ne donne pas de consigne.", "source_field": "documented_meaning",
                    "source_phrase": fx.LIGHTS_SIDE}],
    "inconnu": [{"texte": "Rien d'autre n'est précisé.", "source_field": "documented_meaning", "source_phrase": fx.LIGHTS_SIDE}],
}


def with_explanations(monkeypatch, manifest, entries):
    return wire(monkeypatch, manifest, explanations_path=fx.build_explanations(manifest, entries=entries),
                situations_path=fx.build_situations(manifest))


def caution(r, x) -> dict:
    (u,) = uncertainties(r, kind="situation.no_consigne", entry_id=x)
    return u


def test_lighting_group_head_and_caution_folded(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_green_side_lights"])
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    # No prepared explanation: each variant starts with its designation and situation type, side by side.
    assert [(h["entry_id"], h["explanation"], h["situation_label"]) for h in b["explanations"]] == [
        ("fx_green_side_lights", None, "Indication de fonctionnement"), ("fx_green_follow_me", None, "Indication de fonctionnement")]
    assert [h["only_for"] for h in b["explanations"]] == [v["only_for"] for v in b["variants"]]
    for v in b["variants"]:
        assert v["entry"]["situation"]["no_consigne_placement"] == "details"
        u = caution(r, v["entry"]["entry_id"])
        assert u["placement"] == "details" and u["reason"] == "generic_caution"
    assert b["common"] == [] and b["no_common"] == vc.DRAFT_LABELS["no_common"]  # no invented common meaning


def test_variant_without_prepared_explanation_beside_one_with(monkeypatch, grouped, client):
    with_explanations(monkeypatch, grouped, {"fx_green_side_lights": SIDE_LIGHTS_EXPLANATION})
    r = restitution(client, ["fx_green_side_lights"])
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    side, follow = b["explanations"]
    assert side["explanation"] == {"title": "Ce que la notice indique", "sentences": [{
        "text": "Ce voyant fictif indique que les feux de position fictifs sont allumés.",
        "citation": "the fictive side lights are on", "source_field": "documented_meaning"}]}
    assert side["situation_label"] is None
    assert follow["explanation"] is None and follow["situation_label"] == "Indication de fonctionnement"
    assert b["explanation_mention"] == vc.LABELS["draft_explanation"] and b["explanation_mention_placement"] == "details"


def test_belt_group_explanations_side_by_side_never_merged(monkeypatch, grouped, client):
    with_explanations(monkeypatch, grouped, BELT_EXPLANATIONS)
    r = restitution(client, ["fx_red_belt_fixed"])
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    assert [[s_["text"] for s_ in h["explanation"]["sentences"]] for h in b["explanations"]] == [
        [BELT_EXPLANATIONS[x]["indique"][0]["texte"]] for x in ("fx_red_belt_fixed", "fx_red_belt_flashing")]
    assert b["limit"] == vc.LIMIT_V1 and b["urgent"] == [] and b["red_offer"] is None
    # Belts: an expected driver action, but no stop, no condition, nothing critical: generic caution, folded.
    # The fixed/flashing uncertainty stays in the body (it changes the explanation).
    for x in ("fx_red_belt_fixed", "fx_red_belt_flashing"):
        u = caution(r, x)
        assert u["placement"] == "details" and u["reason"] == "generic_caution"
        v = next(v for v in b["variants"] if v["entry"]["entry_id"] == x)
        assert v["entry"]["situation"]["no_consigne_placement"] == "details"
    (g,) = uncertainties(r, kind="group.variant_undetermined")
    assert g["placement"] == "corps" and "explication" in g["points"]


def test_brake_group_caution_in_body_stop_visible(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_red_pb_failure"])
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    applied = next(v for v in b["variants"] if v["entry"]["entry_id"] == "fx_red_pb_applied")
    # Operating indication, but in a group with a critical variant: the caution sentence stays in the body.
    assert applied["entry"]["situation"]["no_consigne_placement"] == "corps"
    u = caution(r, "fx_red_pb_applied")
    assert u["placement"] == "corps" and u["point"] == "applicabilite_consigne" and "critical_variant" in u["body_reasons"]
    assert [x["entry_id"] for x in b["urgent"]] == ["fx_red_pb_fluid"]  # the stop stays visible, never folded
    assert [h["entry_id"] for h in b["explanations"]] == ["fx_red_pb_failure", "fx_red_pb_fluid", "fx_red_pb_applied"]


@pytest.mark.parametrize("nature,placement", [("situation_non_determinee", "corps"), ("anomalie_defaut", "corps"),
                                               ("information_a_prendre_en_compte", "details"),
                                               ("action_conducteur", "details"), ("fonctionnement_normal", "details")])
def test_caution_criterion_is_usefulness_not_type(grouped, nature, placement):
    from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
    e = ManifestNoticeRepository(grouped).catalogue.entry("fx_green_side_lights")
    a = vc.Anchor("documented_meaning", "the fictive side lights are on", "F-20", 20)
    lone = vc.Situation(nature, a, (), (), None, True)
    assert vc.no_consigne_uncertainty(e, lone)["placement"] == placement
    ok = vc.Situation("fonctionnement_normal", a, (), (), None, True)
    assert vc.no_consigne_uncertainty(e, ok, [(e, ok), (e, None)])["body_reasons"] == ["undetermined_situation"]
    assert vc.no_consigne_uncertainty(e, ok)["placement"] == "details"


def test_conditional_or_unknown_condition_keeps_caution_in_body(grouped):
    from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
    cat = ManifestNoticeRepository(grouped).catalogue
    sits, _, _ = vc.load_situations(fx.build_situations(grouped), cat, dev_trial=True)
    e = cat.entry("fx_green_side_lights")
    ok = sits["fx_green_side_lights"]
    tyre = cat.entry("fx_amber_tyre_low")
    u = vc.no_consigne_uncertainty(e, ok, [(e, ok), (tyre, sits["fx_amber_tyre_low"])])
    assert u["placement"] == "corps" and {"conditional_consigne", "condition_unknown"} <= set(u["body_reasons"])


def test_variant_with_cited_instruction_has_no_caution_sentence(monkeypatch, grouped, client):
    """Brake group: a variant whose passage cites an instruction gets no « Aucune consigne… » sentence;
    a variant without one, beside a critical variant, keeps it in the body; the stop stays visible."""
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_red_pb_failure"])
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    sit = {v["entry"]["entry_id"]: v["entry"]["situation"] for v in b["variants"]}
    assert sit["fx_red_pb_failure"]["consignes"] and sit["fx_red_pb_failure"]["no_consigne"] is None
    assert sit["fx_red_pb_failure"]["no_consigne_placement"] is None
    assert uncertainties(r, kind="situation.no_consigne", entry_id="fx_red_pb_failure") == []
    assert sit["fx_red_pb_applied"]["no_consigne_placement"] == "corps"
    assert [x["entry_id"] for x in b["urgent"]] == ["fx_red_pb_fluid"]


def test_unknown_condition_keeps_caution_in_body(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_red_steer_a"])
    u = caution(r, "fx_red_steer_b")  # no instruction of its own, beside a variant with an unanswered condition
    assert u["placement"] == "corps" and "condition_unknown" in u["body_reasons"]


def test_designation_marked_as_notice_text_in_every_only_for_label(monkeypatch, grouped, client):
    full(monkeypatch, grouped)
    r = restitution(client, ["fx_red_steer_a"])
    (b,) = r["premier_constat"]["presentation"]["ambiguous"]
    items = (b["explanations"] + b["urgent"] + b["situations"] + b["conditionals"] + b["actions"] + b["variants"]
             + r["premier_constat"]["presentation"]["stops"])
    assert items
    for x in items:  # same text as before, split: French label + notice designation + French title
        assert x["only_for"] == x["only_for_label"] + x["designation"] + (" — " + x["title"] if x["title"] else "")
