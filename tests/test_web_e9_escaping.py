"""E9 — aucune donnée n'est insérée brute dans le HTML de la page PGDR.

Le script de la page (`_PHOTO_HTML`) est EXÉCUTÉ dans Node.js avec un DOM minimal
simulé : on y injecte « <script> » et du HTML dans une observation (E9, ancienne ligne
1113) et dans tous les autres champs affichés, puis on vérifie que tout ressort échappé.
Un contrôle statique vérifie en plus que chaque insertion `${…}` dans un fragment HTML
passe par escapeHtml.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from pgdr import web_app

NODE = shutil.which("node")
PIEGE = '<script>alert("x")</script><img src=x onerror=alert(1)>'
APOSTROPHE = "');alert(1);//"


def _script() -> str:
    m = re.search(r"<script>(.*)</script>", web_app._PHOTO_HTML, re.S)
    assert m, "script de la page introuvable"
    return m.group(1)


HARNAIS = r"""
const vm = require('vm');
const elements = {};
function el(id) {
  if (!elements[id]) {
    elements[id] = {
      id, innerHTML: '', textContent: '', value: '', dataset: {}, style: {},
      classList: {add() {}, remove() {}, contains() { return false; }},
      insertAdjacentHTML(pos, h) { this.innerHTML += h; },
      addEventListener() {}, appendChild() {}, setAttribute() {},
      querySelectorAll() { return []; }, querySelector() { return null; },
    };
  }
  return elements[id];
}
const ctx = {
  console, URLSearchParams, JSON, String, Array, Object,
  window: {location: {search: '?intake=session-test'}},
  document: {getElementById: el, createElement: () => el('_tmp_' + Math.random()),
             addEventListener() {}, querySelectorAll() { return []; }},
  fetch: async () => ({ok: true, json: async () => ({})}),
  setTimeout() {}, alert() {},
};
vm.createContext(ctx);
vm.runInContext(SCRIPT + `
;globalThis.__f = {showReport, showSafetyAlert, showQuestion};`, ctx);
const P = PIEGE, A = APOSTROPHE;
const f = ctx.__f;
f.showSafetyAlert({level: P, user_instruction: P});
f.showQuestion({prompt: P, selection_reason: P, answer_type: 'single_choice',
                choices: [P, A]});
f.showReport({
  user_summary: {urgency: {label: P, explanation: P}, main_observations: [P],
                 next_actions: [P], disclaimer: [P]},
  garage_preparation_report: {customer_reported_problem: P,
    systems_to_examine: [{system_family: P, confidence: 0.8}],
    suggested_professional_checks: [P], unresolved_questions: [P],
    dashboard_identifications: [{origin: 'photo', description: P}]},
});
const out = {};
for (const [k, v] of Object.entries(elements)) { if (v.innerHTML) out[k] = v.innerHTML; }
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="Node.js indisponible")
def test_injected_script_and_html_come_out_escaped():
    code = (HARNAIS.replace("SCRIPT +", json.dumps(_script()) + " +")
            .replace("const P = PIEGE, A = APOSTROPHE;",
                     f"const P = {json.dumps(PIEGE)}, A = {json.dumps(APOSTROPHE)};"))
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rendus = json.loads(r.stdout)
    # les trois zones affichées ont bien été produites
    assert {"safety-alert", "question-container"} <= set(rendus)
    rapport = next(v for k, v in rendus.items() if "Observations principales" in v)
    tout = "".join(rendus.values())
    for brut in ("<script", "<img"):                   # aucune balise injectée brute
        assert brut not in tout, brut
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in rapport     # E9 : observation
    assert rapport.count("&lt;script&gt;") >= 9          # urgence, actions, garage, avertissement…
    assert "(confiance : 0.8)" in rapport                # un nombre reste lisible
    q = rendus["question-container"]
    assert "onclick=\"submitAnswer('" not in q           # plus de valeur dans un onclick
    assert 'data-choice="&#039;);alert(1);//"' in q


def test_every_html_insertion_goes_through_escape_html():
    """Garde statique : dans un fragment HTML (html = / html +=), chaque ${…}
    commence par escapeHtml(."""
    fautes = []
    for n, ligne in enumerate(_script().splitlines(), 1):
        if re.search(r"\bhtml\s*\+?=", ligne):
            for m in re.finditer(r"\$\{", ligne):
                if not ligne[m.end():].startswith("escapeHtml("):
                    fautes.append((n, ligne.strip()))
            if re.search(r"'\s*\+\s*(?!escapeHtml)[A-Za-z_]", ligne):
                if ".map(escapeHtml)" not in ligne:
                    fautes.append((n, ligne.strip()))
    assert fautes == []


def test_escape_html_handles_non_text_values():
    s = _script()
    assert "String(unsafe)" in s and "unsafe === null || unsafe === undefined" in s


CLIC = r"""
const vm = require('vm');
const decoder = s => s.replace(/&quot;/g, '"').replace(/&#039;/g, "'").replace(/&lt;/g, '<')
                      .replace(/&gt;/g, '>').replace(/&amp;/g, '&');     // décodage HTML d'un attribut
function el(id) {
  return {
    id, innerHTML: '', classList: {add() {}, remove() {}},
    addEventListener() {},
    // Boutons réellement produits par la page : attribut data-choice décodé comme le
    // ferait un navigateur, gestionnaire de clic mémorisé.
    querySelectorAll(sel) {
      if (sel !== '.choice-btn[data-choice]') return [];
      return [...this.innerHTML.matchAll(/<button class="choice-btn" data-choice="([^"]*)">/g)]
        .map(m => ({dataset: {choice: decoder(m[1])}, handlers: [],
                    addEventListener(t, f) { if (t === 'click') this.handlers.push(f); }}))
        .map(b => (boutons.push(b), b));
    },
  };
}
const boutons = [], elements = {};
const ctx = {console, URLSearchParams, JSON, String, Array, Object,
  window: {location: {search: '?intake=session-test'}},
  document: {getElementById: id => elements[id] || (elements[id] = el(id)),
             addEventListener() {}, querySelectorAll() { return []; }},
  fetch: async () => ({ok: true, json: async () => ({})}), setTimeout() {}};
vm.createContext(ctx);
vm.runInContext(SCRIPT, ctx);
const recus = [];
ctx.submitAnswer = v => recus.push(v);           // remplace l'envoi réel par un relevé
ctx.showQuestion({prompt: 'q', answer_type: 'single_choice', choices: CHOIX});
for (const b of boutons) for (const h of b.handlers) h();
process.stdout.write(JSON.stringify({recus, nb_boutons: boutons.length}));
"""


@pytest.mark.skipif(NODE is None, reason="Node.js indisponible")
def test_clicking_a_choice_submits_its_exact_value():
    choix = ["Oui, c'est l'essai", 'Il a dit "stop"', "<script>alert('x')</script>",
             "&amp; déjà encodé", "');alert(1);//"]
    code = CLIC.replace("SCRIPT", json.dumps(_script())).replace("CHOIX", json.dumps(choix))
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    sortie = json.loads(r.stdout)
    assert sortie["nb_boutons"] == len(choix)
    assert sortie["recus"] == choix                  # valeur EXACTE, octet pour octet
