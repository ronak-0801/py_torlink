"""apibay / Pirate Bay fixture parsing."""

from __future__ import annotations

import json
from pathlib import Path

from pytorlink.sources.piratebay import apibay_items_to_results

FIXTURE = Path(__file__).parent / "fixtures" / "apibay_sample.json"
SENTINEL = Path(__file__).parent / "fixtures" / "apibay_sentinel.json"


def test_apibay_fixture_skips_sentinel_and_maps_fields():
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = apibay_items_to_results(items)
    assert len(results) == 2
    by_hash = {r.info_hash: r for r in results}
    assert "abcdef0123456789abcdef0123456789abcdef01" in by_hash
    hit = by_hash["abcdef0123456789abcdef0123456789abcdef01"]
    assert hit.seeders == 55
    assert hit.size_bytes == 2147483648
    assert hit.magnet.startswith("magnet:?")
    assert hit.source.value == "piratebay"


def test_apibay_sentinel_only_yields_empty():
    items = json.loads(SENTINEL.read_text(encoding="utf-8"))
    assert apibay_items_to_results(items) == []
