"""V1 parcours — content layered over the verified notice, all prepared IN
ADVANCE (no model at run time):

  * V1 labels for the manual choice (owner wording, 2026-10-08). The photo
    parcours labels (APPROVED_LABELS / APPROVED_BANNERS) are not changed.
  * Variant groups: catalogue images that are the same picture but carry
    different passages. Automatic groups = identical image_sha256 only.
    Other groups come only from a VALIDATED groups file.
  * Explanations: three short French parts per entry (ce que la notice
    indique / quoi faire maintenant / ce qui reste inconnu). Every sentence
    carries an exact anchor in the passage, checked verbatim at load; an
    invalid anchor rejects that entry's explanation. A draft is shown only in
    the development trial, with a visible mention.
  * The V1 presentation of the Premier Constat: structured points show the
    cited phrase only (never an approved label that adds an action, e.g.
    « coupez le contact », « dépannage », « ne reprenez pas la route »).

Every file is bound to the catalogue content fingerprint; a mismatch means
the file is not used at all.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Optional

import yaml

from pgdr.adapters.manifest_notice_repository import NoticeCatalogue, NoticeEntry
from pgdr.models import EntryFinding

LABELS = {
    "selected": "Voyant sélectionné par vous",
    "absent": "Cette information n'est pas établie dans les données disponibles.",
    "unverified": "Point pas encore vérifié par PGDR. Lisez la consigne du constructeur ci-dessous.",
    "draft_explanation": "Explication en brouillon, non validée",
}
# V1 title, owner wording (2026-10-08), exact. The photo parcours keeps its own T2.
T2_V1 = ("Premier Constat Constructeur — à partir des voyants sélectionnés par vous dans le catalogue. "
         "Aucune reconnaissance sur photo.")
# Ambiguity limit, owner wording (2026-10-08), exact.
LIMIT_V1 = ("Avec les informations renseignées, nous ne pouvons pas déterminer laquelle de ces situations "
            "correspond à votre voyant.")
# New French texts for ambiguous pictograms: DRAFT, shown with DRAFT_LABELS["draft_texts"].
DRAFT_LABELS = {
    "common": "Indiqué par la notice pour tous ces voyants",
    "no_common": "Aucune information commune n'est citée par la notice pour ces voyants.",
    "only_for": "Indiqué seulement pour : ",
    "condition": "Condition",
    "not_documented": "non documenté",
    "red_offer": "Voir l'écran prévu pour un voyant rouge ou incertain",
    "draft_texts": "Textes de cette section en brouillon, non validés",
    "group_draft": "Groupe en brouillon, non validé",
    "urgent_title": "Consigne urgente possible — elle s'applique seulement si votre voyant correspond à cette situation",
    "action_title": "Action attendue de votre part",
    "conditional_title": "Consigne applicable si…",
    "condition_question": "Cette condition correspond-elle à votre situation ?",
    "condition_confirmed": "Oui",
    "condition_excluded": "Non",
    "condition_unknown": "Je ne sais pas",
    "condition_answer.confirmed": "Vous avez indiqué que cette condition est remplie.",
    "condition_answer.excluded": "Vous avez indiqué que cette condition n'est pas remplie. La consigne reste affichée.",
    "condition_answer.unknown": "Condition non renseignée : la consigne s'applique si la condition est remplie.",
    "stops_title": "Consignes d'arrêt de la notice et leur condition",
    "stop_question": "Cette consigne correspond-elle à votre situation ?",
    "stop_condition_none": "Condition d'application : non établie dans les données validées.",
    "stop_condition_draft": "Condition d'application (interprétation en brouillon, non validée) :",
    "stop_condition_validated": "Condition d'application :",
    "stop_confirmed_title": "Consigne d'arrêt applicable — condition confirmée par vous",
    "message_question": "Un message s'affiche-t-il avec ce voyant ? Recopiez-le exactement.",
    "message_submit": "Valider ce message",
    "message_none": "Aucun message / Je ne sais pas",
    "message_given": "Message renseigné par vous : ",
    "details": "Détails",
}
# Situation classification: the situation DESCRIBED by the passage, never the
# pictogram or its colour alone. Labels are DRAFT texts.
NATURES = ("fonctionnement_normal", "information_a_prendre_en_compte", "action_conducteur", "anomalie_defaut",
           "alerte_consigne_immediate", "situation_non_determinee")
NATURE_LABELS = {
    "fonctionnement_normal": "Indication de fonctionnement",
    "information_a_prendre_en_compte": "Signalement du véhicule",
    "action_conducteur": "Action attendue du conducteur",
    "anomalie_defaut": "Défaut signalé par la notice",
    "alerte_consigne_immediate": "Alerte avec consigne immédiate de la notice",
    "situation_non_determinee": "Situation non déterminée",
}
SITUATION_LABELS = {
    "type": "Type de situation",
    "justification": "Passage qui le justifie",
    "consigne": "Consigne du constructeur",
    "condition": "Si",
    "conditions": "Conditions d'application",
    "no_consigne": "Aucune consigne n'est citée dans ce passage ; cela ne prouve pas l'absence de risque.",
    "draft": "Classement de la situation en brouillon, non validé",
    "action": "Action attendue de votre part",
    "conditional": "Consigne applicable si…",
    "page": "page de la notice",
}
EXPLANATION_PARTS = (("indique", "Ce que la notice indique"), ("maintenant", "Quoi faire maintenant"),
                     ("inconnu", "Ce qui reste inconnu"))
ANCHOR_FIELDS = ("manufacturer_designation", "documented_meaning", "documented_instruction", "displayed_message",
                 "linked_warnings")
# A prepared sentence may never carry a permission to drive or a danger
# grading of its own (the manufacturer's own words stay in the citation).
FORBIDDEN = ("vous pouvez rouler", "vous pouvez continuer", "sans danger", "sans risque", "pas dangereux",
             "peu grave", "pas grave", "rien de grave", "aucun danger", "pouvez reprendre la route")
# A stop instruction names what is stopped (car, vehicle, motor, engine) or
# the pause; « stop lights » / « stop light(s) » / « STOP position » never.
_STOP_INSTRUCTION = re.compile(
    r"\bstop\b(?!\s+(lights?|lamps?|position)\b)\s+(?:(?:the|your)\s+)?(?:[\w-]+\s+){0,2}?(?:car|vehicle|motor|engine)s?\b"
    r"|\bstop\s+(?:to\s+pause|for\s+a\s+break)\b", re.I)
# A defect term of the notice. anomalie_defaut needs one in the entry's own
# passage (never the shared designation), not negated.
_FAILURE_TERM = re.compile(r"\b(fail\w*|fault\w*|malfunction\w*)", re.I)
_NEGATED_FAILURE = re.compile(r"\b(no|not|without|never)\s+(\w+\s+){0,2}(fail|fault|malfunction)", re.I)
# The one documented exception to the urgent presentation: an explicit
# temporary stop, a stated wait, then a restart. Presented as an action
# expected from the driver; the internal level is computed as before (R-5).
_RESTART_PROCEDURE = re.compile(r"\bstop\b.*\bfor\s+(about\s+|approximately\s+)?\d+\s+(seconds?|minutes?)\b.*\brestart",
                                re.I | re.S)


class ContentRejected(Exception):
    pass


def _header(raw: dict, catalogue: NoticeCatalogue) -> dict:
    header = (raw or {}).get("header") or {}
    if header.get("catalogue_content_sha256") != catalogue.content_sha256:
        raise ContentRejected("bound to another catalogue content")
    return header


def _validated(header: dict) -> bool:
    return header.get("status") == "VALIDE" and bool(header.get("validated_by")) and bool(header.get("validated_on"))


def _read(path) -> dict:
    try:
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ContentRejected(f"unreadable: {exc}") from None


def entry_texts(e: NoticeEntry, field: str) -> list[str]:
    if field == "linked_warnings":
        return [w.text for w in e.linked_warnings]
    value = {"manufacturer_designation": e.designation, "documented_meaning": e.documented_meaning,
             "documented_instruction": e.documented_instruction, "displayed_message": e.displayed_message}[field]
    return [value] if value else []


# --- variant groups -------------------------------------------------------------

def auto_groups(catalogue: NoticeCatalogue) -> list[tuple[str, ...]]:
    by_image: dict[str, list[str]] = defaultdict(list)
    for e in catalogue.entries:
        by_image[e.image_sha256].append(e.entry_id)
    return [tuple(ids) for ids in by_image.values() if len(ids) > 1]


def load_groups(path, catalogue: NoticeCatalogue, *, dev_trial: bool = False) -> tuple[list[tuple[str, ...]], bool]:
    """Candidate groups of visually identical images with different files.
    Returns (groups, draft). VALIDATED by name and bound to this catalogue:
    used everywhere. Draft: used ONLY in the development trial (marked)."""
    raw = _read(path)
    header = _header(raw, catalogue)
    if _validated(header):
        draft = False
    elif header.get("status") == "BROUILLON_NON_VALIDE" and dev_trial:
        draft = True
    else:
        raise ContentRejected("groups not validated")
    known = {e.entry_id for e in catalogue.entries}
    groups = []
    for g in raw.get("groups") or []:
        ids = tuple(g.get("entry_ids") or [])
        if len(ids) < 2 or len(set(ids)) != len(ids) or any(x not in known for x in ids):
            raise ContentRejected("invalid group")
        groups.append(ids)
    return groups, draft


def merge_groups(catalogue: NoticeCatalogue, *group_lists) -> list[tuple[str, ...]]:
    """Connected components of all groups, members in manual order."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            x = parent[x]
        return x

    for groups in group_lists:
        for g in groups:
            for x in g[1:]:
                parent[find(x)] = find(g[0])
    comps: dict[str, list[str]] = defaultdict(list)
    for e in catalogue.entries:
        if e.entry_id in parent:
            comps[find(e.entry_id)].append(e.entry_id)
    return [tuple(v) for v in comps.values() if len(v) > 1]


