"""Registered HTTP / direct-download sources and concurrent search helpers.

Mirrors pytorlink.sources.registry, but for direct file sources rather than
torrent indexes. Every source here exposes content its host distributes
legally (public domain or an explicit open licence).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable, Sequence

from pytorlink.httpdl.archive import ArchiveHttpSource
from pytorlink.httpdl.base import HttpSource
from pytorlink.httpdl.commons import CommonsHttpSource
from pytorlink.httpdl.nasa import NasaHttpSource
from pytorlink.httpdl.types import HttpFileResult
from pytorlink.sources.cache import TTLCache
from pytorlink.sources.http import short_exc

log = logging.getLogger(__name__)

HTTP_SOURCES: list[HttpSource] = [
    ArchiveHttpSource(),
    CommonsHttpSource(),
    NasaHttpSource(),
]

DEFAULT_HTTP_SOURCE_IDS: frozenset[str] = frozenset(s.id for s in HTTP_SOURCES)

# Soft-fail a single source if it hangs longer than this.
HTTP_SOURCE_TIMEOUT = 8.0

_cache: TTLCache[list[HttpFileResult]] = TTLCache(ttl_seconds=180.0)

_SOURCE_BY_ID: dict[str, HttpSource] = {s.id: s for s in HTTP_SOURCES}


def get_http_source(source_id: str) -> HttpSource | None:
    return _SOURCE_BY_ID.get(str(source_id))


def http_sources_for_ids(ids: Iterable[str] | None = None) -> list[HttpSource]:
    """Resolve *ids* to sources in registry order. None → the default set."""
    wanted = set(DEFAULT_HTTP_SOURCE_IDS) if ids is None else {str(i) for i in ids}
    return [s for s in HTTP_SOURCES if s.id in wanted]


def default_http_sources() -> list[HttpSource]:
    return http_sources_for_ids(DEFAULT_HTTP_SOURCE_IDS)


def interleave_by_source(batches: Sequence[Sequence[HttpFileResult]]) -> list[HttpFileResult]:
    """Round-robin the per-source batches so no single source dominates the top.

    Relative order within each source (its own relevance ranking) is preserved.
    """
    out: list[HttpFileResult] = []
    if not batches:
        return out
    for row in range(max((len(b) for b in batches), default=0)):
        for batch in batches:
            if row < len(batch):
                out.append(batch[row])
    return out


async def iter_http_search(
    query: str,
    *,
    sources: Sequence[HttpSource] | None = None,
    limit_per_source: int = 50,
    timeout: float = HTTP_SOURCE_TIMEOUT,
) -> AsyncIterator[tuple[str, list[HttpFileResult] | None, str | None]]:
    """Yield ``(source_label, results_or_none, error_or_none)`` as sources finish."""
    q = query.strip()
    if not q:
        return

    srcs = list(sources) if sources is not None else default_http_sources()

    async def _one(src: HttpSource) -> tuple[str, list[HttpFileResult] | None, str | None]:
        try:
            results = await asyncio.wait_for(
                src.search(q, limit=limit_per_source),
                timeout=timeout,
            )
            return src.label, results, None
        except asyncio.TimeoutError:
            msg = f"{src.label}: timed out after {timeout:g}s"
            log.warning("http source soft-fail: %s", msg)
            return src.label, None, msg
        except Exception as exc:
            msg = f"{src.label}: {short_exc(exc, max_len=100)}"
            log.warning("http source soft-fail: %s", msg)
            return src.label, None, msg

    tasks = [asyncio.create_task(_one(s)) for s in srcs]
    try:
        for finished in asyncio.as_completed(tasks):
            yield await finished
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def search_http_all(
    query: str,
    *,
    sources: Sequence[HttpSource] | None = None,
    limit_per_source: int = 50,
    use_cache: bool = True,
    timeout: float = HTTP_SOURCE_TIMEOUT,
) -> tuple[list[HttpFileResult], list[str]]:
    """Search every enabled HTTP source concurrently.

    Returns ``(results, errors)`` with one short message per soft-failed source.
    """
    q = query.strip()
    if not q:
        return [], []

    srcs = list(sources) if sources is not None else default_http_sources()
    cache_key = f"{q.lower()}|{','.join(sorted(s.id for s in srcs))}"
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached, []

    # Keep batches keyed by label so interleaving follows registry order, not
    # completion order (which would make result ranking non-deterministic).
    by_label: dict[str, list[HttpFileResult]] = {}
    errors: list[str] = []
    async for label, batch, error in iter_http_search(
        q,
        sources=srcs,
        limit_per_source=limit_per_source,
        timeout=timeout,
    ):
        if error:
            errors.append(error)
        if batch:
            by_label[label] = batch

    results = interleave_by_source([by_label[s.label] for s in srcs if s.label in by_label])
    if use_cache and results:
        _cache.set(cache_key, results)
    return results, errors


async def resolve_http_result(result: HttpFileResult, **kwargs) -> HttpFileResult:
    """Resolve *result* to a concrete URL using its originating source."""
    if (result.url or "").strip():
        return result
    source = get_http_source(result.source)
    if source is None:
        raise ValueError(f"No HTTP source registered for '{result.source}': {result.name}")
    return await source.resolve(result, **kwargs)
