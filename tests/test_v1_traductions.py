"""V1 parcours — prepared French translations of notice sentences, on a
FICTIVE notice only. The exact notice text always stays; the translation is
shown beside it with « Traduction préparée, non validée »; a record whose
notice text is not verbatim in its entry is rejected alone; a draft is
refused outside the development trial; the internal level is unchanged."""
from __future__ import annotations

import json
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
import yaml
from fastapi.testclient import TestClient
from playwright.sync_api import Page, expect

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

TOKEN = "v1-traductions-token"
_PORT = 8772
FR_DESIGNATION = "LIQUIDE FICTIF BAS"
FR_MEANING = "Le témoin rouge fictif s'allume lorsque le liquide de frein fictif est bas."
FR_WARNING = "Si le témoin fictif reste allumé, arrêtez le véhicule fictif dans un endroit sûr et contactez un atelier fictif."
BAD_ANCHOR = "This fictive sentence is not in the notice."


def build_translations(manifest, *, status="BROUILLON_NON_VALIDE", validated_by="", extra=()) -> str:
    repo = ManifestNoticeRepository(manifest)
    header = {"status": status, "catalogue_content_sha256": repo.catalogue.content_sha256}
    if validated_by:
        header.update(validated_by=validated_by, validated_on="2026-10-08")
    entries = [
        {"entry_id": "fx_red_fluid", "source_field": "manufacturer_designation", "source_phrase": "FICTIVE LOW FLUID",
         "texte": FR_DESIGNATION},
        {"entry_id": "fx_red_fluid", "source_field": "documented_meaning", "source_phrase": fx.RED_MEANING, "texte": FR_MEANING},
        {"entry_id": "fx_red_fluid", "source_field": "linked_warnings", "source_phrase": fx.SHARED_WARNING, "texte": FR_WARNING},
        {"entry_id": "fx_green_lamps", "source_field": "documented_meaning", "source_phrase": BAD_ANCHOR,
         "texte": "Cette phrase fictive n'est pas dans la notice."},
        *extra]
    path = manifest.parent / "traductions.yaml"
    path.write_text(yaml.safe_dump({"header": header, "entries": entries}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)


@pytest.fixture
def notice(tmp_path):
    return fx.build(tmp_path / "notice")


def wire(monkeypatch, manifest, **paths):
    w = v1.build_wiring(ManifestNoticeRepository(manifest), dev_trial=paths.pop("dev_trial", True), **paths)
    monkeypatch.setattr(v1, "_wiring", w)
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    return w


def confirm(client, ids) -> dict:
    r = client.post("/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}, json={
        "resolution_id": "VIR-FICTIVE", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}).json()
    pid = r["parcours_id"]
    client.post(f"/api/v1/parcours/{pid}/vir-seen")
    client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True})
    client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ids})
    out = client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ids, "confirmed": True})
    assert out.status_code == 200, out.text
    return out.json()