def distinguishing_fields(variants: list[NoticeEntry]) -> list[str]:
    """The documented fields that tell every variant apart: only fields the
    notice documents for EVERY variant (displayed message, fixed/flashing).
    Empty = the notice documents nothing distinctive."""
    fields = [f for f in ("displayed_message", "state")
              if all(getattr(v, f) not in (None, "unknown") for v in variants)]
    keys = [tuple(getattr(v, f) for f in fields) for v in variants]
    return fields if fields and len(set(keys)) == len(keys) else []


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def text_units(e: NoticeEntry) -> list[dict]:
    """Every manufacturer text of an entry, verbatim, as the units compared
    across variants: designation, each sentence of the meaning / instruction,
    displayed message, start-up sentence, each linked warning. With page."""
    page = {"printed_page": e.page_reference, "pdf_page": e.pdf_page}
    units = [{"field": "Désignation", "text": e.designation, **page}]
    for label, text in (("Texte de la notice", e.documented_meaning), ("Consigne", e.documented_instruction)):
        units += [{"field": label, "text": s, **page} for s in _SENTENCE.split(text or "") if s.strip()]
    if e.displayed_message:
        units.append({"field": "Message affiché", "text": e.displayed_message, **page})
    if e.documented_startup_check:
        units.append({"field": "Au démarrage", "text": e.documented_startup_check, **page})
    units += [{"field": f"Avertissement {w.number}", "text": w.text, "printed_page": w.printed_page,
               "pdf_page": w.pdf_page} for w in e.linked_warnings]
    return units


