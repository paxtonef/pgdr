"""V1 parcours — draft mentions follow the real status (FICTIVE notice only).

« Textes de cette section en brouillon, non validés » is shown only when one of
the section's texts comes from draft content (label not validated, draft group,
explanation, classification or translation); absent when everything shown
comes from VALIDATED files bound to the catalogue. Interface texts are
validated only by a VALIDATED labels file (exact current text, key by key).
The internal level does not depend on these mentions."""
from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from test_v1_premier_constat import confirm, wire

ALL_KEYS = sorted(set(v1.BLOCK_LABEL_KEYS) | set(v1.STOPS_LABEL_KEYS))


def build_labels(manifest, *, status="VALIDE", keys=ALL_KEYS, override=None) -> str:
    repo = ManifestNoticeRepository(manifest)
    header = {"status": status, "catalogue_content_sha256": repo.catalogue.content_sha256}
    if status == "VALIDE":
        header.update(validated_by="Fictive Owner", validated_on="2026-10-08")
    labels = {k: vc.DRAFT_LABELS[k] for k in keys}
    labels.update(override or {})
    path = manifest.parent / "libelles.yaml"
    path.write_text(yaml.safe_dump({"header": header, "labels": labels}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def grouped(tmp_path):
    return fx.build(tmp_path / "grouped", with_groups=True)


@pytest.fixture
def client():
    return TestClient(web.app)


def validated_paths(manifest) -> dict:
    return {"situations_path": fx.build_situations(manifest, status="VALIDE", validated_by="Fictive Owner"),
            "explanations_path": fx.build_explanations(manifest, status="VALIDE", validated_by="Fictive Owner")}


class TestMentionFollowsStatus:
    def test_absent_with_validated_content(self, monkeypatch, grouped, client):
        w = wire(monkeypatch, grouped, labels_path=build_labels(grouped), **validated_paths(grouped))
        assert w.labels_status == "validated" and set(ALL_KEYS) <= w.labels_validated
        assert w.situations_status == "validated"
        r = confirm(client, ["fx_amber_code_a"])
        assert "questions" not in r  # no message is ever asked (clôture V1: no free text)
        (b,) = r["premier_constat"]["presentation"]["ambiguous"]
        assert b["draft_texts"] is None and b["group_draft"] is None
        assert vc.DRAFT_LABELS["draft_texts"] not in json.dumps(b, ensure_ascii=False)

    def test_present_with_draft_labels(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped, **validated_paths(grouped))  # no labels file: labels keep their draft status
        r = confirm(client, ["fx_amber_code_a"])
        (b,) = r["premier_constat"]["presentation"]["ambiguous"]
        assert b["draft_texts"] == vc.DRAFT_LABELS["draft_texts"]

    def test_present_with_draft_classification(self, monkeypatch, grouped, client):
        wire(monkeypatch, grouped, labels_path=build_labels(grouped), situations_path=fx.build_situations(grouped))
        r = confirm(client, ["fx_amber_code_a"])
        (b,) = r["premier_constat"]["presentation"]["ambiguous"]
        assert b["draft_texts"] == vc.DRAFT_LABELS["draft_texts"]  # draft situations shown in the block


class TestLabelsFile:
    def test_draft_refused_outside_the_trial(self, monkeypatch, grouped):
        w = wire(monkeypatch, grouped, dev_trial=False, labels_path=build_labels(grouped, status="BROUILLON_NON_VALIDE"))
        assert w.labels_validated == frozenset() and w.labels_status == "refused: labels not validated"

    def test_draft_in_trial_validates_nothing(self, monkeypatch, grouped):
        w = wire(monkeypatch, grouped, labels_path=build_labels(grouped, status="BROUILLON_NON_VALIDE"))
        assert w.labels_validated == frozenset() and w.labels_status == "draft_dev_trial"

    def test_changed_text_rejected_alone(self, monkeypatch, grouped, client):
        w = wire(monkeypatch, grouped, labels_path=build_labels(grouped, override={"common": "Autre texte fictif"}),
                 **validated_paths(grouped))
        assert "common" not in w.labels_validated and w.labels_rejected == {"common": "text differs from the current label"}
        assert "no_common" in w.labels_validated
        r = confirm(client, ["fx_amber_code_a"])
        (b,) = r["premier_constat"]["presentation"]["ambiguous"]
        assert b["draft_texts"] == vc.DRAFT_LABELS["draft_texts"]

    def test_unknown_key_rejected(self, monkeypatch, grouped):
        w = wire(monkeypatch, grouped, labels_path=build_labels(grouped, override={"fictive_key": "Texte fictif"}))
        assert w.labels_rejected == {"fictive_key": "unknown label"}


def test_internal_level_identical_with_and_without_validated_labels(monkeypatch, grouped, client):
    out = []
    for extra in ({}, {"labels_path": build_labels(grouped)}):
        wire(monkeypatch, grouped, findings_path=fx.build_findings(grouped), **validated_paths(grouped), **extra)
        r = confirm(client, ["fx_red_fluid", "fx_amber_code_a"])
        out.append(r["premier_constat"])
    a, b = out
    assert a["triage"] == b["triage"]
    norm = lambda pc: [u for u in pc["internal"]["uncertainties"] if u.get("kind") != "texts.draft"]
    assert norm(a) == norm(b)
    assert a["internal"]["consignes"] == b["internal"]["consignes"] and a["internal"]["stops"] == b["internal"]["stops"]
