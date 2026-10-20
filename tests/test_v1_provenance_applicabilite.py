"""Provenance VIR -> PI -> PGDR and the applicability decision (passe identité, provenance et applicabilité).

A value resting on a driver confirmation reaches PGDR in field_provenance, marked user_confirmed, never in
vehicle_identity; it never becomes established and never makes the notice applicable by itself. The
applicability decision keeps four questions apart (value and provenance, criterion justified, exact match,
decision); an attestation is accepted only for the vehicle and the notice version it covers. An attachment
keeps earlier validations when only applicability metadata differ. FICTIVE notice and values only.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

import v1_fictive_notice as fx
from pgdr import v1_applicabilite as va
from pgdr import v1_parcours as v1
from pgdr import v1_rattachement as vr
from pgdr import web_app as web
from pgdr.adapters.manifest_notice_repository import ManifestNoticeRepository, NoticeRejected, content_fingerprint
from pgdr.application.vehicle_applicability import resolve_dashboard_reference
from pgdr.domain.dashboard_knowledge import ApplicabilityStatus
from pgdr.models import VehicleIdentityContext

TOKEN = "v1-provenance-handoff-token"
VEHICLE_A = "asset-fictif-a"
VEHICLE_B = "asset-fictif-b"
CONFIRMATION = {"source_id": "driver_confirmation", "method": "user_confirmation", "role": "user_confirmation"}
DECODE = {"source_id": "vin_decoder", "method": "decode", "role": "concordant"}
SIMULATED = {"source_id": "registration_provider", "method": "provider", "role": "concordant", "simulated": True}


def wire(monkeypatch, manifest, *, attestations=None, dev_trial=False, rattachement=None):
    repo = ManifestNoticeRepository(manifest, rattachement_path=rattachement) if manifest is not None else None
    monkeypatch.setattr(v1, "_wiring", v1.build_wiring(repo, dev_trial=dev_trial, applicability_path=attestations))
    monkeypatch.setattr(v1, "_parcours", {})
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, TOKEN)
    return repo


def confirmed_generation_context(*, vehicle_ref=VEHICLE_A, generation=fx.VEHICLE["generation"], **extra) -> dict:
    """What PI's map_resolution hands on when VIR's generation rests on the driver's confirmation alone."""
    body = {"resolution_id": "VIR-FICTIVE-PROV", "resolution_status": "provisionally_resolved",
            "vehicle_identity": {**fx.VIR_IDENTITY, "generation": None},
            "unresolved_fields": ["generation"], "contradictions": [],
            "field_provenance": {
                "manufacturer": {"status": "provider_not_established", "value": fx.VEHICLE["manufacturer"],
                                 "sources": [SIMULATED]},
                "model": {"status": "provider_not_established", "value": fx.VEHICLE["model"], "sources": [SIMULATED]},
                "generation": {"status": "user_confirmed", "value": generation, "sources": [CONFIRMATION]}},
            "vehicle_ref": vehicle_ref}
    body.update(extra)
    return body


def post(body: dict) -> dict:
    r = TestClient(web.app).post("/api/v1/vir-handoff", json=body, headers={web.IDENTITY_HANDOFF_TOKEN_HEADER: TOKEN})
    assert r.status_code == 200, r.text
    return r.json()


def criterion(value, notice_kind="printed_notice", vehicle_kind="registration_document"):
    return {"value": value, "notice_source": {"kind": notice_kind, "reference": "couverture fictive, page F-0"},
            "vehicle_source": {"kind": vehicle_kind, "reference": "rubrique fictive"}}


def attestation(manifest: Path, *, vehicle_ref=VEHICLE_A, **over) -> dict:
    repo = ManifestNoticeRepository(manifest)
    a = {"status": "VALIDE", "attested_by": "Fictive Owner", "verified_on": "2026-10-18",
         "document_id": repo.catalogue.document.document_id,
         "catalogue_content_sha256": repo.catalogue.content_sha256, "vehicle_ref": vehicle_ref,
         "criteria": {k: criterion(v) for k, v in fx.VEHICLE.items()}}
    a.update(over)
    return a


