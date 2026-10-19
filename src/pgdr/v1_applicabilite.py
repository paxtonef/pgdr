"""Applicability of the V1 notice to the vehicle: four distinct questions, never merged.

1. Value available, and its provenance -- for each identity key the notice is resolved on
   (pgdr.application.vehicle_applicability.APPLICABILITY_IDENTITY_FIELDS), the value VIR handed on through PI
   and VIR's own status for it (VehicleIdentityContext.field_provenance): established, confirmed by the
   driver, supplied by a source without being established, declared, not stated (an older producer),
   unknown, contradictory. PGDR computes no status.
2. Criterion sufficiently justified -- an applicability attestation names, for each criterion, where it was
   read on the notice and on the vehicle. A notice criterion read only from the file name, the download
   address or the PDF metadata is not justified; a driver confirmation alone does not justify a vehicle
   criterion.
3. Match between vehicle and notice -- exact equality (case and edge spaces aside), no approximate match, no
   alias, nothing deduced (ManifestNoticeRepository.matches).
4. Applicability decision -- an attestation limited to this vehicle (the product's opaque vehicle reference)
   and to this exact version of the notice (content fingerprint); or the notice's own established
   applicability (manifest, bloc 3A), which never covers a key resting on a driver confirmation alone; or
   the development trial. A confirmed value alone never makes a notice applicable.

Every refusal carries the precise reasons, what remains to be checked, and the next useful action. Any
contradiction on a key prevents the opening. Nothing here reads a VIN, a plate or a registration document.

Attestation file (PGDR_V1_APPLICABILITE, outside the repository), prepared by the notice owner:

    format: pgdr-attestation-applicabilite-1
    attestations:
      - status: VALIDE
        attested_by: <name>
        verified_on: <YYYY-MM-DD>
        document_id: <manifest document_id>
        catalogue_content_sha256: <manifest content fingerprint>
        vehicle_ref: <the product's opaque vehicle reference>
        criteria:
          <key>:
            value: <value compared>
            notice_source: {kind: printed_notice, reference: <where on the printed notice>}
            vehicle_source: {kind: registration_document | manufacturer_label | vir_established,
                             reference: <where on the vehicle side>}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

import yaml

from pgdr.application.vehicle_applicability import APPLICABILITY_IDENTITY_FIELDS
from pgdr.models import FieldEpistemicStatus as S
from pgdr.models import VehicleIdentityContext

ATTESTATION_FORMAT = "pgdr-attestation-applicabilite-1"
NOT_STATED = "not_stated"   # a value handed on without provenance (older producer): no qualification added

KEY_NAMES = {"manufacturer": ("la marque", "La marque", "f"), "model": ("le modèle", "Le modèle", "m"),
             "generation": ("la génération", "La génération", "f")}
PROVENANCE_LABELS = {
    # Worded as VIR's own labels (vir.domain.driver_confirmation.EPISTEMIC_LABELS), about the driver.
    S.ESTABLISHED.value: "établi (décodage ou source qualifiée)",
    S.USER_CONFIRMED.value: "confirmé par le conducteur, sans vérification indépendante",
    S.USER_DECLARED.value: "déclaré par le conducteur, non vérifié",
    S.PROVIDER_NOT_ESTABLISHED.value: "fourni par une source, non établi",
    NOT_STATED: "provenance non transmise",
    S.UNKNOWN.value: "inconnu",
    S.CONTRADICTORY.value: "contradictoire",
}

# The applicability keys a driver may confirm in VIR (vir.domain.driver_confirmation.CONFIRMABLE_FIELDS; PI's
# tests pin the equality): the next action suggests a confirmation only for them.
DRIVER_CONFIRMABLE_KEYS = frozenset({"generation"})

NOTICE_SOURCE_KINDS = {"printed_notice": "texte imprimé de la notice"}
UNJUSTIFIED_NOTICE_SOURCE_KINDS = {"file_name": "nom du fichier", "url": "adresse de téléchargement",
                                   "pdf_metadata": "métadonnées du PDF"}
VEHICLE_SOURCE_KINDS = {"registration_document": "certificat d'immatriculation",
                        "manufacturer_label": "étiquette ou plaque du constructeur sur le véhicule",
                        "vir_established": "valeur établie par VIR"}
UNJUSTIFIED_VEHICLE_SOURCE_KINDS = {"driver_confirmation": "confirmation du conducteur seule"}

MESSAGES = {
    "notice_unavailable": "La notice de ce véhicule n'est pas disponible (revue absente ou obsolète, ou fichier non conforme).",
    "vehicle_identity_insufficient": "L'identité du véhicule n'est pas établie par VIR.",
    "vehicle_not_supported": "Aucune notice disponible pour ce véhicule.",
    "applicability_not_confirmed": "L'applicabilité de la notice à ce véhicule n'est pas confirmée.",
}
TO_VERIFY_APPLICABILITY = (
    "Comparer la marque, le modèle et la génération du véhicule avec le texte imprimé de la notice et avec le "
    "véhicule (certificat d'immatriculation ou étiquette du constructeur) ; le certificat ne porte pas "
    "nécessairement de rubrique « génération ».",
    "Ne retenir aucun critère de la notice tiré seulement du nom du fichier, de l'adresse de téléchargement ou "
    "des métadonnées du PDF.",
)
NEXT_ACTION = {
    "applicability_not_confirmed": (
        "Le propriétaire de la notice enregistre une attestation d'applicabilité limitée à ce véhicule et à cette "
        "version de la notice (critères comparés, sources, auteur, date). Les contenus déjà validés de la notice "
        "n'ont pas à être refaits."),
    "vehicle_identity_insufficient": (
        "Compléter l'identification du véhicule dans le dossier (la génération peut être confirmée par le "
        "conducteur dans le résultat d'identification), puis rouvrir la notice. Une confirmation seule ne rend pas "
        "la notice applicable."),
    "vehicle_identity_insufficient_not_confirmable": (
        "L'identification du véhicule par VIR doit être complétée (la marque et le modèle ne peuvent pas être "
        "confirmés par le conducteur), puis rouvrir la notice."),
    "vehicle_identity_contradictory": (
        "Lever la contradiction dans le résultat d'identification (confirmation ou correction), puis rouvrir la "
        "notice. Rien n'est tranché automatiquement."),
    "vehicle_not_supported": (
        "Vérifier que cette notice correspond au véhicule : aucune correspondance approchée ni aucun alias n'est "
        "appliqué. Un libellé différent ne peut être rapproché que par une décision du propriétaire de la notice."),
}


@dataclass(frozen=True)
class KeyValue:
    key: str
    value: Optional[str]
    status: str   # a FieldEpistemicStatus value, or NOT_STATED

    def shown(self) -> dict:
        return {"key": self.key, "label": KEY_NAMES[self.key][1], "value": self.value, "provenance": self.status,
                "provenance_label": PROVENANCE_LABELS[self.status]}


def identity_keys(identity: VehicleIdentityContext) -> dict[str, KeyValue]:
    """Question 1: each key's value and VIR's status for it. A value resting on a driver confirmation alone
    comes only from field_provenance (never from vehicle_identity); a value without provenance keeps the
    reading of bloc 3A (present, neither unresolved nor contradictory) and is marked not stated."""
    vehicle = identity.vehicle_identity or {}
    unresolved, contradicted = set(identity.unresolved_fields), set(identity.contradictions)
    out = {}
    for key in APPLICABILITY_IDENTITY_FIELDS:
        p = identity.field_provenance.get(key)
        given = vehicle.get(key)
        if key in contradicted or (p is not None and p.status == S.CONTRADICTORY):
            value = given if given is not None else (p.value if p is not None else None)
            out[key] = KeyValue(key, value if isinstance(value, str) else None, S.CONTRADICTORY.value)
        elif p is not None and p.status == S.USER_CONFIRMED:
            out[key] = KeyValue(key, p.value if isinstance(p.value, str) and p.value.strip() else None,
                                S.USER_CONFIRMED.value)
        elif not isinstance(given, str) or not given.strip() or key in unresolved or (
                p is not None and p.status == S.UNKNOWN):
            out[key] = KeyValue(key, None, S.UNKNOWN.value)
        else:
            out[key] = KeyValue(key, given, p.status.value if p is not None else NOT_STATED)
    # A confirmed value that is not text is no value for these keys.
    return {k: (KeyValue(k, None, S.UNKNOWN.value) if v.status == S.USER_CONFIRMED.value and v.value is None else v)
            for k, v in out.items()}


def shown_vehicle(keys: dict) -> list[str]:
    """The keys as the parcours page shows them: each value, with its provenance when it is not established."""
    return [k.value + ("" if k.status in (S.ESTABLISHED.value, NOT_STATED) else f" ({PROVENANCE_LABELS[k.status]})")
            for k in keys.values() if k.value]


def same(a, b) -> bool:
    """Question 3: the only equality used (as ManifestNoticeRepository.matches)."""
    return isinstance(a, str) and isinstance(b, str) and a.strip().casefold() == b.strip().casefold()


# --- attestations ------------------------------------------------------------------------------------------

class AttestationRejected(Exception):
    pass


@dataclass(frozen=True)
class Attestation:
    attested_by: str
    verified_on: date
    document_id: str
    catalogue_content_sha256: str
    vehicle_ref: str
    criteria: dict   # key -> value compared (each justified on the notice and on the vehicle side)


def _text(v, label: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise AttestationRejected(f"{label} manquant")
    return v.strip()


def _source(raw, kinds: dict, unjustified: dict, key: str, side: str) -> None:
    if not isinstance(raw, dict):
        raise AttestationRejected(f"critère {key} : source côté {side} manquante")
    kind = raw.get("kind")
    if kind in unjustified:
        raise AttestationRejected(f"critère {key} non justifié : source côté {side} « {unjustified[kind]} »")
    if kind not in kinds:
        raise AttestationRejected(f"critère {key} : type de source côté {side} inconnu")
    _text(raw.get("reference"), f"critère {key} : référence côté {side}")


def parse_attestation(raw, today: Optional[date] = None) -> Attestation:
    """Question 2, checked on the attestation alone: a named author, a verification date not in the future,
    the notice version (document and content fingerprint), one vehicle, and every identity key of the
    notice justified on both sides. Raises AttestationRejected with the precise reason."""
    if not isinstance(raw, dict):
        raise AttestationRejected("attestation illisible")
    if raw.get("status") != "VALIDE":
        raise AttestationRejected("attestation non validée")
    verified = raw.get("verified_on")
    if isinstance(verified, str):
        try:
            verified = date.fromisoformat(verified)
        except ValueError:
            raise AttestationRejected("date de vérification invalide") from None
    if not isinstance(verified, date) or verified > (today or date.today()):
        raise AttestationRejected("date de vérification invalide")
    sha = _text(raw.get("catalogue_content_sha256"), "empreinte de la notice")
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise AttestationRejected("empreinte de la notice invalide")
    criteria = raw.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        raise AttestationRejected("critères manquants")
    unknown = sorted(set(criteria) - set(APPLICABILITY_IDENTITY_FIELDS))
    if unknown:
        raise AttestationRejected(f"critère non comparé par PGDR : {', '.join(unknown)}")
    values = {}
    for key in APPLICABILITY_IDENTITY_FIELDS:
        c = criteria.get(key)
        if not isinstance(c, dict):
            raise AttestationRejected(f"critère {key} manquant")
        values[key] = _text(c.get("value"), f"critère {key} : valeur")
        _source(c.get("notice_source"), NOTICE_SOURCE_KINDS, UNJUSTIFIED_NOTICE_SOURCE_KINDS, key, "notice")
        _source(c.get("vehicle_source"), VEHICLE_SOURCE_KINDS, UNJUSTIFIED_VEHICLE_SOURCE_KINDS, key, "véhicule")
    return Attestation(attested_by=_text(raw.get("attested_by"), "auteur"), verified_on=verified,
                       document_id=_text(raw.get("document_id"), "document"), catalogue_content_sha256=sha,
                       vehicle_ref=_text(raw.get("vehicle_ref"), "référence du véhicule"), criteria=values)


@dataclass
class Attestations:
    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)   # (index, reason): never applied
    status: str = "absent"


def load_attestations(path, today: Optional[date] = None) -> Attestations:
    """Every attestation of the file, each accepted or rejected with its reason; an unreadable file applies
    none. Never fetched from elsewhere, never written by PGDR."""
    out = Attestations(status="configured")
    try:
        raw = yaml.safe_load(open(path, encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return Attestations(rejected=[(None, "fichier d'attestations illisible")], status="unreadable")
    if not isinstance(raw, dict) or raw.get("format") != ATTESTATION_FORMAT or not isinstance(
            raw.get("attestations"), list):
        return Attestations(rejected=[(None, f"format attendu : {ATTESTATION_FORMAT}")], status="unreadable")
    for i, item in enumerate(raw["attestations"]):
        try:
            out.accepted.append(parse_attestation(item, today))
        except AttestationRejected as exc:
            out.rejected.append((i, str(exc)))
    return out


def covering_attestation(attestations: Attestations, vehicle_ref: Optional[str], catalogue, keys: dict
                         ) -> tuple[Optional[Attestation], list[str]]:
    """Question 4, attestation side: the attestation for THIS vehicle and THIS notice version whose criteria
    equal both the notice's vehicle and the values handed on, or None with the reason."""
    if not vehicle_ref:
        return None, ["Le véhicule n'est pas désigné par le produit : aucune attestation d'applicabilité ne peut "
                      "s'y appliquer."]
    mine = [a for a in attestations.accepted if a.vehicle_ref == vehicle_ref]
    if not mine:
        return None, ["Aucune attestation d'applicabilité ne couvre ce véhicule et cette version de la notice."]
    version = [a for a in mine if a.document_id == catalogue.document.document_id
               and a.catalogue_content_sha256 == catalogue.content_sha256]
    if not version:
        return None, ["Une attestation existe pour ce véhicule, mais pour une autre notice ou une autre version de "
                      "cette notice (contenu différent) : elle ne s'applique pas."]
    reasons = []
    for a in version:
        notice_diff = [k for k in APPLICABILITY_IDENTITY_FIELDS if not same(a.criteria[k], str(catalogue.vehicle[k]))]
        vehicle_diff = [k for k in APPLICABILITY_IDENTITY_FIELDS if not same(a.criteria[k], keys[k].value)]
        if not notice_diff and not vehicle_diff:
            return a, []
        if notice_diff:
            reasons.append("L'attestation compare des critères qui ne sont pas ceux de la notice : "
                           + ", ".join(KEY_NAMES[k][0] for k in notice_diff) + ".")
        if vehicle_diff:
            reasons.append("Le véhicule transmis diffère de celui de l'attestation : "
                           + ", ".join(KEY_NAMES[k][0] for k in vehicle_diff) + ".")
    return None, reasons


