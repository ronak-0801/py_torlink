"""SubsPlease fixture parsing."""

from __future__ import annotations

import json
from pathlib import Path

from pytorlink.sources.subsplease import subsplease_payload_to_results

FIXTURE = Path(__file__).parent / "fixtures" / "subsplease_sample.json"


def test_subsplease_picks_best_resolution():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = subsplease_payload_to_results(payload)
    assert len(results) == 2
    first = next(r for r in results if "Example Show" in r.name)
    assert "1080p" in first.name
    assert first.info_hash == "b" * 40
    assert first.size_bytes == 3000
    assert first.magnet.startswith("magnet:?")


def test_subsplease_empty_list_payload():
    assert subsplease_payload_to_results([]) == []
