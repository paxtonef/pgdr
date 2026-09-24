"""PGDR Part 1 — Manufacturer First Finding (Execution Mandate v0.2 FINAL).

Loader/representation invariants (§3, §4), the builder against the approved
§8 table for all 11 real owner-attested Peugeot entries, the controller/web
flow (§12), and the byte-exact approved driver-facing wording (§7, D-C7).

The deterministic provider is an integration-test mechanism only (see
photo_first_support.py); the manufacturer entries are the exact attested
text copied from PI's seed (fixtures/peugeot_3008_manufacturer_entries.json).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import photo_first_support as sup
from pgdr import web_app as web
from pgdr.application import part1_first_finding as p1
from pgdr.domain.dashboard_knowledge import DashboardReferenceEntry
from pgdr.domain.photo_provenance import LOCATION_QUESTION_ID
from pgdr.enums import DrivingAssessment, FindingBasis, TriageLevel
from pgdr.errors import ConfigurationError
from pgdr.models import EntryFinding, FindingItem

NE = "not_established"
MAPPING = p1.load_part1_mapping()
GENERIC_QUESTION_IDS = {
    "Q-STATE-001", "Q-STATE-002", "Q-SYM-001", "Q-SYM-002", "Q-COND-001", "Q-EVT-001", "Q-EVT-002",
    "Q-EVI-001", "Q-EVI-002",
}


def _finding(entry_id: str, origin: str = "visual_provider_match") -> EntryFinding:
    return p1.build_entry_finding(sup.REAL_ENTRIES[entry_id], identification_origin=origin, mapping=MAPPING)


def _write_mapping(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load(p1.MAPPING_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "mapping.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def _record(raw: dict, entry_id: str) -> dict:
    return next(r for r in raw["entries"] if r["entry_id"] == entry_id)


# ============================================================ §8 table ===
# (stop_vehicle_engine_off, vehicle_immobilization, operability,
#  professional_attention, urgency_phrase, documented_suitability, practical)
_DOC_SUIT = "a PEUGEOT dealer or a qualified workshop"
EXPECTED = {
    "oil-pressure-warning": ("required", "required", "do_not_drive", "required", NE, _DOC_SUIT, "towing_required"),
    "engine-diag-fixed": (NE, NE, NE, "required", "without delay", _DOC_SUIT, "garage_required"),
    "engine-diag-flashing": (NE, NE, NE, "required", NE, _DOC_SUIT, "garage_required"),
    "adblue-level-state-a": (NE, NE, NE, NE, NE, NE, "neither_required"),
    "adblue-level-state-b": (NE, NE, NE, NE, "Promptly", _DOC_SUIT, "neither_required"),
    "adblue-level-state-c": (NE, NE, NE, NE, NE, NE, "neither_required"),
    "adblue-level-state-d": (NE, NE, "starting_prevented", NE, NE, NE, "neither_required"),
    "service-warning-lamp-fixed": (NE, NE, NE, NE, NE, NE, NE),
    "scr-malfunction-detected": (NE, NE, NE, NE, NE, NE, NE),
    "scr-malfunction-confirmed-countdown": (
        NE, NE, NE, "required", "without delay", "a PEUGEOT dealer or qualified workshop", "garage_required"),
    "scr-starting-prevented": (NE, NE, "starting_prevented", "required", NE, _DOC_SUIT, "towing_required"),
}
EXPECTED_DERIVED = {  # (item, rule) for every DERIVED item; everything else is DOCUMENTED or NE
    "oil-pressure-warning": {("vehicle_immobilization", "R-1"), ("operability", "R-1"), ("practical_assistance", "R-2")},
    "scr-starting-prevented": {("practical_assistance", "R-2")},
}
EXPECTED_FIGURES = {
    "adblue-level-state-a": [("1,500–500 miles (2,400–800 km) of range remaining", "l'autonomie AdBlue® restante", True)],
    "adblue-level-state-b": [("500–62 miles (800–100 km) of range remaining", "l'autonomie AdBlue® restante", True)],
    "adblue-level-state-c": [("less than 62 miles (100 km) remaining",
                              "l'autonomie AdBlue® restante avant que le démarrage puisse être empêché", True)],
    "adblue-level-state-d": [("at least 5 litres", "la quantité minimale d'AdBlue® à ajouter", False)],
    "scr-malfunction-confirmed-countdown": [("Up to 685 miles / 1,100 km may remain before engine immobilisation",
                                             "le kilométrage restant avant blocage du démarrage", True)],
}


class TestBuilderMatchesApprovedTable:
    def test_the_mapping_covers_exactly_the_eleven_attested_entries(self):
        assert sorted(k[1] for k in MAPPING) == sorted(sup.REAL_ENTRY_IDS) and len(MAPPING) == 11

    @pytest.mark.parametrize("entry_id", sup.REAL_ENTRY_IDS)
    def test_each_entry_equals_the_section_8_table(self, entry_id):
        f = _finding(entry_id)
        got = (
            f.stop_vehicle_engine_off.value, f.vehicle_immobilization.value, f.operability.value,
            f.professional_attention.value, f.urgency_phrase.value, f.documented_suitability.value,
            f.practical_assistance.requirement.value,
        )
        assert got == EXPECTED[entry_id]
        assert f.provenance.mapping_fingerprint_match is True and f.audit_flags == []
        for name in ("exit_vehicle", "move_away_from_vehicle", "environment_dependent_requirement",
                     "max_speed", "max_distance", "max_duration"):
            assert getattr(f, name).value == NE, name        # NE for all 11 entries (§8 summary)
        derived = {
            (name, getattr(f, name).rule_id) for name in p1.ITEM_VALUE_SETS
            if name != "practical_assistance" and getattr(f, name).basis == FindingBasis.DERIVED
        }
        if f.practical_assistance.requirement.basis == FindingBasis.DERIVED:
            derived.add(("practical_assistance", f.practical_assistance.requirement.rule_id))
        assert derived == EXPECTED_DERIVED.get(entry_id, set())
        assert [(x.source_phrase, x.meaning, x.caution) for x in f.documented_figures] == EXPECTED_FIGURES.get(entry_id, [])
        expected_stops = ["Stop the vehicle as soon as it is safe to do so"] if entry_id == "oil-pressure-warning" else []
        assert [s.source_phrase for s in f.stop_conditions] == expected_stops
        assert f.practical_assistance.provider_status.value == "not_integrated"
        assert f.practical_assistance.precise_location_needed == (
            EXPECTED[entry_id][6] in ("garage_required", "towing_required"))

    def test_no_entry_ever_yields_may_drive(self):
        assert all(_finding(e).operability.value not in ("may_drive", "may_drive_with_restrictions")
                   for e in sup.REAL_ENTRY_IDS)

    def test_manufacturer_text_in_the_finding_is_the_live_record_verbatim(self):
        for entry_id, entry in sup.REAL_ENTRIES.items():
            f = _finding(entry_id)
            assert (f.documented_meaning, f.documented_instruction, f.displayed_message, f.manufacturer_designation) == (
                entry.documented_meaning, entry.documented_instruction, entry.displayed_message,
                entry.manufacturer_designation)
            assert f.provenance.freshness_status == "owner_attested_unverified"
            assert f.provenance.document_id == "9999_9999_326_en-GB"


# ================================================= loader / representation ===

class TestLoaderInvariants:
    def test_may_drive_derived_is_a_load_error(self, tmp_path):
        def mutate(raw):
            _record(raw, "engine-diag-fixed")["items"]["operability"] = {
                "value": "may_drive", "basis": "derived", "rule_id": "R-3", "source_field": "documented_instruction",
                "source_phrase": "Go to a PEUGEOT dealer or a qualified workshop"}
        with pytest.raises(ConfigurationError):
            p1.load_part1_mapping(_write_mapping(tmp_path, mutate))

    def test_may_drive_without_a_phrase_is_rejected(self):
        with pytest.raises(ValueError):
            FindingItem(value="may_drive", basis=FindingBasis.DOCUMENTED)

    def test_may_drive_derived_is_rejected_by_the_model_itself(self):
        f = _finding("engine-diag-fixed")
        derived = FindingItem(value="may_drive", basis=FindingBasis.DERIVED, rule_id="R-1",
                              source_field="documented_instruction", source_phrase="Go to")
        with pytest.raises(ValueError):
            EntryFinding.model_validate({**f.model_dump(), "operability": derived.model_dump()})

    @pytest.mark.parametrize("value,basis", [(NE, "documented"), ("required", "not_established")])
    def test_value_and_basis_must_agree_on_not_established(self, value, basis):
        with pytest.raises(ValueError):
            FindingItem(value=value, basis=FindingBasis(basis),
                        source_field="documented_instruction" if basis != NE else None,
                        source_phrase="x" if basis != NE else None)

    def test_a_source_phrase_that_is_not_a_substring_of_the_live_record_fails_closed(self, tmp_path):
        def mutate(raw):
            _record(raw, "oil-pressure-warning")["items"]["stop_vehicle_engine_off"]["source_phrase"] = "Stop at once"
        mapping = p1.load_part1_mapping(_write_mapping(tmp_path, mutate))
        with pytest.raises(ConfigurationError):
            p1.build_entry_finding(sup.REAL_ENTRIES["oil-pressure-warning"], identification_origin="user_selection",
                                   mapping=mapping)

    @pytest.mark.parametrize("rule_id", ["R-9", "R-3", "R-4", "R-5"])
    def test_unknown_or_non_storable_rule_ids_are_load_errors(self, tmp_path, rule_id):
        def mutate(raw):
            _record(raw, "oil-pressure-warning")["items"]["vehicle_immobilization"]["rule_id"] = rule_id
        with pytest.raises(ConfigurationError):
            p1.load_part1_mapping(_write_mapping(tmp_path, mutate))

    def test_rule_preconditions_are_checked(self, tmp_path):
        def mutate(raw):   # R-2 without professional_attention REQUIRED
            del _record(raw, "scr-starting-prevented")["items"]["professional_attention"]
        with pytest.raises(ConfigurationError):
            p1.load_part1_mapping(_write_mapping(tmp_path, mutate))

    def test_a_figure_can_never_populate_a_distance_limit(self, tmp_path):
        def mutate(raw):
            _record(raw, "scr-malfunction-confirmed-countdown")["items"]["max_distance"] = {
                "value": "Up to 685 miles / 1,100 km may remain before engine immobilisation", "basis": "documented",
                "source_field": "documented_meaning",
                "source_phrase": "Up to 685 miles / 1,100 km may remain before engine immobilisation"}
        with pytest.raises(ConfigurationError):
            p1.load_part1_mapping(_write_mapping(tmp_path, mutate))

    def test_documented_figures_never_populate_max_distance_or_duration_for_any_entry(self):
        for entry_id in sup.REAL_ENTRY_IDS:
            f = _finding(entry_id)
            figures = {x.source_phrase for x in f.documented_figures}
            assert f.max_distance.source_phrase not in figures and f.max_duration.source_phrase not in figures
            assert f.max_distance.value == NE and f.max_duration.value == NE

    def test_fingerprint_mismatch_makes_the_whole_entry_not_established(self):
        live = sup.REAL_ENTRIES["oil-pressure-warning"]
        changed = live.model_copy(update={"documented_instruction": live.documented_instruction + " "})
        f = p1.build_entry_finding(changed, identification_origin="visual_provider_match", mapping=MAPPING)
        assert f.audit_flags == ["mapping_fingerprint_mismatch"] and f.provenance.mapping_fingerprint_match is False
        assert all(getattr(f, n).value == NE for n in p1.ITEM_VALUE_SETS if n != "practical_assistance")
        assert f.practical_assistance.requirement.value == NE
        assert f.documented_instruction == changed.documented_instruction      # verbatim text still present

    def test_an_unmapped_entry_is_all_not_established_with_its_text(self):
        entry = sup.AIRBAG       # synthetic, test-only entry: no mapping record
        f = p1.build_entry_finding(entry, identification_origin="visual_provider_match", mapping=MAPPING)
        assert f.audit_flags == ["no_mapping_record"]
        assert f.stop_vehicle_engine_off.value == f.operability.value == f.practical_assistance.requirement.value == NE
        assert f.documented_meaning == entry.documented_meaning

    def test_stop_vehicle_engine_off_and_operability_are_distinct_fields(self):
        f = _finding("oil-pressure-warning")
        assert "stop_vehicle_engine_off" in EntryFinding.model_fields and "operability" in EntryFinding.model_fields
        g = f.model_copy(update={"stop_vehicle_engine_off": FindingItem.not_established()})
        assert g.operability == f.operability
        h = f.model_copy(update={"operability": FindingItem.not_established()})
        assert h.stop_vehicle_engine_off == f.stop_vehicle_engine_off

    def test_the_mapping_is_not_a_manufacturer_knowledge_store(self):
        """Knowledge boundary (§4): no documented_meaning / documented_instruction
        text appears in the mapping file other than as a phrase anchor."""
        text = p1.MAPPING_PATH.read_text(encoding="utf-8")
        for entry_id, entry in sup.REAL_ENTRIES.items():
            record = MAPPING[(entry.applicability.document_id, entry_id)]
            anchors = {i.source_phrase for i in record.items.values()}
            anchors |= {x.source_phrase for x in record.stop_conditions} | {x.source_phrase for x in record.documented_figures}
            for field in (entry.documented_meaning, entry.documented_instruction, entry.displayed_message):
                if field and field in text:
                    assert field in anchors, (entry_id, field)

    def test_the_fixture_is_the_pi_seed_verbatim_when_pi_is_available(self):
        seed = Path(__file__).resolve().parents[2] / "pi01-main" / "src" / "product_integration" / "knowledge" / "seed_peugeot_3008.py"
        if not seed.exists():
            pytest.skip("PI checkout not available next to PGDR")
        import ast
        tree = ast.parse(seed.read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "_ENTRIES")
        pi_entries = [{k.arg: ast.literal_eval(k.value) for k in call.keywords} for call in node.value.elts]
        fixture = json.loads((Path(__file__).parent / "fixtures" / "peugeot_3008_manufacturer_entries.json").read_text("utf-8"))
        assert fixture["entries"] == pi_entries


# ============================================================== flow ===

@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, sup.HANDOFF_TOKEN)
    saved = (web._photo_wiring, web._session_controller)
    provider = sup.DeterministicDashboardProvider()
    web._photo_wiring = web.PhotoWiring(
        interpretation_provider=provider, knowledge_repository=sup.RealPeugeotKnowledgeRepository(),
    )
    web._session_controller = None
    web._sessions.clear()
    web._photo_intakes.clear()
    try:
        yield TestClient(web.app), provider
    finally:
        web._photo_wiring, web._session_controller = saved
        web._sessions.clear()
        web._photo_intakes.clear()


def _run(client, provider, entry_id, origin, seed):
    handed = sup.handoff(client).json()
    sid = handed["intake_id"]
    client.post("/api/photo/session", json={"intake_id": sid, "consent_media_analysis": True})
    entry = sup.REAL_ENTRIES[entry_id]
    if origin == "visual_provider_match":
        image = provider.script(sup.png_bytes(seed), sup.match(entry, "Voyant observé"))
        payload = client.post(f"/api/photo/{sid}/media", content=image, headers={"Content-Type": "image/png"}).json()
    else:
        image = provider.script(sup.png_bytes(seed), sup.no_match())
        client.post(f"/api/photo/{sid}/media", content=image, headers={"Content-Type": "image/png"})
        payload = client.post(f"/api/photo/{sid}/selection", json={"entry_id": entry_id}).json()
    return sid, payload


def _all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_strings(v)


ORIGINS = ["visual_provider_match", "user_selection"]


class TestPart1Flow:
    @pytest.mark.parametrize("origin", ORIGINS)
    @pytest.mark.parametrize("entry_id", sup.REAL_ENTRY_IDS)
    def test_no_question_follows_the_photo_and_the_session_ends_with_the_finding(self, env, entry_id, origin):
        client, provider = env
        sid, payload = _run(client, provider, entry_id, origin, 400 + sup.REAL_ENTRY_IDS.index(entry_id) * 2 + ORIGINS.index(origin))
        assert payload["status"] == "analysed"
        assert payload["pending_questions"] == []                           # no question at all, incl. Q-STATE-001
        session = web._sessions[sid]
        assert session.state.value in ("completed", "escalated")            # terminal
        assert session.pending_questions == [] and session.questions_asked == []
        assert not [q for q in web._session_controller._case_states[sid].questions if q.id in GENERIC_QUESTION_IDS]
        answered = client.post(f"/api/session/{sid}/answer", json={"question_id": LOCATION_QUESTION_ID, "value": "garage"})
        assert answered.status_code == 400                                  # nothing can be answered

        report = client.get(f"/api/session/{sid}/report").json()
        finding = report["manufacturer_first_finding"]
        assert [e["provenance"]["entry_id"] for e in finding["entries"]] == [entry_id]
        assert finding["entries"][0]["provenance"]["identification_origin"] == origin
        assert report["garage_preparation_report"]["manufacturer_first_finding"] == finding   # additive key
        for legacy_key in ("safety_information", "systems_to_examine", "dashboard_identifications"):
            assert legacy_key in report["garage_preparation_report"]                         # unchanged keys

        presentation = report["part1_presentation"]
        strings = list(_all_strings(presentation))
        assert not any("Aucun signal critique" in s for s in strings)
        assert not any("hypothèses compatibles" in s for s in strings)
        assert not any("112" in s for s in strings)
        # B2-R5 hypotheses stay internal: present in case state, absent from the page payload.
        hyp_descriptions = {h.description for h in web._session_controller._case_states[sid].hypotheses}
        assert not any(d and d in s for d in hyp_descriptions for s in strings)
        if EXPECTED[entry_id][2] == NE:
            assert presentation["entries"][0]["vehicle_use"] == \
                "La notice ne permet pas d'établir si le véhicule peut continuer à rouler."

    @pytest.mark.parametrize("origin", ORIGINS)
    def test_oil_pressure_stop_then_do_not_drive_and_never_aucun_signal_critique(self, env, origin):
        client, provider = env
        sid, payload = _run(client, provider, "oil-pressure-warning", origin, 480 + ORIGINS.index(origin))
        assert payload["escalated"] is True
        assert payload["safety_triage"]["level"] == TriageLevel.EMERGENCY_STOP.value
        assert payload["safety_triage"]["roadside_assistance_recommended"] is True
        assert payload["safety_triage"]["emergency_services_required"] is False
        session = web._sessions[sid]
        assert session.safety_triage.driving_assessment == DrivingAssessment.DO_NOT_DRIVE
        assert "Aucun signal critique" not in session.safety_triage.user_instruction
        report = client.get(f"/api/session/{sid}/report").json()
        assert "Aucun signal critique" not in report["garage_preparation_report"]["safety_information"]["statement"]
        entry = report["part1_presentation"]["entries"][0]
        assert entry["immediate_safety"][0] == \
            "Arrêtez le véhicule dès que vous pouvez le faire en sécurité, puis coupez le contact."     # first (A4)
        assert entry["vehicle_use"] == "Ne reprenez pas la route avec ce véhicule."                    # separate
        assert entry["practical"]["requirement"] == "towing_required"
        assert report["manufacturer_first_finding"]["triage_composition"] == \
            ["R-5:stop_vehicle_engine_off:oil-pressure-warning"]

    @pytest.mark.parametrize("entry_id", ["adblue-level-state-a", "adblue-level-state-b", "adblue-level-state-c",
                                          "scr-malfunction-confirmed-countdown"])
    def test_documented_figures_carry_the_t6_caution_and_operability_stays_not_established(self, env, entry_id):
        client, provider = env
        _, payload = _run(client, provider, entry_id, "visual_provider_match", 490 + sup.REAL_ENTRY_IDS.index(entry_id))
        sid = payload["session_id"]
        entry = client.get(f"/api/session/{sid}/report").json()["part1_presentation"]["entries"][0]
        (figure,) = entry["restrictions"]["figures"]
        assert figure["caution"].endswith("Ce n'est ni une autorisation de rouler, ni une distance de conduite sûre.")
        assert entry["vehicle_use"] == "La notice ne permet pas d'établir si le véhicule peut continuer à rouler."

    @pytest.mark.parametrize("entry_id", sup.REAL_ENTRY_IDS)
    def test_numeric_audit_every_rendered_number_is_in_the_source(self, env, entry_id):
        client, provider = env
        _, payload = _run(client, provider, entry_id, "visual_provider_match", 520 + sup.REAL_ENTRY_IDS.index(entry_id))
        presentation = client.get(f"/api/session/{payload['session_id']}/report").json()["part1_presentation"]
        entry = sup.REAL_ENTRIES[entry_id]
        source = " ".join(filter(None, [
            entry.documented_meaning, entry.documented_instruction, entry.displayed_message,
            entry.manufacturer_designation, entry.applicability.document_id, entry.applicability.document_title,
        ]))
        source_numbers = set(re.findall(r"\d+", source))
        rendered_numbers = {n for s in _all_strings(presentation) for n in re.findall(r"\d+", s)}
        assert rendered_numbers <= source_numbers, rendered_numbers - source_numbers

    def test_none_of_the_offered_symbols_ends_part_1_with_no_entry(self, env):
        client, provider = env
        handed = sup.handoff(client).json()
        sid = handed["intake_id"]
        client.post("/api/photo/session", json={"intake_id": sid, "consent_media_analysis": True})
        image = provider.script(sup.png_bytes(560), sup.no_match())
        client.post(f"/api/photo/{sid}/media", content=image, headers={"Content-Type": "image/png"})
        payload = client.post(f"/api/photo/{sid}/selection", json={"entry_id": None}).json()
        assert payload["pending_questions"] == [] and web._sessions[sid].state.value == "completed"
        report = client.get(f"/api/session/{sid}/report").json()
        assert report["manufacturer_first_finding"]["entries"] == []
        assert report["part1_presentation"]["banner"] == [] and report["part1_presentation"]["entries"] == []
        assert report["part1_presentation"]["no_identification"].encode("utf-8") == NO_IDENTIFIED_SYMBOL.encode("utf-8")
        assert report["part1_presentation"]["end"] == p1.APPROVED_BANNERS["T8"][0]
        assert client.post(f"/api/session/{sid}/answer",
                           json={"question_id": "Q-STATE-001", "value": "garage"}).status_code == 400

    def test_the_page_banner_is_t1_and_the_legacy_banner_is_gone(self, env):
        client, _ = env
        page = client.get("/").text
        assert "PGDR lit le voyant de votre tableau de bord avec la notice du constructeur de votre véhicule." in page
        assert "hypothèses compatibles" not in page and "__PART1_T1__" not in page


# ============================================ approved wording, byte-exact ===
# Literal copies of Execution Mandate v0.2 FINAL §7 T1–T8 and §7.1 (D-C7).

APPROVED_T = {
    "T1": ("PGDR lit le voyant de votre tableau de bord avec la notice du constructeur de votre véhicule.",
           "PGDR n'établit pas la cause mécanique d'une panne et ne remplace pas l'examen du véhicule par un professionnel."),
    "T2": ("Premier Constat Constructeur",
           "Ce constat reprend ce que la notice du constructeur indique pour le voyant identifié sur votre photo. "
           "Lorsque la notice donne une consigne — par exemple arrêter le véhicule ou couper le contact — cette "
           "consigne s'applique : suivez-la.",
           "Ce constat ne recherche pas la cause mécanique de la panne et ne remplace pas l'examen du véhicule par un "
           "professionnel."),
    "T3": ("Source : notice constructeur « {document_title} » (réf. {document_id}). Transcription fournie et attestée "
           "par l'exploitant de PGDR ; elle n'a pas été vérifiée de façon indépendante. Le texte du constructeur est "
           "reproduit en anglais, sans traduction.",),
    "T4": ("« Non établi » signifie que la notice du constructeur ne précise pas ce point. Cela ne veut jamais dire que "
           "rouler, ou continuer à rouler, est sans risque.",),
    "T5": ("Texte du constructeur (anglais, tel que fourni) :",),
    "T6": ("Ce chiffre est indiqué par le constructeur pour décrire {meaning}. Ce n'est ni une autorisation de rouler, "
           "ni une distance de conduite sûre.",),
    "T7": ("PGDR ne recherche pas encore de garage ni de dépanneur. Contactez vous-même {documented_suitability, "
           "verbatim, if established; otherwise: \"un professionnel qualifié\"}.",),
    "T8": ("Ce Premier Constat est terminé. PGDR ne propose pas encore de pré-diagnostic mécanique approfondi "
           "(recherche de la cause) : cette étape n'est pas disponible aujourd'hui.",),
}
APPROVED_71 = {
    "operability = DO_NOT_DRIVE": "Ne reprenez pas la route avec ce véhicule.",
    "operability = STARTING_PREVENTED": "D'après la notice, le démarrage du moteur est empêché.",
    "operability = MAY_DRIVE (unused)": "D'après la notice, le véhicule peut rouler.",
    "operability = MAY_DRIVE_WITH_RESTRICTIONS (unused)":
        "D'après la notice, le véhicule peut rouler, avec les restrictions ci-dessous.",
    "operability = NOT_ESTABLISHED": "La notice ne permet pas d'établir si le véhicule peut continuer à rouler.",
    "stop_vehicle_engine_off = REQUIRED":
        "Arrêtez le véhicule dès que vous pouvez le faire en sécurité, puis coupez le contact.",
    "vehicle_immobilization = REQUIRED": "Laissez le véhicule à l'arrêt jusqu'à l'intervention d'un professionnel.",
    "professional_attention = REQUIRED":
        "Faites intervenir un professionnel. Délai indiqué par la notice : « {urgency_phrase} » / non précisé.",
    "practical = GARAGE_REQUIRED": "Le véhicule doit être vu par : « {documented_suitability} ».",
    "practical = TOWING_REQUIRED": "Le véhicule ne devant pas rouler, son transport vers un professionnel nécessite "
                                   "un dépannage (sauf intervention sur place).",
    "practical = NEITHER_REQUIRED":
        "La notice indique une action que vous pouvez réaliser vous-même (voir le texte du constructeur).",
    "max_speed / max_distance / max_duration = NOT_ESTABLISHED":
        "Vitesse maximale / distance maximale / durée maximale : non établie par la notice.",
    "exit_vehicle / move_away / environment = NOT_ESTABLISHED":
        "Quitter le véhicule / s'en éloigner / précaution liée au lieu : non établi par la notice.",
    # Owner Completion Authority, item 2.
    "stop_vehicle_engine_off = NOT_ESTABLISHED":
        "Arrêt immédiat du véhicule et coupure du contact : non établi par la notice.",
    "vehicle_immobilization = NOT_ESTABLISHED": "Maintien du véhicule à l'arrêt : non établi par la notice.",
    "professional_attention = NOT_ESTABLISHED": "Intervention d'un professionnel : non établie par la notice.",
    "practical_assistance = NOT_ESTABLISHED": "Besoin d'un garage ou d'un dépannage : non établi par la notice.",
}
NO_IDENTIFIED_SYMBOL = (
    "Aucun voyant n'a pu être identifié parmi les voyants proposés à partir de la notice disponible. "
    "PGDR ne peut donc pas établir de Premier Constat Constructeur pour cette photo."
)


def test_t1_to_t8_are_byte_identical_to_the_approved_text():
    assert p1.APPROVED_BANNERS == APPROVED_T
    for key, lines in APPROVED_T.items():
        assert [l.encode("utf-8") for l in p1.APPROVED_BANNERS[key]] == [l.encode("utf-8") for l in lines]


def test_section_7_1_labels_are_byte_identical_to_the_approved_text():
    assert p1.APPROVED_LABELS == APPROVED_71
    assert list(p1.APPROVED_LABELS) == list(APPROVED_71)


@pytest.mark.parametrize("key", [
    "stop_vehicle_engine_off = NOT_ESTABLISHED", "vehicle_immobilization = NOT_ESTABLISHED",
    "professional_attention = NOT_ESTABLISHED", "practical_assistance = NOT_ESTABLISHED",
])
def test_the_four_completion_labels_are_byte_identical(key):
    assert p1.APPROVED_LABELS[key].encode("utf-8") == APPROVED_71[key].encode("utf-8")


def test_the_no_identified_symbol_text_is_byte_identical():
    assert p1.APPROVED_NO_IDENTIFIED_SYMBOL.encode("utf-8") == NO_IDENTIFIED_SYMBOL.encode("utf-8")


@pytest.mark.parametrize("entry_id", sup.REAL_ENTRY_IDS)
def test_every_not_established_item_is_listed_with_its_approved_label(entry_id):
    """§5 item 9: every NE item, grouped, now that every item has an approved
    NOT_ESTABLISHED label (the four completion labels included)."""
    f = _finding(entry_id)
    listed = web._present_entry(f)["not_established"]
    single = {
        "stop_vehicle_engine_off": f.stop_vehicle_engine_off, "vehicle_immobilization": f.vehicle_immobilization,
        "professional_attention": f.professional_attention, "practical_assistance": f.practical_assistance.requirement,
    }
    for name, item in single.items():
        label = APPROVED_71[f"{name} = NOT_ESTABLISHED"]
        assert (label in listed) == (item.value == NE), (name, entry_id)
    assert APPROVED_71["max_speed / max_distance / max_duration = NOT_ESTABLISHED"] in listed
    assert APPROVED_71["exit_vehicle / move_away / environment = NOT_ESTABLISHED"] in listed
