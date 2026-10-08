"""V1 parcours -> Premier Constat on a FICTIVE notice with FICTIVE prepared
content (classification, variant groups, explanations).

Covered: stop instruction kept in its documented scope with no added action;
the two « not established » labels; variant groups (question, « je ne sais
pas » -> fallback, no distinctive element -> fallback); explanation with an
invalid anchor rejected; notice content reused across parcours; R-5 never
lowers the SafetyEngine level.
"""
from __future__ import annotations

import builtins
import json
import socket
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from pgdr.application.part1_first_finding import APPROVED_BANNERS, severity_rank
from pgdr.enums import TriageLevel
from pgdr.errors import ConfigurationError

TOKEN = "v1-constat-token"
T2_V1 = ("Premier Constat Constructeur — à partir des voyants sélectionnés par vous dans le catalogue. "
         "Aucune reconnaissance sur photo.")
ADDED_ACTIONS = ("coupez le contact", "dépann", "reprenez pas la route", "ne roulez pas", "ne pas rouler",
                 "laissez le véhicule à l'arrêt", "switch off")


@pytest.fixture
def notice(tmp_path):
    return fx.build(tmp_path / "notice")


@pytest.fixture
def grouped(tmp_path):
    return fx.build(tmp_path / "grouped", with_groups=True)


@pytest.fixture
def client():
    return TestClient(web.app)


def wire(monkeypatch, manifest, *, dev_trial=True, **paths):
    w = v1.build_wiring(ManifestNoticeRepository(manifest), dev_trial=dev_trial, **paths)
    monkeypatch.setattr(v1, "_wiring", w)
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    return w


def open_parcours(client) -> str:
    r = client.post("/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}, json={
        "resolution_id": "VIR-FICTIVE", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}).json()
    pid = r["parcours_id"]
    client.post(f"/api/v1/parcours/{pid}/vir-seen")
    client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True})
    return pid


def confirm(client, ids, pid=None) -> dict:
    pid = pid or open_parcours(client)
    client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids})
    out = client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True})
    assert out.status_code == 200, out.text
    return {**out.json(), "pid": pid}


def entry(r, entry_id) -> dict:
    return next(e for e in r["premier_constat"]["presentation"]["entries"] if e["entry_id"] == entry_id)


def point(e, key) -> dict:
    return next(p for p in e["points"] if p["key"] == key)


class TestStopWithoutAddedAction:
    def test_no_classification_everything_unverified_with_warnings_shown(self, monkeypatch, notice, client):
        wire(monkeypatch, notice)
        r = confirm(client, ["fx_red_fluid"])
        p = r["premier_constat"]["presentation"]
        assert p["title"] == T2_V1 and p["end"] == APPROVED_BANNERS["T8"][0]
        e = entry(r, "fx_red_fluid")
        assert e["selected_label"] == "Voyant sélectionné par vous"
        assert all(pt["label"] == vc.LABELS["unverified"] and pt["quotes"] == [] for pt in e["points"])
        assert e["manufacturer_text"]["linked_warnings"] == [{"number": "7)", "text": fx.SHARED_WARNING}]
        assert vc.LABELS["absent"] not in json.dumps(r, ensure_ascii=False)

    def test_validated_stop_is_the_cited_phrase_only(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, findings_path=fx.build_findings(notice))
        r = confirm(client, ["fx_red_fluid"])
        e = entry(r, "fx_red_fluid")
        assert point(e, "stop") == {"key": "stop", "title": "Sécurité immédiate", "quotes": [fx.STOP_PHRASE], "label": None,
                                    "placement": "corps"}
        assert point(e, "professional")["quotes"] == [fx.CONTACT_PHRASE]
        # No derived instruction: vehicle use stays unverified (linked warnings present).
        assert point(e, "operability")["label"] == vc.LABELS["unverified"]
        text = json.dumps(r["premier_constat"]["presentation"], ensure_ascii=False).lower()
        assert not [a for a in ADDED_ACTIONS if a in text]

    def test_level_not_lower_than_cited_stop(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, findings_path=fx.build_findings(notice))
        for ids in (["fx_red_fluid"], ["fx_green_lamps", "fx_red_fluid"]):
            t = confirm(client, ids)["premier_constat"]["triage"]
            assert t["level"] == "emergency_stop" and t["r5_rows"] == ["R-5:stop_vehicle_engine_off:fx_red_fluid"]
            assert severity_rank(TriageLevel(t["level"])) >= severity_rank(TriageLevel(t["engine_level"]))

    def test_r5_never_lowers_the_safety_engine(self, monkeypatch, tmp_path, client):
        m = fx.build(tmp_path / "n")
        d = fx.load(m)
        d["entries"][0]["manufacturer_designation"] = "FICTIVE LOW BRAKE FLUID"
        fx.approve_manifest(d)
        fx.save(m, d)
        wire(monkeypatch, m)
        t = confirm(client, ["fx_red_fluid"])["premier_constat"]["triage"]
        assert (t["engine_level"], t["level"]) == ("do_not_drive", "do_not_drive")


