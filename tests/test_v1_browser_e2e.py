"""V1 parcours — browser end-to-end (real uvicorn + real Chromium) on a
FICTIVE notice: VIR -> consent -> optional local photo -> complete catalogue
-> selection -> confirmation -> exact restitution, and both colour fallbacks
with « Revenir aux images ». The photo must never leave the browser and no
provider may be reached."""
from __future__ import annotations

import os
import socket
import threading
import re
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
import yaml
from playwright.sync_api import Page, expect

import v1_fictive_notice as fx
from pgdr import v1_parcours as v1
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
from pgdr.application.part1_first_finding import APPROVED_BANNERS, APPROVED_LABELS

_PORT = 8771
TOKEN = "v1-e2e-handoff-token"
BANNER = "Essai de développement — Applicabilité de cette notice au véhicule non confirmée"
ORDER: list[str] = []  # manual order, set from the fictive manifest


def _french_screens() -> dict:
    p = Path(__file__).resolve().parents[1] / "outils" / "preparation_v1" / "config" / "fallback_screens.fr.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))["screens"]


# Interface text = every text node and alt/title/placeholder/aria-label OUTSIDE an element
# whose lang is not French (manufacturer texts carry the notice language).
_UI_TEXT_JS = """() => {
  const out = [];
  const foreign = n => { const e = n.nodeType === 1 ? n : n.parentElement; const l = e && e.closest('[lang]'); return l && !l.lang.startsWith('fr'); };
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (n.parentElement.closest('script,style')) continue;
    if (!foreign(n) && n.textContent.trim()) out.push(n.textContent.trim());
  }
  for (const e of document.body.querySelectorAll('[alt],[title],[placeholder],[aria-label]'))
    for (const a of ['alt','title','placeholder','aria-label']) if (e.getAttribute(a) && !foreign(e)) out.push(e.getAttribute(a));
  out.push(document.title);
  return out;
}"""
# English-only words (no French homograph: « image », « page », « message », « source » are excluded).
_ENGLISH = re.compile(r"\b(the|and|of|is|warning|light|lights|return|manual|stop|safely|select|selection|"
                      r"confirm|none|match|unknown|don't|know|red|amber|yellow|green|blue|white|grey|fixed|flashing|"
                      r"continue|back|consent|take|your|vehicle|unresolved|human|verification|required|where|provided|"
                      r"switches|start-up|startup|field|sound|colour|color|choose|pictogram|printed|see|loading|error)\b",
                      re.I)


def test_english_detector_is_effective():
    for english in ("Return to manual images", "Stop safely — human verification required", "Fixed", "amber"):
        assert _ENGLISH.search(english), english
    for french in ("Revenir aux images de la notice", "Page de la notice : 84 (page PDF 86)", "Message affiché",
                   "Source du champ « signal sonore »", "s'allume au démarrage", "selon équipement"):
        assert not _ENGLISH.search(french), french


def _no_english_ui(page: Page) -> None:
    texts = page.evaluate(_UI_TEXT_JS)
    bad = [x for x in texts if _ENGLISH.search(x)]
    assert bad == [], bad


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    notice = fx.build(tmp_path_factory.mktemp("fictive") / "notice", with_groups=True)
    globals()["NOTICE"] = notice
    ORDER[:] = [e["entry_id"] for e in fx.load(notice)["entries"]]
    saved = (v1._wiring, os.environ.get(web.IDENTITY_HANDOFF_TOKEN_ENV), web._photo_wiring)
    v1._wiring = v1.build_wiring(ManifestNoticeRepository(notice), dev_trial=True,
                                 explanations_path=fx.build_explanations(notice),
                                 situations_path=fx.build_situations(notice))
    v1._parcours.clear()
    os.environ[web.IDENTITY_HANDOFF_TOKEN_ENV] = TOKEN
    web._photo_wiring = web.PhotoWiring()  # no interpretation provider at all
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
    page = context.new_page()
    yield page
    context.close()
    browser.close()


class Traffic:
    """Every request the page makes: proves the photo is never sent and that
    nothing but the local PGDR server is contacted."""

    def __init__(self, page: Page, base: str):
        self.base, self.requests = base, []
        page.on("request", lambda r: self.requests.append((r.method, r.url, r.post_data_buffer)))

    def assert_clean(self, photo: bytes):
        assert self.requests
        for method, url, body in self.requests:
            assert url.startswith(self.base) or url.startswith("blob:"), url
            assert url.startswith("blob:") or method in ("GET", "POST"), url
            if body:
                assert photo[:16] not in body and b"multipart" not in body.lower()


