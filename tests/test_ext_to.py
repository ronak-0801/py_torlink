"""EXT.to HTML fixture parsing."""

from __future__ import annotations

from pathlib import Path

from pytorlink.sources.ext_to import (
    ext_to_html_to_results,
    extract_ext_to_tokens,
    parse_ext_to_candidates,
)
from pytorlink.sources.types import SourceId

FIXTURE = Path(__file__).parent / "fixtures" / "ext_to_sample.html"


def test_ext_to_html_extracts_magnets_and_hashes() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    results = ext_to_html_to_results(html)
    hashes = {r.info_hash for r in results}
    assert "a" * 40 in hashes
    assert "b" * 40 in hashes
    assert "c" * 40 in hashes
    ubuntu = next(r for r in results if r.info_hash == "a" * 40)
    assert "Ubuntu" in ubuntu.name
    assert ubuntu.seeders == 120
    assert ubuntu.size_bytes is not None and ubuntu.size_bytes > 1_000_000_000
    assert ubuntu.source == SourceId.EXT_TO
    assert ubuntu.magnet.startswith("magnet:?")


def test_ext_to_tokens_and_candidates() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    page, csrf = extract_ext_to_tokens(html)
    assert page == "abc123def456"
    assert csrf == "c5f789abc012"
    cands = parse_ext_to_candidates(html)
    ids = {c["torrent_id"] for c in cands}
    assert ids == {"111", "222", "333"}
    mint = next(c for c in cands if c["torrent_id"] == "222")
    assert "Mint" in mint["name"]
