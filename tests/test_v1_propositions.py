"""V1 parcours — proposed images (owner decision of 2026-10-19): 1 to 3
images proposed from the driver's photo, as an aid to the driver's own
selection. FICTIVE notice, FAKE sorting transport only: these tests prove the
wiring and the refusals, never any recognition quality.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import v1_propositions as vp
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository

TOKEN = "v1-propositions-handoff-token"
IDS = ["fx_red_fluid", "fx_amber_sensor", "fx_green_lamps", "fx_white_cruise"]  # notice order
RECIPIENT = "Composant de tri d'essai (faux transport)"
# Identifiers that must never reach a sorting component (fictive values).
PLATE, VIN = "AB-123-CD", "VF1FICTIVE0000001"


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_with_metadata(rgb=(10, 20, 30)) -> bytes:
    """A valid PNG carrying text, EXIF and time metadata (fictive)."""
    base = fx.png(rgb, 8)
    ihdr_end = 8 + 25
    meta = (chunk(b"tEXt", b"Comment\x00plaque " + PLATE.encode()) + chunk(b"eXIf", b"MM\x00*GPS 48.85N 2.35E")
            + chunk(b"tIME", b"\x07\xea\x0a\x13\x0c\x00\x00") + chunk(b"iTXt", b"VIN\x00\x00\x00\x00\x00" + VIN.encode()))
    return base[:ihdr_end] + meta + base[ihdr_end:]


def seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def jpeg_with_metadata() -> bytes:
    """A structurally valid JPEG stream with APP0, APP1 (EXIF), APP13, COM,
    entropy data containing stuffed bytes and a restart marker, and a second
    image appended after the first EOI (as phones do), with its own EXIF."""
    body = (seg(0xDB, b"\x00" + bytes(64)) + seg(0xC0, b"\x08\x00\x08\x00\x08\x01\x01\x11\x00")
            + seg(0xC4, b"\x00" + bytes(16) + b"\x00") + seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
            + b"\x12\xff\x00\x34\xff\xd0\x56")
    first = (b"\xff\xd8" + seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
             + seg(0xE1, b"Exif\x00\x00GPS 48.85N plaque " + PLATE.encode()) + seg(0xED, b"Photoshop 3.0\x00IPTC")
             + seg(0xFE, b"VIN " + VIN.encode()) + body + b"\xff\xd9")
    appended = b"\xff\xd8" + seg(0xE1, b"Exif\x00\x00second " + PLATE.encode()) + body + b"\xff\xd9"
    return first + appended, body


def answer(ids) -> str:
    return json.dumps({"proposed_entry_ids": ids})


class Recorder:
    def __init__(self):
        self.demandes = []

    def __call__(self, demande):
        self.demandes.append(demande)


def candidates(repo) -> list[vp.Candidat]:
    return [vp.Candidat(e.entry_id, repo.asset(e.image_sha256), "image/png") for e in repo.catalogue.entries]


# --- metadata --------------------------------------------------------------------

class TestMetadata:
    def test_png_keeps_only_drawing_chunks(self):
        raw = png_with_metadata()
        clean, kind = vp.strip_metadata(raw)
        assert kind == "image/png" and clean == fx.png((10, 20, 30), 8)
        for marker in (PLATE.encode(), VIN.encode(), b"GPS", b"tEXt", b"eXIf", b"tIME", b"iTXt"):
            assert marker not in clean

    def test_jpeg_drops_app_segments_comments_and_appended_image(self):
        raw, body = jpeg_with_metadata()
        clean, kind = vp.strip_metadata(raw)
        assert kind == "image/jpeg"
        assert clean == b"\xff\xd8" + body + b"\xff\xd9"  # DQT/SOF/DHT/SOS and entropy data intact
        for marker in (PLATE.encode(), VIN.encode(), b"Exif", b"JFIF", b"GPS", b"Photoshop"):
            assert marker not in clean

    @pytest.mark.parametrize("data", [
        b"", b"GIF89a....", b"%PDF-1.4", fx.png((1, 2, 3))[:30], b"\xff\xd8\xff\xe1\x00", b"\x89PNG\r\n\x1a\n",
        fx.png((1, 2, 3))[:-5] + b"XXXXX",
    ])
    def test_refused(self, data):
        with pytest.raises(vp.PhotoRefusee):
            vp.strip_metadata(data)

    def test_png_with_bad_crc_refused(self):
        raw = bytearray(fx.png((1, 2, 3)))
        raw[20] ^= 0xFF
        with pytest.raises(vp.PhotoRefusee):
            vp.strip_metadata(bytes(raw))

    def test_oversized_refused(self):
        with pytest.raises(vp.PhotoRefusee):
            vp.strip_metadata(b"\x89PNG\r\n\x1a\n" + bytes(vp.MAX_PHOTO_BYTES))


# --- strict answer ------------------------------------------------------------------

class TestAnswer:
    @pytest.mark.parametrize("text,expected", [
        (answer(["fx_green_lamps"]), ["fx_green_lamps"]),
        (answer(["fx_white_cruise", "fx_red_fluid", "fx_amber_sensor"]), ["fx_white_cruise", "fx_red_fluid", "fx_amber_sensor"]),
        ("```json\n" + answer(["fx_red_fluid"]) + "\n```", ["fx_red_fluid"]),
        (answer([]), []),
    ])
    def test_accepted(self, text, expected):
        assert vp.lire_propositions(text, IDS) == expected

    @pytest.mark.parametrize("text", [
        answer(IDS),                                                     # 4: more than 3
        answer(["fx_red_fluid", "fx_red_fluid"]),                        # duplicate
        answer(["fx_other_notice"]),                                     # outside the applicable catalogue
        json.dumps({"proposed_entry_ids": ["fx_red_fluid"], "scores": [0.97]}),   # invented score
        json.dumps({"proposed_entry_ids": ["fx_red_fluid"], "label": "brake fluid"}),
        json.dumps({"ordered_entry_ids": IDS}),
        '{"proposed_entry_ids": ["fx_red_fluid"], "proposed_entry_ids": ["fx_green_lamps"]}',
        json.dumps({"proposed_entry_ids": [1]}), json.dumps({"proposed_entry_ids": "fx_red_fluid"}),
        json.dumps(["fx_red_fluid"]), "fx_red_fluid", "", "```\n{}\n```\n```\n{}\n```", None, 42,
    ])
    def test_refused(self, text):
        with pytest.raises(vp.ReponseInvalide):
            vp.lire_propositions(text, IDS)


# --- outcome ------------------------------------------------------------------------

class TestProposer:
    @pytest.fixture
    def repo(self, tmp_path):
        return ManifestNoticeRepository(fx.build(tmp_path / "notice"))

    def fake(self, text=None, panne=False, observer=None):
        r = {"panne": True} if panne else {"texte": text}
        return vp.FauxTransportTri(RECIPIENT, {}, r, observer=observer)

    def test_not_configured(self, repo):
        assert vp.proposer(png_with_metadata(), candidates(repo), None) == vp.Resultat(repli="non_configure")

    def test_proposals_in_notice_order_never_in_component_order(self, repo):
        r = vp.proposer(png_with_metadata(), candidates(repo), self.fake(answer(["fx_white_cruise", "fx_red_fluid"])))
        assert r == vp.Resultat(propositions=("fx_red_fluid", "fx_white_cruise"))

    @pytest.mark.parametrize("text,repli", [
        (answer([]), "aucune_proposition"), (answer(IDS), "reponse_invalide"),
        (json.dumps({"proposed_entry_ids": ["fx_red_fluid"], "confidence": 0.9}), "reponse_invalide"),
        ("not json at all", "reponse_invalide"),
    ])
    def test_fallbacks(self, repo, text, repli):
        assert vp.proposer(png_with_metadata(), candidates(repo), self.fake(text)) == vp.Resultat(repli=repli)

    def test_transport_failure(self, repo):
        assert vp.proposer(png_with_metadata(), candidates(repo), self.fake(panne=True)) == vp.Resultat(repli="panne")

        class Broken:
            destinataire, faux = RECIPIENT, True

            def proposer(self, demande):
                raise RuntimeError("secret detail " + PLATE)

        assert vp.proposer(png_with_metadata(), candidates(repo), Broken()) == vp.Resultat(repli="panne")

    def test_refused_photo_never_reaches_the_transport(self, repo):
        rec = Recorder()
        assert vp.proposer(b"GIF89a", candidates(repo), self.fake(answer(["fx_red_fluid"]), observer=rec)) == \
            vp.Resultat(repli="photo_refusee")
        assert rec.demandes == []

    def test_sorting_context_is_photo_without_metadata_and_applicable_images_only(self, repo):
        rec = Recorder()
        vp.proposer(png_with_metadata(), candidates(repo), self.fake(answer(["fx_red_fluid"]), observer=rec))
        (d,) = rec.demandes
        assert [f.name for f in dataclasses.fields(d)] == ["photo", "photo_media_type", "candidats"]
        assert [f.name for f in dataclasses.fields(d.candidats[0])] == ["entry_id", "image", "media_type"]
        assert d.photo == fx.png((10, 20, 30), 8) and d.photo_media_type == "image/png"
        assert [c.entry_id for c in d.candidats] == IDS
        assert [c.image for c in d.candidats] == [repo.asset(e.image_sha256) for e in repo.catalogue.entries]
        blob = repr(d).encode() + d.photo + b"".join(c.image for c in d.candidats)
        for marker in (PLATE.encode(), VIN.encode(), b"GPS", b"Fictiva", b"Testmobile", b"resolution"):
            assert marker not in blob


class TestConfiguration:
    def write(self, tmp_path, obj) -> str:
        p = tmp_path / "faux.json"
        p.write_text(json.dumps(obj), encoding="utf-8")
        return str(p)

    def test_absent(self):
        assert vp.charger_transport(None, None) == (None, "absent")
        assert vp.charger_transport("", "/x") == (None, "absent")

    @pytest.mark.parametrize("mode", ["reel", "openai", "vision", "FAUX", "faux "])
    def test_no_real_component(self, mode, tmp_path):
        good = self.write(tmp_path, {"nature": vp.FAUX_NATURE, "destinataire": RECIPIENT, "reponses": {}})
        t, status = vp.charger_transport(mode, good)
        assert t is None and status == "refused: composant réel non autorisé"

    @pytest.mark.parametrize("obj", [
        {"destinataire": RECIPIENT, "reponses": {}},                                 # nature missing
        {"nature": "fournisseur", "destinataire": RECIPIENT, "reponses": {}},
        {"nature": vp.FAUX_NATURE, "reponses": {}},                                  # no recipient name
        {"nature": vp.FAUX_NATURE, "destinataire": "  ", "reponses": {}},
        {"nature": vp.FAUX_NATURE, "destinataire": RECIPIENT, "reponses": {"x": {"texte": 1}}},
        {"nature": vp.FAUX_NATURE, "destinataire": RECIPIENT, "reponses": {"x": {"texte": "a", "score": 1}}},
        {"nature": vp.FAUX_NATURE, "destinataire": RECIPIENT, "reponses": {}, "defaut": {"panne": False}},
    ])
    def test_invalid_fake_refused(self, obj, tmp_path):
        t, status = vp.charger_transport("faux", self.write(tmp_path, obj), essai=True)
        assert t is None and status.startswith("refused: ")

    def test_fake_needs_its_file(self, tmp_path):
        assert vp.charger_transport("faux", None, essai=True) == (None, "refused: PGDR_V1_TRI_FAUX requis")
        t, status = vp.charger_transport("faux", str(tmp_path / "missing.json"), essai=True)
        assert t is None and status.startswith("refused: ")

    def test_fake_keyed_by_stripped_photo_digest(self, tmp_path):
        clean = fx.png((10, 20, 30), 8)
        t, status = vp.charger_transport("faux", self.write(tmp_path, {
            "nature": vp.FAUX_NATURE, "destinataire": RECIPIENT,
            "reponses": {hashlib.sha256(clean).hexdigest(): {"texte": answer(["fx_green_lamps"])}}}), essai=True)
        assert status == "faux" and t.faux is True and t.destinataire == RECIPIENT
        assert t.proposer(vp.DemandeTri(clean, "image/png", ())) == answer(["fx_green_lamps"])
        with pytest.raises(ConnectionError):  # unknown photo, no default: failure
            t.proposer(vp.DemandeTri(fx.png((1, 1, 1)), "image/png", ()))

    def test_environment_wiring(self, monkeypatch, tmp_path):
        path = self.write(tmp_path, {"nature": vp.FAUX_NATURE, "destinataire": RECIPIENT, "reponses": {}})
        monkeypatch.setattr(v1, "_wiring", None)
        monkeypatch.setenv("PGDR_V1_TRI", "faux")
        monkeypatch.setenv("PGDR_V1_TRI_FAUX", path)
        monkeypatch.setenv("PGDR_V1_ESSAI_TRI", "1")   # signalled trial (bloc 3A)
        monkeypatch.delenv("PGDR_V1_MANIFEST", raising=False)
        w = v1.get_wiring()
        assert w.tri_status == "faux" and w.tri.destinataire == RECIPIENT
        monkeypatch.setattr(v1, "_wiring", None)
        monkeypatch.setenv("PGDR_V1_TRI", "fournisseur-reel")
        w = v1.get_wiring()
        assert w.tri is None and w.tri_status == "refused: composant réel non autorisé"


# --- web parcours ---------------------------------------------------------------------

def wire(monkeypatch, notice: Path, tri=None, labels_validated=frozenset()):
    repo = ManifestNoticeRepository(notice)
    monkeypatch.setattr(v1, "_wiring", v1.build_wiring(repo, dev_trial=True, tri=tri))
    v1._wiring.labels_validated = labels_validated
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    return repo


@pytest.fixture
def notice(tmp_path) -> Path:
    return fx.build(tmp_path / "notice")


@pytest.fixture
def client():
    return TestClient(web.app)


def opened(client) -> str:
    r = client.post("/api/v1/vir-handoff", json={"resolution_id": "VIR-FICTIVE-P", "resolution_status": "resolved",
                                                 "vehicle_identity": fx.VIR_IDENTITY},
                    headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}).json()
    pid = r["parcours_id"]
    client.post(f"/api/v1/parcours/{pid}/vir-seen")
    client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True})
    return pid


def ask(client, pid, photo: bytes, recipient=RECIPIENT):
    return client.post(f"/api/v1/parcours/{pid}/propositions",
                       json={"recipient_consent": recipient, "photo_base64": base64.b64encode(photo).decode()})


def fake(text=None, panne=False, observer=None):
    return vp.FauxTransportTri(RECIPIENT, {}, {"panne": True} if panne else {"texte": text}, observer=observer)


class TestWebParcours:
    def test_without_transport_the_photo_stays_local_and_the_catalogue_explains_why(self, monkeypatch, notice, client):
        wire(monkeypatch, notice)
        pid = opened(client)
        s = client.get(f"/api/v1/parcours/{pid}").json()
        assert s["propositions"] == {"available": False}
        assert s["consent_text"] == list(v1.CONSENT_TEXT)  # « ni analysée, ni envoyée, ni conservée » still true
        c = client.get(f"/api/v1/parcours/{pid}/catalogue").json()
        assert [e["entry_id"] for e in c["entries"]] == IDS
        assert c["repli"]["key"] == "non_configure"
        assert c["repli"]["explanation"] == vc.DRAFT_LABELS["propositions.repli.non_configure"]
        # Even if asked, nothing is decoded: catalogue directly.
        r = ask(client, pid, png_with_metadata()).json()
        assert (r["proposed"], r["repli"]["key"], r["phase"]) == (None, "non_configure", "catalogue")

    def test_offer_names_the_recipient_and_marks_the_fake(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"])))
        pid = opened(client)
        s = client.get(f"/api/v1/parcours/{pid}").json()
        o = s["propositions"]
        assert o["available"] is True and o["recipient"] == RECIPIENT and o["fake"] is True
        assert "« " + RECIPIENT + " »" in o["texts"]["consentement"] and "{destinataire}" not in o["texts"]["consentement"]
        assert o["draft_texts"] == vc.DRAFT_LABELS["draft_texts"]  # not validated by the owner
        assert s["consent_text"][1] == vc.DRAFT_LABELS["propositions.consentement_general"]
        assert "ni envoyée" not in " ".join(s["consent_text"])

    def test_validated_labels_drop_the_draft_mention(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"])),
             labels_validated=frozenset(v1.PROPOSITION_LABEL_KEYS))
        pid = opened(client)
        assert client.get(f"/api/v1/parcours/{pid}").json()["propositions"]["draft_texts"] is None

    def test_c_photo_to_proposals_to_selection_to_notice_and_premier_constat(self, monkeypatch, notice, client):
        rec = Recorder()
        wire(monkeypatch, notice, tri=fake(answer(["fx_green_lamps", "fx_red_fluid"]), observer=rec))
        pid = opened(client)
        r = ask(client, pid, png_with_metadata()).json()
        assert r["phase"] == "propositions" and r["repli"] is None
        assert [e["entry_id"] for e in r["proposed"]["entries"]] == ["fx_red_fluid", "fx_green_lamps"]  # notice order
        for e in r["proposed"]["entries"]:
            assert set(e) == {"entry_id", "manual_order", "image", "alt"}  # no score, no rank, no label
        # Nothing selected or confirmed for the driver.
        assert (r["selection"], r["confirmed"]) == ([], False)
        assert rec.demandes[0].photo == fx.png((10, 20, 30), 8)  # metadata removed before the transport
        assert client.get(f"/api/v1/parcours/{pid}/propositions").json()["proposed"] == r["proposed"]
        # The driver chooses one, then confirms explicitly: the existing steps.
        s = client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ["fx_green_lamps"]}).json()
        assert (s["phase"], s["selection"]) == ("confirmation", ["fx_green_lamps"])
        out = client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ["fx_green_lamps"], "confirmed": True}).json()
        assert out["phase"] == "restitution"
        assert [x["entry_id"] for x in out["sections"]] == ["fx_green_lamps"]
        assert out["sections"][0]["meaning"] == [{"text": fx.GREEN_MEANING}]  # exact notice text
        assert out["premier_constat"]

    def test_proposals_change_nothing_in_the_premier_constat(self, monkeypatch, notice, client, tmp_path):
        """The same confirmed selection gives the same Premier Constat with or without proposals."""
        wire(monkeypatch, notice)
        pid = opened(client)
        client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ["fx_red_fluid"]})
        plain = client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ["fx_red_fluid"], "confirmed": True}).json()
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"])))
        pid2 = opened(client)
        ask(client, pid2, png_with_metadata())
        client.post(f"/api/v1/parcours/{pid2}/selection", json={"entry_ids": ["fx_red_fluid"]})
        proposed = client.post(f"/api/v1/parcours/{pid2}/confirm",
                               json={"entry_ids": ["fx_red_fluid"], "confirmed": True}).json()
        assert json.dumps(proposed["premier_constat"]).replace(pid2, "P") == json.dumps(plain["premier_constat"]).replace(pid, "P")
        assert json.dumps(proposed["sections"]).replace(pid2, "P") == json.dumps(plain["sections"]).replace(pid, "P")

    def test_d_proposals_not_recognised_then_complete_catalogue_then_selection(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"])))
        pid = opened(client)
        assert ask(client, pid, png_with_metadata()).json()["phase"] == "propositions"
        s = client.post(f"/api/v1/parcours/{pid}/return").json()
        assert s["phase"] == "catalogue" and s["selection"] == []
        c = client.get(f"/api/v1/parcours/{pid}/catalogue").json()
        assert [e["entry_id"] for e in c["entries"]] == IDS and c["repli"] is None and c["selection"] == []
        client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ["fx_amber_sensor"]})
        out = client.post(f"/api/v1/parcours/{pid}/confirm", json={"entry_ids": ["fx_amber_sensor"], "confirmed": True}).json()
        assert [x["entry_id"] for x in out["sections"]] == ["fx_amber_sensor"]

    @pytest.mark.parametrize("transport,photo,repli", [
        ("panne", None, "panne"),
        ("invalid", None, "reponse_invalide"),
        ("empty", None, "aucune_proposition"),
        ("ok", b"GIF89a not a photo", "photo_refusee"),
        ("ok", b"", "photo_refusee"),
    ])
    def test_e_failure_gives_the_explained_catalogue(self, monkeypatch, notice, client, transport, photo, repli):
        t = {"panne": fake(panne=True), "invalid": fake(json.dumps({"proposed_entry_ids": IDS[:1], "score": 0.99})),
             "empty": fake(answer([])), "ok": fake(answer(["fx_red_fluid"]))}[transport]
        wire(monkeypatch, notice, tri=t)
        pid = opened(client)
        r = ask(client, pid, png_with_metadata() if photo is None else photo).json()
        assert (r["phase"], r["proposed"], r["repli"]["key"]) == ("catalogue", None, repli)
        assert r["repli"]["explanation"] == vc.DRAFT_LABELS["propositions.repli." + repli]
        c = client.get(f"/api/v1/parcours/{pid}/catalogue").json()
        assert [e["entry_id"] for e in c["entries"]] == IDS and c["repli"]["key"] == repli
        assert client.get(f"/api/v1/parcours/{pid}/propositions").status_code == 409
        assert r["selection"] == []

    def test_invalid_base64_is_a_refused_photo(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"])))
        pid = opened(client)
        r = client.post(f"/api/v1/parcours/{pid}/propositions",
                        json={"recipient_consent": RECIPIENT, "photo_base64": "%%%not base64"}).json()
        assert r["repli"]["key"] == "photo_refusee"

    def test_f_no_image_recognised_keeps_the_existing_safety_outcome(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, tri=fake(answer(["fx_green_lamps"])))
        pid = opened(client)
        ask(client, pid, png_with_metadata())
        client.post(f"/api/v1/parcours/{pid}/return")
        r = client.post(f"/api/v1/parcours/{pid}/no-match", json={"reason": "none_match"}).json()
        assert r["phase"] == "colour" and r["selection"] == []
        red = client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "incertain"}).json()
        assert red["screen"]["key"] == "red_or_uncertain"
        assert red["screen"]["heading"] == v1.load_fallback_screens()["screens"]["red_or_uncertain"]["heading"]

    def test_consent_naming_the_recipient_is_required_before_any_byte(self, monkeypatch, notice, client):
        rec = Recorder()
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"]), observer=rec))
        pid = opened(client)
        for wrong in ("", "oui", RECIPIENT + " ", "PGDR"):
            r = ask(client, pid, png_with_metadata(), recipient=wrong)
            assert r.status_code == 403
        assert rec.demandes == [] and v1._parcours[pid].propositions == []

    def test_parcours_consent_required(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"])))
        r = client.post("/api/v1/vir-handoff", json={"resolution_id": "VIR-X", "resolution_status": "resolved",
                                                     "vehicle_identity": fx.VIR_IDENTITY},
                        headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}).json()
        assert ask(client, r["parcours_id"], png_with_metadata()).status_code == 403
        assert client.get(f"/api/v1/parcours/{r['parcours_id']}/propositions").status_code == 403

    def test_the_photo_is_not_kept(self, monkeypatch, notice, client):
        wire(monkeypatch, notice, tri=fake(answer(["fx_red_fluid"])))
        pid = opened(client)
        photo = png_with_metadata()
        ask(client, pid, photo)
        kept = repr(dataclasses.asdict(v1._parcours[pid])).encode()
        assert base64.b64encode(photo)[:40] not in kept and photo[16:40] not in kept
        assert v1._parcours[pid].propositions == ["fx_red_fluid"]

    def test_no_photo_in_logs_or_errors(self, monkeypatch, notice, client, caplog):
        caplog.set_level("DEBUG")
        wire(monkeypatch, notice, tri=fake(panne=True))
        pid = opened(client)
        photo = png_with_metadata()
        r = ask(client, pid, photo)
        assert r.status_code == 200
        text = caplog.text + r.text
        for marker in (PLATE, VIN, "GPS", base64.b64encode(photo).decode()[:40], "panne simulée"):
            assert marker not in text

    def test_page_has_the_proposals_screen_and_keeps_the_catalogue_reachable(self, client):
        html = client.get("/v1").text
        for anchor in ('id="screen-propositions"', 'id="propositions-catalogue"', 'id="propose-consent"',
                       'id="photo-continue"', 'id="catalogue-repli"', '"image/jpeg", 0.92'):
            assert anchor in html
        assert "recommand" not in html.lower() and "score" not in html.lower()
