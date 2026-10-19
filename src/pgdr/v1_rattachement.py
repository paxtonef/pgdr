"""Attachment of the validations of an earlier notice version to the current one.

The content fingerprint (ManifestNoticeRepository.content_fingerprint) binds every manifest field but the
review, the applicability metadata included. Changing only those metadata therefore changes the fingerprint
under the review and under every validated side file, although no validated content changed. Nothing is
re-signed for that: the old validations stay as they are, bound to the old fingerprint, and the owner records
one new decision -- an attachment -- that covers only the elements that differ.

An attachment (PGDR_V1_RATTACHEMENT, outside the repository) is accepted only when PGDR itself proves, from
the current manifest, that exactly the listed fields differ: the old values it carries, put back into the
current manifest, give the old fingerprint again. Then:
  * the old validations keep their scope (contents unchanged, same signatures, same dates);
  * the listed differences are the exact list (a field listed but unchanged, or a field changed but not
    listed, is refused);
  * only applicability metadata may differ (METADATA_FIELDS); any other difference is a content change and
    invalidates the validation concerned: no attachment is possible;
  * the new decision (decided_by, decided_on, decision) covers the listed differences only.
An applicability attestation (pgdr.v1_applicabilite) is never carried over: it names one notice version.

    format: pgdr-rattachement-1
    status: VALIDE
    decided_by: <name>
    decided_on: <YYYY-MM-DD>
    decision: <the owner's decision on the listed differences>
    from_content_sha256: <fingerprint the existing validations are bound to>
    to_content_sha256: <current fingerprint>
    previous_values: {<field>: <value in the earlier version>}
    previously_absent: [<field absent from the earlier version>]

Command line (prints, writes nothing):
    python -m pgdr.v1_rattachement proposer <earlier manifest.yaml> <current manifest.yaml>
    python -m pgdr.v1_rattachement verifier <rattachement.yaml> <current manifest.yaml>
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from typing import Optional

import yaml

from pgdr.adapters.manifest_notice_repository import content_fingerprint

RATTACHEMENT_FORMAT = "pgdr-rattachement-1"
# Applicability metadata only: none of them is a notice content shown or classified.
METADATA_FIELDS = frozenset({"applicability_vehicle_under_review", "applicability_period_start",
                             "applicability_period_end", "applicability_period_note"})
_HEX = frozenset("0123456789abcdef")
_MISSING = object()


class RattachementRejected(Exception):
    pass


@dataclass(frozen=True)
class Rattachement:
    from_content_sha256: str
    to_content_sha256: str
    changed_fields: tuple
    decided_by: str
    decided_on: date


def _sha(v, label: str) -> str:
    if not isinstance(v, str) or len(v) != 64 or not set(v) <= _HEX:
        raise RattachementRejected(f"{label} invalide")
    return v


def verify(raw, manifest: dict, today: Optional[date] = None) -> Rattachement:
    """The attachment, once proven against the current manifest; RattachementRejected otherwise."""
    if not isinstance(raw, dict) or raw.get("format") != RATTACHEMENT_FORMAT:
        raise RattachementRejected(f"format attendu : {RATTACHEMENT_FORMAT}")
    if raw.get("status") != "VALIDE":
        raise RattachementRejected("rattachement non validé")
    for key in ("decided_by", "decision"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise RattachementRejected(f"{key} manquant")
    decided_on = raw.get("decided_on")
    if isinstance(decided_on, str):
        try:
            decided_on = date.fromisoformat(decided_on)
        except ValueError:
            raise RattachementRejected("date de décision invalide") from None
    if not isinstance(decided_on, date) or decided_on > (today or date.today()):
        raise RattachementRejected("date de décision invalide")
    old, new = _sha(raw.get("from_content_sha256"), "ancienne empreinte"), _sha(raw.get("to_content_sha256"),
                                                                                "nouvelle empreinte")
    if old == new:
        raise RattachementRejected("aucune différence à rattacher")
    current = content_fingerprint(manifest)
    if new != current:
        raise RattachementRejected("la nouvelle empreinte n'est pas celle de la notice actuelle")
    previous = raw.get("previous_values") or {}
    absent = raw.get("previously_absent") or []
    if not isinstance(previous, dict) or not isinstance(absent, list) or set(previous) & set(absent):
        raise RattachementRejected("liste des différences invalide")
    changed = set(previous) | set(absent)
    if not changed:
        raise RattachementRejected("liste des différences vide")
    content = sorted(changed - METADATA_FIELDS)
    if content:
        raise RattachementRejected("différence de contenu (" + ", ".join(content) + ") : la validation concernée est "
                                   "invalidée, aucun rattachement n'est possible")
    for f in sorted(changed):
        if f in previous and manifest.get(f, _MISSING) == previous[f]:
            raise RattachementRejected(f"différence déclarée inexistante : {f}")
        if f in absent and f not in manifest:
            raise RattachementRejected(f"différence déclarée inexistante : {f}")
    earlier = {k: v for k, v in manifest.items() if k != "review"}
    earlier.update(previous)
    for f in absent:
        earlier.pop(f, None)
    if content_fingerprint(earlier) != old:
        raise RattachementRejected("la liste des différences n'est pas exacte : l'ancienne empreinte n'est pas "
                                   "retrouvée (un autre champ a changé)")
    return Rattachement(from_content_sha256=old, to_content_sha256=new, changed_fields=tuple(sorted(changed)),
                        decided_by=raw["decided_by"].strip(), decided_on=decided_on)


def propose(earlier: dict, current: dict) -> dict:
    """A PROPOSAL (status PROPOSITION, never VALIDE) listing the exact differences between two manifest
    versions, or the content differences that make an attachment impossible."""
    keys = (set(earlier) | set(current)) - {"review"}
    differing = sorted(k for k in keys if earlier.get(k, _MISSING) != current.get(k, _MISSING))
    content = [k for k in differing if k not in METADATA_FIELDS]
    proposal = {
        "format": RATTACHEMENT_FORMAT, "status": "PROPOSITION", "decided_by": None, "decided_on": None,
        "decision": None,
        "from_content_sha256": content_fingerprint(earlier), "to_content_sha256": content_fingerprint(current),
        "previous_values": {k: earlier[k] for k in differing if k in earlier and k not in content},
        "previously_absent": [k for k in differing if k not in earlier and k not in content],
        "unchanged_fields": len(keys) - len(differing),
    }
    if content:
        proposal["impossible"] = ("différence de contenu : " + ", ".join(content)
                                  + " ; la validation de ces contenus doit être refaite")
    return proposal


def _load(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 3 and args[0] == "proposer":
        print(yaml.safe_dump(propose(_load(args[1]), _load(args[2])), allow_unicode=True, sort_keys=False))
        return 0
    if len(args) == 3 and args[0] == "verifier":
        try:
            r = verify(_load(args[1]), _load(args[2]))
        except RattachementRejected as exc:
            print(f"Rattachement refusé : {exc}")
            return 1
        print(f"Rattachement accepté : {r.from_content_sha256[:12]}… → {r.to_content_sha256[:12]}… ; différences : "
              f"{', '.join(r.changed_fields)} ; décision de {r.decided_by} du {r.decided_on.isoformat()}")
        return 0
    print(__doc__.split("Command line")[1])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
