"""Pins the test-only Owner Browser Acceptance harness: the PNG files it
writes are exactly the bytes its wiring factory scripts, and it loads
through the existing PGDR_PHOTO_WIRING_FACTORY injection point."""
from __future__ import annotations

import owner_acceptance_harness as harness
import photo_first_support as sup
from pgdr import web_app as web
from pgdr.domain.media import MediaType
from pgdr.ports.dashboard_interpretation import MatchStatus
from pgdr.ports.media_resolver import ResolvedMedia

EXPECTED = {
    101: [MatchStatus.MATCH],
    130: [MatchStatus.MATCH, MatchStatus.MATCH],
    131: [MatchStatus.MATCH],
    102: [MatchStatus.AMBIGUOUS_MATCH],
    103: [MatchStatus.NO_MATCH],
}


def test_written_pngs_map_to_the_scripted_scenarios(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "_photo_wiring", None)
    monkeypatch.setenv("PGDR_PHOTO_WIRING_FACTORY", "owner_acceptance_harness:build_wiring")
    wiring = web._get_photo_wiring()
    assert isinstance(wiring.knowledge_repository, sup.InMemoryKnowledgeRepository)

    paths = harness.write_pngs(tmp_path)
    assert {p.name for p in paths} == {name for name, _ in harness.SCENARIOS.values()}
    reference_set = type("RefSet", (), {"entries": sup.ALL_ENTRIES})()
    for seed, (name, _) in harness.SCENARIOS.items():
        content = (tmp_path / name).read_bytes()
        assert content == sup.png_bytes(seed)
        media = ResolvedMedia(content=content, media_type=MediaType.IMAGE, reference=f"media-{seed}")
        results = wiring.interpretation_provider.interpret(media, reference_set)
        assert [r.match_status for r in results] == EXPECTED[seed]
