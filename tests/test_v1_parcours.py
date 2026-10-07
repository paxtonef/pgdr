"""V1 parcours — unit and integration tests on a FICTIVE notice.

Adapter (read-only KnowledgeRepositoryPort over the source manifest) and the
web parcours (VIR -> consent -> optional photo -> complete catalogue ->
selection -> confirmation -> exact restitution, colour fallback).
No real manufacturer content, no CPL, no model provider.
"""
from __future__ import annotations

import hashlib
import os
import socket
import sys
import urllib.request
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import (
    ManifestNoticeRepository, NoticeRejected, content_fingerprint,
)
from pgdr.domain.dashboard_knowledge import VehicleApplicabilityContext
from pgdr.ports.knowledge_repository import KnowledgeRepositoryPort

REPO = Path(__file__).resolve().parents[1]
PREP = REPO / "outils" / "preparation_v1" / "config"
TOKEN = "v1-test-handoff-token"


# --- fixtures -----------------------------------------------------------------

@pytest.fixture
def notice(tmp_path) -> Path:
    return fx.build(tmp_path / "notice")


def rejected(path: Path):
    with pytest.raises(NoticeRejected):
        ManifestNoticeRepository(path)


def mutate(path: Path, f, reapprove: bool = False) -> Path:
    d = fx.load(path)
    f(d)
    if reapprove:
        fx.approve_manifest(d)
    fx.save(path, d)
    return path


@pytest.fixture
def no_provider(monkeypatch):
    """Fails the test on any network connection or model-provider call."""
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise AssertionError("network / provider call during the V1 parcours")

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        if isinstance(address, tuple):
            boom(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(urllib.request, "urlopen", boom)

    class FailingProvider:
        def __getattr__(self, name):
            boom(name)

    monkeypatch.setattr(web, "_photo_wiring", web.PhotoWiring(interpretation_provider=FailingProvider()))
    yield calls
    assert calls == []
    assert "trier_images" not in sys.modules


def wire(monkeypatch, path: Path | None, dev_trial=False, dev_vehicle=None):
    repo = None
    if path is not None:
        repo = ManifestNoticeRepository(path)
    monkeypatch.setattr(v1, "_wiring", v1.V1Wiring(repository=repo, dev_trial=dev_trial, dev_vehicle=dev_vehicle))
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    return repo


@pytest.fixture
def client():
    return TestClient(web.app)


def handoff(client, identity=None, status="resolved"):
    body = {"resolution_id": "VIR-FICTIVE-1", "resolution_status": status,
            "vehicle_identity": identity or fx.VIR_IDENTITY}
    return client.post("/api/v1/vir-handoff", json=body, headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}).json()


def opened(client) -> str:
    r = handoff(client)
    assert r["status"] == "opened", r
    pid = r["parcours_id"]
    assert client.post(f"/api/v1/parcours/{pid}/vir-seen").json()["phase"] == "consent"
    assert client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True}).json()["consent"] is True
    return pid


def joined(segments) -> str:
    return "".join(s["text"] for s in segments if "text" in s)


# --- adapter: verification ----------------------------------------------------