def _open(page: Page, base: str) -> None:
    r = httpx.post(f"{base}/api/v1/vir-handoff",
                   json={"resolution_id": "VIR-FICTIVE-E2E", "resolution_status": "resolved",
                         "vehicle_identity": fx.VIR_IDENTITY},
                   headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN})
    assert r.json()["status"] == "opened", r.text
    page.goto(base + r.json()["url"])


def _banner(page: Page) -> None:
    expect(page.locator("#dev-banner")).to_be_visible()
    expect(page.locator("#dev-banner")).to_have_text(BANNER)


def _to_catalogue(page: Page, photo: bytes | None) -> None:
    expect(page.locator("#screen-vir")).to_be_visible()
    expect(page.locator("#vir-vehicle")).to_contain_text("Fictiva")
    _banner(page)
    page.click("#vir-continue")
    expect(page.locator("#screen-consent")).to_be_visible()
    _banner(page)
    page.click("#consent-continue")  # without ticking: refused
    expect(page.locator("#consent-message")).to_contain_text("Sans votre accord")
    expect(page.locator("#screen-consent")).to_be_visible()
    page.check("#consent-box")
    page.click("#consent-continue")
    expect(page.locator("#screen-photo")).to_be_visible()
    _banner(page)
    if photo is not None:
        page.set_input_files("#photo-input", files=[{"name": "dash.png", "mimeType": "image/png", "buffer": photo}])
        expect(page.locator("#photo-preview")).to_be_visible()
        assert page.locator("#photo-preview").get_attribute("src").startswith("blob:")
    page.click("#photo-continue")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    _banner(page)


def _tiles(page: Page) -> list[str]:
    return page.locator("#catalogue-grid .tile").evaluate_all("ts => ts.map(t => t.dataset.entryId)")


def _pressed(page: Page) -> list[str]:
    return page.locator('#catalogue-grid .tile[aria-pressed="true"]').evaluate_all("ts => ts.map(t => t.dataset.entryId)")