def attestations_file(tmp_path: Path, *items: dict) -> Path:
    path = tmp_path / "applicabilite.yaml"
    path.write_text(yaml.safe_dump({"format": va.ATTESTATION_FORMAT, "attestations": list(items)},
                                   allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def notice(tmp_path) -> Path:
    return fx.build(tmp_path / "notice", applicability_established=False)


@pytest.fixture
def established_notice(tmp_path) -> Path:
    return fx.build(tmp_path / "notice-established", applicability_established=True)


# --- contract ---------------------------------------------------------------------------------------------

class TestContract:

    def test_confirmed_value_is_kept_with_its_provenance_and_apart_from_admissible_values(self):
        ctx = VehicleIdentityContext.model_validate(confirmed_generation_context())
        p = ctx.field_provenance["generation"]
        assert (p.status.value, p.value) == ("user_confirmed", fx.VEHICLE["generation"])
        assert [s.method for s in p.sources] == ["user_confirmation"]
        assert ctx.vehicle_identity["generation"] is None and "generation" in ctx.unresolved_fields

    def test_confirmed_value_never_in_vehicle_identity(self):
        body = confirmed_generation_context()
        body["vehicle_identity"]["generation"] = fx.VEHICLE["generation"]
        with pytest.raises(ValidationError, match="never in vehicle_identity"):
            VehicleIdentityContext.model_validate(body)

    def test_confirmation_alone_never_reads_as_established(self):
        body = confirmed_generation_context()
        body["field_provenance"]["generation"]["status"] = "established"
        with pytest.raises(ValidationError, match="never establishes"):
            VehicleIdentityContext.model_validate(body)

    def test_user_confirmed_needs_the_confirmation_source(self):
        body = confirmed_generation_context()
        body["field_provenance"]["generation"]["sources"] = [DECODE]
        with pytest.raises(ValidationError):
            VehicleIdentityContext.model_validate(body)

    def test_older_context_without_provenance_reads_as_before(self):
        ctx = VehicleIdentityContext.model_validate({"resolution_id": "OLD", "resolution_status": "resolved",
                                                     "vehicle_identity": dict(fx.VIR_IDENTITY)})
        keys = va.identity_keys(ctx)
        assert {k.status for k in keys.values()} == {va.NOT_STATED}   # no qualification added
        assert ctx.field_provenance == {} and ctx.vehicle_ref is None

    def test_provider_value_not_established_is_not_promoted(self):
        keys = va.identity_keys(VehicleIdentityContext.model_validate(confirmed_generation_context()))
        assert keys["model"].status == "provider_not_established"
        assert va.PROVENANCE_LABELS[keys["model"].status] == "fourni par une source, non établi"
        assert keys["generation"].status == "user_confirmed"
        assert va.PROVENANCE_LABELS["user_confirmed"].startswith("confirmé par le conducteur")


# --- decision ---------------------------------------------------------------------------------------------

class TestDecision:

    def test_confirmed_generation_alone_never_opens_even_on_an_established_notice(self, monkeypatch,
                                                                                  established_notice):
        wire(monkeypatch, established_notice)
        r = post(confirmed_generation_context())
        assert r["status"] == "applicability_not_confirmed" and fx.notice_parcours_opened() == []
        assert any("seule confirmation du conducteur" in x for x in r["reasons"])
        assert r["to_verify"] and "déjà validés" in r["next_action"]
        shown = {k["key"]: k for k in r["identity"]}
        assert shown["generation"]["provenance_label"].startswith("confirmé par le conducteur")

    def test_without_attestation_the_refusal_names_what_is_missing(self, monkeypatch, notice):
        wire(monkeypatch, notice)
        r = post(confirmed_generation_context())
        assert r["status"] == "applicability_not_confirmed"
        assert r["message"] == va.MESSAGES["applicability_not_confirmed"]
        assert any("n'est pas établie par sa revue" in x for x in r["reasons"])
        assert any("Aucune attestation" in x for x in r["reasons"])
        assert any("nom du fichier" in x for x in r["to_verify"])

    def test_attestation_for_this_vehicle_and_version_opens(self, monkeypatch, notice, tmp_path):
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, attestation(notice)))
        r = post(confirmed_generation_context())
        assert r["status"] == "opened" and r["applicability_basis"] == "attestation"
        p = v1._parcours[r["parcours_id"]]
        assert p.vehicle["generation"] is None                     # still not an admissible value elsewhere
        assert any("confirmé par le conducteur" in x for x in p.vehicle_shown)
        state = TestClient(web.app).get(f"/api/v1/parcours/{r['parcours_id']}").json()
        assert state["vehicle_shown"] == p.vehicle_shown

    def test_attestation_for_another_vehicle_is_refused(self, monkeypatch, notice, tmp_path):
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, attestation(notice, vehicle_ref=VEHICLE_B)))
        r = post(confirmed_generation_context())
        assert r["status"] == "applicability_not_confirmed"
        assert any("Aucune attestation" in x for x in r["reasons"])
        assert post(confirmed_generation_context(vehicle_ref=None))["status"] == "applicability_not_confirmed"

    def test_two_owners_two_vehicles_are_isolated(self, monkeypatch, notice, tmp_path):
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, attestation(notice, vehicle_ref=VEHICLE_A)))
        assert post(confirmed_generation_context(vehicle_ref=VEHICLE_A))["status"] == "opened"
        assert post(confirmed_generation_context(vehicle_ref=VEHICLE_B))["status"] == "applicability_not_confirmed"

    def test_attestation_for_another_notice_version_is_refused(self, monkeypatch, notice, tmp_path):
        a = attestation(notice)
        d = fx.load(notice)
        d["entries"][0]["documented_meaning"] = d["entries"][0]["documented_meaning"] + " Fictive addition."
        fx.approve_manifest(d)
        fx.save(notice, d)                                          # content modified, reviewed again
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, a))
        r = post(confirmed_generation_context())
        assert r["status"] == "applicability_not_confirmed"
        assert any("autre version" in x for x in r["reasons"])

    def test_attestation_for_another_notice_is_refused(self, monkeypatch, notice, tmp_path):
        other = fx.build(tmp_path / "other", applicability_established=False)
        d = fx.load(other)
        d["document_id"] = "FICTIVE-OTHER-DOC"
        fx.approve_manifest(d)
        fx.save(other, d)
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, attestation(other)))
        assert post(confirmed_generation_context())["status"] == "applicability_not_confirmed"

    @pytest.mark.parametrize("kind", ["file_name", "url", "pdf_metadata"])
    def test_notice_criterion_from_file_name_or_url_is_not_justified(self, monkeypatch, notice, tmp_path, kind):
        a = attestation(notice)
        a["criteria"]["generation"] = criterion(fx.VEHICLE["generation"], notice_kind=kind)
        path = attestations_file(tmp_path, a)
        loaded = va.load_attestations(path)
        assert loaded.accepted == [] and "non justifié" in loaded.rejected[0][1]
        wire(monkeypatch, notice, attestations=path)
        assert post(confirmed_generation_context())["status"] == "applicability_not_confirmed"

    def test_driver_confirmation_alone_does_not_justify_a_vehicle_criterion(self, notice, tmp_path):
        a = attestation(notice)
        a["criteria"]["generation"] = criterion(fx.VEHICLE["generation"], vehicle_kind="driver_confirmation")
        loaded = va.load_attestations(attestations_file(tmp_path, a))
        assert loaded.accepted == [] and "confirmation du conducteur" in loaded.rejected[0][1]

    @pytest.mark.parametrize("change", [
        lambda a: a.pop("attested_by"), lambda a: a.update(status="PROPOSITION"),
        lambda a: a.update(verified_on=(date.today() + timedelta(days=1)).isoformat()),
        lambda a: a["criteria"].pop("generation"), lambda a: a["criteria"].update(market=criterion("FR")),
        lambda a: a.update(catalogue_content_sha256="0" * 12)])
    def test_incomplete_attestation_is_rejected_with_its_reason(self, notice, tmp_path, change):
        a = attestation(notice)
        change(a)
        loaded = va.load_attestations(attestations_file(tmp_path, a))
        assert loaded.accepted == [] and loaded.rejected[0][1]

    def test_attested_criteria_must_be_the_notice_and_the_vehicle(self, monkeypatch, notice, tmp_path):
        a = attestation(notice)
        a["criteria"]["generation"] = criterion("X9")
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, a))
        r = post(confirmed_generation_context())
        assert r["status"] == "applicability_not_confirmed"
        assert any("ne sont pas ceux de la notice" in x for x in r["reasons"])

    def test_different_model_label_is_refused_with_a_reason_and_no_alias(self, monkeypatch, established_notice):
        wire(monkeypatch, established_notice)
        body = confirmed_generation_context()
        body["vehicle_identity"]["model"] = "Testmobile Nouvelle"
        body["field_provenance"]["model"]["value"] = "Testmobile Nouvelle"
        r = post(body)
        assert r["status"] == "vehicle_not_supported"
        assert any("Le modèle transmis (« Testmobile Nouvelle »)" in x and "sans correspondance approchée" in x
                   for x in r["reasons"])

    def test_explicit_equality_ignores_only_case_and_edge_spaces(self, monkeypatch, notice, tmp_path):
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, attestation(notice)))
        body = confirmed_generation_context()
        body["vehicle_identity"]["model"] = "  TESTMOBILE "
        assert post(body)["status"] == "opened"

    def test_missing_generation_is_refused_and_never_deduced(self, monkeypatch, notice, tmp_path):
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, attestation(notice)), dev_trial=True)
        body = confirmed_generation_context()
        del body["field_provenance"]["generation"]
        body["vehicle_identity"]["production"] = {"year": 2019, "start_date": None, "end_date": None}
        r = post(body)
        assert r["status"] == "vehicle_identity_insufficient"
        assert r["reasons"] == ["La génération du véhicule n'est pas connue : VIR ne la transmet pas comme une valeur "
                                "utilisable."]
        assert "la génération peut être confirmée par le conducteur" in r["next_action"]

    def test_unknown_model_never_suggests_a_driver_confirmation(self, monkeypatch, notice):
        wire(monkeypatch, notice)
        body = confirmed_generation_context()
        body["vehicle_identity"]["model"] = None
        del body["field_provenance"]["model"]
        r = post(body)
        assert r["status"] == "vehicle_identity_insufficient"
        assert "ne peuvent pas être confirmés par le conducteur" in r["next_action"]

    def test_contradiction_prevents_opening_even_with_attestation_and_dev_trial(self, monkeypatch, notice, tmp_path):
        wire(monkeypatch, notice, attestations=attestations_file(tmp_path, attestation(notice)), dev_trial=True)
        r = post(confirmed_generation_context(contradictions=["model"]))
        assert r["status"] == "vehicle_identity_insufficient"
        assert any("contradictoire" in x for x in r["reasons"]) and "contradiction" in r["next_action"]
        assert fx.notice_parcours_opened() == []

    def test_established_values_on_an_established_notice_open_as_before(self, monkeypatch, established_notice):
        wire(monkeypatch, established_notice)
        body = {"resolution_id": "VIR-EST", "resolution_status": "resolved", "vehicle_identity": dict(fx.VIR_IDENTITY),
                "field_provenance": {k: {"status": "established", "value": v, "sources": [DECODE]}
                                     for k, v in fx.VIR_IDENTITY.items()}}
        r = post(body)
        assert r["status"] == "opened" and r["applicability_basis"] == "notice_established"

    def test_photo_first_reference_keeps_a_confirmed_key_as_a_gap(self, established_notice):
        ctx = VehicleIdentityContext.model_validate(confirmed_generation_context())
        ref = resolve_dashboard_reference(ctx, ManifestNoticeRepository(established_notice))
        assert ref.applicability_status == ApplicabilityStatus.VEHICLE_IDENTITY_INSUFFICIENT
        assert "generation (user_confirmed only)" in ref.provenance_note

    def test_check_command_reports_each_attestation(self, notice, tmp_path):
        bad = attestation(notice)
        bad["criteria"]["generation"] = criterion(fx.VEHICLE["generation"], notice_kind="file_name")
        lines = va.check(attestations_file(tmp_path, attestation(notice), bad), notice)
        assert any("recevable pour cette version" in x for x in lines)
        assert any("non justifié" in x for x in lines)


