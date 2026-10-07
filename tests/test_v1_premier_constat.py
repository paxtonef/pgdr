"""V1 parcours -> Premier Constat (existing Part 1 chain) on a FICTIVE notice
with FICTIVE structured fields.

selection -> confirmation -> Premier Constat (approved French only) ->
documented instruction -> end of parcours (T8, no question). Cases: linked
stop warning, several lights, absent fields (« non établi »), unvalidated or
mismatching classification never used, R-5 never lowers the SafetyEngine.
"""
from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from pgdr.application.part1_first_finding import (
    APPROVED_BANNERS, APPROVED_LABELS, banner, professional_label, severity_rank,
)
from pgdr.enums import TriageLevel
from pgdr.errors import ConfigurationError
from pgdr.models import FindingItem

TOKEN = "v1-constat-token"
T8 = APPROVED_BANNERS["T8"][0]
STOP = APPROVED_LABELS["stop_vehicle_engine_off = REQUIRED"]


@pytest.fixture
def notice(tmp_path):
    return fx.build(tmp_path / "notice")


@pytest.fixture
def client():
    return TestClient(web.app)


def wire(monkeypatch, manifest, findings_path=None):
    repo = ManifestNoticeRepository(manifest)
    findings, status = {}, "absent"
    if findings_path is not None:
        findings, status = v1.load_v1_findings(findings_path, repo), "validated"
    monkeypatch.setattr(v1, "_wiring", v1.V1Wiring(repository=repo, dev_trial=True, findings=findings,
                                                   findings_status=status))
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)


def constat(client, ids) -> dict:
    r = client.post("/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}, json={
        "resolution_id": "VIR-FICTIVE", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}).json()
    pid = r["parcours_id"]
    client.post(f"/api/v1/parcours/{pid}/vir-seen")
    client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True})
    client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids})
    out = client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True})
    assert out.status_code == 200, out.text
    return out.json()


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def approved_or_manufacturer(manifest) -> set[str]:
    """Every string the presentation may contain: approved banners/labels
    (with their declared substitutions), the approved origin wording, and
    verbatim manufacturer fields / identifiers / enum values."""
    allowed = {line for lines in APPROVED_BANNERS.values() for line in lines} | set(APPROVED_LABELS.values())
    allowed |= set(banner("T3", document_title="FICTIVE OWNER HANDBOOK", document_id="FICTIVE-NOTICE-001"))
    allowed |= set(banner("T7", documented_suitability="a fictive workshop"))
    allowed |= {professional_label(FindingItem.not_established())}
    allowed |= set(web._ORIGIN_TEXT.values())
    for e in fx.load(manifest)["entries"]:
        allowed |= {v for v in (e["entry_id"], e["manufacturer_designation"], e["documented_meaning"],
                                e["documented_instruction"], e["displayed_message"], e["colour"], e["state"]) if v}
    allowed |= {"user_selection", "not_established", "towing_required", "garage_required", "neither_required",
                "a fictive workshop", fx.STOP_PHRASE, fx.CONTACT_PHRASE}
    return allowed


class TestPremierConstatWithoutClassification:
    def test_all_structured_fields_not_established(self, monkeypatch, notice, client):
        wire(monkeypatch, notice)
        r = constat(client, ["fx_red_fluid"])
        pc = r["premier_constat"]
        assert pc["classification_status"] == "absent"
        p = pc["presentation"]
        assert p["banner"] == list(APPROVED_BANNERS["T2"]) and p["end"] == T8
        e = p["entries"][0]
        assert e["identified"]["origin"] == "user_selection"
        assert e["manufacturer_text"]["label"] == APPROVED_BANNERS["T5"][0]
        assert e["manufacturer_text"]["documented_meaning"] == fx.RED_MEANING
        assert e["immediate_safety"] == []
        assert e["vehicle_use"] == APPROVED_LABELS["operability = NOT_ESTABLISHED"]
        assert APPROVED_LABELS["stop_vehicle_engine_off = NOT_ESTABLISHED"] in e["not_established"]
        assert APPROVED_LABELS["professional_attention = NOT_ESTABLISHED"] in e["not_established"]
        assert p["legend"] == APPROVED_BANNERS["T4"][0]
        # The exact passage and its complete linked warnings stay available.
        red = r["sections"][0]
        assert "".join(s["text"] for s in red["warnings"][0]["text"] if "text" in s) == fx.SHARED_WARNING

    def test_only_approved_french_or_verbatim_manufacturer_text(self, monkeypatch, notice, client):
        wire(monkeypatch, notice)
        pc = constat(client, ["fx_red_fluid", "fx_green_lamps"])["premier_constat"]["presentation"]
        allowed = approved_or_manufacturer(notice)
        assert [s for s in strings(pc) if s not in allowed] == []

    def test_no_question_after_identification(self, monkeypatch, notice, client):
        wire(monkeypatch, notice)
        r = constat(client, ["fx_red_fluid"])
        assert r["phase"] == "restitution"
        assert "question" not in str(r).lower().replace("questions", "")
        assert r["premier_constat"]["presentation"]["end"] == T8


