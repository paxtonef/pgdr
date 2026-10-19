"""V1 parcours: 1 to 3 PROPOSED notice images, from the driver's photo, as an
aid to the driver's own selection (owner decision of 2026-10-19, which
supersedes PGDR-V1-02 on this point).

Boundaries, all deliberate:
  * A proposal is never an identification: nothing is selected, ranked,
    scored or recommended for the driver. Proposed images are shown in the
    notice order; the driver selects and confirms through the existing
    selection -> confirmation -> restitution steps. The complete catalogue
    stays reachable at every moment.
  * Candidates are the entries of the catalogue applicable to the parcours,
    nothing else; an answer naming any other entry is refused as a whole.
  * The sorting context is the photo and the candidate images with their
    opaque entry_ids. No vehicle identity, plate, VIN or registration
    document data exists in it (DemandeTri has no field for them).
  * Image metadata is removed (strip_metadata) before any transport. This
    does not remove identifiers visible in the pixels.
  * The photo is held only for the duration of the request: never stored,
    never logged; only the proposed entry_ids are kept in the parcours.
  * No real sorting component exists here. The only transport is
    FauxTransportTri, a fake for verification (canned answers keyed by the
    photo digest): it proves the wiring, never any recognition quality.
  * Whatever goes wrong (not configured, photo refused, transport failure,
    invalid answer, empty answer), the outcome is the complete catalogue in
    the notice order with an explanation. That fallback says nothing about
    the quality of the sorting.

Configuration (environment, read once by pgdr.v1_parcours.get_wiring):
  PGDR_V1_TRI        absent or empty: no proposals. "faux": the fake
                     transport below, for a signalled trial only
                     (PGDR_V1_ESSAI_TRI=1, permanent banner on every screen);
                     refused otherwise. Any other value is refused (no real
                     component is authorised).
  PGDR_V1_TRI_FAUX   with "faux": JSON file {"nature": FAUX_NATURE,
                     "destinataire": "<name shown in the consent>",
                     "reponses": {"<photo sha256 after stripping>": R},
                     "defaut": R}, R = {"texte": "<raw answer>"} or
                     {"panne": true}.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

MAX_PROPOSITIONS = 3
MAX_PHOTO_BYTES = 15 * 1024 * 1024
FAUX_NATURE = "faux transport d'essai"


class PhotoRefusee(ValueError):
    """The photo is not a well-formed PNG or JPEG (or is too large)."""


class ReponseInvalide(ValueError):
    """The sorting answer is not exactly a list of 0 to 3 applicable entry_ids."""


# --- metadata --------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Chunks needed to draw the pixels; every other chunk (tEXt, iTXt, zTXt, eXIf,
# tIME, iCCP, ...) is dropped.
_PNG_KEPT = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}


def media_type(data: bytes) -> Optional[str]:
    if data.startswith(_PNG_SIGNATURE):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def strip_metadata(data: bytes) -> tuple[bytes, str]:
    """The same image without its metadata: PNG keeps only the chunks that
    draw it; JPEG loses every APPn segment (EXIF, XMP, JFIF, ICC, maker
    notes...) and comment, and anything after the end of the first image
    (e.g. an appended second image with its own EXIF). Raises PhotoRefusee
    for anything else or anything malformed."""
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise PhotoRefusee("taille")
    kind = media_type(data)
    if kind == "image/png":
        return _strip_png(data), kind
    if kind == "image/jpeg":
        return _strip_jpeg(data), kind
    raise PhotoRefusee("format")


def _strip_png(data: bytes) -> bytes:
    out, pos = [_PNG_SIGNATURE], len(_PNG_SIGNATURE)
    seen_end = False
    while pos < len(data):
        if pos + 12 > len(data):
            raise PhotoRefusee("png tronqué")
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise PhotoRefusee("png tronqué")
        body = data[pos + 8:pos + 8 + length]
        if struct.unpack(">I", data[pos + 8 + length:end])[0] != zlib.crc32(kind + body) & 0xFFFFFFFF:
            raise PhotoRefusee("png corrompu")
        if kind in _PNG_KEPT:
            out.append(data[pos:end])
        pos = end
        if kind == b"IEND":
            seen_end = True
            break
    if not seen_end or out[1][4:8] != b"IHDR":
        raise PhotoRefusee("png incomplet")
    return b"".join(out)


def _strip_jpeg(data: bytes) -> bytes:
    out, pos, n = [b"\xff\xd8"], 2, len(data)
    while True:
        if pos + 2 > n or data[pos] != 0xFF:
            raise PhotoRefusee("jpeg malformé")
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xD9:  # EOI: the first image ends here; what follows is dropped
            out.append(b"\xff\xd9")
            return b"".join(out)
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:  # stand-alone markers
            out.append(data[pos:pos + 2])
            pos += 2
            continue
        if pos + 4 > n:
            raise PhotoRefusee("jpeg tronqué")
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        end = pos + 2 + length
        if length < 2 or end > n:
            raise PhotoRefusee("jpeg tronqué")
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE):  # APPn and COM are dropped
            out.append(data[pos:end])
        pos = end
        if marker == 0xDA:  # SOS: entropy-coded data up to the next real marker
            start = pos
            while True:
                if pos + 1 >= n:
                    raise PhotoRefusee("jpeg tronqué")
                if data[pos] == 0xFF and data[pos + 1] != 0x00 and not 0xD0 <= data[pos + 1] <= 0xD7:
                    break
                pos += 2 if data[pos] == 0xFF else 1
            out.append(data[start:pos])


# --- sorting port -----------------------------------------------------------------

@dataclass(frozen=True)
class Candidat:
    entry_id: str
    image: bytes
    media_type: str


@dataclass(frozen=True)
class DemandeTri:
    """Everything a sorting component receives: the photo (metadata removed)
    and the applicable catalogue images, each with its opaque entry_id."""
    photo: bytes
    photo_media_type: str
    candidats: tuple[Candidat, ...]


class TransportTri(Protocol):
    destinataire: str  # the name the driver consents to, shown verbatim
    faux: bool         # True: a fake for verification, never a real analysis

    def proposer(self, demande: DemandeTri) -> str:
        """The component's raw answer (text). May raise: any exception is a failure."""


