"""Wikimedia Commons HTTP search parsing (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from pytorlink.httpdl.commons import (
    MEDIA_FILTER,
    build_search_params,
    clean_upload_url,
    pages_to_results,
)
from pytorlink.httpdl.types import HttpSourceId, looks_like_http_url

FIXTURES = Path(__file__).parent / "fixtures"


def _payload() -> dict:
    return json.loads((FIXTURES / "commons_search.json").read_text(encoding="utf-8"))


def test_pages_to_results_orders_by_search_rank() -> None:
    results = pages_to_results(_payload())
    assert [r.name for r in results] == [
        "Apollo 13 Houston, We've Got a Problem.ogv",
        "Apollo 15 feather and hammer drop.ogv",
        "Apollo 4 separation of interstage ring.webm",
    ]


def test_pages_to_results_skips_pages_without_imageinfo() -> None:
    results = pages_to_results(_payload())
    assert all("No info here" not in r.name for r in results)


def test_results_are_directly_downloadable() -> None:
    results = pages_to_results(_payload())
    for result in results:
        assert looks_like_http_url(result.url)
        assert result.url.startswith("https://upload.wikimedia.org/")
        assert not result.needs_resolve
        assert result.source == HttpSourceId.COMMONS
        assert result.source_label == "Wikimedia"


def test_result_carries_size_license_and_duration() -> None:
    first = pages_to_results(_payload())[0]
    assert first.size_bytes == 130880468
    assert first.extra["license"] == "Public domain"
    assert first.extra["mediatype"] == "application/ogg"
    # 1700.8s -> 28:20, and long clips get an hours component only past 3600s.
    assert first.extra["duration"] == "28:20"


def test_clean_upload_url_strips_analytics_params() -> None:
    dirty = (
        "https://upload.wikimedia.org/wikipedia/commons/a/b/Clip.webm"
        "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo"
    )
    assert clean_upload_url(dirty) == "https://upload.wikimedia.org/wikipedia/commons/a/b/Clip.webm"


def test_clean_upload_url_keeps_meaningful_params() -> None:
    url = "https://upload.wikimedia.org/x.webm?page=2&utm_source=commons"
    assert clean_upload_url(url) == "https://upload.wikimedia.org/x.webm?page=2"


def test_clean_upload_url_handles_empty() -> None:
    assert clean_upload_url("") == ""
    assert clean_upload_url("   ") == ""


def test_build_search_params_restricts_to_media_and_files() -> None:
    params = dict(build_search_params("apollo", 10))
    assert params["gsrsearch"] == f"apollo {MEDIA_FILTER}"
    assert params["gsrnamespace"] == "6"
    assert params["gsrlimit"] == "10"
    assert params["formatversion"] == "2"


def test_build_search_params_clamps_limit() -> None:
    assert dict(build_search_params("x", 500))["gsrlimit"] == "50"
    assert dict(build_search_params("x", 0))["gsrlimit"] == "1"