def test_v1_complete_parcours_two_images_one_red(page: Page, live_server):
    photo = fx.png((12, 34, 56), 16)
    traffic = Traffic(page, live_server)
    _open(page, live_server)
    _to_catalogue(page, photo)
    assert _tiles(page) == ORDER  # complete, manual order
    _no_english_ui(page)
    expect(page.locator("#photo-compare")).to_be_visible()
    for img in page.locator("#catalogue-grid img").all():
        assert img.evaluate("i => i.complete && i.naturalWidth > 0")
    expect(page.locator("#selection-continue")).to_be_disabled()
    page.click('.tile[data-entry-id="fx_green_lamps"]')
    page.click('.tile[data-entry-id="fx_red_fluid"]')
    expect(page.locator("#selection-count")).to_have_text("2")
    page.click("#selection-continue")
    expect(page.locator("#screen-confirmation")).to_be_visible()
    _banner(page)
    assert page.locator("#confirmation-grid .tile").evaluate_all("ts => ts.map(t => t.dataset.entryId)") == [
        "fx_red_fluid", "fx_green_lamps"]
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    _banner(page)

    sections = page.locator("article.restitution")
    expect(sections).to_have_count(2)
    red, green = sections.nth(0), sections.nth(1)
    assert red.get_attribute("data-entry-id") == "fx_red_fluid"
    expect(red.locator("h2")).to_have_text("FICTIVE LOW FLUID")
    assert red.locator(".meaning").text_content() == fx.RED_MEANING
    expect(red.locator(".meaning img")).to_have_count(1)
    expect(red.locator(".where-provided")).to_have_text("selon équipement")
    expect(red.locator(".startup-check")).to_have_text("s'allume au démarrage")
    expect(red.locator(".startup-text")).to_contain_text(fx.RED_STARTUP)
    expect(red.locator(".warning")).to_have_count(1)
    assert red.locator(".warning .exact").text_content() == fx.SHARED_WARNING
    expect(red.locator(".warning")).to_contain_text("Avertissement 7)")
    expect(red.locator(".warning")).to_contain_text("Page de la notice : F-2 (page PDF 2)")
    expect(red).to_contain_text("Page de la notice : F-1 (page PDF 1)")
    expect(red).to_contain_text("Stop the fictive vehicle.")
    assert green.get_attribute("data-entry-id") == "fx_green_lamps"
    assert green.locator(".meaning").text_content() == fx.GREEN_MEANING
    expect(green.locator(".where-provided")).to_have_count(0)
    expect(green.locator(".startup-check")).to_have_count(0)
    expect(green.locator(".warning")).to_have_count(0)
    expect(green).to_contain_text("Page de la notice : F-2 (page PDF 2)")
    expect(page.locator("#language-note")).to_have_text(
        "Texte du constructeur reproduit dans la langue de la notice disponible (anglais).")
    expect(red).to_contain_text("Couleur : rouge")
    expect(red).to_contain_text("État : fixe")
    expect(page.locator(".notes")).to_have_count(0)
    expect(page.locator("#restitution details")).to_have_count(0)  # exact passages: never folded
    assert "Fictive curation note." not in page.locator("body").inner_text()
    _no_english_ui(page)

    # Premier Constat, separated from and above the exact passage, then T3/T8.
    pc = page.locator("#premier-constat")
    expect(pc.locator("h1")).to_have_text(
        "Premier Constat Constructeur — à partir des voyants sélectionnés par vous dans le catalogue. "
        "Aucune reconnaissance sur photo.")
    for hidden in ("PGDR-SAF", "emergency_stop", "do_not_drive", "monitor_and_document", "passage documenté"):
        assert hidden not in page.locator("body").inner_text()
    expect(pc.locator(".finding-entry")).to_have_count(2)
    red_pc = pc.locator('.finding-entry[data-entry-id="fx_red_fluid"]')
    expect(red_pc.locator(".selected")).to_contain_text("Voyant sélectionné par vous")
    expect(red_pc.locator(".draft-mention")).to_have_text("Explication en brouillon, non validée")
    expect(red_pc.locator(".part-maintenant")).to_contain_text("La note 7) demande d'arrêter le véhicule fictif")
    expect(red_pc.locator(".part-maintenant .citation").first).to_contain_text(fx.STOP_PHRASE)
    expect(red_pc.locator(".point-stop .point-label")).to_have_text(
        "Point pas encore vérifié par PGDR. Lisez la consigne du constructeur ci-dessous.")
    expect(red_pc.locator(".linked-warning span")).to_have_text(fx.SHARED_WARNING)
    expect(page.locator("#part1-t8")).to_have_text(APPROVED_BANNERS["T8"][0])
    order = page.evaluate("""() => ['premier-constat', 'restitution', 'part1-t8'].map(
        id => document.getElementById(id).getBoundingClientRect().top)""")
    assert order == sorted(order)
    expect(page.locator("#screen-restitution input, #screen-restitution select, #screen-restitution textarea")).to_have_count(0)
    _no_english_ui(page)
    traffic.assert_clean(photo)


def test_v1_premier_constat_with_validated_stop_classification(page: Page, live_server):
    """FICTIVE validated classification: the stop instruction of linked warning 7) is shown
    as its exact cited phrase, with no added action; green (covered, no warning) = absent."""
    w = v1._wiring
    saved = (w.findings, w.findings_status, w.findings_covered)
    w.findings = v1.load_v1_findings(fx.build_findings(NOTICE), w.repository)
    w.findings_status = "validated"
    w.findings_covered = frozenset(ORDER)
    try:
        _open(page, live_server)
        _to_catalogue(page, None)
        page.click('.tile[data-entry-id="fx_red_fluid"]')
        page.click('.tile[data-entry-id="fx_green_lamps"]')
        page.click("#selection-continue")
        page.click("#confirm")
        red = page.locator('#premier-constat .finding-entry[data-entry-id="fx_red_fluid"]')
        expect(red.locator(".point-stop blockquote")).to_have_text(fx.STOP_PHRASE)
        expect(red.locator(".point-professional blockquote")).to_have_text(fx.CONTACT_PHRASE)
        expect(red.locator(".point-operability .point-label")).to_have_text(
            "Point pas encore vérifié par PGDR. Lisez la consigne du constructeur ci-dessous.")
        green = page.locator('#premier-constat .finding-entry[data-entry-id="fx_green_lamps"]')
        expect(green.locator(".point-stop .point-label")).to_have_text("Cette information n'est pas établie dans les données disponibles.")
        body = page.locator("#premier-constat").inner_text().lower()
        for added in ("coupez le contact", "dépann", "reprenez pas la route", "ne roulez pas"):
            assert added not in body
        assert page.locator('article.restitution[data-entry-id="fx_red_fluid"] .warning .exact').text_content() == fx.SHARED_WARNING
        expect(page.locator("#part1-t8")).to_have_text(APPROVED_BANNERS["T8"][0])
        _no_english_ui(page)
    finally:
        w.findings, w.findings_status, w.findings_covered = saved


