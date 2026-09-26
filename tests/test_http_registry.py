"""HTTP source registry: fan-out, soft-fail, interleaving, resolve dispatch."""

from __future__ import annotations

import asyncio

import pytest

from pytorlink.httpdl import registry
from pytorlink.httpdl.base import HttpSource
from pytorlink.httpdl.registry import (
    HTTP_SOURCES,
    default_http_sources,
    get_http_source,
    http_sources_for_ids,
    interleave_by_source,
    resolve_http_result,
    search_http_all,
)
from pytorlink.httpdl.types import HttpFileResult, HttpSourceId


def _result(name: str, source: str, url: str = "") -> HttpFileResult:
    extra = {} if url else {"identifier": name}
    return HttpFileResult(name=name, url=url, size_bytes=None, source=source, extra=extra)


class FakeSource(HttpSource):
    """Returns canned results, or raises / hangs to exercise soft-fail."""

    def __init__(
        self,
        source_id: str,
        label: str,
        results: list[HttpFileResult] | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.id = source_id
        self.label = label
        self._results = results or []
        self._error = error
        self._delay = delay

    async def search(self, query, *, limit=50, client=None):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return list(self._results)


@pytest.fixture(autouse=True)
def _clear_cache():
    registry._cache.clear()
    yield
    registry._cache.clear()


def test_registered_sources_have_unique_ids_and_labels() -> None:
    ids = [s.id for s in HTTP_SOURCES]
    labels = [s.label for s in HTTP_SOURCES]
    assert len(set(ids)) == len(ids)
    assert len(set(labels)) == len(labels)
    assert set(ids) == {HttpSourceId.ARCHIVE, HttpSourceId.COMMONS, HttpSourceId.NASA}


def test_all_sources_enabled_by_default() -> None:
    assert len(default_http_sources()) == len(HTTP_SOURCES)


def test_get_http_source_by_id() -> None:
    assert get_http_source(HttpSourceId.COMMONS).label == "Wikimedia Commons"
    assert get_http_source("nope") is None


def test_http_sources_for_ids_follows_registry_order() -> None:
    picked = http_sources_for_ids([HttpSourceId.NASA, HttpSourceId.ARCHIVE])
    assert [s.id for s in picked] == [HttpSourceId.ARCHIVE, HttpSourceId.NASA]


def test_http_sources_for_ids_ignores_unknown() -> None:
    assert http_sources_for_ids(["bogus"]) == []


def test_interleave_round_robins_across_sources() -> None:
    a = [_result("a1", "a"), _result("a2", "a"), _result("a3", "a")]
    b = [_result("b1", "b")]
    merged = interleave_by_source([a, b])
    assert [r.name for r in merged] == ["a1", "b1", "a2", "a3"]


def test_interleave_handles_empty_input() -> None:
    assert interleave_by_source([]) == []
    assert interleave_by_source([[], []]) == []


async def test_search_http_all_merges_in_registry_order() -> None:
    first = FakeSource("a", "A", [_result("a1", "a", "https://x/a1")])
    # Slower source still lands second because merging follows source order.
    second = FakeSource("b", "B", [_result("b1", "b", "https://x/b1")], delay=0.05)
    results, errors = await search_http_all("q", sources=[first, second], use_cache=False)
    assert [r.name for r in results] == ["a1", "b1"]
    assert errors == []


async def test_search_http_all_soft_fails_one_source() -> None:
    good = FakeSource("a", "A", [_result("a1", "a", "https://x/a1")])
    bad = FakeSource("b", "B", error=RuntimeError("boom"))
    results, errors = await search_http_all("q", sources=[good, bad], use_cache=False)
    assert [r.name for r in results] == ["a1"]
    assert errors == ["B: boom"]


async def test_search_http_all_times_out_slow_source() -> None:
    good = FakeSource("a", "A", [_result("a1", "a", "https://x/a1")])
    slow = FakeSource("b", "B", delay=5.0)
    results, errors = await search_http_all(
        "q", sources=[good, slow], use_cache=False, timeout=0.05
    )
    assert [r.name for r in results] == ["a1"]
    assert errors and "timed out" in errors[0]


async def test_search_http_all_blank_query_short_circuits() -> None:
    assert await search_http_all("   ") == ([], [])


async def test_search_http_all_caches_by_query_and_sources() -> None:
    source = FakeSource("a", "A", [_result("a1", "a", "https://x/a1")])
    await search_http_all("q", sources=[source], use_cache=True)
    source._error = RuntimeError("should not be called again")
    results, errors = await search_http_all("q", sources=[source], use_cache=True)
    assert [r.name for r in results] == ["a1"]
    assert errors == []


async def test_resolve_passes_through_direct_urls() -> None:
    direct = _result("d", HttpSourceId.COMMONS, "https://upload.wikimedia.org/x.webm")
    assert await resolve_http_result(direct) is direct


async def test_resolve_rejects_unknown_source() -> None:
    orphan = _result("o", "mystery")
    with pytest.raises(ValueError, match="No HTTP source registered"):
        await resolve_http_result(orphan)


async def test_base_resolve_default_raises_without_url() -> None:
    source = FakeSource("a", "A")
    with pytest.raises(ValueError, match="no URL"):
        await source.resolve(_result("x", "a"))