class TestPremierConstatWithFictiveClassification:
    def test_linked_stop_warning_gives_documented_instruction_and_emergency_level(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, fx.build_findings(notice))
        pc = constat(client, ["fx_red_fluid"])["premier_constat"]
        e = pc["presentation"]["entries"][0]
        assert e["immediate_safety"] == [STOP, APPROVED_LABELS["vehicle_immobilization = REQUIRED"]]
        assert e["vehicle_use"] == APPROVED_LABELS["operability = DO_NOT_DRIVE"]
        assert e["professional"]["label"] == professional_label(FindingItem.not_established())
        assert e["professional"]["documented_suitability"] == "a fictive workshop"
        assert pc["triage"]["level"] == TriageLevel.EMERGENCY_STOP.value
        assert pc["triage"]["driving_assessment"] == "do_not_drive"
        assert pc["triage"]["r5_rows"] == ["R-5:stop_vehicle_engine_off:fx_red_fluid"]
        assert [s for s in strings(pc["presentation"]) if s not in approved_or_manufacturer(notice)] == []

    def test_several_lights_one_section_each_and_max_level(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, fx.build_findings(notice))
        r = constat(client, ["fx_amber_sensor", "fx_red_fluid", "fx_green_lamps"])
        p = r["premier_constat"]["presentation"]
        assert [e["entry_id"] for e in p["entries"]] == ["fx_red_fluid", "fx_amber_sensor", "fx_green_lamps"]
        assert [s["entry_id"] for s in r["sections"]] == ["fx_red_fluid", "fx_amber_sensor", "fx_green_lamps"]
        red, amber, green = p["entries"]
        assert STOP in red["immediate_safety"]
        for e in (amber, green):  # no record: absent fields are « non établi », never guessed
            assert e["immediate_safety"] == [] and e["professional"] is None
            assert e["vehicle_use"] == APPROVED_LABELS["operability = NOT_ESTABLISHED"]
        assert r["premier_constat"]["triage"]["level"] == "emergency_stop"

    def test_level_never_lower_than_cited_stop_warning(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, fx.build_findings(notice))
        for ids in (["fx_red_fluid"], ["fx_green_lamps", "fx_red_fluid"], ["fx_white_cruise", "fx_red_fluid"]):
            t = constat(client, ids)["premier_constat"]["triage"]
            assert severity_rank(TriageLevel(t["level"])) >= severity_rank(TriageLevel.EMERGENCY_STOP)
            assert severity_rank(TriageLevel(t["level"])) >= severity_rank(TriageLevel(t["engine_level"]))

    def test_r5_never_lowers_the_safety_engine(self, monkeypatch, tmp_path, client):
        # A red « BRAKE » designation triggers the unmodified SafetyEngine (do_not_drive);
        # without classification nothing may lower it.
        m = fx.build(tmp_path / "n")
        d = fx.load(m)
        d["entries"][0]["manufacturer_designation"] = "FICTIVE LOW BRAKE FLUID"
        fx.approve_manifest(d)
        fx.save(m, d)
        wire(monkeypatch, m)
        t = constat(client, ["fx_red_fluid"])["premier_constat"]["triage"]
        assert t["engine_level"] == "do_not_drive" and t["level"] == "do_not_drive"
        assert t["driving_assessment"] == "do_not_drive"


class TestClassificationNeverUsedUnlessValidated:
    def test_draft_refused(self, notice):
        path = fx.build_findings(notice, status="BROUILLON_NON_VALIDE")
        with pytest.raises(ConfigurationError):
            v1.load_v1_findings(path, ManifestNoticeRepository(notice))

    def test_unnamed_approval_refused(self, notice):
        path = fx.build_findings(notice, approved_by="")
        with pytest.raises(ConfigurationError):
            v1.load_v1_findings(path, ManifestNoticeRepository(notice))

    def test_other_catalogue_content_refused(self, notice):
        path = fx.build_findings(notice)
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["header"]["catalogue_content_sha256"] = "0" * 64
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(ConfigurationError):
            v1.load_v1_findings(path, ManifestNoticeRepository(notice))

    def test_anchor_not_in_live_warning_refused(self, notice):
        path = fx.build_findings(notice)
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["entries"][0]["items"]["stop_vehicle_engine_off"]["source_phrase"] = "stop at once"
        doc["entries"][0]["items"]["operability"]["source_phrase"] = "stop at once"
        doc["entries"][0]["items"]["vehicle_immobilization"]["source_phrase"] = "stop at once"
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(ConfigurationError):
            v1.load_v1_findings(path, ManifestNoticeRepository(notice))

    def test_refused_classification_from_environment_means_not_established(self, monkeypatch, notice, client):
        monkeypatch.setattr(v1, "_wiring", None)
        monkeypatch.setattr(v1, "_parcours", {})
        monkeypatch.setenv("PGDR_V1_MANIFEST", str(notice))
        monkeypatch.setenv("PGDR_V1_DEV_TRIAL", "1")
        monkeypatch.setenv("PGDR_V1_FINDINGS", str(fx.build_findings(notice, status="BROUILLON_NON_VALIDE")))
        monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
        pc = constat(client, ["fx_red_fluid"])["premier_constat"]
        assert pc["classification_status"].startswith("refused")
        assert pc["presentation"]["entries"][0]["immediate_safety"] == []
        assert pc["presentation"]["entries"][0]["vehicle_use"] == APPROVED_LABELS["operability = NOT_ESTABLISHED"]

    def test_validated_classification_from_environment_used(self, monkeypatch, notice, client):
        monkeypatch.setattr(v1, "_wiring", None)
        monkeypatch.setattr(v1, "_parcours", {})
        monkeypatch.setenv("PGDR_V1_MANIFEST", str(notice))
        monkeypatch.setenv("PGDR_V1_DEV_TRIAL", "1")
        monkeypatch.setenv("PGDR_V1_FINDINGS", str(fx.build_findings(notice)))
        monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
        pc = constat(client, ["fx_red_fluid"])["premier_constat"]
        assert pc["classification_status"] == "validated"
        assert STOP in pc["presentation"]["entries"][0]["immediate_safety"]