# --- decision ----------------------------------------------------------------------------------------------

@dataclass
class Decision:
    status: str                       # "applicable" or a refusal status
    basis: Optional[str] = None       # with "applicable": attestation | notice_established | dev_trial
    reasons: list = field(default_factory=list)
    to_verify: list = field(default_factory=list)
    keys: dict = field(default_factory=dict)
    attestation: Optional[Attestation] = None

    def refusal(self) -> dict:
        status = "vehicle_identity_insufficient" if self.status == "vehicle_identity_contradictory" else self.status
        next_action = NEXT_ACTION.get(self.status)
        unknown = {k.key for k in self.keys.values() if k.status == S.UNKNOWN.value}
        if self.status == "vehicle_identity_insufficient" and unknown - DRIVER_CONFIRMABLE_KEYS:
            next_action = NEXT_ACTION["vehicle_identity_insufficient_not_confirmable"]
        return {"status": status, "message": MESSAGES[status], "reasons": list(self.reasons),
                "to_verify": list(self.to_verify), "next_action": next_action,
                "identity": [k.shown() for k in self.keys.values()]}


def _unknown_reason(key: str) -> str:
    _, cap, gender = KEY_NAMES[key]
    known, pronoun = ("connue", "la") if gender == "f" else ("connu", "le")
    return f"{cap} du véhicule n'est pas {known} : VIR ne {pronoun} transmet pas comme une valeur utilisable."