class TestAdapterVerification:
    def test_fingerprint_identical_to_preparation_package(self):
        # Vector computed with outils/preparation_v1/scripts/notices.py::content_fingerprint.
        d = {"schema_version": 2, "title": "Fictive é ✓",
             "entries": [{"entry_id": "b", "x": None, "n": 1.5, "t": True}, {"entry_id": "a"}],
             "review": {"status": "approved"}}
        assert content_fingerprint(d) == "d54d00ac6465dbfd341c06414c5d2b9dc2f3cf19b91509765060e380f7ad837a"

    def test_approved_notice_loads_in_manual_order(self, notice):
        c = ManifestNoticeRepository(notice).catalogue
        assert [e.entry_id for e in c.entries] == [e["entry_id"] for e in fx.load(notice)["entries"]]
        assert c.content_sha256 == content_fingerprint(fx.load(notice))

    def test_pending_review_rejected(self, notice):
        rejected(mutate(notice, lambda d: d["review"].update(status="pending")))

    def test_obsolete_review_rejected_after_text_change(self, notice):
        rejected(mutate(notice, lambda d: d["entries"][0].update(documented_meaning="Changed fictive text.")))

    def test_declared_fingerprint_not_trusted(self, notice):
        # Content changed AND the declared review fingerprint replaced by another
        # declared value: only a recomputation catches it.
        def f(d):
            d["entries"][1]["documented_meaning"] = "Changed fictive text."
            d["review"]["content_sha256"] = d["manual_sha256"]
        rejected(mutate(notice, f))

    def test_obsolete_after_reorder(self, notice):
        rejected(mutate(notice, lambda d: d["entries"].reverse()))

    def test_obsolete_after_presentation_change(self, notice):
        rejected(mutate(notice, lambda d: d["entries"][0].update(where_provided=False)))

    def test_image_bytes_changed_rejected(self, notice):
        (notice.parent / "images" / "green.png").write_bytes(fx.png((1, 2, 3)))
        rejected(notice)

    def test_pictogram_bytes_changed_rejected(self, notice):
        (notice.parent / "images" / "picto.png").write_bytes(fx.png((9, 9, 9), 4))
        rejected(notice)

    def test_manual_bytes_changed_rejected(self, notice):
        (notice.parent / "manual.pdf").write_bytes(b"%PDF-1.4\n% other\n")
        rejected(notice)

    def test_re_declared_digest_without_new_review_rejected(self, notice):
        data = fx.png((1, 2, 3))
        (notice.parent / "images" / "green.png").write_bytes(data)
        rejected(mutate(notice, lambda d: d["entries"][2].update(image_sha256=fx.sha(data))))

    def test_missing_file_rejected(self, notice):
        (notice.parent / "images" / "white.png").unlink()
        rejected(notice)

    def test_path_outside_package_rejected(self, notice, tmp_path):
        (tmp_path / "outside.png").write_bytes(fx.png((200, 0, 0)))
        rejected(mutate(notice, lambda d: d["entries"][0].update(image_file="../outside.png"), reapprove=True))

    def test_absolute_path_rejected(self, notice):
        p = str(notice.parent / "images" / "red.png")
        rejected(mutate(notice, lambda d: d["entries"][0].update(image_file=p), reapprove=True))

    def test_symlink_escape_rejected(self, notice, tmp_path):
        (tmp_path / "outside.png").write_bytes((notice.parent / "images" / "red.png").read_bytes())
        (notice.parent / "images" / "link.png").symlink_to(tmp_path / "outside.png")
        rejected(mutate(notice, lambda d: d["entries"][0].update(image_file="images/link.png"), reapprove=True))

    def test_reviewer_missing_rejected(self, notice):
        rejected(mutate(notice, lambda d: d["review"].update(reviewer_name="")))

    def test_future_review_date_rejected(self, notice):
        rejected(mutate(notice, lambda d: d["review"].update(reviewed_at="2999-01-01T00:00:00+00:00")))

    def test_reviewed_change_accepted(self, notice):
        mutate(notice, lambda d: d["entries"][0].update(documented_meaning="Changed fictive text."), reapprove=True)
        assert ManifestNoticeRepository(notice).catalogue.entries[0].documented_meaning == "Changed fictive text."

    def test_read_only(self, notice):
        def snapshot():
            return {p: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                    for p in notice.parent.rglob("*") if p.is_file()}
        before = snapshot()
        repo = ManifestNoticeRepository(notice)
        repo.entries_for_document("FICTIVE-NOTICE-001")
        assert snapshot() == before

    def test_assets_are_the_verified_bytes(self, notice):
        repo = ManifestNoticeRepository(notice)
        e = repo.catalogue.entries[0]
        assert repo.asset(e.image_sha256) == (notice.parent / "images" / "red.png").read_bytes()
        assert repo.asset("0" * 64) is None


