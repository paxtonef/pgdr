"""Clôture PGDR V1 — no dialogue, no dead end (FICTIVE notices only).

1. Without a notice (none provided by the assembly, or the one provided does not correspond to the vehicle):
   PGDR's refusal stands, unchanged, and a parcours WITHOUT notice opens beside it -- a fixed screen, the colour
   as the only (closed) choice, then the validated safety screen (red or uncertain -> stop). Never a catalogue,
   an image or a text of the notice that does not correspond.
2. No free input in the V1 page: every control is a button, a checkbox or the photo picker.
3. The legacy dialogue engines (SessionController, DiagnosticLoop, ComplaintParser) are never constructed nor
   called by the whole parcours -- with or without notice, with proposed images or the catalogue, clarification,
   condition, colour: spies make the test fail.
4. The routes the parcours exposes are exactly the closed list below.
"""
from __future__ import annotations

import base64
import json
import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

import v1_fictive_notice as fx
from pgdr import v1_contenu as vc
from pgdr import v1_parcours as v1
from pgdr import v1_propositions as vp
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from test_v1_3a_applicabilite import TOKEN, established, handoff
from test_v1_3a_applicabilite import wire as wire_3a

RECIPIENT = "Composant de tri d'essai (faux transport)"


@pytest.fixture
def client():
    return TestClient(web.app)


# --- 1. without a notice -----------------------------------------------------------------------------

CASES = {
    "notice_unavailable": (lambda tmp: None, "resolved", dict(fx.VIR_IDENTITY), ()),
    "vehicle_not_supported": (established, "provisionally_resolved", {**fx.VIR_IDENTITY, "generation": "X2"}, ()),
    "applicability_not_confirmed": (lambda tmp: fx.build(tmp / "notice"), "resolved", dict(fx.VIR_IDENTITY), ()),
    "vehicle_identity_insufficient": (established, "resolved", {**fx.VIR_IDENTITY, "model": None}, ("model",)),
}


def notice_texts(manifest) -> list[str]:
    if manifest is None:
        return []
    c = ManifestNoticeRepository(manifest).catalogue
    return [t for e in c.entries for t in (e.designation, e.documented_meaning, e.documented_instruction) if t]


@pytest.mark.parametrize("status", sorted(CASES))
def test_refusal_opens_a_parcours_without_notice_fixed_screen_then_safety(monkeypatch, tmp_path, client, status):
    build, vir_status, identity, unresolved = CASES[status]
    manifest = build(tmp_path)
    wire_3a(monkeypatch, manifest)
    r = handoff(status=vir_status, identity=identity, unresolved=unresolved)
    # The refusal itself is unchanged: status, message, reasons.
    assert r["status"] == status and r["message"]
    assert fx.notice_parcours_opened() == []
    pid = r["parcours_id"]
    assert r["url"] == f"/v1?p={pid}"
    seen = [r]

    s = client.get(f"/api/v1/parcours/{pid}").json()
    seen.append(s)
    assert s["phase"] == "sans_notice" and s["vehicle"] == {"manufacturer": None, "model": None, "generation": None}
    t = s["sans_notice"]
    assert (t["titre"], t["explication"], t["consignes"]) == tuple(vc.DRAFT_LABELS[k] for k in v1.SANS_NOTICE_LABEL_KEYS)
    assert t["message"] == r["message"] and t["screen"] is None
    assert t["draft_texts"] == vc.DRAFT_LABELS["draft_texts"]  # new texts: draft until the owner validates them
    assert [c["key"] for c in s["colours"]] == [k for k, _ in v1.COLOURS]

    # Nothing of a notice is reachable: no catalogue, no image, no consent, no selection, no restitution.
    entry = ManifestNoticeRepository(manifest).catalogue.entries[0] if manifest else None
    asset = f"/asset/{entry.image_sha256}" if entry else "/asset/" + "0" * 64
    for method, path, body in (("GET", "/catalogue", None), ("GET", "/propositions", None), ("GET", asset, None),
                               ("POST", "/vir-seen", {}), ("POST", "/consent", {"accepted": True}),
                               ("POST", "/propositions", {"recipient_consent": RECIPIENT, "photo_base64": ""}),
                               ("POST", "/selection", {"entry_ids": ["fx_red_fluid"]}),
                               ("POST", "/confirm", {"entry_ids": ["fx_red_fluid"], "confirmed": True}),
                               ("POST", "/clarify", {"group": 0, "answer": "dont_know"}),
                               ("POST", "/condition", {"key": "x#y", "answer": "confirmed"}),
                               ("POST", "/no-match", {"reason": "none_match", "entry_ids": []}),
                               ("POST", "/return", {})):
        out = client.request(method, f"/api/v1/parcours/{pid}{path}", json=body)
        assert out.status_code == 409, (path, out.status_code, out.text)
        seen.append(out.json())

    screens = v1.load_fallback_screens()["screens"]
    for colour, key in (("rouge", "red_or_uncertain"), ("incertain", "red_or_uncertain"), ("vert", "other_colour"),
                        ("orange", "other_colour")):
        out = client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": colour})
        assert out.status_code == 200, out.text
        screen = out.json()["screen"]
        assert screen == {"key": key, "lang": "fr", "heading": screens[key]["heading"],
                          "paragraphs": screens[key]["paragraphs"]}
        again = client.get(f"/api/v1/parcours/{pid}").json()
        assert again["colour"] == colour and again["sans_notice"]["screen"] == screen and again["phase"] == "sans_notice"
        seen += [out.json(), again]
    assert screens["red_or_uncertain"]["heading"].startswith("Arrêtez-vous en sécurité")
    assert client.post(f"/api/v1/parcours/{pid}/colour", json={"colour": "violet"}).status_code == 422

    # Never a word of the notice that does not correspond (nor of any notice).
    shown = json.dumps(seen, ensure_ascii=False)
    for text in notice_texts(manifest):
        assert text not in shown