def common_texts(variants: list[NoticeEntry]) -> list[dict]:
    """Only the texts identical word for word in EVERY variant, with each
    variant's field and page. No synthesis, no generalisation."""
    per_variant = [{u["text"]: u for u in reversed(text_units(v))} for v in variants]
    out, seen = [], set()
    for u in text_units(variants[0]):
        t = u["text"]
        if t in seen or not all(t in pv for pv in per_variant):
            continue
        seen.add(t)
        out.append({"text": t, "sources": [{"entry_id": v.entry_id, "manual_order": v.manual_order, **{
            k: pv[t][k] for k in ("field", "printed_page", "pdf_page")}} for v, pv in zip(variants, per_variant)]})
    return out


def is_stop_instruction(text: str) -> bool:
    """A stop instruction asked of the driver, with its object (« stop the
    car », « stop the vehicle immediately », « stop the motor », « stop to
    pause »). Never the bare word: « stop lights », « STOP position »."""
    return bool(_STOP_INSTRUCTION.search(text))


def stop_cited(e: NoticeEntry, finding: Optional[EntryFinding] = None) -> bool:
    """A stop instruction is cited for this entry: a documented stop item of
    a validated classification, or a stop instruction in its passage or its
    linked warnings."""
    if finding is not None and finding.stop_vehicle_engine_off.basis.value == "documented":
        return True
    texts = [e.documented_meaning, e.documented_instruction or ""] + [w.text for w in e.linked_warnings]
    return any(is_stop_instruction(t) for t in texts)


def is_restart_procedure(text: str) -> bool:
    """Every stop of `text` belongs to a documented temporary stop + wait +
    restart procedure (sentence by sentence: another stop in the same unit
    keeps the whole unit urgent)."""
    stops = [s for s in _SENTENCE.split(text) if is_stop_instruction(s)]
    return bool(stops) and all(_RESTART_PROCEDURE.search(s) for s in stops)


def _sentences_with(e: NoticeEntry, phrase: str) -> list[str]:
    return [s for u in text_units(e) if u["field"] != "Désignation" for s in _SENTENCE.split(u["text"]) if phrase in s]


def consigne_is_action(e: NoticeEntry, phrase: str) -> bool:
    """Every sentence citing this instruction is a restart procedure."""
    found = _sentences_with(e, phrase)
    return bool(found) and all(_RESTART_PROCEDURE.search(s) for s in found)


def full_text(e: NoticeEntry, phrase: str) -> str:
    """The cited phrase widened to its whole sentence(s), verbatim: a stop
    instruction is never shortened."""
    for u in text_units(e):
        if u["field"] == "Désignation" or phrase not in u["text"]:
            continue
        t = u["text"]
        i = t.index(phrase)
        bounds = [0] + [m.end() for m in _SENTENCE.finditer(t)] + [len(t)]
        a = max(b for b in bounds if b <= i)
        z = min(b for b in bounds[1:] if b >= i + len(phrase))
        return t[a:z].strip()
    return phrase


def immediate_stop_item(e: NoticeEntry, phrase: str) -> bool:
    """For preparing a structured classification: may this cited phrase be
    recorded as the immediate stop item (stop_vehicle_engine_off)? Only a
    stop instruction that is not a restart procedure; a restart procedure or
    a conditional stop belongs to stop_conditions (cited, never removed)."""
    return is_stop_instruction(full_text(e, phrase)) and not consigne_is_action(e, phrase)


def failure_term(text: str) -> bool:
    return bool(_FAILURE_TERM.search(text)) and not _NEGATED_FAILURE.search(text)


def _covered(sentence: str, situation: Optional["Situation"]) -> bool:
    """A stop sentence presented elsewhere than as urgent: a documented
    restart procedure, or a CONDITIONAL stop instruction of a situation that
    is not an immediate alert (shown under « Consigne applicable si… »)."""
    if _RESTART_PROCEDURE.search(sentence):
        return True
    return situation is not None and any(
        c.conditional and (c.anchor.source_phrase in sentence or sentence in c.anchor.source_phrase)
        for c in situation.consignes)


def uncovered_stops(e: NoticeEntry, situation: Optional["Situation"]) -> list[str]:
    return [s for u in text_units(e) if u["field"] != "Désignation" for s in _SENTENCE.split(u["text"])
            if is_stop_instruction(s) and not _covered(s, situation)]


def action_passages(e: NoticeEntry, situation: Optional["Situation"] = None) -> list[dict]:
    """The expected actions of ONE entry, verbatim with page and condition:
    each restart procedure, and each instruction the classification presents
    as an expected action (never a stop instruction)."""
    out = []
    for u in text_units(e):
        if u["field"] == "Désignation":
            continue
        # Sentence by sentence: a restart procedure inside a mixed warning is shown too.
        for t in ([u["text"]] if is_restart_procedure(u["text"]) else
                  [x for x in _SENTENCE.split(u["text"]) if is_restart_procedure(x)]):
            if any(t == o["text"] for o in out):
                continue
            cond = next((c.condition for c in (situation.consignes if situation else ())
                         if c.condition is not None and c.anchor.source_phrase in t), None)
            out.append({**u, "text": t, "condition": None if cond is None else {
                "text": cond.source_phrase, "printed_page": cond.printed_page, "pdf_page": cond.pdf_page}})
    for c in (situation.consignes if situation else ()):
        if c.action and not consigne_is_action(e, c.anchor.source_phrase) and not any(c.anchor.source_phrase in o["text"] for o in out):
            out.append({"field": "Consigne", "text": c.anchor.source_phrase, "printed_page": c.anchor.printed_page,
                        "pdf_page": c.anchor.pdf_page, "condition": None if c.condition is None else {
                            "text": c.condition.source_phrase, "printed_page": c.condition.printed_page,
                            "pdf_page": c.condition.pdf_page}})
    return out