class TestTwoLabels:
    def test_exact_wording(self):
        assert vc.LABELS["absent"] == "Cette information n'est pas établie dans les données disponibles."
        assert vc.LABELS["unverified"] == ("Point pas encore vérifié par PGDR. "
                                           "Lisez la consigne du constructeur ci-dessous.")

    def test_absent_only_when_validated_and_covered_without_warnings(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, findings_path=fx.build_findings(notice))
        r = confirm(client, ["fx_amber_sensor", "fx_green_lamps"])
        green, amber = entry(r, "fx_green_lamps"), entry(r, "fx_amber_sensor")
        assert {pt["label"] for pt in green["points"]} == {vc.LABELS["absent"]}
        # Linked warning present: never declared absent.
        assert {pt["label"] for pt in amber["points"]} == {vc.LABELS["unverified"]}

    def test_not_covered_means_unverified(self, monkeypatch, notice, client):
        path = fx.build_findings(notice)
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["header"]["covered_entry_ids"] = ["fx_red_fluid"]
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        wire(monkeypatch, notice, findings_path=path)
        green = entry(confirm(client, ["fx_green_lamps"]), "fx_green_lamps")
        assert {pt["label"] for pt in green["points"]} == {vc.LABELS["unverified"]}

    def test_stop_word_in_passage_never_absent(self, monkeypatch, tmp_path, client):
        m = fx.build(tmp_path / "n")
        d = fx.load(m)
        d["entries"][2]["documented_meaning"] = fx.GREEN_MEANING + " Stop the fictive car if it blinks."
        fx.approve_manifest(d)
        fx.save(m, d)
        wire(monkeypatch, m, findings_path=fx.build_findings(m))
        green = entry(confirm(client, ["fx_green_lamps"]), "fx_green_lamps")
        assert point(green, "stop")["label"] == vc.LABELS["unverified"]
        assert point(green, "professional")["label"] == vc.LABELS["absent"]

    def test_draft_classification_never_used(self, notice):
        with pytest.raises(ConfigurationError):
            v1.load_v1_findings(fx.build_findings(notice, status="BROUILLON_NON_VALIDE"), ManifestNoticeRepository(notice))


def ambiguous(r) -> list[dict]:
    return r["premier_constat"]["presentation"]["ambiguous"]


class TestT2:
    def test_v1_title_exact(self, monkeypatch, notice, client):
        wire(monkeypatch, notice)
        assert confirm(client, ["fx_green_lamps"])["premier_constat"]["presentation"]["title"] == T2_V1
        assert vc.T2_V1 == T2_V1

    def test_photo_parcours_t2_unchanged(self, tmp_path):
        original = ("Premier Constat Constructeur",
                    "Ce constat reprend ce que la notice du constructeur indique pour le voyant identifié sur votre photo. "
                    "Lorsque la notice donne une consigne — par exemple arrêter le véhicule ou couper le contact — cette "
                    "consigne s'applique : suivez-la.",
                    "Ce constat ne recherche pas la cause mécanique de la panne et ne remplace pas l'examen du véhicule "
                    "par un professionnel.")
        assert APPROVED_BANNERS["T2"] == original
        # The photo parcours presenter renders exactly that original T2, never the V1 title.
        from pgdr.application.part1_first_finding import build_manufacturer_first_finding
        repo = ManifestNoticeRepository(fx.build(tmp_path / "n"))
        e = repo.entries_for_document("FICTIVE-NOTICE-001")[0]
        finding = build_manufacturer_first_finding([(e, "visual_provider_match")], mapping={})
        assert web.present_first_finding(finding)["banner"] == list(original)
        assert T2_V1 not in web._PHOTO_HTML and T2_V1 not in json.dumps(web.present_first_finding(finding), ensure_ascii=False)


