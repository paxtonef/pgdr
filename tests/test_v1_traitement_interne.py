"""V1 internal processing on a FICTIVE notice: what reaches the unchanged
SafetyEngine and R-5, and what the result carries.

Covered: temporary stop + wait + restart procedure; real immediate stop;
conditional stop with its condition confirmed, excluded and unknown; group
mixing a parking brake failure and a low brake fluid; restoring the pressure
kept apart from the conditional stop; « stop lights » without any stop;
citations, conditions and pages kept up to the result; the colour fallback
for an unidentified red light. Assertions are on internal data and results.
"""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from pgdr.application.part1_first_finding import entry_fingerprint
from test_v1_premier_constat import confirm, open_parcours, wire


@pytest.fixture
def grouped(tmp_path):
    return fx.build(tmp_path / "grouped", with_groups=True)


@pytest.fixture
def client():
    return TestClient(web.app)


def situations(monkeypatch, manifest, **kw):
    return wire(monkeypatch, manifest, situations_path=fx.build_situations(manifest), **kw)


def internal(r) -> dict:
    return r["premier_constat"]["internal"]


def consignes(r, entry_id) -> list[dict]:
    return [c for c in internal(r)["consignes"] if c["entry_id"] == entry_id]


def triage(r) -> dict:
    return r["premier_constat"]["triage"]


def answer(client, r, key, value) -> dict:
    out = client.post(f"/api/v1/parcours/{r['pid']}/condition", json={"key": key, "answer": value})
    assert out.status_code == 200, out.text
    return {**out.json(), "pid": r["pid"]}


def findings_file(manifest, records) -> str:
    """A FICTIVE validated Part 1 classification with the given records (tests only)."""
    repo = ManifestNoticeRepository(manifest)
    live = {e.entry_id: e for e in repo.entries_for_document("FICTIVE-NOTICE-001")}
    doc = {"header": {"status": "VALIDE", "approved_by": "Fictive Owner", "approval_date": "2026-10-08",
                      "nature": "FICTIVE", "catalogue_content_sha256": repo.catalogue.content_sha256,
                      "covered_entry_ids": [e.entry_id for e in repo.catalogue.entries]},
           "rules": {r: "fictive" for r in ("R-1", "R-2", "R-3", "R-4", "R-5")},
           "entries": [{"document_id": "FICTIVE-NOTICE-001", "entry_id": x, "fingerprint": entry_fingerprint(live[x]), **rec}
                       for x, rec in records.items()]}
    path = manifest.parent / "classement_test.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def stop_item(field, phrase):
    return {"stop_vehicle_engine_off": {"value": "required", "basis": "documented", "source_field": field, "source_phrase": phrase}}


class TestRestartProcedure:
    def test_procedure_alone_never_an_emergency(self, monkeypatch, grouped, client):
        situations(monkeypatch, grouped)
        r = confirm(client, ["fx_red_steer_a"])
        kinds = [(c["kind"], c["transmitted"]) for c in consignes(r, "fx_red_steer_a")]
        assert kinds == [("restart_procedure", None), ("conditional_stop", None)]
        assert triage(r)["level"] not in ("emergency_stop", "do_not_drive") and triage(r)["r5_rows"] == []
        # Recorded in stop_conditions by the classification: cited, not an immediate stop.
        assert not vc.immediate_stop_item(ManifestNoticeRepository(grouped).catalogue.entry("fx_red_steer_a"), fx.STEER_PROCEDURE)
        situations(monkeypatch, grouped, findings_path=findings_file(grouped, {"fx_red_steer_a": {
            "items": {}, "stop_conditions": [{"source_field": "documented_instruction", "source_phrase": fx.STEER_PROCEDURE}]}}))
        r = confirm(client, ["fx_red_steer_a"])
        assert triage(r)["r5_rows"] == [] and triage(r)["level"] == "monitor_and_document"
        assert internal(r)["limits"][0]["key"] == "fx_red_steer_a#1"  # the unknown conditional stop, listed

    def test_procedure_recorded_as_immediate_stop_is_reported_not_altered(self, monkeypatch, grouped, client):
        situations(monkeypatch, grouped, findings_path=findings_file(grouped, {"fx_red_steer_a": {
            "items": stop_item("documented_instruction", "stop the fictive vehicle, stop the fictive motor for about 20 seconds")}}))
        r = confirm(client, ["fx_red_steer_a"])
        # R-5 is unchanged and receives the validated item: the level is NOT forced down.
        assert triage(r)["level"] == "emergency_stop" and triage(r)["r5_rows"] == ["R-5:stop_vehicle_engine_off:fx_red_steer_a"]
        assert any("procédure d'arrêt temporaire" in x["limit"] for x in internal(r)["limits"])
        assert consignes(r, "fx_red_steer_a")[0]["transmitted"] == "R-5 stop_vehicle_engine_off (classement validé)"