class TestAdapterPort:
    def test_is_knowledge_repository_port(self, notice):
        assert isinstance(ManifestNoticeRepository(notice), KnowledgeRepositoryPort)

    def test_applicable_document_by_vehicle(self, notice):
        repo = ManifestNoticeRepository(notice)
        ok = VehicleApplicabilityContext(manufacturer="FICTIVA", model="testmobile", generation="X1")
        assert [d.document_id for d in repo.find_applicable_documents(ok)] == ["FICTIVE-NOTICE-001"]
        other = VehicleApplicabilityContext(manufacturer="Fictiva", model="Testmobile", generation="X2")
        assert repo.find_applicable_documents(other) == []
        assert repo.find_applicable_documents(VehicleApplicabilityContext()) == []

    def test_entries_exact_and_ordered(self, notice):
        repo = ManifestNoticeRepository(notice)
        entries = repo.entries_for_document("FICTIVE-NOTICE-001")
        assert [e.entry_id for e in entries] == ["fx_red_fluid", "fx_amber_sensor", "fx_green_lamps", "fx_white_cruise"]
        assert entries[0].documented_meaning == fx.RED_MEANING
        assert repo.entries_for_document("OTHER") == []
        assert repo.get_document_by_id("FICTIVE-NOTICE-001").document_title == "FICTIVE OWNER HANDBOOK"
        assert repo.get_document_by_id("OTHER") is None


# --- web parcours -------------------------------------------------------------

