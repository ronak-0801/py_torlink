"""Tests for streaming search + per-source timeout."""

from __future__ import annotations

import asyncio

import pytest

from pytorlink.sources.registry import iter_search, search_all
from pytorlink.sources.types import SourceId, TorrentResult


def _hit(name: str, seeders: int, source: SourceId = SourceId.YTS) -> TorrentResult:
    h = f"{abs(hash(name)):040x}"[:40]
    return TorrentResult(
        name=name,
        info_hash=h,
        size_bytes=1024,
        seeders=seeders,
        source=source,
        magnet=f"magnet:?xt=urn:btih:{h}",
    )


class FakeSource:
    def __init__(
        self,
        *,
        id: SourceId,
        label: str,
        delay: float,
        results: list[TorrentResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.id = id
        self.label = label
        self.delay = delay
        self.results = results or []
        self.error = error

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return list(self.results)[:limit]


@pytest.mark.asyncio
async def test_iter_search_yields_fast_source_first() -> None:
    fast = FakeSource(
        id=SourceId.PIRATEBAY,
        label="TPB",
        delay=0.01,
        results=[_hit("fast", 10, SourceId.PIRATEBAY)],
    )
    slow = FakeSource(
        id=SourceId.NYAA,
        label="Nyaa",
        delay=0.15,
        results=[_hit("slow", 5, SourceId.NYAA)],
    )
    labels: list[str] = []
    async for label, batch, error in iter_search(
        "q", sources=[slow, fast], timeout=2.0
    ):
        assert error is None
        assert batch is not None
        labels.append(label)
    assert labels[0] == "TPB"
    assert labels[1] == "Nyaa"


@pytest.mark.asyncio
async def test_iter_search_timeout_soft_fails() -> None:
    hung = FakeSource(id=SourceId.EZTV, label="EZTV", delay=2.0, results=[_hit("late", 1)])
    ok = FakeSource(
        id=SourceId.YTS,
        label="YTS",
        delay=0.01,
        results=[_hit("movie", 99)],
    )
    events: list[tuple[str, bool]] = []
    async for label, batch, error in iter_search(
        "q", sources=[hung, ok], timeout=0.05
    ):
        events.append((label, error is not None))
        if label == "EZTV":
            assert batch is None
            assert error is not None
            assert "timed out" in error
        if label == "YTS":
            assert batch is not None
            assert error is None
    assert ("YTS", False) in events
    assert ("EZTV", True) in events


@pytest.mark.asyncio
async def test_search_all_collects_stream_and_dedupes() -> None:
    a = FakeSource(
        id=SourceId.YTS,
        label="YTS",
        delay=0.01,
        results=[_hit("same", 5, SourceId.YTS)],
    )
    shared = _hit("same", 50, SourceId.PIRATEBAY)
    b = FakeSource(
        id=SourceId.PIRATEBAY,
        label="TPB",
        delay=0.02,
        results=[shared],
    )
    boom = FakeSource(
        id=SourceId.FITGIRL,
        label="FitGirl",
        delay=0.01,
        error=RuntimeError("down"),
    )
    results, errors = await search_all(
        "q", sources=[a, b, boom], use_cache=False, timeout=2.0
    )
    assert any("FitGirl" in e for e in errors)
    assert len(results) == 1
    assert results[0].seeders == 50


@pytest.mark.asyncio
async def test_search_all_empty_query() -> None:
    results, errors = await search_all("  ", use_cache=False)
    assert results == []
    assert errors == []