CONDITION_ANSWERS = ("confirmed", "excluded", "unknown")


def consigne_key(entry_id: str, index: int) -> str:
    return f"{entry_id}#{index}"


def condition_answer(answers: Optional[Mapping[str, str]], key: str) -> str:
    """What the driver said about one condition; never assumed: unknown by default."""
    a = (answers or {}).get(key)
    return a if a in CONDITION_ANSWERS else "unknown"


def conditional_passages(e: NoticeEntry, situation: Optional["Situation"] = None,
                         answers: Optional[Mapping[str, str]] = None) -> list[dict]:
    """Conditional stop instructions of ONE entry (not an immediate alert):
    exact condition, then the whole instruction with its page, the key of
    the condition and what the driver said about it (unknown by default)."""
    out = []
    for i, c in enumerate(situation.consignes if situation else ()):
        if not c.conditional:
            continue
        key = stop_key(e.entry_id, _first_stop_sentence(c.full))
        answer = condition_answer(answers, key)
        out.append({"condition": {"text": c.condition.source_phrase, "printed_page": c.condition.printed_page,
                                  "pdf_page": c.condition.pdf_page},
                    "text": c.full, "printed_page": c.anchor.printed_page, "pdf_page": c.anchor.pdf_page,
                    "key": key, "answer": answer, "answer_label": DRAFT_LABELS[f"condition_answer.{answer}"]})
    return out


def consigne_kind(c: "Consigne") -> str:
    """The nature of the action asked by the manufacturer — from the
    classification's structure, never from the bare word « stop », the
    colour or the type label."""
    if c.restart:
        return "restart_procedure"
    if c.action:
        return "expected_action"
    if c.conditional:
        return "conditional_stop"
    if is_stop_instruction(c.full):
        return "immediate_stop"
    return "instruction"


def internal_consignes(e: NoticeEntry, situation: Optional["Situation"], variant: str,
                       answers: Optional[Mapping[str, str]] = None) -> list[dict]:
    """Every instruction of ONE entry as transmitted internally: its nature,
    exact condition, the variant status (selected / possible), the whole
    citation with its page, and the driver's answer on the condition."""
    out = []
    for i, c in enumerate(situation.consignes if situation else ()):
        kind = consigne_kind(c)
        key = consigne_key(e.entry_id, i)
        out.append({
            "key": key, "entry_id": e.entry_id, "variant": variant, "kind": kind,
            "citation": {"text": c.full, "source_field": c.anchor.source_field, "source_phrase": c.anchor.source_phrase,
                         "printed_page": c.anchor.printed_page, "pdf_page": c.anchor.pdf_page},
            "condition": None if c.condition is None else {
                "text": c.condition.source_phrase, "source_field": c.condition.source_field,
                "printed_page": c.condition.printed_page, "pdf_page": c.condition.pdf_page},
            "stop_key": stop_key(e.entry_id, _first_stop_sentence(c.full)) if kind in ("conditional_stop", "immediate_stop") else None,
            "condition_status": (condition_answer(answers, stop_key(e.entry_id, _first_stop_sentence(c.full)))
                                 if kind == "conditional_stop" else "stated" if c.condition is not None else "none"),
        })
    return out


def urgent_passages(e: NoticeEntry, situation: Optional["Situation"] = None) -> list[dict]:
    """The urgent instructions documented for ONE entry, verbatim with page:
    every unit citing a stop instruction (passage or linked warning), plus
    the instruction of a situation classified alerte_consigne_immediate (a
    classification can add urgency, never remove it). A unit leaves this
    list only when each of its stop sentences is a restart procedure or a
    conditional instruction shown, whole, under « Consigne applicable si… »."""
    out = [{**u} for u in text_units(e) if u["field"] != "Désignation" and is_stop_instruction(u["text"])
           and not all(_covered(s, situation) for s in _SENTENCE.split(u["text"]) if is_stop_instruction(s))]
    if situation is not None and situation.nature == "alerte_consigne_immediate":
        for c in situation.consignes:
            if c.action:
                continue
            if not any(c.anchor.source_phrase in u["text"] for u in out):
                out.append({"field": "Consigne", "text": c.anchor.source_phrase, "printed_page": c.anchor.printed_page,
                            "pdf_page": c.anchor.pdf_page})
    return out


def red_offer(variants: list[NoticeEntry], findings: Mapping[str, EntryFinding],
              situations: Optional[Mapping[str, "Situation"]] = None) -> bool:
    """An ambiguous group keeps the red/uncertain screen on offer (a button,
    never automatic) only when a variant documents an urgent instruction
    (a validated stop item, or an urgent passage). Never from ambiguity or
    colour alone, nor from a conditional instruction shown apart."""
    situations = situations or {}
    return any((findings.get(v.entry_id) is not None
                and (findings[v.entry_id].stop_vehicle_engine_off.basis.value == "documented"
                     or any(cs.condition_status.value == "confirmed" for cs in findings[v.entry_id].conditional_stops)))
               or urgent_passages(v, situations.get(v.entry_id)) for v in variants)


def stop_key(entry_id: str, sentence: str) -> str:
    return f"{entry_id}#{hashlib.sha256(sentence.encode()).hexdigest()[:10]}"


_FIELD_OF_UNIT = {"Texte de la notice": "documented_meaning", "Consigne": "documented_instruction"}