class TestParcoursOpening:
    def test_handoff_requires_credential(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        body = {"resolution_id": "x", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}
        assert client.post("/api/v1/vir-handoff", json=body).status_code == 403

    def test_unestablished_applicability_refused_outside_dev_trial(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=False)
        assert handoff(client)["status"] == "applicability_not_confirmed"

    def test_established_applicability_opens_without_banner(self, monkeypatch, tmp_path, client):
        wire(monkeypatch, fx.build(tmp_path / "n", applicability_established=True), dev_trial=False)
        r = handoff(client)
        assert r["status"] == "opened"
        assert client.get(f"/api/v1/parcours/{r['parcours_id']}").json()["dev_trial_banner"] is None

    def test_dev_trial_opens_with_permanent_banner(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        assert client.get(f"/api/v1/parcours/{pid}").json()["dev_trial_banner"] == (
            "Essai de développement — Applicabilité de cette notice au véhicule non confirmée")

    def test_other_vehicle_not_supported(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        assert handoff(client, {"manufacturer": "Other", "model": "M", "generation": "G"})["status"] == "vehicle_not_supported"

    def test_unresolved_vir_identity_refused(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        assert handoff(client, status="ambiguous")["status"] == "vehicle_identity_insufficient"

    def test_no_notice_unavailable(self, monkeypatch, client):
        wire(monkeypatch, None, dev_trial=True)
        assert handoff(client)["status"] == "notice_unavailable"

    def test_rejected_notice_from_environment_not_served(self, monkeypatch, notice, client):
        mutate(notice, lambda d: d["review"].update(status="pending"))
        monkeypatch.setattr(v1, "_wiring", None)
        monkeypatch.setenv("PGDR_V1_MANIFEST", str(notice))
        monkeypatch.setenv("PGDR_V1_DEV_TRIAL", "1")
        monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
        assert v1.get_wiring().repository is None and "pending" in v1.get_wiring().error
        assert handoff(client)["status"] == "notice_unavailable"

    def test_dev_entry_only_in_dev_trial(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=False, dev_vehicle=fx.VIR_IDENTITY)
        assert client.get("/v1/essai-dev", follow_redirects=False).status_code == 404
        wire(monkeypatch, notice, dev_trial=True, dev_vehicle=fx.VIR_IDENTITY)
        r = client.get("/v1/essai-dev", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/v1?p=V1-")

    def test_unknown_parcours(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        assert client.get("/api/v1/parcours/V1-unknown").status_code == 404


class TestParcoursFlow:
    def test_consent_required_before_catalogue_and_images(self, monkeypatch, notice, client):
        repo = wire(monkeypatch, notice, dev_trial=True)
        pid = handoff(client)["parcours_id"]
        assert client.get(f"/api/v1/parcours/{pid}/catalogue").status_code == 403
        sha = repo.catalogue.entries[0].image_sha256
        assert client.get(f"/api/v1/parcours/{pid}/asset/{sha}").status_code == 403
        r = client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": False}).json()
        assert r["status"] == "consent_required" and r["consent"] is False
        assert client.get(f"/api/v1/parcours/{pid}/catalogue").status_code == 403

    def test_catalogue_complete_in_manual_order(self, monkeypatch, notice, client):
        repo = wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        c = client.get(f"/api/v1/parcours/{pid}/catalogue").json()
        assert [e["entry_id"] for e in c["entries"]] == [e["entry_id"] for e in fx.load(notice)["entries"]]
        assert [e["manual_order"] for e in c["entries"]] == list(range(4))
        for e in c["entries"]:
            r = client.get(e["image"])
            assert r.status_code == 200 and r.headers["content-type"] == "image/png"
            assert r.content == repo.asset(e["image"].rsplit("/", 1)[1])

    def test_no_photo_upload_endpoint(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        for path in ("photo", "media", "upload"):
            assert client.post(f"/api/v1/parcours/{pid}/{path}", content=fx.png((1, 1, 1)),
                               headers={"Content-Type": "image/png"}).status_code in (404, 405)

    def test_unvalidated_selection_kept_through_fallback(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        r = client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": "none_match", "entry_ids": ["fx_white_cruise"]}).json()
        assert (r["selection"], r["confirmed"]) == (["fx_white_cruise"], False)
        assert client.post(f"/api/v1/parcours/{pid}/no-match",
                           json={"reason": "none_match", "entry_ids": ["nope"]}).status_code == 400

    def test_selection_validation(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        url = f"/api/v1/parcours/{pid}/selection"
        assert client.post(url, json={"entry_ids": ["nope"]}).status_code == 400
        assert client.post(url, json={"entry_ids": ["fx_red_fluid", "fx_red_fluid"]}).status_code == 400
        assert client.post(url, json={"entry_ids": []}).status_code == 422

    def test_explicit_confirmation_required(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        url = f"/api/v1/parcours/{pid}/confirm"
        ids = ["fx_green_lamps", "fx_red_fluid"]
        assert client.post(url, json={"entry_ids": ids, "confirmed": True}).status_code == 409  # nothing selected yet
        client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids})
        assert client.post(url, json={"entry_ids": ids, "confirmed": False}).status_code == 409
        assert client.post(url, json={"entry_ids": ["fx_red_fluid"], "confirmed": True}).status_code == 409
        assert client.post(url, json={"entry_ids": ids, "confirmed": True}).status_code == 200

    def test_exact_restitution_one_section_per_image(self, monkeypatch, notice, client, no_provider):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        sel = client.post(f"/api/v1/parcours/{pid}/selection",
                          json={"entry_ids": ["fx_amber_sensor", "fx_red_fluid"]}).json()
        assert [c["entry_id"] for c in sel["chosen"]] == ["fx_red_fluid", "fx_amber_sensor"]  # manual order
        r = client.post(f"/api/v1/parcours/{pid}/confirm",
                        json={"entry_ids": ["fx_red_fluid", "fx_amber_sensor"], "confirmed": True}).json()
        src = {e["entry_id"]: e for e in fx.load(notice)["entries"]}
        assert [s["entry_id"] for s in r["sections"]] == ["fx_red_fluid", "fx_amber_sensor"]
        red, amber = r["sections"]
        assert red["designation"] == "FICTIVE LOW FLUID"
        assert joined(red["meaning"]) == fx.RED_MEANING
        assert [s for s in red["meaning"] if "pictogram" in s][0]["printed_page"] == "F-2"
        assert red["instruction"] == "Stop the fictive vehicle."
        assert red["audible_signal"] == "A fictive chime sounds."
        assert red["where_provided"] is True and red["startup_check"] == fx.RED_STARTUP
        assert (red["page_reference"], red["pdf_page"]) == ("F-1", 1)
        assert (red["colour"], red["state"], amber["colour"]) == ("rouge", "fixe", "ambre")
        assert "curation_notes" not in red and "Fictive curation note." not in str(r)
        assert r["document"]["language_note"] == (
            "Texte du constructeur reproduit dans la langue de la notice disponible (anglais).")
        assert red["field_sources"] == [{"field": "signal sonore", "text": "A fictive chime sounds.",
                                         "printed_page": "F-3", "pdf_page": 3}]
        # The same numbered warning linked to two images is shown complete in BOTH sections.
        for s in (red, amber):
            assert len(s["warnings"]) == 1
            w = s["warnings"][0]
            assert (w["number"], w["printed_page"], w["pdf_page"]) == ("7)", "F-2", 2)
            assert joined(w["text"]) == fx.SHARED_WARNING
            assert any("pictogram" in seg for seg in w["text"])
        assert amber["where_provided"] is False and amber["startup_check"] is None
        assert joined(amber["meaning"]) == src["fx_amber_sensor"]["documented_meaning"]

    def test_fallback_red_and_other_with_validated_french(self, monkeypatch, notice, client, no_provider):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        en = yaml.safe_load((PREP / "fallback_screens.fr.yaml").read_text(encoding="utf-8"))
        assert client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "rouge"}).status_code == 409
        for reason, colour, key in (("none_match", "rouge", "red_or_uncertain"), ("dont_know", "incertain", "red_or_uncertain"),
                                    ("none_match", "vert", "other_colour"), ("dont_know", "orange", "other_colour"),
                                    ("none_match", "blanc", "other_colour")):
            assert client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": reason}).json()["phase"] == "colour"
            s = client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": colour}).json()["screen"]
            assert s["key"] == key and s["lang"] == "fr"
            assert s["heading"] == en["screens"][key]["heading"]
            assert s["paragraphs"] == en["screens"][key]["paragraphs"]
        assert client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "violet"}).status_code == 422

    def test_return_preserves_selection_and_colour_and_requires_new_confirmation(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, dev_trial=True)
        pid = opened(client)
        ids = ["fx_red_fluid", "fx_white_cruise"]
        client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids})
        client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True})
        client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": "dont_know", "entry_ids": ids})
        client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "rouge"})
        r = client.post(f"/api/v1/parcours/{pid}/return").json()
        assert (r["phase"], r["selection"], r["colour"], r["confirmed"]) == ("catalogue", ids, "rouge", False)
        c = client.get(f"/api/v1/parcours/{pid}/catalogue").json()
        assert c["selection"] == ids and c["colour"] == "rouge"
        assert [e["entry_id"] for e in c["entries"]] == [e["entry_id"] for e in fx.load(notice)["entries"]]
        assert client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True}).status_code == 409
        client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids})
        assert client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True}).status_code == 200


