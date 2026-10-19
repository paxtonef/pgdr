"""Bloc 3A, point 6 — opening a V1 parcours rests on the real applicability
criteria, never on VIR's global status alone.

The criteria PGDR can check are the ones the notice and the handed-on
identity carry: the identity keys the notice is resolved on (manufacturer,
model, generation), each established by VIR (present, neither unresolved nor
contradictory), the notice's own vehicle, and its applicability period when
the notice declares one. A notice whose applicability is not established
stays refused outside the development trial; nothing is ever chosen by
default. FICTIVE notice only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

TOKEN = "v1-3a-handoff-token"


def wire(monkeypatch, manifest, dev_trial=False):
    repo = ManifestNoticeRepository(manifest) if manifest is not None else None
    monkeypatch.setattr(v1, "_wiring", v1.V1Wiring(repository=repo, dev_trial=dev_trial))
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)


def established(tmp_path, **period):
    path = fx.build(tmp_path / "notice", applicability_established=True)
    if period:
        d = fx.load(path)
        d.update(period)
        fx.approve_manifest(d)
        fx.save(path, d)
    return path


def handoff(status="resolved", identity=None, unresolved=(), contradictions=()):
    body = {"resolution_id": "VIR-FICTIVE-3A", "resolution_status": status,
            "vehicle_identity": dict(fx.VIR_IDENTITY) if identity is None else identity,
            "unresolved_fields": list(unresolved), "contradictions": list(contradictions)}
    r = TestClient(web.app).post("/api/v1/vir-handoff", json=body, headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN})
    assert r.status_code == 200, r.text
    return r.json()


def test_provisional_identity_meeting_every_criterion_opens(monkeypatch, tmp_path):
    wire(monkeypatch, established(tmp_path))
    r = handoff(status="provisionally_resolved")
    assert r["status"] == "opened" and r["parcours_id"] in v1._parcours


@pytest.mark.parametrize("field", ["manufacturer", "model", "generation"])
def test_missing_criterion_is_refused(monkeypatch, tmp_path, field):
    wire(monkeypatch, established(tmp_path))
    identity = {**fx.VIR_IDENTITY, field: None}
    for status in ("resolved", "provisionally_resolved"):
        r = handoff(status=status, identity=identity, unresolved=[field])
        assert r["status"] == "vehicle_identity_insufficient", (status, r)
    assert v1._parcours == {}


@pytest.mark.parametrize("status", ["resolved", "provisionally_resolved"])
def test_value_vir_does_not_establish_is_never_used(monkeypatch, tmp_path, status):
    """A value present but reported by VIR as unresolved (e.g. resting on a
    driver confirmation where an established source is required) or as
    contradictory is not a criterion met, whatever the global status."""
    wire(monkeypatch, established(tmp_path))
    assert handoff(status=status, unresolved=["generation"])["status"] == "vehicle_identity_insufficient"
    assert handoff(status=status, contradictions=["model"])["status"] == "vehicle_identity_insufficient"
    assert v1._parcours == {}


@pytest.mark.parametrize("status", ["ambiguous", "insufficient_data", "contradictory"])
def test_no_single_identity_is_refused_even_with_every_field(monkeypatch, tmp_path, status):
    # Several candidates or contradictions: taking the fields shown would be a default choice.
    wire(monkeypatch, established(tmp_path))
    assert handoff(status=status)["status"] == "vehicle_identity_insufficient"
    assert v1._parcours == {}


def test_other_vehicle_is_not_supported(monkeypatch, tmp_path):
    wire(monkeypatch, established(tmp_path))
    r = handoff(status="provisionally_resolved", identity={**fx.VIR_IDENTITY, "generation": "X2"})
    assert r["status"] == "vehicle_not_supported" and v1._parcours == {}


def test_declared_period_is_a_criterion(monkeypatch, tmp_path):
    wire(monkeypatch, established(tmp_path, applicability_period_start="2015-01-01",
                                  applicability_period_end="2019-12-31"))
    inside = {**fx.VIR_IDENTITY, "production": {"year": 2017, "start_date": None, "end_date": None}}
    before = {**fx.VIR_IDENTITY, "production": {"year": 2012, "start_date": None, "end_date": None}}
    after = {**fx.VIR_IDENTITY, "production": {"year": None, "start_date": "2021-03-01", "end_date": None}}
    unknown = {**fx.VIR_IDENTITY, "production": {"year": None, "start_date": None, "end_date": None}}
    assert handoff(identity=before)["status"] == "vehicle_not_supported"
    assert handoff(identity=after)["status"] == "vehicle_not_supported"
    assert handoff(identity=unknown)["status"] == "vehicle_identity_insufficient"
    assert handoff(identity=dict(fx.VIR_IDENTITY))["status"] == "vehicle_identity_insufficient"
    assert handoff(identity=inside, unresolved=["production.year"])["status"] == "vehicle_identity_insufficient"
    assert v1._parcours == {}
    assert handoff(status="provisionally_resolved", identity=inside)["status"] == "opened"


def test_notice_without_period_does_not_ask_for_one(monkeypatch, tmp_path):
    wire(monkeypatch, established(tmp_path))
    assert handoff(identity=dict(fx.VIR_IDENTITY))["status"] == "opened"


def test_insufficiently_applicable_notice_stays_refused(monkeypatch, tmp_path):
    wire(monkeypatch, fx.build(tmp_path / "notice", applicability_established=False))
    assert handoff(status="provisionally_resolved")["status"] == "applicability_not_confirmed"
    assert handoff(status="resolved")["status"] == "applicability_not_confirmed"
    assert v1._parcours == {}


def test_absent_notice_is_refused(monkeypatch):
    wire(monkeypatch, None)
    assert handoff(status="provisionally_resolved")["status"] == "notice_unavailable"
    assert v1._parcours == {}