class TestNoSideEffectOnSafety:

    def test_restitution_and_premier_constat_identical_whatever_the_basis(self, monkeypatch, established_notice,
                                                                          tmp_path):
        """SafetyEngine, R-5 and the sorting rules see the same vehicle and give the same result whether the
        parcours opened on established values or on an attestation over a confirmed generation."""
        def run(body):
            client = TestClient(web.app)
            r = post(body)
            assert r["status"] == "opened", r
            pid = r["parcours_id"]
            client.post(f"/api/v1/parcours/{pid}/vir-seen")
            client.post(f"/api/v1/parcours/{pid}/consent", json={"accepted": True})
            client.post(f"/api/v1/parcours/{pid}/selection", json={"entry_ids": ["fx_red_fluid", "fx_amber_sensor"]})
            out = client.post(f"/api/v1/parcours/{pid}/confirm",
                              json={"entry_ids": ["fx_red_fluid", "fx_amber_sensor"], "confirmed": True}).json()
            out = json.loads(json.dumps(out).replace(pid, "PID"))
            return out.pop("vehicle"), out.pop("vehicle_shown"), out

        wire(monkeypatch, established_notice,
             attestations=attestations_file(tmp_path, attestation(established_notice)))
        legacy = run({"resolution_id": "VIR-EST", "resolution_status": "provisionally_resolved",
                      "vehicle_identity": dict(fx.VIR_IDENTITY)})
        attested = run(confirmed_generation_context())
        assert attested[2] == legacy[2]                     # restitution, Premier Constat, safety outcome
        assert legacy[0]["generation"] == "X1" and attested[0]["generation"] is None   # admissible values only
        assert any("confirmé par le conducteur" in x for x in attested[1])