# --- content rules ------------------------------------------------------------

def _flow_texts(monkeypatch, notice, client) -> str:
    wire(monkeypatch, notice, dev_trial=True)
    pid = opened(client)
    out = [client.get("/v1").text, str(client.get(f"/api/v1/parcours/{pid}").json())]
    ids = ["fx_red_fluid", "fx_green_lamps"]
    out.append(str(client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids}).json()))
    out.append(str(client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True}).json()))
    for colour in ("rouge", "vert"):
        out.append(str(client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": "none_match"}).json()))
        out.append(str(client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": colour}).json()))
    out.append(str(client.post(f"/api/v1/parcours/{pid}/return").json()))
    return "\n".join(out)


class TestContentRules:
    def test_packaged_fallback_identical_to_validated_copy(self):
        packaged = REPO / "src" / "pgdr" / "config" / "v1_fallback_screens.fr.yaml"
        assert packaged.read_bytes() == (PREP / "fallback_screens.fr.yaml").read_bytes()
        assert not (PREP / "fallback_screens.fr.BROUILLON_NON_VALIDE.yaml").exists()

    def test_french_translation_carries_named_validation(self):
        fr = yaml.safe_load((PREP / "fallback_screens.fr.yaml").read_text(encoding="utf-8"))
        assert fr["status"] == "VALIDE"
        assert fr["validation"]["validated_by"] == "Fred Cobral"
        assert fr["validation"]["validated_on"] == "2026-10-07"
        en = (PREP / "fallback_screens.en.yaml").read_bytes()
        assert fr["translates_sha256"] == hashlib.sha256(en).hexdigest()

    def test_unvalidated_translation_refused(self):
        fr = yaml.safe_load((PREP / "fallback_screens.fr.yaml").read_text(encoding="utf-8"))
        for broken in (dict(fr, status="BROUILLON_NON_VALIDE"), dict(fr, validation={})):
            with pytest.raises(RuntimeError):
                v1.validated_fallback(broken)

    def test_validated_french_served_english_not(self, monkeypatch, notice, client):
        texts = _flow_texts(monkeypatch, notice, client)
        fr = yaml.safe_load((PREP / "fallback_screens.fr.yaml").read_text(encoding="utf-8"))
        en = yaml.safe_load((PREP / "fallback_screens.en.yaml").read_text(encoding="utf-8"))
        for s in fr["screens"].values():
            assert s["heading"] in texts and all(p in texts for p in s["paragraphs"])
        assert fr["shared"]["return_button"] in texts
        for s in en["screens"].values():
            assert s["heading"] not in texts and not any(p in texts for p in s["paragraphs"])
        assert en["shared"]["return_button"] not in texts

    def test_consent_text_announces_no_external_provider(self):
        runtime = yaml.safe_load((PREP / "runtime.yaml").read_text(encoding="utf-8"))
        names = [p.get("recipient_name") for p in runtime["providers"].values() if p.get("recipient_name")]
        names += [m["name"] for m in runtime["llm_catalog"]]
        consent = " ".join(v1.CONSENT_TEXT).lower()
        for word in names + ["lm studio", "openrouter", "fournisseur", "intelligence artificielle", " ia ",
                             "modèle", "serveur", "transmis à", "envoyée à", "analysée par"]:
            assert word.lower() not in consent
        assert "ni analysée, ni envoyée, ni conservée" in consent

    def test_no_screen_grants_driving_or_announces_contact(self, monkeypatch, notice, client):
        texts = _flow_texts(monkeypatch, notice, client).lower()
        for phrase in ("vous pouvez rouler", "vous pouvez reprendre la route", "vous pouvez continuer",
                       "sans danger", "you may continue driving", "you can continue driving", "safe to drive",
                       "a été contacté", "a été prévenu", "nous avons contacté", "nous avons prévenu",
                       "has been contacted", "we have contacted", "has been notified", "assistance est en route"):
            assert phrase not in texts

    def test_full_parcours_calls_no_provider(self, monkeypatch, notice, client, no_provider):
        _flow_texts(monkeypatch, notice, client)

    def test_no_provider_guard_really_fails(self, no_provider):
        with pytest.raises(AssertionError):
            socket.create_connection(("127.0.0.1", 9))
        no_provider.clear()

    def test_parcours_module_has_no_provider_dependency(self):
        src = Path(v1.__file__).read_text(encoding="utf-8")
        for name in ("httpx", "requests", "urllib", "trier_images", "DashboardInterpretationPort", "openrouter", "lmstudio"):
            assert name not in src