def test_v1_variant_group_question_then_ambiguity_belts_without_stop(page: Page, live_server):
    """Same image, two belt passages told apart by fixed/flashing: the driver answers. « Je ne sais
    pas » -> both belt situations are shown, complete; no stop screen from this ambiguity alone.
    An informative group with nothing distinctive -> ambiguity shown, no red offer."""
    _open(page, live_server)
    _to_catalogue(page, None)
    page.click('.tile[data-entry-id="fx_red_belt_fixed"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#screen-clarification")).to_be_visible()
    _banner(page)
    choices = page.locator("#clarification-questions button.choice")
    expect(choices).to_have_count(2)
    expect(choices.nth(0)).to_contain_text("État du voyant : fixe")
    expect(choices.nth(1)).to_contain_text("État du voyant : clignotant")
    expect(choices.nth(1)).to_contain_text("page de la notice F-4 (page PDF 4)")
    _no_english_ui(page)
    page.click("#clarification-questions button.dont-know-variant")
    expect(page.locator("#screen-restitution")).to_be_visible()
    block = page.locator("#premier-constat .ambiguous")
    expect(block).to_have_count(1)
    expect(block.locator(".limit")).to_have_text(
        "Avec les informations renseignées, nous ne pouvons pas déterminer laquelle de ces situations "
        "correspond à votre voyant.")
    expect(block.locator(".variant")).to_have_count(2)
    expect(block.locator(".variant").nth(0)).to_contain_text("Indiqué seulement pour : FICTIVE BELT")
    expect(block.locator(".variant").nth(0).locator(".meaning")).to_have_text(fx.BELT_MEANING_FIXED)
    expect(block.locator(".variant").nth(1).locator(".meaning")).to_have_text(fx.BELT_MEANING_FLASHING)
    expect(block.locator(".variant .situation-title")).to_have_text(["Ceinture fictive ouverte",
                                                                    "Ceinture fictive ouverte en roulant"])
    # Draft status: technical, kept in the block's folded « Détails » (one click), never removed.
    expect(block.locator(":scope > details.details > .draft-mention").first).to_be_attached()
    expect(block.locator(":scope > details.details > summary")).to_have_text("Détails")
    # Red belts, no stop documented: no stop screen, no urgent block, no red offer.
    expect(page.locator("#premier-constat .urgent")).to_have_count(0)
    expect(block.locator("button.red-offer")).to_have_count(0)
    expect(page.locator("#screen-restitution")).not_to_contain_text("Arrêtez-vous en sécurité")
    _no_english_ui(page)

    # Back to images, answer this time: only the driver's own choice is restituted.
    page.click("#screen-restitution button.return")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    page.click("#selection-continue")
    page.click("#confirm")
    page.click('#clarification-questions button.choice[data-entry-id="fx_red_belt_flashing"]')
    expect(page.locator("article.restitution")).to_have_count(1)
    assert page.locator("#restitution article.restitution").get_attribute("data-entry-id") == "fx_red_belt_flashing"
    expect(page.locator("#premier-constat .ambiguous")).to_have_count(0)

    # Informative group, nothing distinctive, no common text: ambiguity shown, no red offer.
    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_red_belt_fixed"]')
    page.click('.tile[data-entry-id="fx_blue_mode_x"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    block = page.locator("#premier-constat .ambiguous")
    expect(block.locator(".no-common")).to_have_text("Aucune information commune n'est citée par la notice pour ces voyants.")
    expect(block.locator("button.red-offer")).to_have_count(0)


def _restitution_for(page: Page, live_server, ids: list[str]) -> None:
    _open(page, live_server)
    _to_catalogue(page, None)
    for x in ids:
        page.click(f'.tile[data-entry-id="{x}"]')
    page.click("#selection-continue")
    page.click("#confirm")


def test_v1_operating_group_mixed_group_and_message_question(page: Page, live_server):
    """Operating indications: possibilities explained, no stop screen. Mixed group: the stop
    instruction stays visible under its own variant only. Message question: exact text, never mapped."""
    _restitution_for(page, live_server, ["fx_blue_mode_x"])
    expect(page.locator("#screen-restitution")).to_be_visible()
    block = page.locator("#premier-constat .ambiguous")
    expect(block.locator(".situation-fonctionnement_normal")).to_have_count(2)
    expect(block.locator(".situation-title")).to_have_text(["Mode X fictif choisi", "Mode Y fictif actif"])
    expect(page.locator("#premier-constat .urgent")).to_have_count(0)
    expect(block.locator("button.red-offer")).to_have_count(0)
    expect(page.locator("#screen-restitution")).not_to_contain_text("Arrêtez-vous en sécurité")
    _no_english_ui(page)

    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_blue_mode_x"]')
    page.click('.tile[data-entry-id="fx_red_alarm_b"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#screen-restitution")).to_be_visible()
    block = page.locator("#premier-constat .ambiguous")
    urgent = block.locator(".urgent")
    expect(urgent).to_be_visible()
    expect(urgent.locator(".urgent-variant")).to_have_count(1)
    assert urgent.locator(".urgent-variant").get_attribute("data-entry-id") == "fx_red_alarm_a"
    expect(urgent).to_contain_text("Indiqué seulement pour : FICTIVE ALARM — Perte de pression fictive")
    expect(urgent).to_contain_text(fx.ALARM_STOP)
    # Above the variants, and never under variant B.
    assert block.evaluate("b => !!(b.querySelector('.urgent').compareDocumentPosition(b.querySelector('.variant')) "
                          "& Node.DOCUMENT_POSITION_FOLLOWING)")
    expect(block.locator('.variant[data-entry-id="fx_red_alarm_b"]')).not_to_contain_text(fx.ALARM_STOP)
    expect(block.locator(".red-inline")).to_have_count(0)
    _no_english_ui(page)

    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_red_alarm_b"]')
    page.click('.tile[data-entry-id="fx_amber_code_a"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#screen-clarification")).to_be_visible()
    q = page.locator('#clarification-questions .question[data-kind="message"]')
    expect(q).to_contain_text("Un message s'affiche-t-il avec ce voyant ? Recopiez-le exactement.")
    expect(q.locator("button.message-none")).to_have_text("Aucun message / Je ne sais pas")
    _no_english_ui(page)
    q.locator("input.message-input").fill("CODE 12")
    q.locator("button.message-submit").click()
    expect(page.locator("#screen-restitution")).to_be_visible()
    block = page.locator("#premier-constat .ambiguous")
    expect(block.locator(".message-given")).to_have_text("Message renseigné par vous : « CODE 12 »")
    expect(block.locator(".variant")).to_have_count(2)
    expect(block.locator('.variant[data-entry-id="fx_amber_code_a"] .consigne')).to_contain_text(fx.CODE_A_INSTRUCTION)
    expect(block.locator('.variant[data-entry-id="fx_amber_code_b"]')).not_to_contain_text(fx.CODE_A_INSTRUCTION)
    expect(page.locator("#premier-constat .urgent")).to_have_count(0)


def test_v1_restart_procedure_expected_action_and_take_into_account(page: Page, live_server):
    """A documented temporary stop + wait + restart is shown as « Action attendue de votre part »,
    with its condition and page; a conditional stop of the same variant is shown apart, whole, under
    « Consigne applicable si… », without urgent title nor red button. « Signalement du véhicule »
    keeps the caution sentence when no instruction is cited."""
    _restitution_for(page, live_server, ["fx_red_steer_a"])
    expect(page.locator("#screen-restitution")).to_be_visible()
    block = page.locator("#premier-constat .ambiguous")
    action = block.locator(".expected-action")
    expect(action.locator("h3")).to_have_text("Action attendue de votre part")
    expect(action.locator(".action-variant")).to_have_count(1)
    expect(action.locator(".action-condition")).to_contain_text(fx.STEER_CONDITION)
    expect(action.locator(".action-quote").first).to_contain_text(fx.STEER_PROCEDURE)
    expect(action.locator(".action-quote").first).to_contain_text("page de la notice F-13 (page PDF 13)")
    expect(block.locator(".urgent")).to_have_count(0)
    cond = block.locator(".conditional")
    expect(cond.locator("h3")).to_have_text("Consigne applicable si…")
    expect(cond.locator(".conditional-condition")).to_contain_text("If the fictive steering light flashes")
    expect(cond.locator(".conditional-quote")).to_contain_text("If the fictive steering light flashes, stop the fictive vehicle at once.")
    expect(block.locator("button.red-offer")).to_have_count(0)
    q = cond.locator(".condition-question")
    expect(q.locator("p.label")).to_have_text("Cette condition correspond-elle à votre situation ?")
    expect(q.locator(".condition-answer")).to_have_text("Condition non renseignée : la consigne s'applique si la condition est remplie.")
    q.locator("button.condition-confirmed").click()
    block = page.locator("#premier-constat .ambiguous")
    expect(block.locator(".conditional .condition-answer")).to_have_text("Vous avez indiqué que cette condition est remplie.")
    expect(block.locator(".conditional .conditional-quote")).to_contain_text("If the fictive steering light flashes, stop the fictive vehicle at once.")
    expect(block.locator("button.red-offer")).to_have_count(1)  # confirmed stop: red screen offered, never automatic
    # Confirmed: at the top of the result, without any click, with its condition and source.
    top = page.locator("#premier-constat .confirmed-stops")
    expect(top.locator("h3")).to_have_text("Consigne d'arrêt applicable — condition confirmée par vous")
    expect(top.locator(".confirmed-condition")).to_contain_text("If the fictive steering light flashes")
    expect(top.locator(".confirmed-citation")).to_contain_text(
        "If the fictive steering light flashes, stop the fictive vehicle at once. — page de la notice F-14 (page PDF 14)")
    assert page.evaluate("() => document.querySelector('#premier-constat h1').nextElementSibling.classList.contains('confirmed-stops')")
    # Unknown stays unknown in the stops list (the procedure is not one).
    items = page.locator("#premier-constat .stops .stop-item")
    expect(items).to_have_count(1)
    expect(page.locator("#premier-constat .stops")).not_to_contain_text(fx.STEER_PROCEDURE)
    expect(block.locator('.variant[data-entry-id="fx_red_steer_a"] .action-label')).to_have_text("Action attendue de votre part :")
    _no_english_ui(page)

    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_red_steer_a"]')
    page.click('.tile[data-entry-id="fx_blue_frost"]')
    page.click("#selection-continue")
    page.click("#confirm")
    frost = page.locator('#premier-constat .finding-entry[data-entry-id="fx_blue_frost"]')
    sit = frost.locator(".situation")
    expect(sit.locator("h3")).to_have_text("Type de situation : Signalement du véhicule")
    # Generic caution (nothing critical, no condition, no stop in the passage): kept, folded in « Détails ».
    expect(sit.locator(".no-consigne")).to_have_count(0)
    expect(frost.locator(":scope > details.details .no-consigne")).to_have_text(
        "Aucune consigne n'est citée dans ce passage ; cela ne prouve pas l'absence de risque.")
    expect(page.locator("#screen-restitution")).not_to_contain_text("Vous pouvez rouler")


def test_v1_fallback_red_then_other_colour_with_return(page: Page, live_server):
    photo = fx.png((90, 10, 10), 16)
    traffic = Traffic(page, live_server)
    screens = _french_screens()
    _open(page, live_server)
    _to_catalogue(page, photo)
    page.click('.tile[data-entry-id="fx_white_cruise"]')

    # 1. « Aucune ne correspond » -> rouge -> red-or-uncertain screen (validated English).
    page.click("#none-match")
    expect(page.locator("#screen-colour")).to_be_visible()
    _banner(page)
    page.click('#colour-choices button[data-colour="rouge"]')
    expect(page.locator("#screen-fallback")).to_be_visible()
    _banner(page)
    expect(page.locator("#fallback-content h1")).to_have_text(screens["red_or_uncertain"]["heading"])
    assert page.locator("#fallback-content p").all_text_contents() == screens["red_or_uncertain"]["paragraphs"]
    assert page.locator("#fallback-content").get_attribute("lang") == "fr"
    expect(page.locator("#screen-fallback button.return")).to_have_text("Revenir aux images de la notice")
    _no_english_ui(page)

    # « Revenir aux images »: manual order, selection kept.
    page.click("#screen-fallback button.return")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    assert _tiles(page) == ORDER
    assert _pressed(page) == ["fx_white_cruise"]

    # 2. « Je ne sais pas » -> colour kept (rouge highlighted) -> vert -> other-colour screen.
    page.click("#dont-know")
    expect(page.locator('#colour-choices button[data-colour="rouge"]')).to_have_class("primary")
    page.click('#colour-choices button[data-colour="vert"]')
    expect(page.locator("#fallback-content h1")).to_have_text(screens["other_colour"]["heading"])
    assert page.locator("#fallback-content p").all_text_contents() == screens["other_colour"]["paragraphs"]
    _no_english_ui(page)

    # Back again: selection still kept; a NEW confirmation is required before any restitution.
    page.click("#screen-fallback button.return")
    expect(page.locator("#screen-catalogue")).to_be_visible()
    assert _pressed(page) == ["fx_white_cruise"]
    page.click("#selection-continue")
    expect(page.locator("#screen-confirmation")).to_be_visible()
    expect(page.locator("#screen-restitution")).to_be_hidden()
    page.click("#confirm")
    expect(page.locator("article.restitution")).to_have_count(1)
    expect(page.locator("article.restitution .where-provided")).to_have_text("selon équipement")

    body = page.locator("body").inner_text().lower()
    for phrase in ("vous pouvez rouler", "you may continue driving", "safe to drive", "a été contacté",
                   "has been contacted", "we have contacted"):
        assert phrase not in body
    traffic.assert_clean(photo)


def _visible_texts(loc) -> list[str]:
    return loc.evaluate_all("ns => ns.filter(n => n.checkVisibility()).map(n => n.textContent)")


def test_v1_presentation_rule_body_and_folded_details(page: Page, live_server):
    """Explain first, give the established action, then only the useful uncertainty; technical ones folded
    in « Détails » (citations and pages still there). Block order unchanged."""
    # Informative light: no instruction block, no technical uncertainty in the body.
    _restitution_for(page, live_server, ["fx_green_lamps"])
    e = page.locator('#premier-constat .finding-entry[data-entry-id="fx_green_lamps"]')
    expect(e.locator(".situation .no-consigne")).to_have_count(0)  # operating indication: caution sentence folded
    expect(e.locator(":scope > details.details .no-consigne")).to_have_text(
        "Aucune consigne n'est citée dans ce passage ; cela ne prouve pas l'absence de risque.")
    assert _visible_texts(e.locator(".point")) == [] and _visible_texts(e.locator(".draft-mention")) == []
    det = e.locator(":scope > details.details")
    expect(det.locator("summary")).to_have_text("Détails")
    expect(det.locator(".point")).to_have_count(4)
    det.locator("summary").click()
    expect(det.locator(".draft-mention").first).to_be_visible()
    expect(page.locator("#premier-constat .stops, #premier-constat .urgent")).to_have_count(0)
    _no_english_ui(page)

    # Two lighting functions: the variant uncertainty is shown (it changes the explanation), no safety screen.
    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_green_lamps"]')
    page.click('.tile[data-entry-id="fx_green_side_lights"]')
    page.click("#selection-continue")
    page.click("#confirm")
    block = page.locator("#premier-constat .ambiguous")
    expect(block.locator(".limit")).to_be_visible()
    expect(block.locator(".variant")).to_have_count(2)
    expect(page.locator("#premier-constat .urgent, #premier-constat .stops, button.red-offer")).to_have_count(0)

    # Brake group with a conditional stop: the stop stays visible above the variants, the uncertainty is shown.
    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_green_side_lights"]')
    page.click('.tile[data-entry-id="fx_red_pb_failure"]')
    page.click("#selection-continue")
    page.click("#confirm")
    block = page.locator("#premier-constat .ambiguous")
    expect(block.locator(".limit")).to_be_visible()
    expect(block.locator(".urgent")).to_be_visible()
    expect(block.locator(".urgent")).to_contain_text(fx.PB_FLUID_WARNING)
    assert block.evaluate("b => !!(b.querySelector('.urgent').compareDocumentPosition(b.querySelector('.variant')) "
                          "& Node.DOCUMENT_POSITION_FOLLOWING)")
    stops = page.locator("#premier-constat .stops")
    expect(stops.locator(".stop-item").first).to_be_visible()
    expect(stops.locator(".condition-answer").first).to_be_visible()
    expect(stops.locator(":scope > .draft-mention")).to_have_count(0)  # status folded in the block's « Détails »

    # Unknown condition: visible. Unvalidated condition with no dependent instruction: in « Détails ».
    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_red_pb_failure"]')
    page.click('.tile[data-entry-id="fx_red_steer_a"]')
    page.click("#selection-continue")
    page.click("#confirm")
    expect(page.locator("#premier-constat .conditional .condition-answer")).to_have_text(
        "Condition non renseignée : la consigne s'applique si la condition est remplie.")
    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_red_steer_a"]')
    page.click('.tile[data-entry-id="fx_amber_code_b"]')
    page.click("#selection-continue")
    page.click("#confirm")
    page.locator('#clarification-questions .question[data-kind="message"] button.message-none').click()
    v = page.locator('#premier-constat .variant[data-entry-id="fx_amber_code_b"]')
    q = v.locator(":scope > details.details .condition-quote")
    expect(q).to_have_count(1)
    expect(q).to_be_hidden()
    expect(q).to_contain_text("comes on with a dedicated message — page de la notice F-11 (page PDF 11)")
    order = page.evaluate("""() => ['premier-constat', 'restitution', 'part1-t8'].map(
        id => document.getElementById(id).getBoundingClientRect().top)""")
    assert order == sorted(order)
    _no_english_ui(page)


def test_v1_group_block_variant_explanations_first_and_caution_placement(page: Page, live_server):
    """Group block: what each variant concerns first (side by side, never merged), then the limit sentence.
    Caution sentence folded for an informative lighting group, kept in the body in a brake group."""
    _restitution_for(page, live_server, ["fx_green_side_lights"])
    block = page.locator("#premier-constat .ambiguous")
    heads = block.locator(":scope > .variant-explanations > .variant-explanation")
    expect(heads).to_have_count(2)
    expect(heads.nth(0)).to_contain_text("Indiqué seulement pour : FICTIVE SIDE LIGHTS — Feux de position fictifs allumés")
    expect(heads.nth(0)).to_contain_text("Type de situation : Indication de fonctionnement")
    first_text = block.evaluate("""b => [...b.children].filter(n => n.tagName !== 'IMG' && n.checkVisibility())[0].className""")
    assert first_text == "variant-explanations"
    assert block.evaluate("b => !!(b.querySelector('.variant-explanations').compareDocumentPosition(b.querySelector('.limit')) "
                          "& Node.DOCUMENT_POSITION_FOLLOWING)")
    expect(block.locator(".limit")).to_be_visible()
    assert _visible_texts(block.locator(".no-consigne")) == []
    expect(block.locator(".variant > details.details .no-consigne")).to_have_count(2)
    expect(page.locator("#premier-constat .urgent, button.red-offer")).to_have_count(0)
    _no_english_ui(page)

    page.click("#screen-restitution button.return")
    page.click('.tile[data-entry-id="fx_green_side_lights"]')
    page.click('.tile[data-entry-id="fx_red_pb_failure"]')
    page.click("#selection-continue")
    page.click("#confirm")
    block = page.locator("#premier-constat .ambiguous")
    expect(block.locator(":scope > .variant-explanations > .variant-explanation")).to_have_count(3)
    expect(block.locator(".urgent")).to_be_visible()
    expect(block.locator(".urgent")).to_contain_text(fx.PB_FLUID_WARNING)
    applied = block.locator('.variant[data-entry-id="fx_red_pb_applied"] .situation .no-consigne')
    expect(applied).to_be_visible()
    expect(applied).to_have_text("Aucune consigne n'est citée dans ce passage ; cela ne prouve pas l'absence de risque.")
    order = page.evaluate("""() => ['premier-constat', 'restitution', 'part1-t8'].map(
        id => document.getElementById(id).getBoundingClientRect().top)""")
    assert order == sorted(order)
    _no_english_ui(page)