def catalogue_stops(e: NoticeEntry) -> list[dict]:
    """The stop instructions of ONE entry, read from the reviewed manufacturer
    text itself (no presentation classification needed): each whole sentence,
    its field and page. A restart procedure is not a stop instruction here."""
    out, seen = [], set()
    for u in text_units(e):
        field = _FIELD_OF_UNIT.get(u["field"]) or ("linked_warnings" if u["field"].startswith("Avertissement") else None)
        if field is None:
            continue
        for sentence in _SENTENCE.split(u["text"]):
            sentence = sentence.strip()
            if not is_stop_instruction(sentence) or _RESTART_PROCEDURE.search(sentence) or sentence in seen:
                continue
            seen.add(sentence)
            out.append({"key": stop_key(e.entry_id, sentence), "text": sentence, "source_field": field,
                        "printed_page": u["printed_page"], "pdf_page": u["pdf_page"]})
    return out


def stop_condition(stop: dict, situation: Optional["Situation"]) -> Optional[tuple["Consigne", bool]]:
    """The condition a structured preparation pairs with this stop sentence, and
    whether that pairing is validated. None when no preparation gives one."""
    for c in (situation.consignes if situation else ()):
        if c.restart or c.condition is None:
            continue
        if c.anchor.source_phrase in stop["text"] or stop["text"] in c.full:
            return c, situation.conditions_validated
    return None


def _first_stop_sentence(full: str) -> str:
    return next((x.strip() for x in _SENTENCE.split(full) if is_stop_instruction(x)), full)


_MESSAGE_WORD = re.compile(r"\bmessages?\b", re.I)


def mentions_message(e: NoticeEntry) -> bool:
    return bool(e.displayed_message) or any(_MESSAGE_WORD.search(t or "") for t in (e.documented_meaning, e.documented_instruction))


def message_question(variants: list[NoticeEntry], situations: Mapping[str, "Situation"]) -> bool:
    """Ask for the displayed message only where the notice speaks of a message
    for some variants and not all of them, and the variants are not all
    classified as operating indications."""
    some = [mentions_message(v) for v in variants]
    if not any(some) or all(some):
        return False
    return not all(situations.get(v.entry_id) is not None and situations[v.entry_id].nature == "fonctionnement_normal"
                   for v in variants)


def _norm_message(t: str) -> str:
    return " ".join(t.split()).casefold()


def message_match(variants: list[NoticeEntry], message: str) -> Optional[str]:
    """Exact match only (spacing and case aside) with a DOCUMENTED displayed
    message. Never inferred from a description of a message."""
    hits = [v.entry_id for v in variants if v.displayed_message and _norm_message(v.displayed_message) == _norm_message(message)]
    return hits[0] if len(hits) == 1 else None


# --- uncertainties of the presentation -------------------------------------------
# What each uncertainty of the result touches. In the body of the screen when its
# resolution can change the explanation of the situation, the action to take or the
# applicability of a safety instruction; only a purely TECHNICAL one goes to the
# folded « Détails », always with its reason. Internal data (API), never displayed.
UNCERTAINTY_POINTS = ("explication", "action", "applicabilite_consigne", "technique")
DETAILS_REASONS = {
    "draft_status": "statut de brouillon d'un texte ou d'un classement : ne change ni l'explication, ni l'action, "
                    "ni l'applicabilité d'une consigne",
    "unverified_point": "point structuré pas encore vérifié par PGDR : les consignes citées restent affichées "
                        "(classement de la situation, texte du constructeur)",
    "stop_shown_with_condition": "point structuré pas encore vérifié par PGDR : chaque consigne d'arrêt du passage est "
                                 "affichée avec sa condition dans « Consignes d'arrêt de la notice »",
    "point_not_established": "point sans objet : aucune donnée établie et aucune consigne citée n'en dépend",
    "condition_without_consigne": "interprétation non validée d'une condition dont aucune consigne ne dépend",
    "generic_caution": "précaution générique : aucune consigne citée, sans variante critique, consigne d'arrêt dans le "
                       "passage, consigne conditionnelle, condition inconnue ni situation non déterminée ; la phrase ne "
                       "change ni l'explication, ni l'action, ni l'applicabilité d'une consigne",
}
# Why an uncertainty that could have been folded stays in the body (internal, never displayed).
BODY_REASONS = {
    "stop_in_passage": "le passage cite une consigne d'arrêt",
    "critical_variant": "le groupe contient une variante critique (consigne d'arrêt ou alerte immédiate)",
    "conditional_consigne": "le groupe contient une consigne conditionnelle",
    "condition_unknown": "une condition reste non renseignée",
    "undetermined_situation": "une situation du groupe est non déterminée ou non classée",
    "defect_without_instruction": "défaut signalé par la notice sans aucune consigne citée : l'action reste inconnue",
}


def uncertainty(kind: str, point: str, *, reason: Optional[str] = None, **where) -> dict:
    """One uncertainty of the result and what it touches. In case of doubt it is
    shown: « Détails » only for a technical point with a known reason."""
    if point not in UNCERTAINTY_POINTS:
        raise ValueError(f"unknown point {point!r}")
    details = point == "technique" and reason in DETAILS_REASONS
    return {"kind": kind, "point": point, "placement": "details" if details else "corps",
            **({"reason": reason, "reason_text": DETAILS_REASONS[reason]} if details else {}), **where}


# --- situation classification ---------------------------------------------------

@dataclass(frozen=True)
class Anchor:
    source_field: str
    source_phrase: str
    printed_page: str
    pdf_page: int


@dataclass(frozen=True)
class Consigne:
    anchor: Anchor
    condition: Optional[Anchor]
    action: bool = False  # restart procedure, or presented as an expected action
    restart: bool = False  # documented temporary stop + wait + restart procedure
    conditional: bool = False  # conditional stop instruction, not an immediate alert
    full: str = ""  # the whole sentence(s) of the instruction, verbatim


@dataclass(frozen=True)
class Situation:
    nature: str
    justification: Anchor
    consignes: tuple[Consigne, ...]
    conditions: tuple[Anchor, ...]
    title: Optional[str]
    draft: bool
    # The structured preparation of instructions and conditions is approved SEPARATELY
    # from the presentation classification (header « structured_consignes »).
    conditions_validated: bool = False


