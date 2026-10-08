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

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Optional

import yaml

from pgdr.adapters.manifest_notice_repository import NoticeCatalogue, NoticeEntry
from pgdr.models import EntryFinding

LABELS = {
    "selected": "Voyant sélectionné par vous",
    "absent": "La notice n'indique pas ce point.",
    "unverified": "Point pas encore vérifié par PGDR. Lisez la consigne du constructeur ci-dessous.",
    "draft_explanation": "Explication en brouillon, non validée",
}
EXPLANATION_PARTS = (("indique", "Ce que la notice indique"), ("maintenant", "Quoi faire maintenant"),
                     ("inconnu", "Ce qui reste inconnu"))
ANCHOR_FIELDS = ("manufacturer_designation", "documented_meaning", "documented_instruction", "displayed_message",
                 "linked_warnings")
# A prepared sentence may never carry a permission to drive or a danger
# grading of its own (the manufacturer's own words stay in the citation).
FORBIDDEN = ("vous pouvez rouler", "vous pouvez continuer", "sans danger", "sans risque", "pas dangereux",
             "peu grave", "pas grave", "rien de grave", "aucun danger", "pouvez reprendre la route")
_STOP_WORD = re.compile(r"\bstop", re.I)


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


def load_groups(path, catalogue: NoticeCatalogue) -> list[tuple[str, ...]]:
    """Groups of visually identical images with different files: used only
    when VALIDATED by name and bound to this catalogue."""
    raw = _read(path)
    header = _header(raw, catalogue)
    if not _validated(header):
        raise ContentRejected("groups not validated")
    known = {e.entry_id for e in catalogue.entries}
    groups = []
    for g in raw.get("groups") or []:
        ids = tuple(g.get("entry_ids") or [])
        if len(ids) < 2 or len(set(ids)) != len(ids) or any(x not in known for x in ids):
            raise ContentRejected("invalid group")
        groups.append(ids)
    return groups


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


# --- V1 presentation of the Premier Constat -----------------------------------

def _ne_label(e: NoticeEntry, item: str, covered: bool) -> str:
    """« La notice n'indique pas ce point » only when a VALIDATED
    classification covers the entry AND nothing in the passage could hold
    that point unseen: never when the entry has linked warnings, and for the
    stop / vehicle-use points never when the passage mentions a stop."""
    if not covered or e.linked_warnings:
        return LABELS["unverified"]
    if item in ("stop", "operability"):
        texts = [e.designation, e.documented_meaning, e.documented_instruction or "", e.displayed_message or ""]
        if any(_STOP_WORD.search(t) for t in texts):
            return LABELS["unverified"]
    return LABELS["absent"]


def present_entry(f: EntryFinding, e: NoticeEntry, *, covered: bool, explanation: Optional[Explanation],
                  t5_label: str) -> dict:
    def cited(item) -> Optional[str]:
        # Only DOCUMENTED values are shown, as the cited phrase itself.
        # Derived values (R-1/R-2) are never displayed (internal level only).
        return item.source_phrase if item.basis.value == "documented" else None

    points = []
    for key, title, item in (("stop", "Sécurité immédiate", f.stop_vehicle_engine_off),
                             ("operability", "Utilisation du véhicule", f.operability),
                             ("professional", "Intervention d'un professionnel", f.professional_attention),
                             ("practical", "Assistance pratique", f.practical_assistance.requirement)):
        quotes = [q for q in [cited(item)] if q]
        if key == "professional" and quotes:
            quotes += [q for q in (cited(f.urgency_phrase), cited(f.documented_suitability)) if q and q not in quotes[0]]
        points.append({"key": key, "title": title, "quotes": quotes,
                       "label": None if quotes else _ne_label(e, key, covered)})
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
            "parts": [{"key": k, "title": title,
                       "sentences": [{"text": s.text, "citation": s.source_phrase, "source_field": s.source_field}
                                     for s in explanation.parts[k]]}
                      for k, title in EXPLANATION_PARTS],
        },
        "points": points,
        "stop_conditions": [p.source_phrase for p in f.stop_conditions],
    }
