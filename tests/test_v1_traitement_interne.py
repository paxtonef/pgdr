"""V1 safety processing on a FICTIVE notice: what reaches the SafetyEngine and
R-5, the rules applied and what the result carries (internal data, not titles).

Corrected behaviours (the defects were first reproduced, then turned into
these tests):
  1. R-5 conditions of application: confirmed / excluded / unknown, the last
     one an explicit uncertainty (safety_status), distinct from an ordinary
     situation; no answer == unknown.
  2. PGDR-SAF-012: no « do_not_drive » for an established ordinary
     indication from the shared designation keyword; unchanged otherwise.
  3. A reviewed manufacturer stop instruction reaches R-5 without any
     presentation classification; an unvalidated interpretation of its
     condition stays uncertain.
Plus: restart procedure, other alerts, multiple selection, colour fallback.
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

TYRE_KEY = vc.stop_key("fx_amber_tyre_low", fx.TYRE_STOP)
FLUID_KEY = vc.stop_key("fx_red_pb_fluid", fx.PB_FLUID_WARNING)


@pytest.fixture
def grouped(tmp_path):
    return fx.build(tmp_path / "grouped", with_groups=True)


@pytest.fixture
def client():
    return TestClient(web.app)


def draft(monkeypatch, manifest, **kw):
    return wire(monkeypatch, manifest, situations_path=fx.build_situations(manifest), **kw)


def validated(monkeypatch, manifest, *, consignes=True, **kw):
    return wire(monkeypatch, manifest, situations_path=fx.build_situations(
        manifest, status="VALIDE", validated_by="Fictive Owner", consignes_validated_by="Fictive Owner" if consignes else ""), **kw)


def constat(ids, ambiguous=(), conditions=None) -> dict:
    return v1.premier_constat(v1.Parcours(vehicle={}, conditions=dict(conditions or {})), list(ids), list(ambiguous))


def group_of(x) -> int:
    return next(i for i, g in enumerate(v1.get_wiring().groups) if x in g)


def stops(r, entry_id) -> list[dict]:
    return [s for s in r["internal"]["stops"] if s["entry_id"] == entry_id]


def answer(client, r, key, value) -> dict:
    out = client.post(f"/api/v1/parcours/{r['pid']}/condition", json={"key": key, "answer": value})
    assert out.status_code == 200, out.text
    return {**out.json(), "pid": r["pid"]}


def findings_file(manifest, records) -> str:
    """A FICTIVE validated Part 1 classification (tests only)."""
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


# --- 1. R-5 conditions of application -------------------------------------------------------------

class TestConditionOfApplication:
    def test_unknown_is_an_explicit_uncertainty_distinct_from_ordinary(self, monkeypatch, grouped):
        draft(monkeypatch, grouped)
        t = constat(["fx_amber_tyre_low"])["triage"]
        ordinary = constat(["fx_green_lamps"])["triage"]
        assert ordinary["safety_status"] == "established" and ordinary["safety_uncertainties"] == []
        assert t["safety_status"] == "uncertain" and t["level"] == ordinary["level"]  # level not forced
        (u,) = [u for u in t["safety_uncertainties"] if u["key"] == TYRE_KEY]
        assert u == {"kind": "condition_inconnue", "rule": "R-5:conditional_stop_uncertain:fx_amber_tyre_low",
                     "entry_id": "fx_amber_tyre_low", "key": TYRE_KEY, "variant": "selected",
                     "origin": v1.CATALOGUE_ORIGIN, "source_field": "linked_warnings", "citation": fx.TYRE_STOP,
                     "printed_page": "F-17", "pdf_page": 17, "condition": fx.TYRE_CONDITION,
                     "condition_established": False, "condition_status": "unknown"}
        assert t["driving_assessment"] != "do_not_drive" and "R-5" not in " ".join(t["triggered_rules"])

    def test_no_answer_equals_unknown(self, monkeypatch, grouped):
        draft(monkeypatch, grouped)
        a = constat(["fx_amber_tyre_low"])
        b = constat(["fx_amber_tyre_low"], conditions={TYRE_KEY: "unknown"})
        c = constat(["fx_amber_tyre_low"], conditions={TYRE_KEY: "nonsense"})
        assert a["triage"] == b["triage"] == c["triage"] and a["internal"]["stops"] == b["internal"]["stops"] == c["internal"]["stops"]

    def test_confirmed_applies_with_its_rule_condition_and_source(self, monkeypatch, grouped, client):
        draft(monkeypatch, grouped)
        r = confirm(client, ["fx_amber_tyre_low"])
        r = answer(client, r, TYRE_KEY, "confirmed")
        t = r["premier_constat"]["triage"]
        assert t["level"] == "emergency_stop" and t["driving_assessment"] == "do_not_drive"
        assert t["r5_rows"] == ["R-5:conditional_stop_confirmed:fx_amber_tyre_low"]
        o = next(o for o in t["origin"] if o["origin"] == "passage documenté")
        assert (o["citation"], o["condition"], o["condition_status"], o["printed_page"]) == (
            fx.TYRE_STOP, fx.TYRE_CONDITION, "confirmed", "F-17")
        # Shown at the top of the result, without any click, with its condition and source.
        (top,) = r["premier_constat"]["presentation"]["stops_confirmed"]
        assert top["citation"] == {"text": fx.TYRE_STOP, "printed_page": "F-17", "pdf_page": 17}
        assert top["condition"]["text"] == fx.TYRE_CONDITION and top["answer"] == "confirmed"
        # The other variant's own stop keeps its own (unknown) answer: never transferred.
        (other,) = stops(r["premier_constat"], "fx_amber_tyre_fault")
        assert other["condition_status"] == "unknown"

    def test_excluded_on_unvalidated_interpretation_stays_uncertain(self, monkeypatch, grouped):
        draft(monkeypatch, grouped)
        t = constat(["fx_amber_tyre_low"], conditions={TYRE_KEY: "excluded"})["triage"]
        (u,) = [u for u in t["safety_uncertainties"] if u["key"] == TYRE_KEY]
        assert u["kind"] == "condition_exclue_interpretation_non_validee" and u["condition_status"] == "excluded"
        assert t["r5_rows"] == [] and t["safety_status"] == "uncertain"

    def test_excluded_on_validated_preparation_does_not_raise_but_stays_consultable(self, monkeypatch, grouped):
        validated(monkeypatch, grouped)
        r = constat(["fx_amber_tyre_low"], conditions={TYRE_KEY: "excluded"})
        assert [u for u in r["triage"]["safety_uncertainties"] if u["key"] == TYRE_KEY] == []
        assert r["triage"]["r5_rows"] == [] and r["triage"]["level"] == "monitor_and_document"
        (s,) = stops(r, "fx_amber_tyre_low")
        assert (s["citation"], s["condition"], s["condition_status"], s["condition_established"]) == (
            fx.TYRE_STOP, fx.TYRE_CONDITION, "excluded", True)

    def test_restore_pressure_is_not_a_stop(self, monkeypatch, grouped):
        draft(monkeypatch, grouped)
        r = constat(["fx_amber_tyre_low"])
        assert [s["citation"] for s in stops(r, "fx_amber_tyre_low")] == [fx.TYRE_STOP]
        kinds = [c["kind"] for c in r["internal"]["consignes"] if c["entry_id"] == "fx_amber_tyre_low"]
        assert kinds == ["expected_action", "conditional_stop"]

    def test_answer_refused_where_no_stop(self, monkeypatch, grouped, client):
        draft(monkeypatch, grouped)
        r = confirm(client, ["fx_amber_tyre_low"])
        out = client.post(f"/api/v1/parcours/{r['pid']}/condition", json={"key": "fx_amber_tyre_low#0", "answer": "confirmed"})
        assert out.status_code == 409


# --- 2. PGDR-SAF-012 -------------------------------------------------------------------------------

class TestBrakeRule:
    def test_parking_brake_applied_established_no_do_not_drive(self, monkeypatch, grouped):
        validated(monkeypatch, grouped)
        t = constat(["fx_red_pb_applied"])["triage"]
        assert "PGDR-SAF-012" not in t["triggered_rules"] and t["engine_level"] == "monitor_and_document"
        assert t["rule_exclusions"] == [{"rule": "PGDR-SAF-012", "excluded": [{
            "entry_id": "fx_red_pb_applied", "nature": "fonctionnement_normal",
            "provenance": "classement des situations validé", "variant": "selected"}]}]

    def test_insufficient_information_no_silent_downgrade(self, monkeypatch, grouped):
        draft(monkeypatch, grouped)  # draft classification: no structured fact
        t = constat(["fx_red_pb_applied"])["triage"]
        assert "PGDR-SAF-012" in t["triggered_rules"] and t["engine_level"] == "do_not_drive" and t["rule_exclusions"] == []
        wire(monkeypatch, grouped)  # no classification at all (other parcours shape)
        assert "PGDR-SAF-012" in constat(["fx_red_pb_applied"])["triage"]["triggered_rules"]

    def test_low_fluid_with_applicable_instruction_kept(self, monkeypatch, grouped):
        validated(monkeypatch, grouped)
        t = constat(["fx_red_pb_fluid"])["triage"]
        assert "PGDR-SAF-012" in t["triggered_rules"] and t["level"] == "do_not_drive" and t["safety_status"] == "uncertain"
        t = constat(["fx_red_pb_fluid"], conditions={FLUID_KEY: "confirmed"})["triage"]
        assert t["level"] == "emergency_stop" and "PGDR-SAF-012" in t["triggered_rules"]
        assert t["r5_rows"] == ["R-5:conditional_stop_confirmed:fx_red_pb_fluid"]

    def test_undetermined_group_keeps_critical_possibility_without_confirming(self, monkeypatch, grouped):
        validated(monkeypatch, grouped)
        r = constat([], [group_of("fx_red_pb_fluid")])
        t = r["triage"]
        assert "PGDR-SAF-012" in t["triggered_rules"] and t["rule_exclusions"] == []  # possible variant: never excluded
        assert {v["status"] for v in r["internal"]["variants"]} == {"possible"}
        (u,) = [u for u in t["safety_uncertainties"] if u["entry_id"] == "fx_red_pb_fluid"]
        assert u["variant"] == "possible" and u["kind"] == "condition_inconnue" and u["citation"] == fx.PB_FLUID_WARNING
        # With a validated immediate stop for the fluid variant: critical level kept, variant still not confirmed.
        validated(monkeypatch, grouped, findings_path=findings_file(grouped, {"fx_red_pb_fluid": {
            "items": stop_item("linked_warnings", "stop the fictive vehicle immediately")}}))
        t = constat([], [group_of("fx_red_pb_fluid")])["triage"]
        assert t["level"] == "emergency_stop"
        assert [u["kind"] for u in t["safety_uncertainties"] if u["entry_id"] == "fx_red_pb_fluid"] == ["variante_non_departagee"]

    def test_other_rules_and_parcours_unchanged(self, monkeypatch, grouped):
        validated(monkeypatch, grouped)
        # Multiple selection: the established ordinary indication does not hide the other red brake indicator.
        t = constat(["fx_red_pb_applied", "fx_red_pb_fluid"])["triage"]
        assert "PGDR-SAF-012" in t["triggered_rules"]


# --- 3. Manufacturer instruction without a presentation classification ------------------------------

class TestManufacturerInstructionAlone:
    def test_reviewed_stop_reaches_r5_without_any_classification(self, monkeypatch, grouped):
        wire(monkeypatch, grouped)  # no situations, no Part 1 classification
        r = constat(["fx_red_pb_fluid"])
        (s,) = stops(r, "fx_red_pb_fluid")
        assert (s["citation"], s["origin"], s["condition"], s["condition_established"], s["condition_status"]) == (
            fx.PB_FLUID_WARNING, v1.CATALOGUE_ORIGIN, None, False, "unknown")
        assert r["triage"]["safety_status"] == "uncertain"
        t = constat(["fx_red_pb_fluid"], conditions={FLUID_KEY: "confirmed"})["triage"]
        assert t["level"] == "emergency_stop" and t["r5_rows"] == ["R-5:conditional_stop_confirmed:fx_red_pb_fluid"]

    def test_exact_citation_does_not_validate_an_interpretation(self, monkeypatch, grouped):
        validated(monkeypatch, grouped, consignes=False)  # presentation validated, preparation NOT validated
        (s,) = stops(constat(["fx_red_pb_fluid"]), "fx_red_pb_fluid")
        assert s["condition"] == "If the fictive light comes on while driving" and s["condition_established"] is False


# --- 4. Restart procedure (non-regression) ----------------------------------------------------------

class TestRestartProcedure:
    def test_procedure_never_an_emergency_nor_a_permission(self, monkeypatch, grouped):
        draft(monkeypatch, grouped)
        r = constat(["fx_red_steer_a"])
        assert fx.STEER_PROCEDURE not in [s["citation"] for s in r["internal"]["stops"]]
        (proc,) = [c for c in r["internal"]["consignes"] if c["kind"] == "restart_procedure"]
        assert proc["citation"]["text"] == fx.STEER_PROCEDURE and proc["condition"]["text"] == fx.STEER_CONDITION
        assert proc["citation"]["printed_page"] == "F-13"
        assert r["triage"]["level"] == "monitor_and_document" and r["triage"]["r5_rows"] == []
        assert r["triage"]["driving_assessment"] != "do_not_drive"
        # The real stop of the mixed warning stays an explicit uncertainty.
        assert [u["citation"] for u in r["triage"]["safety_uncertainties"]] == [
            "If the fictive steering light flashes, stop the fictive vehicle at once."]

    def test_procedure_recorded_as_immediate_stop_is_reported_not_altered(self, monkeypatch, grouped):
        draft(monkeypatch, grouped, findings_path=findings_file(grouped, {"fx_red_steer_a": {
            "items": stop_item("documented_instruction", "stop the fictive vehicle, stop the fictive motor for about 20 seconds")}}))
        r = constat(["fx_red_steer_a"])
        assert r["triage"]["level"] == "emergency_stop"  # never forced down after calculation
        assert any("procédure d'arrêt temporaire" in x["limit"] for x in r["internal"]["limits"])


# --- Other behaviours kept --------------------------------------------------------------------------

class TestKept:
    def test_other_alert_and_multiple_selection(self, monkeypatch, grouped):
        draft(monkeypatch, grouped, findings_path=fx.build_findings(grouped))
        t = constat(["fx_red_fluid", "fx_green_lamps"])["triage"]
        assert t["level"] == "emergency_stop" and "R-5:stop_vehicle_engine_off:fx_red_fluid" in t["r5_rows"]
        assert "PGDR-SAF-012" not in t["rule_exclusions"]

    def test_stop_lights_no_stop(self, monkeypatch, grouped):
        draft(monkeypatch, grouped)
        r = constat(["fx_amber_lamp_fault"])
        assert r["internal"]["stops"] == [] and r["triage"]["safety_status"] == "established"

    def test_unknown_red_light_fallback_kept(self, monkeypatch, grouped, client):
        draft(monkeypatch, grouped)
        pid = open_parcours(client)
        client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": "dont_know", "entry_ids": []})
        s = client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "incertain"}).json()["screen"]
        assert s["key"] == "red_or_uncertain" and s["heading"].startswith("Arrêtez-vous en sécurité")
