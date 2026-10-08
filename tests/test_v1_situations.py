"""V1 situation classification and its presentation, on a FICTIVE notice with
FICTIVE prepared content.

Covered: operating indication without automatic alert; ambiguous belts
without an automatic stop instruction; mixed group without transfer of an
instruction between variants; conditional urgent instruction kept; message
question with exact match only; unknown red light keeps the colour fallback;
draft classification never activated as a validated one.
"""
from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from test_v1_premier_constat import ADDED_ACTIONS, confirm, entry, open_parcours, wire


@pytest.fixture
def grouped(tmp_path):
    return fx.build(tmp_path / "grouped", with_groups=True)


@pytest.fixture
def client():
    return TestClient(web.app)


def ambiguous(r) -> list[dict]:
    return r["premier_constat"]["presentation"]["ambiguous"]


def clarify(client, r, answer, message=None) -> dict:
    body = {"group": r["questions"][0]["group"], "answer": answer}
    if message is not None:
        body["message"] = message
    out = client.post(f"/api/v1/parcours/{r['pid']}/clarify", json=body)
    assert out.status_code == 200, out.text
    return out.json()


def with_situations(monkeypatch, manifest, **kw):
    return wire(monkeypatch, manifest, situations_path=fx.build_situations(manifest), **kw)