class FauxTransportTri:
    """Verification fake: canned answers keyed by the SHA-256 of the
    (stripped) photo. It looks at nothing; it never analyses an image."""
    faux = True

    def __init__(self, destinataire: str, reponses: dict, defaut: Optional[dict] = None,
                 observer: Optional[Callable[[DemandeTri], None]] = None):
        if not isinstance(destinataire, str) or not destinataire.strip():
            raise ValueError("destinataire requis")
        self.destinataire = destinataire
        self._reponses = dict(reponses)
        self._defaut = defaut
        self._observer = observer

    @classmethod
    def depuis_fichier(cls, path) -> "FauxTransportTri":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or raw.get("nature") != FAUX_NATURE:
            raise ValueError(f"nature « {FAUX_NATURE} » requise")
        reponses = raw.get("reponses") or {}
        if not isinstance(reponses, dict) or any(not _reponse_faux_valide(r) for r in reponses.values()):
            raise ValueError("réponses invalides")
        defaut = raw.get("defaut")
        if defaut is not None and not _reponse_faux_valide(defaut):
            raise ValueError("réponse par défaut invalide")
        return cls(raw.get("destinataire"), reponses, defaut)

    def proposer(self, demande: DemandeTri) -> str:
        if self._observer is not None:
            self._observer(demande)
        r = self._reponses.get(hashlib.sha256(demande.photo).hexdigest(), self._defaut)
        if r is None or r.get("panne"):
            raise ConnectionError("faux transport : panne simulée")
        return r["texte"]


def _reponse_faux_valide(r) -> bool:
    return isinstance(r, dict) and (r == {"panne": True} or (set(r) == {"texte"} and isinstance(r["texte"], str)))