def test_the_development_trial_entry_still_refuses_without_notice(monkeypatch, tmp_path, client):
    manifest = fx.build(tmp_path / "notice")
    monkeypatch.setattr(v1, "_wiring", v1.V1Wiring(repository=ManifestNoticeRepository(manifest), dev_trial=False))
    monkeypatch.setattr(v1, "_parcours", {})
    assert client.get("/v1/essai-dev", follow_redirects=False).status_code == 404


# --- 2. no free input ---------------------------------------------------------------------------------

class _Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.controls, self.screen = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self.screen = a.get("id")
        if tag in ("input", "textarea", "select", "button") or "contenteditable" in a:
            self.controls.append((self.screen, tag, a.get("type"), a.get("id") or a.get("class")))


def test_the_v1_page_has_no_free_input():
    p = _Controls()
    p.feed(v1.V1_HTML)
    inputs = {(screen, tag, kind, name) for screen, tag, kind, name in p.controls if tag != "button"}
    assert inputs == {("screen-consent", "input", "checkbox", "consent-box"),
                      ("screen-photo", "input", "file", "photo-input"),
                      ("screen-photo", "input", "checkbox", "propose-consent")}
    script = v1.V1_HTML.split("<script>", 1)[1]
    assert not re.search(r"""(createElement|make)\(\s*["'](input|textarea|select)["']""", script)
    assert "contenteditable" not in v1.V1_HTML.lower() and "prompt(" not in script


def test_a_typed_message_is_never_accepted(monkeypatch, tmp_path, client):
    from test_v1_premier_constat import confirm, wire
    wire(monkeypatch, fx.build(tmp_path / "grouped", with_groups=True))
    r = confirm(client, ["fx_red_belt_fixed"])
    assert r["phase"] == "clarification" and all(q["kind"] == "choice" for q in r["questions"])
    g = r["questions"][0]["group"]
    out = client.post(f"/api/v1/parcours/{r['pid']}/clarify", json={"group": g, "answer": "message", "message": "CODE"})
    assert out.status_code == 400  # only an entry of the group, « je ne sais pas » or « aucun de ceux-ci »


# --- 3. the legacy dialogue engines are never reached ----------------------------------------------------