class TestVariantGroups:
    def test_identical_files_grouped_automatically(self, grouped):
        c = ManifestNoticeRepository(grouped).catalogue
        assert vc.auto_groups(c) == [("fx_red_belt_fixed", "fx_red_belt_flashing"), ("fx_amber_twin_a", "fx_amber_twin_b"),
                                     ("fx_blue_mode_x", "fx_blue_mode_y"), ("fx_red_alarm_a", "fx_red_alarm_b"),
                                     ("fx_amber_code_a", "fx_amber_code_b"), ("fx_red_steer_a", "fx_red_steer_b"),
                                     ("fx_amber_tyre_low", "fx_amber_tyre_fault"),
                                     ("fx_red_pb_failure", "fx_red_pb_fluid", "fx_red_pb_applied"),
                                     ("fx_green_side_lights", "fx_green_follow_me")]

    def test_question_with_documented_elements_and_sources(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        r = confirm(client, ["fx_red_belt_fixed"])
        assert r["phase"] == "clarification"
        (q,) = r["questions"]
        assert [(c["entry_id"], [e["value"] for e in c["elements"]]) for c in q["choices"]] == [
            ("fx_red_belt_fixed", ["fixe"]), ("fx_red_belt_flashing", ["clignotant"])]
        assert q["choices"][1]["source"] == {"designation": "FICTIVE BELT", "page_reference": "F-4", "pdf_page": 4,
                                             "text": "The fictive belt light flashes."}
        out = client.post(f"/api/v1/parcours/{r['pid']}/clarify", json={"group": q["group"], "answer": "fx_red_belt_flashing"}).json()
        # A choice resolves the group: only that variant is restituted.
        assert out["phase"] == "restitution" and ambiguous(out) == []
        assert [s["entry_id"] for s in out["sections"]] == ["fx_red_belt_flashing"]
        assert [e["entry_id"] for e in out["premier_constat"]["presentation"]["entries"]] == ["fx_red_belt_flashing"]

    def test_dont_know_or_none_shows_the_ambiguity_never_a_choice(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        for answer in ("dont_know", "none"):
            r = confirm(client, ["fx_red_belt_flashing"])
            out = client.post(f"/api/v1/parcours/{r['pid']}/clarify", json={"group": r["questions"][0]["group"], "answer": answer}).json()
            assert out["phase"] == "restitution" and out["premier_constat"]["presentation"]["entries"] == []
            (b,) = ambiguous(out)
            assert [v["entry"]["entry_id"] for v in b["variants"]] == ["fx_red_belt_fixed", "fx_red_belt_flashing"]
            # Red belts, no stop documented: no red screen, no urgent instruction from the ambiguity.
            assert b["red_offer"] is None and b["urgent"] == []
            assert out["premier_constat"]["presentation"]["red_screen"] is None

    def test_indistinguishable_with_common_information(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        r = confirm(client, ["fx_amber_twin_b"])
        assert r["phase"] == "restitution" and "questions" not in r
        (b,) = ambiguous(r)
        assert b["limit"] == vc.LIMIT_V1 and b["draft_texts"] == vc.DRAFT_LABELS["draft_texts"]
        assert [c["text"] for c in b["common"]] == ["FICTIVE TWIN", fx.TWIN_COMMON] and b["no_common"] is None
        assert b["common"][1]["sources"] == [
            {"entry_id": "fx_amber_twin_a", "manual_order": 6, "field": "Texte de la notice", "printed_page": "F-5", "pdf_page": 5},
            {"entry_id": "fx_amber_twin_b", "manual_order": 7, "field": "Texte de la notice", "printed_page": "F-5", "pdf_page": 5}]
        # Each variant: its own complete passage, under « Indiqué seulement pour ».
        a_, b_ = b["variants"]
        assert a_["only_for"] == "Indiqué seulement pour : FICTIVE TWIN"
        assert a_["entry"]["manufacturer_text"]["documented_meaning"] == fx.TWIN_A
        assert b_["entry"]["manufacturer_text"]["documented_meaning"] == fx.TWIN_B
        assert a_["condition"]["state"] == vc.DRAFT_LABELS["not_documented"]

    def test_indistinguishable_without_common_information(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        (b,) = ambiguous(confirm(client, ["fx_blue_mode_x"]))
        assert b["common"] == [] and b["no_common"] == "Aucune information commune n'est citée par la notice pour ces voyants."

    def test_entirely_informative_group_no_stop_no_fallback(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        for ids in (["fx_blue_mode_y"], ["fx_amber_twin_a"]):
            r = confirm(client, ids)
            assert r["phase"] == "restitution"
            (b,) = ambiguous(r)
            assert b["red_offer"] is None and r["premier_constat"]["presentation"]["red_screen"] is None
            assert r["premier_constat"]["triage"]["level"] != "emergency_stop"
            assert not [rr for rr in r["premier_constat"]["triage"]["r5_rows"]]

    def test_variant_with_stop_kept_under_its_condition_red_offered_highest_level(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped, findings_path=fx.build_findings(grouped))
        r = confirm(client, ["fx_red_alarm_b"])
        (b,) = ambiguous(r)
        a_, b_ = b["variants"]
        assert a_["entry"]["manufacturer_text"]["linked_warnings"] == [{"number": "9)", "text": fx.ALARM_STOP}]
        assert next(pt for pt in a_["entry"]["points"] if pt["key"] == "stop")["quotes"] == [fx.ALARM_STOP_PHRASE]
        assert b_["entry"]["manufacturer_text"]["linked_warnings"] == []
        assert fx.ALARM_STOP not in [c["text"] for c in b["common"]]  # never presented as valid for all
        assert b["red_offer"] and r["premier_constat"]["presentation"]["red_screen"]["key"] == "red_or_uncertain"
        t = r["premier_constat"]["triage"]
        # Highest of its variants (alarm A's cited stop), even though B was the image clicked.
        assert t["level"] == "emergency_stop" and t["r5_rows"] == ["R-5:stop_vehicle_engine_off:fx_red_alarm_a"]
        text = json.dumps(r["premier_constat"]["presentation"], ensure_ascii=False).lower()
        assert not [a for a in ADDED_ACTIONS if a in text]

    def test_level_never_comes_from_ambiguity_alone(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        t_group = confirm(client, ["fx_blue_mode_x"])["premier_constat"]["triage"]
        t_alone = v1.premier_constat(v1.Parcours(vehicle={}), ["fx_blue_mode_x", "fx_blue_mode_y"])["triage"]
        assert t_group["level"] == t_alone["level"] and t_group["triggered_rules"] == t_alone["triggered_rules"]

    def test_resolved_light_keeps_its_constat_beside_an_ambiguous_group(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped, explanations_path=fx.build_explanations(grouped))
        r = confirm(client, ["fx_red_fluid", "fx_amber_twin_a"])
        p = r["premier_constat"]["presentation"]
        assert [e["entry_id"] for e in p["entries"]] == ["fx_red_fluid"]
        assert p["entries"][0]["explanation"]["mention"] == "Explication en brouillon, non validée"
        assert [s["entry_id"] for s in r["sections"]] == ["fx_red_fluid"]
        (b,) = ambiguous(r)
        assert [v["entry"]["entry_id"] for v in b["variants"]] == ["fx_amber_twin_a", "fx_amber_twin_b"]

    def test_candidate_group_draft_only_in_dev_trial_and_marked(self, monkeypatch, grouped, client):
        w = wire(monkeypatch, grouped, groups_path=fx.build_groups(grouped, status="BROUILLON_NON_VALIDE"))
        assert w.groups_status == "draft_dev_trial"
        r = confirm(client, ["fx_green_look_a"])
        assert r["phase"] == "clarification"
        out = client.post(f"/api/v1/parcours/{r['pid']}/clarify", json={"group": r["questions"][0]["group"], "answer": "dont_know"}).json()
        assert ambiguous(out)[0]["group_draft"] == "Groupe en brouillon, non validé"
        # Outside the development trial a draft group is not used at all.
        m = fx.build(grouped.parent / "prod", with_groups=True, applicability_established=True)
        w = wire(monkeypatch, m, dev_trial=False, groups_path=fx.build_groups(m, status="BROUILLON_NON_VALIDE"))
        assert w.groups_status.startswith("refused")
        assert confirm(client, ["fx_green_look_a"])["phase"] == "restitution"

    def test_validated_candidate_group_unmarked(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped, groups_path=fx.build_groups(grouped))
        r = confirm(client, ["fx_green_look_a"])
        assert [[e["value"] for e in c["elements"]] for c in r["questions"][0]["choices"]] == [["LOOK A"], ["LOOK B"]]
        out = client.post(f"/api/v1/parcours/{r['pid']}/clarify", json={"group": r["questions"][0]["group"], "answer": "none"}).json()
        assert ambiguous(out)[0]["group_draft"] is None

    def test_never_chosen_for_the_driver(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        r = confirm(client, ["fx_red_belt_fixed"])
        g = r["questions"][0]["group"]
        assert client.post(f"/api/v1/parcours/{r['pid']}/clarify", json={"group": g, "answer": "fx_green_lamps"}).status_code == 400
        assert client.post(f"/api/v1/parcours/{r['pid']}/clarify", json={"group": g + 99, "answer": "none"}).status_code == 409

    def test_return_resets_clarification_keeps_selection(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped)
        r = confirm(client, ["fx_red_belt_fixed", "fx_green_lamps"])
        back = client.post(f"/api/v1/parcours/{r['pid']}/return").json()
        assert back["phase"] == "catalogue" and back["selection"] == ["fx_green_lamps", "fx_red_belt_fixed"]


class TestLevelOrigin:
    def test_documented_passage_sets_the_level(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, findings_path=fx.build_findings(notice))
        o = confirm(client, ["fx_red_fluid"])["premier_constat"]["triage"]["origin"]
        assert {"origin": "passage documenté", "rule": "R-5:stop_vehicle_engine_off:fx_red_fluid",
                "entry_id": "fx_red_fluid", "citation": fx.STOP_PHRASE, "sets_level": True} in o

    def test_pgdr_rule_sets_the_level(self, monkeypatch, tmp_path, client):
        m = fx.build(tmp_path / "n")
        d = fx.load(m)
        d["entries"][0]["manufacturer_designation"] = "FICTIVE LOW BRAKE FLUID"
        fx.approve_manifest(d)
        fx.save(m, d)
        wire(monkeypatch, m)
        o = confirm(client, ["fx_red_fluid"])["premier_constat"]["triage"]["origin"]
        assert o == [{"origin": "règle PGDR déclenchée", "rule": "PGDR-SAF-012", "name": "Voyant frein rouge", "sets_level": True}]

    def test_default_rule_when_nothing_fires(self, monkeypatch, notice, client):
        wire(monkeypatch, notice)
        o = confirm(client, ["fx_green_lamps"])["premier_constat"]["triage"]["origin"]
        assert o == [{"origin": "règle PGDR par défaut (aucun signal)", "rule": "default", "name": None, "sets_level": True}]

    def test_level_and_origin_never_in_the_page(self):
        js = v1.V1_HTML
        for word in ("triage", "origin", "engine_level", "r5_rows"):
            assert word not in js


class TestExplanations:
    def test_draft_shown_in_dev_trial_with_mention(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, explanations_path=fx.build_explanations(notice))
        e = entry(confirm(client, ["fx_red_fluid"]), "fx_red_fluid")
        assert e["explanation"]["mention"] == "Explication en brouillon, non validée"
        assert [p["title"] for p in e["explanation"]["parts"]] == [
            "Ce que la notice indique", "Quoi faire maintenant", "Ce qui reste inconnu"]
        assert e["explanation"]["parts"][1]["sentences"][0]["citation"] == fx.STOP_PHRASE

    def test_draft_never_shown_outside_dev_trial(self, monkeypatch, tmp_path, client):
        m = fx.build(tmp_path / "n", applicability_established=True)
        w = wire(monkeypatch, m, dev_trial=False, explanations_path=fx.build_explanations(m))
        assert w.explanations == {} and w.explanations_status.startswith("refused")
        assert entry(confirm(client, ["fx_red_fluid"]), "fx_red_fluid")["explanation"] is None

    def test_validated_needs_name_and_catalogue_binding(self, monkeypatch, tmp_path, client):
        m = fx.build(tmp_path / "n", applicability_established=True)
        wire(monkeypatch, m, dev_trial=False, explanations_path=fx.build_explanations(m, status="VALIDE", validated_by="Fictive Owner"))
        assert entry(confirm(client, ["fx_red_fluid"]), "fx_red_fluid")["explanation"]["mention"] is None
        unnamed = fx.build_explanations(m, status="VALIDE")
        with pytest.raises(vc.ContentRejected):
            vc.load_explanations(unnamed, ManifestNoticeRepository(m).catalogue, dev_trial=False)
        other = fx.build_explanations(m, status="VALIDE", validated_by="Fictive Owner")
        doc = yaml.safe_load(other.read_text(encoding="utf-8"))
        doc["header"]["catalogue_content_sha256"] = "0" * 64
        other.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        with pytest.raises(vc.ContentRejected):
            vc.load_explanations(other, ManifestNoticeRepository(m).catalogue, dev_trial=True)

    def test_invalid_anchor_rejects_only_that_entry(self, monkeypatch, notice, client):
        bad = json.loads(json.dumps(fx.EXPLANATION_RED))
        bad["maintenant"][0]["source_phrase"] = "stop the fictive vehicle at once"
        w = wire(monkeypatch, notice, explanations_path=fx.build_explanations(
            notice, entries={"fx_red_fluid": bad, "fx_green_lamps": fx.EXPLANATION_GREEN}))
        assert "fx_red_fluid" in w.explanations_rejected and "fx_green_lamps" in w.explanations
        r = confirm(client, ["fx_red_fluid", "fx_green_lamps"])
        red = entry(r, "fx_red_fluid")
        assert red["explanation"] is None
        assert {pt["label"] for pt in red["points"]} == {vc.LABELS["unverified"]}
        assert red["manufacturer_text"]["documented_meaning"] == fx.RED_MEANING
        assert entry(r, "fx_green_lamps")["explanation"] is not None

    def test_permission_wording_rejected(self, notice):
        bad = json.loads(json.dumps(fx.EXPLANATION_GREEN))
        bad["maintenant"][0]["texte"] = "Vous pouvez rouler normalement."
        path = fx.build_explanations(notice, entries={"fx_green_lamps": bad})
        out, rejected, _ = vc.load_explanations(path, ManifestNoticeRepository(notice).catalogue, dev_trial=True)
        assert out == {} and "fx_green_lamps" in rejected


class TestReuse:
    def test_second_parcours_reuses_notice_without_any_read_or_fetch(self, monkeypatch, notice, client):
        monkeypatch.setattr(v1, "_wiring", None)
        monkeypatch.setattr(v1, "_parcours", {})
        monkeypatch.setenv("PGDR_V1_MANIFEST", str(notice))
        monkeypatch.setenv("PGDR_V1_DEV_TRIAL", "1")
        monkeypatch.setenv("PGDR_V1_EXPLANATIONS", str(fx.build_explanations(notice)))
        monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
        first = confirm(client, ["fx_red_fluid"])
        client.post(f"/api/v1/parcours/{first['pid']}/no-match", json={"reason": "dont_know", "entry_ids": ["fx_red_fluid"]})
        client.post(f"/api/v1/parcours/{first['pid']}/colour", json={"colour": "rouge"})

        reads = []
        real_open, real_rb, real_rt = builtins.open, Path.read_bytes, Path.read_text
        package = str(notice.parent)

        def spy(name):
            def wrapper(self_or_file, *a, **k):
                target = str(self_or_file)
                if target.startswith(package):
                    reads.append((name, target))
                return {"open": real_open, "read_bytes": real_rb, "read_text": real_rt}[name](self_or_file, *a, **k)
            return wrapper

        monkeypatch.setattr(builtins, "open", spy("open"))
        monkeypatch.setattr(Path, "read_bytes", spy("read_bytes"))
        monkeypatch.setattr(Path, "read_text", spy("read_text"))
        monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("external fetch"))

        pid2 = open_parcours(client)
        state = client.get(f"/api/v1/parcours/{pid2}").json()
        assert (state["selection"], state["colour"], state["confirmed"]) == ([], None, False)  # nothing of the other driver
        cat = client.get(f"/api/v1/parcours/{pid2}/catalogue").json()
        assert cat["selection"] == [] and cat["colour"] is None
        for e in cat["entries"]:
            assert client.get(e["image"]).status_code == 200
        second = confirm(client, ["fx_red_fluid"], pid=pid2)
        assert entry(second, "fx_red_fluid")["explanation"] == entry(first, "fx_red_fluid")["explanation"]
        assert reads == []
        assert v1._parcours[first["pid"]].colour == "rouge" and v1._parcours[pid2].colour is None
        # The spy is effective: a real reload of the notice IS seen.
        ManifestNoticeRepository(notice)
        assert any(target.endswith("manifest.yaml") for _, target in reads)
