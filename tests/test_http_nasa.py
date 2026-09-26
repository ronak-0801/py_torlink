"""NASA image and video library parsing / asset selection (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from pytorlink.httpdl.nasa import (
    https_url,
    items_to_results,
    pick_nasa_asset,
)
from pytorlink.httpdl.types import HttpSourceId

FIXTURES = Path(__file__).parent / "fixtures"


def _search_payload() -> dict:
    return json.loads((FIXTURES / "nasa_search.json").read_text(encoding="utf-8"))


def _manifest() -> list[str]:
    return json.loads((FIXTURES / "nasa_asset.json").read_text(encoding="utf-8"))


def test_items_to_results_reads_titles_and_ids() -> None:
    results = items_to_results(_search_payload())
    assert [r.name for r in results] == ["Apollo 11 Productions", "Apollo 11 Activities"]
    assert results[0].extra["identifier"].startswith("KSC-19850101-MH-NAS01")
    assert results[0].extra["center"] == "KSC"
    assert results[0].source == HttpSourceId.NASA


def test_search_results_need_resolving() -> None:
    for result in items_to_results(_search_payload()):
        assert result.url == ""
        assert result.needs_resolve
        assert result.extra["manifest"].endswith("/collection.json")


def test_items_to_results_ignores_items_without_data() -> None:
    payload = {"collection": {"items": [{"href": "https://x/collection.json"}, {"data": []}]}}
    assert items_to_results(payload) == []


def test_items_to_results_handles_empty_payload() -> None:
    assert items_to_results({}) == []
    assert items_to_results({"collection": {}}) == []


def test_pick_nasa_asset_prefers_original_rendition() -> None:
    chosen = pick_nasa_asset(_manifest())
    assert chosen is not None
    assert chosen.endswith("~orig.mp4")
    assert chosen.startswith("https://")


def test_pick_nasa_asset_falls_back_down_the_quality_ladder() -> None:
    base = "https://images-assets.nasa.gov/video/x/x"
    assert pick_nasa_asset([f"{base}~small.mp4", f"{base}~mobile.mp4"]).endswith("~small.mp4")
    assert pick_nasa_asset([f"{base}~preview.mp4", f"{base}~large.mp4"]).endswith("~large.mp4")


def test_pick_nasa_asset_skips_sidecar_files() -> None:
    sidecars = [
        "https://images-assets.nasa.gov/video/x/x.vtt",
        "https://images-assets.nasa.gov/video/x/metadata.json",
        "https://images-assets.nasa.gov/video/x/x~thumb.jpg",
    ]
    assert pick_nasa_asset(sidecars) is None


def test_pick_nasa_asset_accepts_unsuffixed_media() -> None:
    chosen = pick_nasa_asset(["http://images-assets.nasa.gov/video/x/plain.mp4"])
    assert chosen == "https://images-assets.nasa.gov/video/x/plain.mp4"


def test_https_url_upgrades_plain_http() -> None:
    assert https_url("http://example.com/a.mp4") == "https://example.com/a.mp4"
    assert https_url("https://example.com/a.mp4") == "https://example.com/a.mp4"
    assert https_url("") == ""