def decide(identity: VehicleIdentityContext, catalogue, attestations: Attestations, *, dev_trial: bool,
           single_identity: bool, period: Callable[[], Optional[str]]) -> Decision:
    keys = identity_keys(identity)
    if not single_identity:
        return Decision("vehicle_identity_insufficient", keys=keys, reasons=[
            f"VIR n'a pas retenu une identité unique (statut « {identity.resolution_status.value} ») : aucune "
            "identité n'est choisie par défaut."])
    contradicted = [k for k in keys.values() if k.status == S.CONTRADICTORY.value]
    if contradicted:
        return Decision("vehicle_identity_contradictory", keys=keys, reasons=[
            f"{KEY_NAMES[k.key][1]} du véhicule est contradictoire entre les sources de VIR : rien n'est tranché."
            for k in contradicted])
    unknown = [k for k in keys.values() if k.status == S.UNKNOWN.value]
    if unknown:
        return Decision("vehicle_identity_insufficient", keys=keys, reasons=[_unknown_reason(k.key) for k in unknown])
    mismatched = [k for k in keys.values() if not same(k.value, str(catalogue.vehicle[k.key]))]
    if mismatched:
        return Decision("vehicle_not_supported", keys=keys, reasons=[
            f"{KEY_NAMES[k.key][1]} transmis{'e' if KEY_NAMES[k.key][2] == 'f' else ''} (« {k.value} ») ne "
            f"correspond pas à {KEY_NAMES[k.key][0]} de la notice (« {catalogue.vehicle[k.key]} ») : la comparaison "
            "est exacte, sans correspondance approchée ni alias." for k in mismatched])
    shortfall = period()
    if shortfall == "unknown":
        return Decision("vehicle_identity_insufficient", keys=keys, reasons=[
            "La notice déclare une période d'applicabilité et la production du véhicule n'est pas établie par VIR."])
    if shortfall == "outside":
        return Decision("vehicle_not_supported", keys=keys, reasons=[
            "La production du véhicule est hors de la période d'applicabilité déclarée par la notice."])

    attestation, attestation_reasons = covering_attestation(attestations, identity.vehicle_ref, catalogue, keys)
    if attestation is not None:
        return Decision("applicable", basis="attestation", keys=keys, attestation=attestation)
    confirmed = [k for k in keys.values() if k.status == S.USER_CONFIRMED.value]
    if catalogue.applicability_established and not confirmed:
        return Decision("applicable", basis="notice_established", keys=keys)
    if dev_trial:
        return Decision("applicable", basis="dev_trial", keys=keys)
    reasons = [f"{KEY_NAMES[k.key][1]} (« {k.value} ») repose sur la seule confirmation du conducteur : cela ne "
               "suffit pas à rendre la notice applicable." for k in confirmed]
    if not catalogue.applicability_established:
        reasons.append("L'applicabilité de cette notice n'est pas établie par sa revue.")
    reasons.extend(attestation_reasons)
    return Decision("applicability_not_confirmed", keys=keys, reasons=reasons, to_verify=list(TO_VERIFY_APPLICABILITY))


