"""YTS fixture parsing."""

from __future__ import annotations

import json
from pathlib import Path

from pytorlink.sources.yts import movie_payload_to_results

FIXTURE = Path(__file__).parent / "fixtures" / "yts_sample.json"


def test_yts_fixture_to_results():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = movie_payload_to_results(payload)
    assert len(results) == 2
    names = {r.name for r in results}
    assert any("720p" in n for n in names)
    assert any("1080p" in n for n in names)
    hashes = {r.info_hash for r in results}
    assert "abcdef0123456789abcdef0123456789abcdef01" in hashes
    assert "1234567890abcdef1234567890abcdef12345678" in hashes
    for r in results:
        assert r.magnet.startswith("magnet:?")
        assert r.seeders is not None
        assert r.size_bytes is not None
