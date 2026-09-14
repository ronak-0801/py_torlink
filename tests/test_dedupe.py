"""Dedupe / sort helpers."""

from __future__ import annotations

from pytorlink.sources.magnet import build_magnet
from pytorlink.sources.types import SourceId, TorrentResult, dedupe_by_info_hash, sort_by_seeders


def _r(name: str, h: str, seeds: int | None, source: SourceId = SourceId.YTS) -> TorrentResult:
    return TorrentResult(
        name=name,
        info_hash=h.lower(),
        size_bytes=1000,
        seeders=seeds,
        source=source,
        magnet=build_magnet(h, name=name),
    )


def test_dedupe_keeps_higher_seeders():
    h = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    a = _r("low", h, 1, SourceId.YTS)
    b = _r("high", h, 99, SourceId.NYAA)
    out = dedupe_by_info_hash([a, b])
    assert len(out) == 1
    assert out[0].name == "high"
    assert out[0].seeders == 99


def test_sort_by_seeders_desc_unknown_last():
    items = [
        _r("a", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 5),
        _r("b", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", None),
        _r("c", "cccccccccccccccccccccccccccccccccccccccc", 20),
    ]
    sorted_items = sort_by_seeders(items)
    assert [i.name for i in sorted_items] == ["c", "a", "b"]