def check(attestations_path, manifest_path, rattachement_path=None) -> list[str]:
    """What PGDR would do with each attestation of the file, against this notice: accepted for this version,
    accepted for another version (never applied here), or rejected with its reason. Writes nothing."""
    from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository
    catalogue = ManifestNoticeRepository(manifest_path, rattachement_path=rattachement_path).catalogue
    loaded = load_attestations(attestations_path)
    lines = [f"Notice {catalogue.document.document_id}, empreinte {catalogue.content_sha256[:12]}…"]
    for i, reason in loaded.rejected:
        lines.append(f"refusée{'' if i is None else f' (n° {i + 1})'} : {reason}")
    for a in loaded.accepted:
        version = a.document_id == catalogue.document.document_id and a.catalogue_content_sha256 == catalogue.content_sha256
        diff = [k for k in APPLICABILITY_IDENTITY_FIELDS if not same(a.criteria[k], str(catalogue.vehicle[k]))]
        verdict = ("autre notice ou autre version : jamais appliquée ici" if not version else
                   "critères différents de ceux de la notice : " + ", ".join(diff) if diff else
                   "recevable pour cette version, pour le seul véhicule désigné")
        lines.append(f"attestation de {a.attested_by} du {a.verified_on.isoformat()} : {verdict}")
    return lines


def main(argv=None) -> int:
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) in (3, 4) and args[0] == "verifier":
        for line in check(*args[1:]):
            print(line)
        return 0
    print("python -m pgdr.v1_applicabilite verifier <attestations.yaml> <manifest.yaml> [<rattachement.yaml>]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