class TestImmediateStop:
    def test_real_immediate_stop_reaches_r5(self, monkeypatch, grouped, client):
        situations(monkeypatch, grouped, findings_path=fx.build_findings(grouped))
        r = confirm(client, ["fx_red_alarm_a"])
        assert triage(r)["level"] == "emergency_stop" and "R-5:stop_vehicle_engine_off:fx_red_alarm_a" in triage(r)["r5_rows"]
        (c,) = consignes(r, "fx_red_alarm_a")
        assert c["kind"] == "immediate_stop" and c["transmitted"] == "R-5 stop_vehicle_engine_off (classement validé)"
        assert c["citation"]["text"] == fx.ALARM_STOP and c["citation"]["printed_page"] == "F-10"
        assert c["condition"]["text"] == "If the fictive alarm light comes on while driving" and c["condition_status"] == "stated"


class TestConditionalStop:
    KEY = "fx_amber_tyre_low#1"

    def _start(self, monkeypatch, grouped, client):
        situations(monkeypatch, grouped)
        r = confirm(client, ["fx_amber_tyre_low"])
        assert r["phase"] == "restitution"
        return r

    def test_unknown_kept_as_unknown(self, monkeypatch, grouped, client):
        r = self._start(monkeypatch, grouped, client)
        c = next(c for c in consignes(r, "fx_amber_tyre_low") if c["key"] == self.KEY)
        assert (c["kind"], c["condition_status"], c["transmitted"]) == ("conditional_stop", "unknown", None)
        assert self.KEY in [x["key"] for x in internal(r)["limits"]]
        assert triage(r)["r5_rows"] == []
        # Neither fulfilled nor excluded: still shown under its exact condition.
        (b,) = r["premier_constat"]["presentation"]["ambiguous"]
        assert [p["answer"] for x in b["conditionals"] for p in x["passages"]] == ["unknown", "unknown"]

    def test_confirmed_taken_into_account(self, monkeypatch, grouped, client):
        r = self._start(monkeypatch, grouped, client)
        before = triage(r)
        r = answer(client, r, self.KEY, "confirmed")
        c = next(c for c in consignes(r, "fx_amber_tyre_low") if c["key"] == self.KEY)
        assert c["condition_status"] == "confirmed" and c["transmitted"].startswith("R-5 stop_vehicle_engine_off")
        assert triage(r)["r5_rows"] == ["R-5:stop_vehicle_engine_off:fx_amber_tyre_low"]
        assert triage(r)["level"] == "emergency_stop" != before["level"]
        assert triage(r)["engine_level"] == before["engine_level"]  # SafetyEngine untouched
        origin = next(o for o in triage(r)["origin"] if o["origin"] == "passage documenté")
        assert origin["citation"] == "stop the fictive car"
        # The other variant's own conditional stop keeps its own (unknown) answer.
        other = consignes(r, "fx_amber_tyre_fault")[0]
        assert other["condition_status"] == "unknown" and other["transmitted"] is None

    def test_excluded_not_transmitted_but_kept(self, monkeypatch, grouped, client):
        r = self._start(monkeypatch, grouped, client)
        r = answer(client, r, self.KEY, "excluded")
        c = next(c for c in consignes(r, "fx_amber_tyre_low") if c["key"] == self.KEY)
        assert (c["condition_status"], c["transmitted"]) == ("excluded", None)
        assert self.KEY not in [x["key"] for x in internal(r)["limits"]]
        (b,) = r["premier_constat"]["presentation"]["ambiguous"]
        kept = [p for x in b["conditionals"] for p in x["passages"] if p["key"] == self.KEY]
        assert kept and kept[0]["text"] == fx.TYRE_STOP and kept[0]["answer"] == "excluded"

    def test_answer_refused_where_no_condition(self, monkeypatch, grouped, client):
        r = self._start(monkeypatch, grouped, client)
        out = client.post(f"/api/v1/parcours/{r['pid']}/condition", json={"key": "fx_amber_tyre_low#0", "answer": "confirmed"})
        assert out.status_code == 409  # « restore the pressure » is an action, not a condition to answer

    def test_restore_pressure_separate_from_conditional_stop(self, monkeypatch, grouped, client):
        r = self._start(monkeypatch, grouped, client)
        kinds = [(c["kind"], c["citation"]["text"]) for c in consignes(r, "fx_amber_tyre_low")]
        assert kinds == [("expected_action", "In this case restore the fictive tyre pressure."), ("conditional_stop", fx.TYRE_STOP)]
        tyre = consignes(r, "fx_amber_tyre_low")[1]
        # Citation, condition and pages kept up to the result.
        assert tyre["citation"] | {} == {"text": fx.TYRE_STOP, "source_field": "linked_warnings", "source_phrase": "stop the fictive car",
                                         "printed_page": "F-17", "pdf_page": 17}
        assert tyre["condition"] == {"text": fx.TYRE_CONDITION, "source_field": "linked_warnings", "printed_page": "F-17", "pdf_page": 17}