def _anchor(e: NoticeEntry, raw) -> Anchor:
    if not isinstance(raw, dict):
        raise ContentRejected("anchor required")
    field, phrase = raw.get("source_field"), raw.get("source_phrase")
    if field not in ANCHOR_FIELDS or not isinstance(phrase, str) or not phrase:
        raise ContentRejected("invalid anchor")
    if field == "linked_warnings":
        w = next((w for w in e.linked_warnings if phrase in w.text), None)
        if w is None:
            raise ContentRejected(f"anchor not verbatim in linked_warnings: {phrase!r}")
        return Anchor(field, phrase, w.printed_page, w.pdf_page)
    if not any(phrase in t for t in entry_texts(e, field)):
        raise ContentRejected(f"anchor not verbatim in {field}: {phrase!r}")
    return Anchor(field, phrase, e.page_reference, e.pdf_page)


def load_situations(path, catalogue: NoticeCatalogue, *, dev_trial: bool) -> tuple[dict[str, Situation], dict[str, str], str]:
    """Situation classification per entry. Returns (usable by entry_id,
    rejected entry_id -> reason, status). VALIDATED by name and bound to this
    catalogue: used everywhere. Draft: development trial only, marked. A
    validated explanation never validates a classification."""
    raw = _read(path)
    header = _header(raw, catalogue)
    if _validated(header):
        draft, status = False, "validated"
    elif header.get("status") == "BROUILLON_NON_VALIDE" and dev_trial:
        draft, status = True, "draft_dev_trial"
    else:
        raise ContentRejected("situations not validated")
    sc = header.get("structured_consignes") or {}
    # Named, separate approval of the instructions/conditions preparation; never implied by
    # an exact citation nor by the presentation classification's own approval.
    conditions_validated = bool(isinstance(sc, dict) and sc.get("status") == "VALIDE" and sc.get("validated_by")
                                and sc.get("validated_on"))
    out, rejected = {}, {}
    for entry_id, d in (raw.get("entries") or {}).items():
        e = catalogue.entry(entry_id)
        try:
            if e is None or not isinstance(d, dict):
                raise ContentRejected("unknown entry")
            nature = d.get("nature")
            if nature not in NATURES:
                raise ContentRejected("unknown nature")
            consignes = []
            for c in d.get("consignes") or []:
                anchor = _anchor(e, c)
                cond = _anchor(e, c["condition"]) if c.get("condition") else None
                full = full_text(e, anchor.source_phrase)
                restart = consigne_is_action(e, anchor.source_phrase)
                if c.get("presentation") not in (None, "action_attendue"):
                    raise ContentRejected("unknown presentation")
                if c.get("presentation") == "action_attendue" and is_stop_instruction(full) and not restart:
                    raise ContentRejected("a stop instruction is never presented as a plain action")
                consignes.append(Consigne(anchor, cond, action=restart or c.get("presentation") == "action_attendue",
                                          conditional=(cond is not None and is_stop_instruction(full) and not restart
                                                       and nature != "alerte_consigne_immediate"),
                                          full=full, restart=restart))
            consignes = tuple(consignes)
            if nature == "alerte_consigne_immediate" and not consignes:
                raise ContentRejected("an immediate alert needs its exact instruction")
            just = _anchor(e, d.get("justification"))
            probe = Situation(nature, just, consignes, (), None, draft)
            if nature in ("fonctionnement_normal", "information_a_prendre_en_compte", "action_conducteur",
                          "anomalie_defaut") and uncovered_stops(e, probe):
                # A stop instruction is never left out: only a conditional one, shown apart under its exact
                # condition, or a restart procedure, leaves the type free.
                raise ContentRejected("stop instruction not shown under its condition")
            if nature == "information_a_prendre_en_compte" and failure_term(just.source_phrase):
                raise ContentRejected("failure term: not an information to take into account")
            if nature == "anomalie_defaut":
                # Reserved to a defect the passage itself names, without a stop instruction.
                if just.source_field == "manufacturer_designation" or not failure_term(just.source_phrase):
                    raise ContentRejected("defect needs a failure term in the entry's own passage")
            title = d.get("intitule")
            if title is not None and (not isinstance(title, str) or not title.strip()
                                      or any(f in title.lower() for f in FORBIDDEN)):
                raise ContentRejected("invalid title")
            out[entry_id] = Situation(nature, just, consignes,
                                      tuple(_anchor(e, c) for c in d.get("conditions") or []), title, draft,
                                      conditions_validated)
        except ContentRejected as exc:
            rejected[entry_id] = str(exc)
    return out, rejected, status


def no_consigne_uncertainty(e: NoticeEntry, st: Optional[Situation],
                            group: Optional[list[tuple[NoticeEntry, Optional[Situation]]]] = None,
                            answers: Optional[Mapping[str, str]] = None) -> Optional[dict]:
    """The caution sentence « Aucune consigne n'est citée… ». The criterion is the usefulness of the
    uncertainty, never the situation type alone: folded in « Détails » when it is only a generic caution
    (no critical variant, no stop in the passage, no conditional instruction, no unknown condition, no
    undetermined situation); kept in the body as soon as it says something useful about the action or
    safety. In case of doubt: body. Placement and reason are traced."""
    if st is None or st.consignes:
        return None
    others = group or [(e, st)]
    body = []
    if st.nature == "anomalie_defaut":
        body.append("defect_without_instruction")  # a reported defect with no instruction: the action is unknown
    if catalogue_stops(e):
        body.append("stop_in_passage")
    for v, s in others:
        if s is None or s.nature == "situation_non_determinee":
            body.append("undetermined_situation")
        if s is not None and (s.nature == "alerte_consigne_immediate" or urgent_passages(v, s)) or catalogue_stops(v):
            body.append("critical_variant")
        if s is not None and any(c.conditional for c in s.consignes):
            body.append("conditional_consigne")
            if any(condition_answer(answers, stop_key(v.entry_id, _first_stop_sentence(c.full))) == "unknown"
                   for c in s.consignes if c.conditional):
                body.append("condition_unknown")
    if not body:
        return uncertainty("situation.no_consigne", "technique", reason="generic_caution")
    reasons = list(dict.fromkeys(body))
    point = "applicabilite_consigne" if {"critical_variant", "conditional_consigne", "condition_unknown"} & set(reasons) else "action"
    return uncertainty("situation.no_consigne", point, body_reasons=reasons,
                       body_reason_texts=[BODY_REASONS[r] for r in reasons])


