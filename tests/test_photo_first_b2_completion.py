"""B2 photo-first completion (E1-E5) -- integration tests through the REAL
upload endpoint, the REAL MediaResolverPort implementation and the REAL
DashboardInterpretationPort call. Only the interpretation RESULT is scripted
(deterministic provider, integration-test mechanism only -- see
photo_first_support.py). None of these PASSes is a Real-World Photo-First PASS.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import photo_first_support as sup
from pgdr import web_app as web
from pgdr.application.diagnostic_intake_from_interpretation import (
    B2D_SOURCE_RULE_ID, build_diagnostic_intake,
)
from pgdr.domain.enums import EvidenceDirection, ObservationSource
from pgdr.domain.photo_provenance import (
    LOCATION_QUESTION_ID, PHOTO_ORIGIN_OBSERVATION_KINDS, PROVIDER_OBSERVATION_KIND, USER_SELECTION_ADAPTER_ID,
    USER_SELECTION_OBSERVATION_KIND, USER_SELECTION_SOURCE_RULE_ID,
)
from pgdr.enums import TriageLevel
from pgdr.models import VehicleIdentityContext


def _vir_context(name: str = "peugeot_3008_ii_by_plate") -> VehicleIdentityContext:
    return VehicleIdentityContext.model_validate(sup.vir_identity(name))


@pytest.fixture()
def env(monkeypatch):
    """Fresh wiring + controller per test; restores module state after."""
    monkeypatch.setenv(web.IDENTITY_HANDOFF_TOKEN_ENV, sup.HANDOFF_TOKEN)
    saved = (web._photo_wiring, web._session_controller)
    provider = sup.DeterministicDashboardProvider()
    web._photo_wiring = web.PhotoWiring(
        interpretation_provider=provider, knowledge_repository=sup.InMemoryKnowledgeRepository(),
    )
    web._session_controller = None
    web._sessions.clear()
    web._photo_intakes.clear()
    client = TestClient(web.app)
    try:
        yield client, provider
    finally:
        web._photo_wiring, web._session_controller = saved
        web._sessions.clear()
        web._photo_intakes.clear()


def _start(client, *, consent=True, identity=None):
    """PI hands over the VIR identity artifact, then the driver consents.
    Creates a pre-session INTAKE only: PGDR itself starts when the first
    photo is submitted. Returns the handoff response when no intake results."""
    handed = sup.handoff(client, identity)
    if handed.json().get("status") != "awaiting_consent":
        return handed
    return client.post("/api/photo/session", json={
        "intake_id": handed.json()["intake_id"], "consent_media_analysis": consent,
    })


def _intake(client, **kw) -> str:
    return _start(client, **kw).json()["intake_id"]


def _upload(client, sid, content: bytes, content_type="image/png"):
    return client.post(f"/api/photo/{sid}/media", content=content, headers={"Content-Type": content_type})


def _case(sid):
    return web._session_controller._case_states[sid]


def _drive_questions(client, sid, first_payload, answer="je ne sais pas", limit=30):
    """Answers every question through the real /answer endpoint until the
    session completes; returns the ordered list of question ids asked."""
    asked = []
    payload = first_payload
    for _ in range(limit):
        pending = payload["pending_questions"]
        if not pending:
            break
        q = pending[0]
        asked.append(q["question_id"])
        value = q["choices"][-1] if q["choices"] else answer
        payload = client.post(f"/api/session/{sid}/answer", json={"question_id": q["question_id"], "value": value}).json()
    return asked


# ---------------------------------------------------------------- consent ---

class TestConsent:
    def test_declined_consent_shows_bounded_message_and_pgdr_does_not_start(self, env):
        client, provider = env
        r = _start(client, consent=False)
        assert r.status_code == 200  # a product-level explanation, not an error state
        body = r.json()
        assert body["status"] == "consent_required"
        assert "PGDR ne peut pas démarrer sans votre accord" in body["message"]
        assert "erreur" not in body["message"].lower()
        assert not web._sessions
        assert [i.consent_media_analysis for i in web._photo_intakes.values()] == [False]
        assert web._session_controller is None or not web._session_controller._case_states
        assert provider.calls == []

    def test_controller_refuses_to_start_a_photo_case_without_media_consent(self, env):
        client, _ = env
        controller = web._get_or_create_controller()
        from pgdr.models import Consent, InitialComplaint, PreGarageDiagnosticRequest
        request = PreGarageDiagnosticRequest(
            request_id="R1",
            vehicle_identity_context=_vir_context(),
            initial_complaint=InitialComplaint(free_text=""),
            consent=Consent(media_analysis_allowed=False),
        )
        with pytest.raises(PermissionError):
            controller.start_photo_case(request)

    def test_photo_cannot_be_submitted_before_a_consented_session_exists(self, env):
        client, provider = env
        r = _upload(client, "NO-SUCH-SESSION", sup.png_bytes(1))
        assert r.status_code == 404
        unconsented = sup.handoff(client).json()["intake_id"]
        assert _upload(client, unconsented, sup.png_bytes(1)).status_code == 400
        assert provider.calls == [] and not web._sessions

    def test_consent_for_an_unknown_intake_is_refused(self, env):
        client, _ = env
        r = client.post("/api/photo/session", json={"intake_id": "SESS-NOPE", "consent_media_analysis": True})
        assert r.status_code == 404


# ------------------------------------------------- VIR identity boundary ---

class TestVirIdentityBoundary:
    """PGDR consumes the VIR identity artifact handed over by PI; it never
    asks the driver for the vehicle, and fails closed when VIR did not
    establish what document applicability needs."""

    def test_real_vir_identity_resolves_the_reference_without_any_driver_input(self, env):
        client, provider = env
        body = sup.handoff(client).json()
        assert body["status"] == "awaiting_consent"
        intake = web._photo_intakes[body["intake_id"]]
        assert intake.identity == _vir_context()
        assert intake.reference_set.applicability_status.value == "reference_set_available"
        # No first-registration date anywhere in the chain, and none asked for.
        assert intake.reference_set.vehicle_applicability.first_registration_date is None
        assert provider.calls == [] and not web._sessions

    def test_the_vir_artifact_reaches_the_pgdr_request_verbatim_with_a_truthful_trace(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(3), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        identity = sup.vir_identity()
        sid = _intake(client, identity=identity)
        _upload(client, sid, image)
        session = web._sessions[sid]
        assert session.request.vehicle_identity_context.model_dump(mode="json") == identity
        reasons = [t["reason"] for t in session.trace]
        assert f"VIR identity artifact consumed: {identity['resolution_id']}" in reasons
        assert not [r for r in reasons if "identity context consumed" in r]

    def test_unsupported_vehicle_is_reported_and_nothing_is_interpreted(self, env):
        client, provider = env
        body = sup.handoff(client, sup.vir_identity("renault_clio_v_by_plate")).json()
        assert body["status"] == "vehicle_not_supported"
        assert "Aucune notice constructeur" in body["message"]
        assert "intake_id" not in body
        assert not web._photo_intakes and not web._sessions and provider.calls == []

    @pytest.mark.parametrize("identity", [
        sup.vir_identity("peugeot_3008_manual_no_generation"),            # real VIR manual path
        {**sup.vir_identity(), "unresolved_fields": ["generation"]},       # VIR says: not established
        {**sup.vir_identity(), "contradictions": ["model"]},               # VIR says: contradictory
        {**sup.vir_identity(), "resolution_status": "insufficient_data", "vehicle_identity": None},
    ], ids=["manual-no-generation", "generation-unresolved", "model-contradicted", "no-vehicle"])
    def test_insufficient_vir_identity_fails_closed_without_asking_the_driver(self, env, identity):
        client, provider = env
        body = sup.handoff(client, identity).json()
        assert body["status"] == "vehicle_identity_insufficient"
        assert body["applicability_status"] == "vehicle_identity_insufficient"
        assert "ne la complète pas" in body["message"]
        assert "intake_id" not in body
        assert not web._photo_intakes and not web._sessions and provider.calls == []

    def test_handoff_requires_the_pi_credential(self, env, monkeypatch):
        client, _ = env
        assert sup.handoff(client, token=None).status_code == 403
        assert sup.handoff(client, token="wrong").status_code == 403
        monkeypatch.delenv(web.IDENTITY_HANDOFF_TOKEN_ENV)
        assert sup.handoff(client).status_code == 503      # not configured: closed
        assert not web._photo_intakes

    def test_a_browser_cannot_type_a_vehicle_into_pgdr(self, env):
        client, _ = env
        typed = {"consent_media_analysis": True, "manufacturer": "Peugeot", "model": "3008", "generation": "II",
                 "first_registration_date": "2020-09-15"}
        assert client.post("/api/photo/session", json=typed).status_code == 422
        assert client.post("/api/photo/identity-handoff", json=typed).status_code in (403, 422)
        assert client.post("/api/photo/SESS-X/registration-date",
                           json={"first_registration_date": "2020-09-15"}).status_code == 404
        assert not web._photo_intakes

    def test_no_fabricated_vir_resolution_remains_in_the_web_product(self):
        import inspect
        source = inspect.getsource(web)
        for gone in ("WEB-VIR-UNRESOLVED", "declared_by", "ResolutionStatus.PROVISIONALLY_RESOLVED",
                     "first_registration_date", "RegistrationDateRequest"):
            assert gone not in source

    def test_no_provider_or_repository_configured_is_reported_plainly(self, env):
        client, _ = env
        web._photo_wiring = web.PhotoWiring()
        body = sup.handoff(client).json()
        assert body["status"] == "photo_analysis_unavailable"
        assert not web._sessions and not web._photo_intakes


# ---------------------------------------- real bytes through the real path ---

class TestRealBytesThroughRealPipeline:
    def test_uploaded_bytes_reach_the_provider_through_the_resolver_and_are_discarded(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(10), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        r = _upload(client, sid, image)
        assert r.status_code == 200
        assert len(provider.calls) == 1
        call = provider.calls[0]
        assert call["sha256"] == sup.sha(image) and call["length"] == len(image)
        assert call["media_reference"].startswith("media-")
        assert call["entry_ids"]  # the governed reference set was supplied
        assert len(web._media_store) == 0, "consent does not authorize retention: bytes must be dropped"

    def test_non_image_and_empty_uploads_are_rejected_before_any_interpretation(self, env):
        client, provider = env
        sid = _intake(client)
        assert _upload(client, sid, b"hello", "text/plain").status_code == 400
        assert _upload(client, sid, b"", "image/png").status_code == 400
        assert provider.calls == []

    def test_provider_output_failing_governed_validation_never_reaches_case_state(self, env):
        """B2-V: a provider result naming an entry that is not in the supplied
        reference set is rejected at the governed boundary (fail closed): the
        request fails, nothing is ingested, no evidence/hypothesis/safety change,
        and the bytes are still discarded."""
        client, provider = env
        rogue = provider.script(sup.png_bytes(14), lambda media: sup._result(
            media, observation="Voyant inventé", status=sup.MatchStatus.MATCH,
            entry_id="not-in-the-reference-set", match_conf=sup.Confidence.HIGH))
        sid = _intake(client)
        r = _upload(client, sid, rogue)
        assert r.status_code == 502
        state = _case(sid)
        assert not [o for o in state.observations if o.kind in PHOTO_ORIGIN_OBSERVATION_KINDS]   # nothing ingested
        assert not state.evidence and not state.hypotheses
        assert state.safety_state.triage.level == TriageLevel.MONITOR_AND_DOCUMENT
        assert len(web._media_store) == 0

    def test_a_provider_that_ignores_the_bytes_is_detectable(self, env):
        """The deterministic provider is keyed on the bytes: unscripted bytes
        fail loudly, so a wiring that lost the image could not silently pass."""
        client, provider = env
        sid = _intake(client)
        with pytest.raises(AssertionError):
            _upload(client, sid, sup.png_bytes(99))


# ------------------------------------------------------------------ MATCH ---

class TestMatchFlow:
    def test_match_reaches_case_state_b2r_relevance_and_ends_with_the_first_finding(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(11), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        assert payload["status"] == "analysed"

        state = _case(sid)
        provider_obs = [o for o in state.observations if o.kind == PROVIDER_OBSERVATION_KIND]
        assert len(provider_obs) == 1 and provider_obs[0].source_type == ObservationSource.PROVIDER
        assert provider_obs[0].context["adapter_id"] == sup.DETERMINISTIC_ADAPTER_ID
        assert provider_obs[0].context["match_status"] == "match"
        b2d_evidence = [e for e in state.evidence if e.source_rule_id == B2D_SOURCE_RULE_ID]
        assert len(b2d_evidence) == 1 and b2d_evidence[0].direction == EvidenceDirection.NEUTRAL

        # B2-R5 relevance: a non-causal, tracked hypothesis + NEUTRAL weight-0.0 evidence.
        b2r_hyps = [h for h in state.hypotheses if (h.domain_ref or "").startswith("b2r_dashboard:")]
        assert len(b2r_hyps) == 1 and b2r_hyps[0].hypothesis_type == "engine_running"
        b2r_evidence = [e for e in state.evidence if e.target_hypothesis_id == b2r_hyps[0].id
                        and (e.source_rule_id or "").startswith("automotive.dashboard.")]
        assert b2r_evidence and all(e.direction == EvidenceDirection.NEUTRAL and e.weight == 0.0 for e in b2r_evidence)

        # PGDR Part 1 (mandate v0.2 §11 step 5, rewritten): no question at all
        # follows the photo -- no location question, no generic question, no
        # "do you have a photo?" -- and the session ends with the First Finding.
        assert payload["safety_triage"]["level"] == TriageLevel.MONITOR_AND_DOCUMENT.value
        assert payload["pending_questions"] == []
        assert _drive_questions(client, sid, payload) == []
        assert web._sessions[sid].state.value == "completed"

        report = client.get(f"/api/session/{sid}/report").json()
        finding = report["manufacturer_first_finding"]
        assert [e["provenance"]["entry_id"] for e in finding["entries"]] == ["oil-pressure-warning"]
        idents = report["garage_preparation_report"]["dashboard_identifications"]
        assert [i["origin"] for i in idents] == ["visual_provider_match"]
        assert idents[0]["machine_verified"] is True
        assert any("identifié sur la photo" in o for o in report["user_summary"]["main_observations"])

    def test_text_free_start_requires_no_complaint_location_or_urgency(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(12), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        _upload(client, sid, image)
        assert web._sessions[sid].request.initial_complaint.free_text == ""

    def test_no_complaint_is_fabricated_from_the_absence_of_one(self, env):
        """An empty complaint must not be classified as an 'unknown' symptom
        that seeds a hypothesis (it ranked above the manufacturer-backed one and
        headlined the driver summary). The photo case knows only what the
        governed photo path established."""
        client, provider = env
        image = provider.script(sup.png_bytes(15), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        state = _case(sid)
        assert not [o for o in state.observations if o.kind in ("raw_complaint", "symptom")]
        assert not [e for e in state.evidence if e.source_rule_id == "automotive.initial_symptom_support"]
        assert [h.domain_ref for h in state.hypotheses] == [
            "b2r_dashboard:Peugeot:9999_9999_326_en-GB:oil-pressure-warning:engine_running"
        ]
        _drive_questions(client, sid, payload)
        report = client.get(f"/api/session/{sid}/report").json()
        assert [c["label"] for c in report["user_summary"]["plausible_causes"]] == ["le fonctionnement du moteur"]
        assert "non identifié" not in report["user_summary"]["situation_explanation"]
        assert [x["system_family"] for x in report["garage_preparation_report"]["systems_to_examine"]] == ["engine_running"]


# ------------------------------------------------------------------ E5 ---

class TestFallbackAmbiguous:
    def test_only_the_preserved_candidates_are_offered_and_selection_is_user_provenance(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(20), sup.ambiguous([sup.ENGINE_FIXED, sup.ENGINE_FLASHING]))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        assert payload["status"] == "selection_required" and payload["trigger"] == "ambiguous_match"
        assert {o["entry_id"] for o in payload["options"]} == {"engine-diag-fixed", "engine-diag-flashing"}
        assert all("documented_meaning" not in o and "meaning" not in " ".join(o.keys()) for o in payload["options"])

        # The ambiguity is preserved as PROVIDER observation, NO evidence, nothing silently resolved.
        state = _case(sid)
        assert [o.context["match_status"] for o in state.observations if o.kind == PROVIDER_OBSERVATION_KIND] == ["ambiguous_match"]
        assert not [e for e in state.evidence if e.source_rule_id == B2D_SOURCE_RULE_ID]

        # A selection outside the offered candidates is rejected (fail closed).
        bad = client.post(f"/api/photo/{sid}/selection", json={"entry_id": "oil-pressure-warning"})
        assert bad.status_code == 400

        done = client.post(f"/api/photo/{sid}/selection", json={"entry_id": "engine-diag-flashing"}).json()
        assert done["status"] == "analysed"
        _assert_user_selection_provenance(_case(sid), "engine-diag-flashing", trigger="ambiguous_match")
        # B2-R relevance ran on the user-selected reference (engine-diag-flashing rule).
        assert any((h.domain_ref or "").endswith("engine-diag-flashing:engine_running") for h in _case(sid).hypotheses)


class TestFallbackNoMatch:
    def test_full_reference_set_is_offered_and_selection_is_user_provenance(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(21), sup.no_match())
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        assert payload["status"] == "selection_required" and payload["trigger"] == "no_match"
        assert {o["entry_id"] for o in payload["options"]} == {e.entry_id for e in sup.ALL_ENTRIES}
        done = client.post(f"/api/photo/{sid}/selection", json={"entry_id": "oil-pressure-warning"}).json()
        assert done["status"] == "analysed"
        _assert_user_selection_provenance(_case(sid), "oil-pressure-warning", trigger="no_match")

    def test_none_of_these_records_an_observation_only_and_no_evidence(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(22), sup.no_match())
        sid = _intake(client)
        _upload(client, sid, image)
        done = client.post(f"/api/photo/{sid}/selection", json={"entry_id": None}).json()
        assert done["status"] == "analysed"
        state = _case(sid)
        obs = [o for o in state.observations if o.kind == USER_SELECTION_OBSERVATION_KIND]
        assert len(obs) == 1 and obs[0].context["selected_reference_entry_id"] is None
        assert not [e for e in state.evidence if e.source_rule_id == USER_SELECTION_SOURCE_RULE_ID]
        assert not [h for h in state.hypotheses if (h.domain_ref or "").startswith("b2r_dashboard:")]


class TestFallbackInsufficientQualityRetake:
    def test_retakes_up_to_the_limit_then_falls_back_to_the_full_list(self, env):
        client, provider = env
        bad1 = provider.script(sup.png_bytes(30), sup.insufficient())
        bad2 = provider.script(sup.png_bytes(31), sup.insufficient())
        bad3 = provider.script(sup.png_bytes(32), sup.insufficient())
        sid = _intake(client)

        first = _upload(client, sid, bad1).json()
        assert first["status"] == "retake_requested" and first["retakes_used"] == 1 and first["retakes_remaining"] == 1
        second = _upload(client, sid, bad2).json()
        assert second["status"] == "retake_requested" and second["retakes_used"] == 2 and second["retakes_remaining"] == 0
        third = _upload(client, sid, bad3).json()
        assert third["status"] == "selection_required" and third["trigger"] == "insufficient_visual_quality"
        assert {o["entry_id"] for o in third["options"]} == {e.entry_id for e in sup.ALL_ENTRIES}
        assert len(provider.calls) == 3

        # Every attempt is preserved as its own PROVIDER observation.
        statuses = [o.context["match_status"] for o in _case(sid).observations if o.kind == PROVIDER_OBSERVATION_KIND]
        assert statuses == ["insufficient_visual_quality"] * 3

        client.post(f"/api/photo/{sid}/selection", json={"entry_id": "engine-diag-fixed"})
        _assert_user_selection_provenance(_case(sid), "engine-diag-fixed", trigger="insufficient_visual_quality")

    def test_a_good_retake_proceeds_as_a_normal_match(self, env):
        client, provider = env
        bad = provider.script(sup.png_bytes(33), sup.insufficient())
        good = provider.script(sup.png_bytes(34), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        assert _upload(client, sid, bad).json()["status"] == "retake_requested"
        assert _upload(client, sid, good).json()["status"] == "analysed"
        assert not [o for o in _case(sid).observations if o.kind == USER_SELECTION_OBSERVATION_KIND]

    def test_declining_the_retake_goes_straight_to_the_fallback(self, env):
        client, provider = env
        bad = provider.script(sup.png_bytes(35), sup.insufficient())
        sid = _intake(client)
        assert _upload(client, sid, bad).json()["status"] == "retake_requested"
        declined = client.post(f"/api/photo/{sid}/decline-retake").json()
        assert declined["status"] == "selection_required" and declined["trigger"] == "insufficient_visual_quality"

    def test_selection_is_refused_when_none_was_requested(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(36), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        assert _upload(client, sid, image).json()["status"] == "analysed"     # no fallback pending
        assert client.post(f"/api/photo/{sid}/selection", json={"entry_id": "oil-pressure-warning"}).status_code == 400
        assert client.post(f"/api/photo/{sid}/decline-retake").status_code == 400


def _assert_user_selection_provenance(state, entry_id, *, trigger):
    user_obs = [o for o in state.observations if o.kind == USER_SELECTION_OBSERVATION_KIND]
    assert len(user_obs) == 1
    u = user_obs[0]
    assert u.source_type == ObservationSource.USER
    assert u.context["adapter_id"] == USER_SELECTION_ADAPTER_ID
    assert u.context["machine_verified"] is False
    assert u.context["selected_reference_entry_id"] == entry_id
    assert u.context["triggering_match_status"] == trigger
    ev = [e for e in state.evidence if e.source_rule_id == USER_SELECTION_SOURCE_RULE_ID]
    assert len(ev) == 1 and ev[0].observation_ids == [u.id]
    assert ev[0].direction == EvidenceDirection.NEUTRAL and ev[0].target_hypothesis_id is None
    assert "non vérifiée visuellement" in ev[0].rationale
    # never a machine-verified visual match
    assert not [e for e in state.evidence if e.source_rule_id == B2D_SOURCE_RULE_ID]


class TestUserVsProviderProvenanceIsNeverConflated:
    def test_case_state_and_reports_keep_the_two_provenances_distinct(self, env):
        client, provider = env
        # Photo A -> real provider MATCH; then a second case where the driver selects.
        matched = provider.script(sup.png_bytes(40), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        unmatched = provider.script(sup.png_bytes(41), sup.no_match())
        sid_m = _intake(client)
        sid_u = _intake(client)
        pm = _upload(client, sid_m, matched).json()
        _upload(client, sid_u, unmatched)
        pu = client.post(f"/api/photo/{sid_u}/selection", json={"entry_id": "oil-pressure-warning"}).json()

        sm, su = _case(sid_m), _case(sid_u)
        # markers
        m_obs = next(o for o in sm.observations if o.kind == PROVIDER_OBSERVATION_KIND)
        u_obs = next(o for o in su.observations if o.kind == USER_SELECTION_OBSERVATION_KIND)
        assert (m_obs.source_type, u_obs.source_type) == (ObservationSource.PROVIDER, ObservationSource.USER)
        assert m_obs.context["adapter_id"] != u_obs.context["adapter_id"]
        assert "machine_verified" not in m_obs.context and u_obs.context["machine_verified"] is False
        m_rules = {e.source_rule_id for e in sm.evidence if e.observation_ids == [m_obs.id]}
        u_rules = {e.source_rule_id for e in su.evidence if e.observation_ids == [u_obs.id]}
        # (B2-R relevance evidence, if any, links to the same observation: it is downstream of both.)
        assert B2D_SOURCE_RULE_ID in m_rules and USER_SELECTION_SOURCE_RULE_ID not in m_rules
        assert USER_SELECTION_SOURCE_RULE_ID in u_rules and B2D_SOURCE_RULE_ID not in u_rules

        # reports
        for sid, payload in ((sid_m, pm), (sid_u, pu)):
            _drive_questions(client, sid, payload)
        rm = client.get(f"/api/session/{sid_m}/report").json()
        ru = client.get(f"/api/session/{sid_u}/report").json()
        im = rm["garage_preparation_report"]["dashboard_identifications"]
        iu = ru["garage_preparation_report"]["dashboard_identifications"]
        assert (im[0]["origin"], im[0]["machine_verified"]) == ("visual_provider_match", True)
        assert (iu[0]["origin"], iu[0]["machine_verified"]) == ("user_selection", False)
        m_text = " ".join(rm["user_summary"]["main_observations"])
        u_text = " ".join(ru["user_summary"]["main_observations"])
        assert "identifié sur la photo" in m_text and "non vérifiée" not in m_text
        assert "indiqué par vous" in u_text and "non vérifiée sur la photo" in u_text
        assert "identifié sur la photo" not in u_text


# ------------------------------------------------------------ E4 safety ---

class TestSafetyReevaluation:
    def test_provider_output_alone_cannot_affect_safety_state(self, env):
        """The separation is provable: running the provider and the whole
        governed intake (B2-V -> B2-D) directly leaves session/case safety
        untouched. ONLY SessionController.acquire_photo -> SafetyEngine can
        change it, from governed reference entries."""
        client, provider = env
        brake = provider.script(sup.png_bytes(50), sup.match(sup.BRAKE, "Voyant rouge de frein"))
        blurry = provider.script(sup.png_bytes(55), sup.insufficient())
        sid = _intake(client)
        assert _upload(client, sid, blurry).json()["status"] == "retake_requested"   # a started, still-neutral case
        controller = web._session_controller
        session = web._sessions[sid]
        before_session, before_case = session.safety_triage.level, _case(sid).safety_state.triage.level

        media = sup.ResolvedMedia(content=brake, media_type=web.MediaType.IMAGE, reference="media-x")
        intake = build_diagnostic_intake(provider, media, web._photo_intakes[sid].reference_set)
        assert intake.matched_reference_entries  # the provider DID match a brake warning ...
        assert session.safety_triage.level == before_session == TriageLevel.MONITOR_AND_DOCUMENT
        assert _case(sid).safety_state.triage.level == before_case
        assert not session.warning_indicators and not session.pending_questions
        assert controller._case_states[sid].safety_state.preempts_analysis is False

        # ... and only the governed path (acquire_photo -> SafetyEngine) changes it.
        payload = _upload(client, sid, brake).json()
        assert payload["safety_triage"]["level"] == TriageLevel.DO_NOT_DRIVE.value

    def test_photo_derived_signal_raises_safety_and_no_question_follows(self, env):
        """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2): the
        photo-derived safety elevation still happens through the unmodified
        SafetyEngine, but the former location question is no longer asked."""
        client, provider = env
        image = provider.script(
            sup.png_bytes(51),
            sup.match(sup.OIL, "Voyant rouge de pression d'huile"),
            sup.match(sup.AIRBAG, "Voyant rouge d'airbag"),
        )
        sid = _intake(client)
        payload = _upload(client, sid, image).json()

        assert payload["status"] == "analysed"
        assert payload["safety_triage"]["level"] == TriageLevel.PROMPT_INSPECTION.value
        assert payload["pending_questions"] == []
        assert web._sessions[sid].state.value == "completed"
        assert not [o for o in _case(sid).observations if o.kind == f"answer:{LOCATION_QUESTION_ID}"]
        finding = client.get(f"/api/session/{sid}/report").json()["manufacturer_first_finding"]
        assert [e["provenance"]["entry_id"] for e in finding["entries"]] == ["oil-pressure-warning", "test-airbag-warning"]

    def test_critical_photo_signal_escalates_and_no_question_follows(self, env):
        """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2)."""
        client, provider = env
        image = provider.script(sup.png_bytes(52), sup.match(sup.BRAKE, "Voyant rouge de frein"))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        assert payload["escalated"] is True
        assert payload["safety_triage"]["level"] == TriageLevel.DO_NOT_DRIVE.value
        assert payload["pending_questions"] == []
        answered = client.post(f"/api/session/{sid}/answer", json={"question_id": LOCATION_QUESTION_ID, "value": "bord de route"})
        assert answered.status_code == 400 and "signal de sécurité" in answered.json()["detail"]
        # No ordinary question can follow an escalated session; existing 400 unchanged.
        assert client.post(f"/api/session/{sid}/answer",
                           json={"question_id": "Q-SYM-001", "value": "toujours"}).status_code == 400
        report = client.get(f"/api/session/{sid}/report").json()
        assert report["user_summary"]["safety_level"] == TriageLevel.DO_NOT_DRIVE.value
        assert [e["provenance"]["entry_id"] for e in report["manufacturer_first_finding"]["entries"]] == ["test-brake-warning"]

    def test_user_selected_symbol_is_evaluated_by_the_same_safety_engine(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(53), sup.no_match())
        sid = _intake(client)
        _upload(client, sid, image)
        payload = client.post(f"/api/photo/{sid}/selection", json={"entry_id": "test-airbag-warning"}).json()
        assert payload["safety_triage"]["level"] == TriageLevel.PROMPT_INSPECTION.value
        # Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2): no question follows.
        assert payload["pending_questions"] == []
        assert web._sessions[sid].state.value == "completed"
        finding = client.get(f"/api/session/{sid}/report").json()["manufacturer_first_finding"]
        assert [(e["provenance"]["entry_id"], e["provenance"]["identification_origin"]) for e in finding["entries"]] == \
            [("test-airbag-warning", "user_selection")]

    def test_no_elevation_means_no_question_at_all(self, env):
        """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5): not only no
        location question -- no question of any kind follows the photo."""
        client, provider = env
        image = provider.script(sup.png_bytes(54), sup.match(sup.ENGINE_FLASHING, "Voyant orange clignotant"))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        assert payload["safety_triage"]["level"] == TriageLevel.MONITOR_AND_DOCUMENT.value
        assert payload["pending_questions"] == [] and _drive_questions(client, sid, payload) == []
        assert web._sessions[sid].state.value == "completed"
        assert client.get(f"/api/session/{sid}/report").json()["manufacturer_first_finding"]["entries"]


# ------------------------------------------------------ session isolation ---

class TestSessionIsolation:
    def test_interleaved_sessions_keep_their_own_photo_consent_and_vehicle_state(self, env):
        client, provider = env
        a_img = provider.script(sup.png_bytes(60), sup.ambiguous([sup.ENGINE_FIXED, sup.ENGINE_FLASHING]))
        b_img = provider.script(sup.png_bytes(61), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid_a = sup.handoff(client).json()["intake_id"]   # A: identity handed over, no consent yet
        sid_b = _intake(client)                            # B: consented
        assert sid_a != sid_b
        assert not web._photo_intakes[sid_a].consent_media_analysis and web._photo_intakes[sid_b].consent_media_analysis

        assert _upload(client, sid_a, a_img).status_code == 400          # A: no consent yet -> refused
        b_payload = _upload(client, sid_b, b_img).json()                 # B proceeds independently
        assert b_payload["status"] == "analysed"
        client.post("/api/photo/session", json={"intake_id": sid_a, "consent_media_analysis": True})
        a_payload = _upload(client, sid_a, a_img).json()
        assert a_payload["status"] == "selection_required"

        sa, sb = _case(sid_a), _case(sid_b)
        assert not [o for o in sb.observations if o.context.get("match_status") == "ambiguous_match"]
        assert not [h for h in sa.hypotheses if (h.domain_ref or "").startswith("b2r_dashboard:")]
        assert web._photo_intakes[sid_a].identity is not web._photo_intakes[sid_b].identity
        ctrl = web._session_controller
        assert ctrl.photo_case_state(web._sessions[sid_a]).phase.value == "selection_required"
        assert ctrl.photo_case_state(web._sessions[sid_b]).phase.value == "completed"

        client.post(f"/api/photo/{sid_a}/selection", json={"entry_id": "engine-diag-fixed"})
        assert not [o for o in _case(sid_b).observations if o.kind == USER_SELECTION_OBSERVATION_KIND]
        assert [o for o in _case(sid_a).observations if o.kind == USER_SELECTION_OBSERVATION_KIND]

    def test_retake_counters_are_per_session(self, env):
        client, provider = env
        bad = provider.script(sup.png_bytes(62), sup.insufficient())
        sid_a = _intake(client)
        sid_b = _intake(client)
        _upload(client, sid_a, bad)
        _upload(client, sid_a, bad)
        assert _upload(client, sid_b, bad).json()["retakes_used"] == 1
        assert web._session_controller.photo_case_state(web._sessions[sid_a]).retakes_used == 2


# ------------------------------------------------ pages and legacy path ---

class TestPages:
    def test_photo_first_page_has_no_generic_upfront_fields(self, env):
        client, _ = env
        html = client.get("/").text
        assert 'lang="fr"' in html and "photo" in html.lower()
        for gone in ('id="location"', 'id="urgency"', 'id="complaint"', "<textarea", "Où se trouve actuellement le véhicule ?",
                     "Urgence perçue", "Décrivez le problème", "startSession()"):
            assert gone not in html
        assert 'id="photo-input"' in html and 'id="consent-checkbox"' in html

    def test_photo_first_page_never_asks_for_the_vehicle(self, env):
        client, _ = env
        html = client.get("/").text
        for gone in ('id="vehicle-manufacturer"', 'id="vehicle-model"', 'id="vehicle-generation"',
                     'id="registration-date"', "Marque du véhicule", "Génération", "première mise en circulation",
                     "registration-date"):
            assert gone not in html


# ------------------------------------- product invariants: no photo / no consent ---

class TestNoPhotoNoPgdr:
    def test_identity_and_consent_alone_do_not_start_pgdr(self, env):
        """No dashboard photo -> PGDR does not start: an accepted intake is
        not a PGDR session/case."""
        client, provider = env
        body = _start(client).json()
        assert body["status"] == "awaiting_photo"
        sid = body["intake_id"]
        assert "session_id" not in body
        assert not web._sessions
        assert web._session_controller is None or not web._session_controller._case_states
        assert client.get(f"/api/session/{sid}/state").status_code == 404
        assert client.get(f"/api/session/{sid}/report").status_code == 404
        assert client.post(f"/api/session/{sid}/answer", json={"question_id": "Q-SYM-001", "value": "x"}).status_code == 404
        assert client.post(f"/api/photo/{sid}/selection", json={"entry_id": None}).status_code == 404
        assert client.post(f"/api/photo/{sid}/decline-retake").status_code == 404
        assert provider.calls == []

    def test_a_rejected_photo_does_not_start_pgdr(self, env):
        client, provider = env
        sid = _intake(client)
        assert _upload(client, sid, b"not an image", "text/plain").status_code == 400
        assert _upload(client, sid, b"", "image/png").status_code == 400
        assert not web._sessions
        assert web._session_controller is None or not web._session_controller._case_states

    def test_pgdr_starts_exactly_when_the_first_photo_is_submitted_with_the_intake_id(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(13), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        assert not web._sessions
        assert _upload(client, sid, image).status_code == 200
        assert list(web._sessions) == [sid]
        assert web._sessions[sid].request.consent.media_analysis_allowed is True
        assert web._sessions[sid].request.initial_complaint.free_text == ""

    def test_no_consent_no_session(self, env):
        client, provider = env
        assert _start(client, consent=False).json()["status"] == "consent_required"
        assert not web._sessions
        assert not any(i.consent_media_analysis for i in web._photo_intakes.values())


class TestNoTextFirstEntryInTheWebProduct:
    """There is no user-accessible text-first path into PGDR: the only route
    that can lead to a session is the consented photo intake."""

    def test_legacy_page_and_text_start_endpoint_do_not_exist(self, env):
        client, _ = env
        assert client.get("/legacy").status_code == 404
        for method, path in (("post", "/api/session/start"), ("get", "/api/session/start"), ("post", "/api/session")):
            r = client.request(method.upper(), path, json={"complaint": "La voiture tremble au ralenti"})
            assert r.status_code in (404, 405)
        assert not web._sessions

    def test_the_only_routes_are_the_photo_intake_and_the_post_start_session_api(self, env):
        client, _ = env
        methods = {(r.path, m) for r in web.app.routes for m in getattr(r, "methods", set()) if m not in ("HEAD", "OPTIONS")}
        session_creating = {(p, m) for (p, m) in methods if m == "POST"}
        assert session_creating == {
            ("/api/photo/identity-handoff", "POST"),              # PI -> PGDR VIR identity (credentialed)
            ("/api/photo/session", "POST"),                       # consent for an intake (creates no PGDR session)
            ("/api/photo/{session_id}/media", "POST"),            # the only place a PGDR session is created
            ("/api/photo/{session_id}/decline-retake", "POST"),
            ("/api/photo/{session_id}/selection", "POST"),
            ("/api/session/{session_id}/answer", "POST"),
        }
        assert not any("complaint" in p for (p, _) in methods)

    def test_no_request_model_of_any_web_route_carries_a_complaint(self, env):
        for model in (web.PhotoSessionRequest, web.SymbolSelectionRequest, web.SubmitAnswerRequest):
            assert not [f for f in model.model_fields if "complaint" in f or "plainte" in f]
        assert not hasattr(web, "StartSessionRequest")
        assert set(web.PhotoSessionRequest.model_fields) == {"intake_id", "consent_media_analysis"}


class TestNoExternalImageTransfer:
    def test_photo_path_modules_import_no_network_or_external_provider_client(self):
        import inspect
        import re as _re
        from pgdr import session_controller
        from pgdr.application import photo_first
        forbidden = _re.compile(
            r"^\s*(import|from)\s+(requests|httpx|urllib|urllib3|http\.client|socket|aiohttp|anthropic|openai|boto3|botocore|"
            r"google\.cloud|vertexai|smtplib|ftplib)\b", _re.M,
        )
        for module in (web, session_controller, photo_first):
            assert not forbidden.search(inspect.getsource(module)), module.__name__

    def test_no_production_vision_provider_is_wired_by_default(self, env):
        client, _ = env
        web._photo_wiring = None
        import os
        os.environ.pop("PGDR_PHOTO_WIRING_FACTORY", None)
        assert web._get_photo_wiring().interpretation_provider is None
        assert web._get_photo_wiring().knowledge_repository is None


# ------------------------------------------- escalated-session /answer boundary ---

def _escalated_text_session(complaint: str):
    """An ESCALATED session created through the core SessionController.start()
    (the pre-photo-first escalation path) and placed in the web store, so the
    /answer boundary can be pinned for escalation paths the web product itself
    can no longer start."""
    controller = web._get_or_create_controller()
    from pgdr.models import Consent, InitialComplaint, PreGarageDiagnosticRequest
    request = PreGarageDiagnosticRequest(
        request_id="BOUNDARY-" + complaint[:6],
        vehicle_identity_context=_vir_context(),
        initial_complaint=InitialComplaint(free_text=complaint),
        consent=Consent(),
    )
    session = controller.start(request)
    web._sessions[session.session_id] = session
    return session


class TestEscalatedSessionAnswerBoundary:
    """Decision 2: /answer accepts an answer from an ESCALATED session ONLY
    when a safety question is actually pending. Both sides are pinned."""

    # ---- A. the newly authorized case --------------------------------------

    def test_A_escalated_photo_session_has_no_safety_question_to_answer(self, env):
        """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2): the
        post-photo location question no longer exists, so an escalated photo
        session has nothing pending and ends with the First Finding."""
        client, provider = env
        image = provider.script(sup.png_bytes(70), sup.match(sup.BRAKE, "Voyant rouge de frein"))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        assert payload["escalated"] is True
        assert payload["pending_questions"] == []

        r = client.post(f"/api/session/{sid}/answer", json={"question_id": LOCATION_QUESTION_ID, "value": "bord de route"})
        assert r.status_code == 400 and "signal de sécurité" in r.json()["detail"]
        assert not [o for o in _case(sid).observations if o.kind == f"answer:{LOCATION_QUESTION_ID}"]
        assert web._sessions[sid].state.value.lower() == "escalated"
        report = client.get(f"/api/session/{sid}/report")
        assert report.status_code == 200 and report.json()["manufacturer_first_finding"]["entries"]

    def test_A_non_escalated_elevation_ends_the_session_without_questions(self, env):
        """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5): a raised but
        not escalated photo case no longer continues with ordinary questions."""
        client, provider = env
        image = provider.script(sup.png_bytes(71), sup.match(sup.OIL, "Voyant rouge d'huile"), sup.match(sup.AIRBAG, "Voyant airbag"))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        assert payload["escalated"] is False and payload["pending_questions"] == []
        assert web._sessions[sid].state.value == "completed"
        r = client.post(f"/api/session/{sid}/answer", json={"question_id": LOCATION_QUESTION_ID, "value": "garage"})
        assert r.status_code == 400 and r.json()["detail"] == "Session déjà terminée"
        assert client.get(f"/api/session/{sid}/report").json()["manufacturer_first_finding"]["entries"]

    # ---- B. pre-existing prohibited cases: still 400 -----------------------

    @pytest.mark.parametrize("complaint,level", [
        ("fumée noire sortant du moteur", "emergency_stop"),      # PGDR-SAF-004
        ("fuite d'essence sous la voiture", "emergency_stop"),    # PGDR-SAF-008
        ("le pneu est à plat", "do_not_drive"),                   # PGDR-SAF-006
    ])
    def test_B_complaint_escalated_sessions_without_a_pending_question_still_return_400(self, env, complaint, level):
        client, _ = env
        session = _escalated_text_session(complaint)
        assert session.state.value.lower() == "escalated"
        assert session.safety_triage.level.value == level
        assert session.pending_questions == []
        r = client.post(f"/api/session/{session.session_id}/answer", json={"question_id": "Q-SYM-001", "value": "toujours"})
        assert r.status_code == 400
        assert "signal de sécurité" in r.json()["detail"]
        r = client.post(f"/api/session/{session.session_id}/answer",
                        json={"question_id": LOCATION_QUESTION_ID, "value": "garage"})
        assert r.status_code == 400, "even the location question cannot be answered when it is not pending"

    def test_B_photo_escalation_returns_400_to_every_answer(self, env):
        """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2): there is
        no safety question to answer first -- every answer is refused."""
        client, provider = env
        image = provider.script(sup.png_bytes(72), sup.match(sup.BRAKE, "Voyant rouge de frein"))
        sid = _intake(client)
        assert _upload(client, sid, image).json()["pending_questions"] == []
        first = client.post(f"/api/session/{sid}/answer", json={"question_id": LOCATION_QUESTION_ID, "value": "garage"})
        assert first.status_code == 400 and "signal de sécurité" in first.json()["detail"]
        again = client.post(f"/api/session/{sid}/answer", json={"question_id": LOCATION_QUESTION_ID, "value": "parking"})
        assert again.status_code == 400 and "signal de sécurité" in again.json()["detail"]
        assert client.get(f"/api/session/{sid}/report").json()["manufacturer_first_finding"]["entries"]

    def test_B_photo_escalation_with_no_safety_question_pending_returns_400(self, env):
        """A critical photo-derived escalation leaves nothing pending.
        Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2): the former
        'location clarification already asked' precondition no longer exists
        -- no photo escalation ever leaves a question pending."""
        client, provider = env
        image = provider.script(sup.png_bytes(73), sup.match(sup.BRAKE, "Voyant rouge de frein"))
        controller = web._get_or_create_controller()
        from pgdr.models import Consent, InitialComplaint, PreGarageDiagnosticRequest
        request = PreGarageDiagnosticRequest(
            request_id="B-NOPENDING",
            vehicle_identity_context=_vir_context(),
            initial_complaint=InitialComplaint(free_text=""),
            consent=Consent(media_analysis_allowed=True),
        )
        session = controller.start_photo_case(request)
        reference = web._media_store.store(image, "image/png")
        reference_set = web._resolve_reference_set(_vir_context())
        try:
            controller.acquire_photo(session, media_reference=reference, resolver=web._media_store, reference_set=reference_set)
        finally:
            web._media_store.discard(reference)      # consent does not authorize retention
        assert session.state.value.lower() == "escalated" and session.pending_questions == []
        assert session.result.manufacturer_first_finding is not None
        web._sessions[session.session_id] = session
        r = client.post(f"/api/session/{session.session_id}/answer", json={"question_id": LOCATION_QUESTION_ID, "value": "garage"})
        assert r.status_code == 400 and "signal de sécurité" in r.json()["detail"]

    def test_B_escalated_photo_session_rejects_any_question_id(self, env):
        """Rewritten for PGDR Part 1 (mandate v0.2 §11 step 5 / D-C2): with no
        pending question, a generic question id is refused like any other."""
        client, provider = env
        image = provider.script(sup.png_bytes(74), sup.match(sup.BRAKE, "Voyant rouge de frein"))
        sid = _intake(client)
        _upload(client, sid, image)
        r = client.post(f"/api/session/{sid}/answer", json={"question_id": "Q-SYM-001", "value": "toujours"})
        assert r.status_code == 400 and "signal de sécurité" in r.json()["detail"]
        assert web._sessions[sid].pending_questions == []

    def test_B_completed_session_still_returns_400(self, env):
        client, provider = env
        image = provider.script(sup.png_bytes(75), sup.match(sup.OIL, "Voyant rouge de pression d'huile"))
        sid = _intake(client)
        payload = _upload(client, sid, image).json()
        _drive_questions(client, sid, payload)
        assert web._sessions[sid].state.value.lower() == "completed"
        r = client.post(f"/api/session/{sid}/answer", json={"question_id": "Q-SYM-001", "value": "toujours"})
        assert r.status_code == 400 and r.json()["detail"] == "Session déjà terminée"
