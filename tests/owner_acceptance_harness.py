"""Owner Browser Acceptance harness -- TEST INFRASTRUCTURE ONLY.

Lets the owner drive the already-approved, provider-independent Photo-First
pipeline in a real browser against the normal PGDR web product, through the
existing PGDR_PHOTO_WIRING_FACTORY injection point:

    export PGDR_IDENTITY_HANDOFF_TOKEN="$(openssl rand -hex 16)"   # never hardcode or commit it
    PYTHONPATH=tests PGDR_PHOTO_WIRING_FACTORY=owner_acceptance_harness:build_wiring \\
        .venv/bin/uvicorn pgdr.web_app:app --host 127.0.0.1 --port 8000

The vehicle is never entered in the browser. For each journey, stand in for
PI by handing the captured real VIR identity artifact (tests/fixtures/
vir_handoff_contexts.json) to PGDR, from a shell with the same
PGDR_IDENTITY_HANDOFF_TOKEN exported; this prints the page URL to open:

    .venv/bin/python tests/owner_acceptance_harness.py intake http://127.0.0.1:8000

This module is manual QA tooling, not a test: pytest does not collect it.
tests/test_owner_acceptance_harness.py (collected by the default run) pins
that its PNGs and scripted results stay in step.

It reuses the deterministic provider and in-memory knowledge repository of
photo_first_support unchanged: the provider maps sha256(uploaded bytes) to a
scripted result and never looks at pixels. It validates browser UX and the
provider-independent governed pipeline; it does NOT validate visual
recognition, and no image ever leaves the process.

The PNGs are generated on demand from png_bytes(seed) into a temporary
directory (never committed):

    .venv/bin/python tests/owner_acceptance_harness.py <output-dir>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

import photo_first_support as sup
from pgdr.web_app import PhotoWiring

# seed -> (upload filename, scripted interpretation results)
SCENARIOS = {
    101: ("pgdr_owner_101_match.png",
          [sup.match(sup.OIL, "Voyant rouge de pression d'huile")]),
    130: ("pgdr_owner_130_safety_prompt_inspection.png",
          [sup.match(sup.OIL, "Voyant rouge de pression d'huile"),
           sup.match(sup.AIRBAG, "Voyant rouge d'airbag")]),
    131: ("pgdr_owner_131_safety_do_not_drive.png",
          [sup.match(sup.BRAKE, "Voyant rouge de frein")]),
    102: ("pgdr_owner_102_ambiguous.png",
          [sup.ambiguous([sup.ENGINE_FIXED, sup.ENGINE_FLASHING])]),
    103: ("pgdr_owner_103_no_match.png",
          [sup.no_match()]),
}


def build_wiring() -> PhotoWiring:
    """PGDR_PHOTO_WIRING_FACTORY target."""
    provider = sup.DeterministicDashboardProvider()
    for seed, (_, results) in SCENARIOS.items():
        provider.script(sup.png_bytes(seed), *results)
    return PhotoWiring(interpretation_provider=provider, knowledge_repository=sup.InMemoryKnowledgeRepository())


def create_intake_url(base_url: str, identity: str = "peugeot_3008_ii_by_plate") -> str:
    """Stands in for PI: hands a captured VIR identity artifact to PGDR and
    returns the Photo-First page URL for the resulting intake."""
    from pgdr.web_app import IDENTITY_HANDOFF_TOKEN_ENV, IDENTITY_HANDOFF_TOKEN_HEADER
    r = httpx.post(f"{base_url}/api/photo/identity-handoff", json=sup.vir_identity(identity),
                   headers={IDENTITY_HANDOFF_TOKEN_HEADER: os.environ[IDENTITY_HANDOFF_TOKEN_ENV]})
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "awaiting_consent":
        raise SystemExit(f"no intake: {body}")
    return f"{base_url}/?intake={body['intake_id']}"


def write_pngs(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for seed, (filename, _) in SCENARIOS.items():
        path = out_dir / filename
        path.write_bytes(sup.png_bytes(seed))
        written.append(path)
    return written


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "intake":
        print(create_intake_url(sys.argv[2].rstrip("/")))
    elif len(sys.argv) == 2:
        for p in write_pngs(Path(sys.argv[1])):
            print(p)
    else:
        sys.exit("usage: owner_acceptance_harness.py <output-dir> | intake <base-url>")