def present_situation(st: Optional[Situation], entry_id: Optional[str] = None,
                      answers: Optional[Mapping[str, str]] = None, no_consigne_placement: str = "corps") -> Optional[dict]:
    if st is None:
        return None

    def answer(i, c) -> dict:
        if not (c.conditional and entry_id):
            return {}
        key = stop_key(entry_id, _first_stop_sentence(c.full))
        a = condition_answer(answers, key)
        return {"key": key, "answer": a, "answer_label": DRAFT_LABELS[f"condition_answer.{a}"]}

    def a(x: Anchor) -> dict:
        return {"text": x.source_phrase, "printed_page": x.printed_page, "pdf_page": x.pdf_page}

    return {
        "nature": st.nature, "label": NATURE_LABELS[st.nature], "title": st.title,
        "mention": SITUATION_LABELS["draft"] if st.draft else None,
        "mention_placement": "details" if st.draft else None,
        "validation": "brouillon" if st.draft else "validé",
        "justification": a(st.justification),
        "consignes": [{"consigne": {**a(c.anchor), "text": c.full} if c.conditional else a(c.anchor),
                       "condition": a(c.condition) if c.condition else None,
                       "label": (SITUATION_LABELS["action"] if c.action else SITUATION_LABELS["conditional"]
                                 if c.conditional else SITUATION_LABELS["consigne"]),
                       "action": c.action, "conditional": c.conditional, **answer(i, c)}
                      for i, c in enumerate(st.consignes)],
        "conditions": [{**a(c), "placement": (u or {}).get("placement", "corps")}
                       for c in st.conditions for u in [_condition_uncertainty(st, c)]],
        "no_consigne": None if st.consignes else SITUATION_LABELS["no_consigne"],
        "no_consigne_placement": None if st.consignes else no_consigne_placement,
    }


def _condition_uncertainty(st: Situation, c: Anchor) -> Optional[dict]:
    """A condition of the situation whose interpretation is not validated. When an
    instruction depends on it, it touches that instruction's applicability (body);
    otherwise it is technical (« Détails »)."""
    if not st.draft and st.conditions_validated:
        return None
    if any(k.condition is not None and k.condition.source_phrase == c.source_phrase for k in st.consignes):
        return uncertainty("situation.condition", "applicabilite_consigne", condition=c.source_phrase)
    return uncertainty("situation.condition", "technique", reason="condition_without_consigne", condition=c.source_phrase)


def situation_uncertainties(st: Optional[Situation], entry_id: str,
                            answers: Optional[Mapping[str, str]] = None) -> list[dict]:
    if st is None:
        return []
    out = [uncertainty("situation.draft", "technique", reason="draft_status")] if st.draft else []
    out += [u for c in st.conditions for u in [_condition_uncertainty(st, c)] if u]
    for c in st.consignes:
        if c.conditional:
            key = stop_key(entry_id, _first_stop_sentence(c.full))
            if condition_answer(answers, key) == "unknown":
                out.append(uncertainty("consigne.condition_unknown", "applicabilite_consigne", key=key,
                                       condition=c.condition.source_phrase))
    return out


# --- explanations ---------------------------------------------------------------

@dataclass(frozen=True)
class Sentence:
    text: str
    source_field: str
    source_phrase: str


@dataclass(frozen=True)
class Explanation:
    parts: Mapping[str, tuple[Sentence, ...]]
    draft: bool


def load_explanations(path, catalogue: NoticeCatalogue, *, dev_trial: bool) -> tuple[dict[str, Explanation], dict[str, str], str]:
    """Returns (usable explanations by entry_id, rejected entry_id -> reason,
    status). A draft is usable only in the development trial; a validated
    file needs a named validation bound to this catalogue."""
    raw = _read(path)
    header = _header(raw, catalogue)
    if _validated(header):
        draft, status = False, "validated"
    elif header.get("status") == "BROUILLON_NON_VALIDE" and dev_trial:
        draft, status = True, "draft_dev_trial"
    else:
        raise ContentRejected("explanations not validated")
    out, rejected = {}, {}
    for entry_id, parts in (raw.get("entries") or {}).items():
        e = catalogue.entry(entry_id)
        try:
            if e is None:
                raise ContentRejected("unknown entry")
            if not isinstance(parts, dict) or set(parts) != {k for k, _ in EXPLANATION_PARTS}:
                raise ContentRejected("three parts required")
            built = {}
            for key, _ in EXPLANATION_PARTS:
                sentences = []
                for s in parts[key] or []:
                    text, field, phrase = s.get("texte"), s.get("source_field"), s.get("source_phrase")
                    if not isinstance(text, str) or not text.strip() or field not in ANCHOR_FIELDS:
                        raise ContentRejected("invalid sentence")
                    if not isinstance(phrase, str) or not phrase or not any(phrase in t for t in entry_texts(e, field)):
                        raise ContentRejected(f"anchor not verbatim in {field}: {phrase!r}")
                    if any(f in text.lower() for f in FORBIDDEN):
                        raise ContentRejected("forbidden wording")
                    sentences.append(Sentence(text, field, phrase))
                if not sentences:
                    raise ContentRejected(f"empty part {key}")
                built[key] = tuple(sentences)
            out[entry_id] = Explanation(parts=built, draft=draft)
        except ContentRejected as exc:
            rejected[entry_id] = str(exc)
    return out, rejected, status