# --- attachment of earlier validations ---------------------------------------------------------------------

def _changed_metadata(manifest: Path) -> tuple[str, dict]:
    """Changes only the applicability metadata (not reviewed again): returns the earlier fingerprint and the
    earlier value."""
    d = fx.load(manifest)
    earlier_fp, earlier = content_fingerprint(d), copy.deepcopy(d.get("applicability_vehicle_under_review"))
    d["applicability_vehicle_under_review"] = {"description": "fictive vehicle under review",
                                               "applicability_established": True}
    fx.save(manifest, d)
    return earlier_fp, earlier


def _rattachement(tmp_path: Path, manifest: Path, earlier_fp: str, earlier, **over) -> Path:
    raw = {"format": vr.RATTACHEMENT_FORMAT, "status": "VALIDE", "decided_by": "Fictive Owner",
           "decided_on": "2026-10-18", "decision": "Applicabilité au véhicule fictif établie.",
           "from_content_sha256": earlier_fp, "to_content_sha256": content_fingerprint(fx.load(manifest)),
           "previous_values": {"applicability_vehicle_under_review": earlier}, "previously_absent": []}
    raw.update(over)
    path = tmp_path / "rattachement.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


class TestRattachement:

    def test_metadata_change_without_attachment_makes_the_review_obsolete(self, notice):
        _changed_metadata(notice)
        with pytest.raises(NoticeRejected, match="review obsolete"):
            ManifestNoticeRepository(notice)

    def test_attachment_keeps_the_review_and_the_validated_files_unchanged(self, monkeypatch, tmp_path):
        notice = fx.build(tmp_path / "notice-groups", applicability_established=False, with_groups=True)
        groups = fx.build_groups(notice)                            # VALIDE, bound to the earlier fingerprint
        before = {p: p.read_bytes() for p in (groups, notice)}
        review_before = fx.load(notice)["review"]
        earlier_fp, earlier = _changed_metadata(notice)
        path = _rattachement(tmp_path, notice, earlier_fp, earlier)
        repo = ManifestNoticeRepository(notice, rattachement_path=path)
        assert repo.catalogue.content_sha256 != earlier_fp
        assert repo.catalogue.accepted_content_sha256 == {earlier_fp, repo.catalogue.content_sha256}
        assert repo.rattachement.changed_fields == ("applicability_vehicle_under_review",)
        assert fx.load(notice)["review"] == review_before          # the old signature is not rewritten
        assert groups.read_bytes() == before[groups]                # nor the validated file
        w = v1.build_wiring(repo, dev_trial=False, groups_path=groups)
        assert w.groups_status == "validated"
        assert repo.catalogue.applicability_established is True

    def test_attachment_does_not_carry_an_applicability_attestation(self, monkeypatch, notice, tmp_path):
        a = attestation(notice)                                     # bound to the earlier fingerprint
        earlier_fp, earlier = _changed_metadata(notice)
        path = _rattachement(tmp_path, notice, earlier_fp, earlier)
        wire(monkeypatch, notice, rattachement=path, attestations=attestations_file(tmp_path, a))
        r = post(confirmed_generation_context())
        assert r["status"] == "applicability_not_confirmed" and any("autre version" in x for x in r["reasons"])

    def test_content_difference_cannot_be_attached(self, notice, tmp_path):
        earlier_fp, earlier = _changed_metadata(notice)
        d = fx.load(notice)
        old_entries = copy.deepcopy(d["entries"])
        d["entries"][0]["documented_meaning"] += " Fictive change."
        fx.save(notice, d)
        path = _rattachement(tmp_path, notice, earlier_fp, earlier,
                             previous_values={"applicability_vehicle_under_review": earlier, "entries": old_entries})
        with pytest.raises(NoticeRejected, match="différence de contenu"):
            ManifestNoticeRepository(notice, rattachement_path=path)

    def test_unlisted_change_is_refused(self, notice, tmp_path):
        earlier_fp, earlier = _changed_metadata(notice)
        d = fx.load(notice)
        d["entries"][0]["documented_meaning"] += " Fictive change."
        fx.save(notice, d)
        path = _rattachement(tmp_path, notice, earlier_fp, earlier)
        with pytest.raises(NoticeRejected, match="pas exacte"):
            ManifestNoticeRepository(notice, rattachement_path=path)

    def test_listed_but_unchanged_field_is_refused(self, notice, tmp_path):
        earlier_fp, earlier = _changed_metadata(notice)
        d = fx.load(notice)
        path = _rattachement(tmp_path, notice, earlier_fp, earlier, previous_values={
            "applicability_vehicle_under_review": earlier,
            "applicability_period_note": d.get("applicability_period_note")})
        assert "applicability_period_note" in d
        with pytest.raises(NoticeRejected, match="inexistante"):
            ManifestNoticeRepository(notice, rattachement_path=path)

    def test_unvalidated_attachment_is_refused(self, notice, tmp_path):
        earlier_fp, earlier = _changed_metadata(notice)
        with pytest.raises(NoticeRejected, match="non validé"):
            ManifestNoticeRepository(notice, rattachement_path=_rattachement(tmp_path, notice, earlier_fp, earlier,
                                                                             status="PROPOSITION"))

    def test_proposal_lists_the_exact_differences_and_never_validates(self, notice, tmp_path):
        earlier = fx.load(notice)
        _changed_metadata(notice)
        proposal = vr.propose(earlier, fx.load(notice))
        assert proposal["status"] == "PROPOSITION" and "impossible" not in proposal
        assert list(proposal["previous_values"]) == ["applicability_vehicle_under_review"]
        changed = fx.load(notice)
        changed["entries"][0]["documented_meaning"] += " x"
        assert "entries" in vr.propose(earlier, changed)["impossible"]