class TestOperatingIndication:
    def test_single_operating_indication_no_alert(self, monkeypatch, grouped, client):
        w = with_situations(monkeypatch, grouped)
        assert w.situations_status == "draft_dev_trial" and not w.situations_rejected
        r = confirm(client, ["fx_green_lamps"])
        st = entry(r, "fx_green_lamps")["situation"]
        assert st["nature"] == "fonctionnement_normal" and st["label"] == "Indication de fonctionnement"
        assert st["justification"] == {"text": "the fictive lamps are on", "printed_page": "F-2", "pdf_page": 2}
        assert st["no_consigne"] == vc.SITUATION_LABELS["no_consigne"]
        assert r["premier_constat"]["presentation"]["red_screen"] is None

    def test_group_all_operating_no_fallback_possibilities_explained(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        r = confirm(client, ["fx_blue_mode_x"])
        assert r["phase"] == "restitution"
        (b,) = ambiguous(r)
        assert b["limit"] == ("Avec les informations renseignées, nous ne pouvons pas déterminer laquelle de ces "
                              "situations correspond à votre voyant.")
        assert b["red_offer"] is None and b["urgent"] == [] and r["premier_constat"]["presentation"]["red_screen"] is None
        assert [v["only_for"] for v in b["variants"]] == ["Indiqué seulement pour : FICTIVE MODE X — Mode X fictif choisi",
                                                          "Indiqué seulement pour : FICTIVE MODE Y — Mode Y fictif actif"]
        assert {v["entry"]["situation"]["nature"] for v in b["variants"]} == {"fonctionnement_normal"}


class TestBelts:
    def test_ambiguous_belts_no_automatic_stop(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        r = confirm(client, ["fx_red_belt_fixed"])
        assert [c["entry_id"] for c in r["questions"][0]["choices"]] == ["fx_red_belt_fixed", "fx_red_belt_flashing"]
        out = clarify(client, r, "dont_know")
        (b,) = ambiguous(out)
        assert [v["entry"]["entry_id"] for v in b["variants"]] == ["fx_red_belt_fixed", "fx_red_belt_flashing"]
        assert b["red_offer"] is None and b["urgent"] == [] and out["premier_constat"]["presentation"]["red_screen"] is None
        # Each belt keeps its own passage.
        assert [v["entry"]["manufacturer_text"]["documented_meaning"] for v in b["variants"]] == [
            fx.BELT_MEANING_FIXED, fx.BELT_MEANING_FLASHING]
        text = json.dumps(out["premier_constat"]["presentation"], ensure_ascii=False)
        assert "Arrêtez" not in text and not [a for a in ADDED_ACTIONS if a in text.lower()]


class TestMixedGroup:
    def test_stop_stays_with_its_variant_conditional_and_visible(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        r = confirm(client, ["fx_red_alarm_b"])
        (b,) = ambiguous(r)
        # Conditional urgent instruction kept, under variant A only.
        assert [(u["entry_id"], u["only_for"]) for u in b["urgent"]] == [
            ("fx_red_alarm_a", "Indiqué seulement pour : FICTIVE ALARM — Perte de pression fictive")]
        assert b["urgent"][0]["passages"] == [{"field": "Avertissement 9)", "text": fx.ALARM_STOP,
                                               "printed_page": "F-10", "pdf_page": 10}]
        assert b["red_offer"] == vc.DRAFT_LABELS["red_offer"]
        a_, b_ = b["variants"]
        assert a_["entry"]["situation"]["consignes"] == [{
            "consigne": {"text": fx.ALARM_STOP_PHRASE, "printed_page": "F-10", "pdf_page": 10},
            "condition": {"text": "If the fictive alarm light comes on while driving", "printed_page": "F-10", "pdf_page": 10},
            "label": "Consigne du constructeur", "action": False}]
        # Never transferred to variant B.
        assert b_["entry"]["situation"]["consignes"] == [] and b_["entry"]["manufacturer_text"]["linked_warnings"] == []
        assert fx.ALARM_STOP not in json.dumps(b_, ensure_ascii=False)
        assert fx.ALARM_STOP not in [c["text"] for c in b["common"]]

    def test_message_question_exact_text_never_mapped(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        r = confirm(client, ["fx_amber_code_a"])
        (q,) = r["questions"]
        assert q["kind"] == "message" and q["none"] == "Aucun message / Je ne sais pas"
        out = clarify(client, r, "message", "  CODE   intrusion ")
        (b,) = ambiguous(out)  # no documented message: never matched to a variant
        assert b["message_given"] == {"label": vc.DRAFT_LABELS["message_given"], "text": "CODE intrusion"}
        a_, b_ = b["variants"]
        # « Contact … » belongs to variant A only.
        assert fx.CODE_A_INSTRUCTION not in [c["text"] for c in b["common"]]
        assert a_["entry"]["situation"]["consignes"][0]["consigne"]["text"] == fx.CODE_A_INSTRUCTION
        assert b_["entry"]["situation"]["consignes"] == [] and b_["entry"]["manufacturer_text"]["documented_instruction"] is None
        assert b["urgent"] == [] and b["red_offer"] is None
        r = confirm(client, ["fx_amber_code_b"])
        (b,) = ambiguous(clarify(client, r, "dont_know"))
        assert b["message_given"] is None

    def test_exact_documented_message_resolves(self, grouped):
        c = ManifestNoticeRepository(grouped).catalogue
        looks = [c.entry("fx_green_look_a"), c.entry("fx_green_look_b")]
        assert vc.message_match(looks, " look  a ") == "fx_green_look_a"
        assert vc.message_match(looks, "LOOK") is None

    def test_no_message_question_when_all_operating(self, grouped):
        c = ManifestNoticeRepository(grouped).catalogue
        e_a, e_b = c.entry("fx_amber_code_a"), c.entry("fx_amber_code_b")
        assert vc.message_question([e_a, e_b], {})
        sit, _, _ = vc.load_situations(fx.build_situations(grouped, entries={
            "fx_amber_code_a": fx.situation("fonctionnement_normal", "a fictive code fault"),
            "fx_amber_code_b": fx.situation("fonctionnement_normal", "a fictive intrusion attempt")}), c, dev_trial=True)
        assert not vc.message_question([e_a, e_b], sit)


class TestUnknownLight:
    def test_unknown_red_light_keeps_colour_fallback(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        pid = open_parcours(client)
        client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": "none_match", "entry_ids": []})
        s = client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "rouge"}).json()["screen"]
        assert s["key"] == "red_or_uncertain" and s["heading"].startswith("Arrêtez-vous en sécurité")


class TestDraftNeverValidated:
    def test_draft_refused_outside_dev_trial(self, monkeypatch, tmp_path, client):
        m = fx.build(tmp_path / "prod", with_groups=True, applicability_established=True)
        # A validated explanation does not validate the classification.
        w = wire(monkeypatch, m, dev_trial=False, situations_path=fx.build_situations(m),
                 explanations_path=fx.build_explanations(m, status="VALIDE", validated_by="Fictive Owner"))
        assert w.explanations_status == "validated" and w.situations_status.startswith("refused") and w.situations == {}
        assert confirm(client, ["fx_green_lamps"])["premier_constat"]["presentation"]["entries"][0]["situation"] is None

    def test_draft_marked_validated_unmarked(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        st = entry(confirm(client, ["fx_green_lamps"]), "fx_green_lamps")["situation"]
        assert st["validation"] == "brouillon" and st["mention"] == vc.SITUATION_LABELS["draft"]
        wire(monkeypatch, grouped, situations_path=fx.build_situations(grouped, status="VALIDE", validated_by="Fictive Owner"))
        st = entry(confirm(client, ["fx_green_lamps"]), "fx_green_lamps")["situation"]
        assert st["validation"] == "validé" and st["mention"] is None

    def test_bound_to_catalogue_and_anchors_checked(self, grouped):
        c = ManifestNoticeRepository(grouped).catalogue
        path = fx.build_situations(grouped, entries={
            "fx_green_lamps": fx.situation("fonctionnement_normal", "lamps are glowing"),  # not verbatim
            "fx_red_fluid": fx.situation("fonctionnement_normal", fx.RED_MEANING),  # stop cited
            "fx_red_alarm_b": fx.situation("alerte_consigne_immediate", "a fictive service reminder"),  # no instruction
        })
        sit, rejected, _ = vc.load_situations(path, c, dev_trial=True)
        assert sit == {} and set(rejected) == {"fx_green_lamps", "fx_red_fluid", "fx_red_alarm_b"}
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["header"]["catalogue_content_sha256"] = "0" * 64
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(vc.ContentRejected):
            vc.load_situations(path, c, dev_trial=True)


class TestInformationToTakeIntoAccount:
    def test_state_without_failure_term_is_to_take_into_account(self, monkeypatch, grouped, client):
        w = with_situations(monkeypatch, grouped)
        assert not w.situations_rejected
        r = confirm(client, ["fx_amber_pressure"])
        st = entry(r, "fx_amber_pressure")["situation"]
        assert st["nature"] == "information_a_prendre_en_compte" and st["label"] == "À prendre en compte"
        # The instruction stays shown, with its exact citation and its condition.
        assert st["consignes"] == [{"consigne": {"text": fx.PRESSURE_CONSIGNE, "printed_page": "F-12", "pdf_page": 12},
                                    "condition": {"text": "In this case", "printed_page": "F-12", "pdf_page": 12},
                                    "label": "Consigne du constructeur", "action": False}]
        assert st["no_consigne"] is None
        # Never a permission to drive.
        text = json.dumps(r["premier_constat"]["presentation"], ensure_ascii=False).lower()
        assert not [f for f in vc.FORBIDDEN if f in text]

    def test_no_instruction_keeps_the_caution_sentence(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        st = entry(confirm(client, ["fx_blue_frost"]), "fx_blue_frost")["situation"]
        assert st["nature"] == "information_a_prendre_en_compte" and st["consignes"] == []
        assert st["no_consigne"] == "Aucune consigne n'est citée dans ce passage ; cela ne prouve pas l'absence de risque."

    def test_failure_term_is_a_reported_defect(self, monkeypatch, grouped, client):
        with_situations(monkeypatch, grouped)
        r = confirm(client, ["fx_amber_code_a"])
        (b,) = ambiguous(clarify(client, r, "message", "FICTIVE"))
        st = b["variants"][0]["entry"]["situation"]
        assert st["nature"] == "anomalie_defaut" and st["label"] == "Défaut signalé par la notice"
        assert "possible" not in vc.NATURE_LABELS["anomalie_defaut"]

    def test_defect_needs_its_own_failure_term(self, grouped):
        c = ManifestNoticeRepository(grouped).catalogue
        sit, rejected, _ = vc.load_situations(fx.build_situations(grouped, entries={
            # no failure term in the passage
            "fx_amber_pressure": fx.situation("anomalie_defaut", "the fictive pressure is lower than the recommended value"),
            # the term only in the shared designation
            "fx_amber_sensor": fx.situation("anomalie_defaut", "FICTIVE SENSOR FAULT", "manufacturer_designation"),
            # a failure term is never « à prendre en compte »
            "fx_amber_code_a": fx.situation("information_a_prendre_en_compte", "a fictive code fault"),
        }), c, dev_trial=True)
        assert sit == {} and set(rejected) == {"fx_amber_pressure", "fx_amber_sensor", "fx_amber_code_a"}
        assert vc.failure_term("a fictive sensor fault") and not vc.failure_term("no fictive fault is reported")


class TestStopNeverLowered:
    def test_stop_instruction_never_reclassified_lower(self, grouped):
        c = ManifestNoticeRepository(grouped).catalogue
        sit, rejected, _ = vc.load_situations(fx.build_situations(grouped, entries={
            "fx_red_fluid": fx.situation("information_a_prendre_en_compte", fx.RED_MEANING),
            "fx_red_steer_a": fx.situation("information_a_prendre_en_compte", "fictive assistance may be reduced"),
            "fx_red_alarm_a": fx.situation("anomalie_defaut", "a fictive pressure loss",
                                           consignes=[(fx.ALARM_STOP_PHRASE, "linked_warnings", None, None)]),
            "fx_amber_code_a": fx.situation("anomalie_defaut", "a fictive code fault",
                                            consignes=[(fx.STOP_PHRASE, "linked_warnings", None, None)]),
        }), c, dev_trial=True)
        assert sit == {} and set(rejected) == {"fx_red_fluid", "fx_red_steer_a", "fx_red_alarm_a", "fx_amber_code_a"}

    def test_restart_procedure_is_an_expected_action_level_unchanged(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        before = confirm(client, ["fx_red_steer_a"])["premier_constat"]["triage"]
        with_situations(monkeypatch, grouped)
        r = confirm(client, ["fx_red_steer_a"])
        (b,) = ambiguous(r)
        assert b["action_title"] == "Action attendue de votre part"
        assert b["actions"] == [{"only_for": "Indiqué seulement pour : FICTIVE STEERING FAILURE — Assistance fictive peut-être réduite",
                                 "entry_id": "fx_red_steer_a", "passages": [{
                                     "field": "Consigne", "text": fx.STEER_PROCEDURE, "printed_page": "F-13", "pdf_page": 13,
                                     "condition": {"text": fx.STEER_CONDITION, "printed_page": "F-13", "pdf_page": 13}}]}]
        # The procedure is no longer an urgent instruction; the other stop (same variant) stays urgent, whole.
        assert [(u["entry_id"], [p["text"] for p in u["passages"]]) for u in b["urgent"]] == [("fx_red_steer_a", [fx.STEER_MIXED])]
        assert fx.STEER_PROCEDURE not in json.dumps(b["urgent"], ensure_ascii=False)
        st = b["variants"][0]["entry"]["situation"]
        assert [(c["label"], c["action"]) for c in st["consignes"]] == [
            ("Action attendue de votre part", True), ("Consigne du constructeur", False)]
        # Internal level computed exactly as before; red screen still on offer, never automatic.
        triage = r["premier_constat"]["triage"]
        assert (triage["level"], triage["engine_level"]) == (before["level"], before["engine_level"])
        assert b["red_offer"] == vc.DRAFT_LABELS["red_offer"]
        assert not vc.is_restart_procedure(fx.STEER_MIXED) and vc.is_restart_procedure(fx.STEER_PROCEDURE)