# Defect wording of the prepared explanations.
DEFECT_OPENING = "Le système signale un défaut"
_FR_FAILURE = re.compile(r"\b(d[ée]fauts?|pannes?|d[ée]faillan\w*|dysfonctionn\w*)\b", re.I)


def defect_wording_rejections(explanations: Mapping[str, "Explanation"], situations: Mapping[str, "Situation"],
                              catalogue: NoticeCatalogue) -> dict[str, str]:
    """Where the notice names a defect in the entry's own situation, the
    explanation opens with « Le système signale un défaut… »; where the
    entry's own passage uses no failure term, no failure word is added.
    (The visit to a workshop is an action, never what defines a defect.)"""
    out = {}
    for x, ex in explanations.items():
        e, st = catalogue.entry(x), situations.get(x)
        first = ex.parts["indique"][0].text if ex.parts.get("indique") else ""
        own = " ".join([e.documented_meaning, e.documented_instruction or ""] + [w.text for w in e.linked_warnings])
        if (st is not None and st.justification.source_field != "manufacturer_designation"
                and failure_term(st.justification.source_phrase) and not first.startswith(DEFECT_OPENING)):
            out[x] = f"defect named by the notice: the explanation opens with « {DEFECT_OPENING}… »"
        elif not failure_term(own) and any(_FR_FAILURE.search(s.text) for part in ex.parts.values() for s in part):
            out[x] = "no failure term in the notice: no failure word added"
    return out


# --- V1 presentation of the Premier Constat -----------------------------------

def _ne_label(e: NoticeEntry, item: str, covered: bool) -> str:
    """« Cette information n'est pas établie dans les données disponibles. » only when a VALIDATED
    classification covers the entry AND nothing in the passage could hold
    that point unseen: never when the entry has linked warnings, and for the
    stop / vehicle-use points never when the passage mentions a stop."""
    if not covered or e.linked_warnings:
        return LABELS["unverified"]
    if item in ("stop", "operability"):
        texts = [e.designation, e.documented_meaning, e.documented_instruction or "", e.displayed_message or ""]
        if any(is_stop_instruction(t) for t in texts):
            return LABELS["unverified"]
    return LABELS["absent"]


def present_entry(f: EntryFinding, e: NoticeEntry, *, covered: bool, explanation: Optional[Explanation],
                  t5_label: str, situation: Optional[Situation] = None,
                  answers: Optional[Mapping[str, str]] = None,
                  group: Optional[list[tuple[NoticeEntry, Optional[Situation]]]] = None) -> dict:
    def cited(item) -> Optional[str]:
        # Only DOCUMENTED values are shown, as the cited phrase itself.
        # Derived values (R-1/R-2) are never displayed (internal level only).
        return item.source_phrase if item.basis.value == "documented" else None

    points, point_uncertainties = [], []
    for key, title, item in (("stop", "Sécurité immédiate", f.stop_vehicle_engine_off),
                             ("operability", "Utilisation du véhicule", f.operability),
                             ("professional", "Intervention d'un professionnel", f.professional_attention),
                             ("practical", "Assistance pratique", f.practical_assistance.requirement)):
        quotes = [q for q in [cited(item)] if q]
        if key == "professional" and quotes:
            quotes += [q for q in (cited(f.urgency_phrase), cited(f.documented_suitability)) if q and q not in quotes[0]]
        label = None if quotes else _ne_label(e, key, covered)
        placement = "corps"
        if label is not None:
            # A point without a cited phrase holds no established action: its status is technical,
            # the instructions of the passage stay displayed where they are.
            reason = ("point_not_established" if label == LABELS["absent"] else
                      "stop_shown_with_condition" if key == "stop" and catalogue_stops(e) else "unverified_point")
            u = uncertainty(f"point.{key}", "technique", reason=reason)
            point_uncertainties.append(u)
            placement = u["placement"]
        points.append({"key": key, "title": title, "quotes": quotes, "label": label, "placement": placement})
    uncertainties = ([] if explanation is None else
                     [uncertainty("explanation.draft", "technique", reason="draft_status")] * explanation.draft
                     + [uncertainty("explanation.inconnu", "explication")])
    caution = no_consigne_uncertainty(e, situation, group, answers)
    uncertainties += situation_uncertainties(situation, e.entry_id, answers) + [caution] * bool(caution) + point_uncertainties
    return {
        "entry_id": e.entry_id,
        "selected_label": LABELS["selected"],
        "designation": e.designation,
        "manufacturer_text": {
            "label": t5_label, "documented_meaning": e.documented_meaning,
            "documented_instruction": e.documented_instruction, "displayed_message": e.displayed_message,
            "linked_warnings": [{"number": w.number, "text": w.text} for w in e.linked_warnings],
        },
        "explanation": None if explanation is None else {
            "mention": LABELS["draft_explanation"] if explanation.draft else None,
            "mention_placement": "details" if explanation.draft else None,
            "parts": [{"key": k, "title": title,
                       "sentences": [{"text": s.text, "citation": s.source_phrase, "source_field": s.source_field}
                                     for s in explanation.parts[k]]}
                      for k, title in EXPLANATION_PARTS],
        },
        "situation": present_situation(situation, e.entry_id, answers,
                                       no_consigne_placement=caution["placement"] if caution else "corps"),
        "points": points,
        "stop_conditions": [p.source_phrase for p in f.stop_conditions],
        "details_label": DRAFT_LABELS["details"],
        # Internal: moved to the result's internal data by the parcours, never displayed.
        "uncertainties": uncertainties,
    }