class TestParkingBrakeAndFluid:
    def test_group_keeps_critical_possibility_without_confirming_a_defect(self, monkeypatch, grouped, client):
        situations(monkeypatch, grouped, findings_path=findings_file(grouped, {"fx_red_pb_fluid": {
            "items": stop_item("linked_warnings", "stop the fictive vehicle immediately")}}))
        r = confirm(client, ["fx_red_pb_failure"])
        (b,) = r["premier_constat"]["presentation"]["ambiguous"]
        assert {x["entry_id"]: x["status"] for x in internal(r)["variants"]} == {
            "fx_red_pb_failure": "possible", "fx_red_pb_fluid": "possible", "fx_red_pb_applied": "possible"}
        # The stop belongs to the fluid variant only, with its condition; never to the parking brake.
        assert [(u["entry_id"], [p["text"] for p in u["passages"]]) for u in b["urgent"]] == [("fx_red_pb_fluid", [fx.PB_FLUID_WARNING])]
        assert [c["kind"] for c in consignes(r, "fx_red_pb_failure")] == ["instruction"]
        (stop,) = consignes(r, "fx_red_pb_fluid")
        assert stop["kind"] == "immediate_stop" and stop["condition"]["text"] == "If the fictive light comes on while driving"
        # Critical possibility kept internally (highest of the variants), not concluded absent.
        assert triage(r)["level"] == "emergency_stop" and triage(r)["r5_rows"] == ["R-5:stop_vehicle_engine_off:fx_red_pb_fluid"]
        assert b["red_offer"] == vc.DRAFT_LABELS["red_offer"]

    def test_unresolved_variant_never_transmitted_as_selection(self, monkeypatch, grouped):
        situations(monkeypatch, grouped)
        c = ManifestNoticeRepository(grouped).catalogue
        groups = v1.get_wiring().groups
        gi = next(i for i, g in enumerate(groups) if "fx_red_pb_fluid" in g)
        r = v1.premier_constat(v1.Parcours(vehicle={}), [], [gi])
        assert {v["status"] for v in r["internal"]["variants"]} == {"possible"}
        r = v1.premier_constat(v1.Parcours(vehicle={}), ["fx_red_pb_failure"])
        assert r["internal"]["variants"] == [{"entry_id": "fx_red_pb_failure", "status": "selected"}]
        assert c.entry("fx_red_pb_failure").designation == fx.PB_TITLE

    def test_engine_limit_brake_keyword_on_shared_designation(self, monkeypatch, grouped):
        """REPRODUCIBLE LIMIT (SafetyEngine unchanged): PGDR-SAF-012 matches « brake » in the shared
        designation with a red colour, so a variant documented as an operating indication (parking
        brake applied) alone gets do_not_drive. Not corrected here; reported."""
        situations(monkeypatch, grouped)
        r = v1.premier_constat(v1.Parcours(vehicle={}), ["fx_red_pb_applied"])
        assert v1.get_wiring().situations["fx_red_pb_applied"].nature == "fonctionnement_normal"
        assert r["triage"]["engine_level"] == "do_not_drive" and "PGDR-SAF-012" in r["triage"]["triggered_rules"]


class TestNoStopAndFallback:
    def test_stop_lights_no_stop_internally(self, monkeypatch, grouped, client):
        situations(monkeypatch, grouped)
        r = confirm(client, ["fx_amber_lamp_fault"])
        assert consignes(r, "fx_amber_lamp_fault") == [] and triage(r)["r5_rows"] == [] and internal(r)["limits"] == []

    def test_unknown_red_light_fallback_kept(self, monkeypatch, grouped, client):
        situations(monkeypatch, grouped)
        pid = open_parcours(client)
        client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": "dont_know", "entry_ids": []})
        s = client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "incertain"}).json()["screen"]
        assert s["key"] == "red_or_uncertain" and s["heading"].startswith("Arrêtez-vous en sécurité")