class TestLoading:
    def test_translation_kept_with_the_exact_text_and_marked(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, translations_path=build_translations(notice))
        assert w.translations_status == "draft_dev_trial"
        assert w.translations == {"FICTIVE LOW FLUID": FR_DESIGNATION, fx.RED_MEANING: FR_MEANING, fx.SHARED_WARNING: FR_WARNING}
        r = confirm(TestClient(web.app), ["fx_red_fluid"])
        assert r["document"]["translations"] == w.translations
        assert r["document"]["translation_mention"] == "Traduction préparée, non validée"
        # The exact notice text is still the one restituted.
        section = r["sections"][0]
        assert section["designation"] == "FICTIVE LOW FLUID"
        assert "".join(s.get("text", "") for s in section["meaning"]) == fx.RED_MEANING

    def test_invalid_anchor_rejected_alone(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, translations_path=build_translations(notice))
        assert list(w.translations_rejected) == [3] and "anchor not verbatim" in w.translations_rejected[3]
        assert BAD_ANCHOR not in w.translations and len(w.translations) == 3

    def test_forbidden_wording_gives_no_translation(self, monkeypatch, notice):
        bad = {"entry_id": "fx_green_lamps", "source_field": "documented_meaning", "source_phrase": fx.GREEN_MEANING,
               "texte": "Les feux fictifs sont allumés, vous pouvez rouler."}
        w = wire(monkeypatch, notice, translations_path=build_translations(notice, extra=[bad]))
        assert fx.GREEN_MEANING not in w.translations and w.translations_rejected[4] == "forbidden wording"

    def test_disagreeing_records_give_no_translation(self, monkeypatch, notice):
        other = {"entry_id": "fx_red_fluid", "source_field": "documented_meaning", "source_phrase": fx.RED_MEANING,
                 "texte": "Une autre traduction fictive."}
        w = wire(monkeypatch, notice, translations_path=build_translations(notice, extra=[other]))
        assert fx.RED_MEANING not in w.translations

    def test_draft_refused_outside_the_trial(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, dev_trial=False, translations_path=build_translations(notice))
        assert w.translations == {} and w.translations_status == "refused: translations not validated"

    def test_validated_file_unmarked(self, monkeypatch, notice):
        w = wire(monkeypatch, notice, dev_trial=False,
                 translations_path=build_translations(notice, status="VALIDE", validated_by="Fictive Owner"))
        assert w.translations_status == "validated" and len(w.translations) == 3
        assert v1._document(w.repository.catalogue)["translation_mention"] is None

    def test_other_catalogue_refused(self, monkeypatch, notice, tmp_path):
        other = fx.build(tmp_path / "other")
        d = fx.load(other)
        d["entries"][0]["documented_meaning"] = fx.RED_MEANING + " Fictive addition."
        fx.approve_manifest(d)
        fx.save(other, d)
        w = wire(monkeypatch, notice, translations_path=build_translations(other))
        assert w.translations == {} and w.translations_status.startswith("refused")

    def test_internal_level_identical(self, monkeypatch, notice):
        paths = {"findings_path": fx.build_findings(notice), "situations_path": fx.build_situations(notice),
                 "explanations_path": fx.build_explanations(notice)}
        out = []
        for extra in ({}, {"translations_path": build_translations(notice)}):
            wire(monkeypatch, notice, **paths, **extra)
            r = confirm(TestClient(web.app), ["fx_red_fluid", "fx_green_lamps"])
            out.append(r)
        without, with_ = out
        same = lambda r, k: json.loads(json.dumps(r[k]).replace(r["parcours_id"], "PID"))
        assert same(with_, "premier_constat") == same(without, "premier_constat")
        assert same(with_, "sections") == same(without, "sections")
        assert with_["premier_constat"]["triage"]["level"] == without["premier_constat"]["triage"]["level"]
        assert without["document"]["translations"] == {} and with_["document"]["translations"]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    notice = fx.build(tmp_path_factory.mktemp("fictive-tr") / "notice")
    saved = (v1._wiring, os.environ.get(web.IDENTITY_HANDOFF_TOKEN_ENV), web._photo_wiring)
    v1._wiring = v1.build_wiring(ManifestNoticeRepository(notice), dev_trial=True,
                                 situations_path=fx.build_situations(notice),
                                 translations_path=build_translations(notice))
    v1._parcours.clear()
    os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = TOKEN
    web._photo_wiring = web.PhotoWiring()
    server = uvicorn.Server(uvicorn.Config(web.app, host="127.0.0.1", port=_PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", _PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        server.should_exit = True
        pytest.fail("Server failed to start")
    yield f"http://127.0.0.1:{_PORT}"
    server.should_exit = True
    thread.join(timeout=5)
    v1._wiring, token, web._photo_wiring = saved
    v1._parcours.clear()
    if token is None:
        os.environ.pop(web.IDENTITY_HANDOFF_TOKEN_ENV, None)
    else:
        os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = token


@pytest.fixture
def page(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    yield context.new_page()
    context.close()
    browser.close()


def test_browser_translation_beside_exact_text(page: Page, live_server):
    r = httpx.post(f"{live_server}/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN},
                   json={"resolution_id": "VIR-FICTIVE-TR", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY})
    page.goto(live_server + r.json()["url"])
    page.click("#vir-continue")
    page.check("#consent-box")
    page.click("#consent-continue")
    page.click("#photo-continue")
    page.click('.tile[data-entry-id="fx_red_fluid"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    art = page.locator("article.restitution").first
    # Exact notice text unchanged, French right after it, with the mention.
    assert art.locator(".meaning").text_content() == fx.RED_MEANING
    tr = art.locator(".meaning + .translation")
    expect(tr).to_have_text(FR_MEANING + vc.TRANSLATION_MENTION)
    assert tr.get_attribute("lang") == "fr"
    expect(tr.locator(".translation-mention")).to_have_text("Traduction préparée, non validée")
    expect(art.locator("h2")).to_have_text("FICTIVE LOW FLUID")
    expect(art.locator("h2 + .translation")).to_contain_text(FR_DESIGNATION)
    expect(art.locator(".warning .translation")).to_contain_text(FR_WARNING)
    # Order of the blocks unchanged: every translation directly follows its exact text.
    for t in art.locator(".translation").all():
        assert t.evaluate("t => t.previousElementSibling.lang") == "en"
    assert "Cette phrase fictive" not in page.content()
    assert page.locator(".translation-mention").count() == page.locator(".translation").count()
