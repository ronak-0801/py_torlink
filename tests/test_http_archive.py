"""Internet Archive HTTP search parsing (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from pytorlink.httpdl.archive import docs_to_results, pick_archive_file, resolved_from_metadata
from pytorlink.httpdl.types import looks_like_http_url

FIXTURES = Path(__file__).parent / "fixtures"


def test_docs_to_results_skips_collections() -> None:
    payload = json.loads((FIXTURES / "archive_search.json").read_text(encoding="utf-8"))
    results = docs_to_results(payload)
    assert [r.extra["identifier"] for r in results] == [
        "night_of_the_living_dead",
        "pg12345",
    ]
    assert results[0].needs_resolve
    assert results[0].source_label == "Archive.org"
    assert results[0].size_bytes == 734003200


def test_pick_archive_file_prefers_original_payload() -> None:
    payload = json.loads((FIXTURES / "archive_metadata.json").read_text(encoding="utf-8"))
    chosen = pick_archive_file(payload["files"])
    assert chosen is not None
    assert chosen["name"] == "night_of_the_living_dead.mpeg"


def test_resolved_from_metadata_builds_download_url() -> None:
    payload = json.loads((FIXTURES / "archive_metadata.json").read_text(encoding="utf-8"))
    result = resolved_from_metadata("night_of_the_living_dead", payload)
    assert result.url.endswith("/night_of_the_living_dead.mpeg")
    assert "archive.org/download/" in result.url
    assert result.size_bytes == 700000000
    assert not result.needs_resolve


def test_looks_like_http_url() -> None:
    assert looks_like_http_url("https://archive.org/download/foo/bar.mp4")
    assert looks_like_http_url("http://example.com/a.zip")
    assert not looks_like_http_url("magnet:?xt=urn:btih:" + "a" * 40)
    assert not looks_like_http_url("file:///etc/passwd")
    assert not looks_like_http_url("ftp://example.com/x")
    assert not looks_like_http_url("not a url")