@pytest.fixture
def forbidden(monkeypatch):
    from pgdr.application.diagnostic_loop import DiagnosticLoop
    from pgdr.complaint_parser import ComplaintParser
    from pgdr.session_controller import SessionController
    calls = []

    def trap(name):
        def refuse(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} reached from the V1 parcours")
        return refuse

    for cls in (SessionController, DiagnosticLoop, ComplaintParser):
        for attr in [a for a, v in vars(cls).items() if callable(v) and (a == "__init__" or not a.startswith("_"))]:
            monkeypatch.setattr(cls, attr, trap(f"{cls.__name__}.{attr}"))
    monkeypatch.setattr(web, "_session_controller", None)
    monkeypatch.setattr(web, "_get_or_create_controller", trap("web_app._get_or_create_controller"))
    for cls in (SessionController, DiagnosticLoop, ComplaintParser):   # the spies do fire
        with pytest.raises(AssertionError):
            cls()
    calls.clear()
    return calls


def test_the_whole_parcours_never_reaches_a_dialogue_engine(monkeypatch, tmp_path, client, forbidden):
    from test_v1_propositions import answer, png_with_metadata
    grouped = fx.build(tmp_path / "grouped", with_groups=True)
    tri = vp.FauxTransportTri(RECIPIENT, {}, {"texte": answer(["fx_red_belt_fixed", "fx_red_fluid"])})
    monkeypatch.setattr(v1, "_wiring", v1.build_wiring(ManifestNoticeRepository(grouped), dev_trial=True, tri=tri))
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    assert client.get("/v1").status_code == 200
    r = client.post("/api/v1/vir-handoff", headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN}, json={
        "resolution_id": "VIR-FICTIVE-CLOTURE", "resolution_status": "resolved", "vehicle_identity": fx.VIR_IDENTITY}).json()
    pid, api = r["parcours_id"], f"/api/v1/parcours/{r['parcours_id']}"

    def ok(method, path, body=None):
        out = client.request(method, api + path, json=body)
        assert out.status_code == 200, (path, out.text)
        return out.json()

    ok("GET", "")
    ok("POST", "/vir-seen", {})
    ok("POST", "/consent", {"accepted": True})
    proposed = ok("POST", "/propositions", {"recipient_consent": RECIPIENT,
                                            "photo_base64": base64.b64encode(png_with_metadata()).decode()})
    assert [e["entry_id"] for e in proposed["proposed"]["entries"]] == ["fx_red_fluid", "fx_red_belt_fixed"]
    ok("GET", "/propositions")
    ok("GET", "/catalogue")
    ok("POST", "/selection", {"entry_ids": ["fx_red_belt_fixed", "fx_red_fluid"]})
    out = ok("POST", "/confirm", {"entry_ids": ["fx_red_belt_fixed", "fx_red_fluid"], "confirmed": True})
    assert out["phase"] == "clarification"
    q = out["questions"][0]
    out = ok("POST", "/clarify", {"group": q["group"], "answer": q["choices"][0]["entry_id"]})
    assert out["phase"] == "restitution"
    for key in [s_["key"] for s_ in out["premier_constat"]["presentation"]["stops"]][:1]:
        ok("POST", "/condition", {"key": key, "answer": "unknown"})
    ok("POST", "/return", {})
    ok("POST", "/no-match", {"reason": "dont_know", "entry_ids": []})
    ok("POST", "/colour", {"colour": "incertain"})

    wire_3a(monkeypatch, None)                     # and without a notice
    refusal = handoff()
    client.post(f"/api/v1/parcours/{refusal['parcours_id']}/colour", json={"colour": "rouge"})
    assert forbidden == []


# --- 4. routes ------------------------------------------------------------------------------------------

def test_the_parcours_exposes_a_closed_list_of_routes():
    routes = {(m, r.path) for r in v1.router.routes for m in r.methods}
    assert routes == {
        ("POST", "/api/v1/vir-handoff"), ("GET", "/v1/essai-dev"), ("GET", "/v1"),
        ("GET", "/api/v1/parcours/{pid}"), ("GET", "/api/v1/parcours/{pid}/catalogue"),
        ("GET", "/api/v1/parcours/{pid}/propositions"), ("GET", "/api/v1/parcours/{pid}/asset/{sha}"),
        *{("POST", f"/api/v1/parcours/{{pid}}/{x}") for x in (
            "vir-seen", "consent", "propositions", "selection", "confirm", "clarify", "condition", "no-match",
            "colour", "return")},
    }