def lire_propositions(texte, applicables: list[str]) -> list[str]:
    """The proposed entry_ids, strictly: one JSON object (optionally in a
    single ```json block) whose ONLY key is proposed_entry_ids, a list of 0
    to 3 distinct entry_ids of the applicable catalogue. Anything else --
    scores, labels, reasons, extra keys, duplicate keys, unknown entries,
    more than 3 -- raises ReponseInvalide."""
    if not isinstance(texte, str):
        raise ReponseInvalide("texte requis")
    texte = texte.strip()
    if texte.startswith("```"):
        m = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", texte, re.DOTALL | re.IGNORECASE)
        if not m:
            raise ReponseInvalide("un seul bloc JSON requis")
        texte = m.group(1)

    def unique_keys(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ReponseInvalide("clé répétée")
            out[k] = v
        return out

    try:
        obj = json.loads(texte, object_pairs_hook=unique_keys)
    except ValueError as exc:
        raise ReponseInvalide("JSON invalide") from exc
    if not isinstance(obj, dict) or set(obj) != {"proposed_entry_ids"}:
        raise ReponseInvalide("réponse non limitée aux propositions")
    ids = obj["proposed_entry_ids"]
    if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
        raise ReponseInvalide("liste d'identifiants requise")
    if len(ids) > MAX_PROPOSITIONS or len(set(ids)) != len(ids):
        raise ReponseInvalide("au plus 3 identifiants distincts")
    known = set(applicables)
    if any(x not in known for x in ids):
        raise ReponseInvalide("identifiant hors du catalogue applicable")
    return ids


# --- outcome ----------------------------------------------------------------------

# Why the complete catalogue is shown directly. The driver's next step is the
# same in every case: choose in the complete catalogue, in the notice order.
REPLIS = ("non_configure", "photo_refusee", "panne", "reponse_invalide", "aucune_proposition")


@dataclass(frozen=True)
class Resultat:
    propositions: tuple[str, ...] = ()  # entry_ids, notice order; empty = fallback
    repli: Optional[str] = None         # one of REPLIS when there is no proposal


def proposer(photo: bytes, candidats: list[Candidat], transport: Optional[TransportTri]) -> Resultat:
    """Never raises: every failure is the catalogue fallback. The photo bytes
    are not kept, logged or put in any error."""
    if transport is None:
        return Resultat(repli="non_configure")
    try:
        clean, kind = strip_metadata(photo)
    except PhotoRefusee:
        return Resultat(repli="photo_refusee")
    ordre = [c.entry_id for c in candidats]
    try:
        texte = transport.proposer(DemandeTri(photo=clean, photo_media_type=kind, candidats=tuple(candidats)))
    except Exception:  # noqa: BLE001 -- any transport failure is the fallback, nothing is disclosed
        return Resultat(repli="panne")
    try:
        ids = set(lire_propositions(texte, ordre))
    except ReponseInvalide:
        return Resultat(repli="reponse_invalide")
    if not ids:
        return Resultat(repli="aucune_proposition")
    # Notice order, never the component's order: no rank is implied.
    return Resultat(propositions=tuple(x for x in ordre if x in ids))


def charger_transport(mode: Optional[str], faux_path: Optional[str],
                      essai: bool = False) -> tuple[Optional[TransportTri], str]:
    """(transport, status). Only the fake exists; any other mode is refused.
    The fake is a verification tool, never a production component: from the
    configuration it is accepted only for a signalled trial (`essai`,
    PGDR_V1_ESSAI_TRI=1), whose screens then carry a permanent banner."""
    if not mode:
        return None, "absent"
    if mode != "faux":
        return None, "refused: composant réel non autorisé"
    if not essai:
        return None, "refused: faux transport hors essai signalé (PGDR_V1_ESSAI_TRI=1)"
    if not faux_path:
        return None, "refused: PGDR_V1_TRI_FAUX requis"
    try:
        return FauxTransportTri.depuis_fichier(faux_path), "faux"
    except (OSError, ValueError) as exc:
        return None, f"refused: {exc}"
