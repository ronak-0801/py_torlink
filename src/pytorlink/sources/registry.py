"""Registered search sources and concurrent / streaming search helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable, Sequence

from pytorlink.sources.bittorrented import BitTorrentedSource
from pytorlink.sources.cache import TTLCache
from pytorlink.sources.ext_to import ExtToSource
from pytorlink.sources.eztv import EztvSource
from pytorlink.sources.fitgirl import FitGirlSource
from pytorlink.sources.http import short_exc
from pytorlink.sources.nyaa import NyaaSource
from pytorlink.sources.piratebay import PirateBaySource
from pytorlink.sources.subsplease import SubsPleaseSource
from pytorlink.sources.types import Source, SourceId, TorrentResult, dedupe_by_info_hash, sort_by_seeders
from pytorlink.sources.yts import YtsSource

log = logging.getLogger(__name__)

# All registered sources (including optional / paywalled ones).
SOURCES: list[Source] = [
    YtsSource(),
    NyaaSource(),
    PirateBaySource(),
    EztvSource(),
    SubsPleaseSource(),
    BitTorrentedSource(),  # optional — often 402 Payment Required; disabled by default
    FitGirlSource(),
    ExtToSource(),
]

# BitTorrented is paywalled / returns 402 for free clients — keep module, omit from defaults.
DISABLED_BY_DEFAULT: frozenset[SourceId] = frozenset({SourceId.BITTORRENTED})

DEFAULT_SOURCE_IDS: frozenset[SourceId] = frozenset(
    s.id for s in SOURCES if s.id not in DISABLED_BY_DEFAULT
)

# Soft-fail a single source if it hangs longer than this.
SOURCE_TIMEOUT = 8.0

_cache: TTLCache[list[TorrentResult]] = TTLCache(ttl_seconds=180.0)

_SOURCE_BY_ID: dict[SourceId, Source] = {s.id: s for s in SOURCES}


def get_source(source_id: SourceId | str) -> Source | None:
    try:
        sid = source_id if isinstance(source_id, SourceId) else SourceId(str(source_id))
    except ValueError:
        return None
    return _SOURCE_BY_ID.get(sid)


def sources_for_ids(ids: Iterable[SourceId | str] | None = None) -> list[Source]:
    """Resolve *ids* to Source instances (registry order). None → default enabled set."""
    if ids is None:
        wanted = set(DEFAULT_SOURCE_IDS)
    else:
        wanted = set()
        for item in ids:
            try:
                wanted.add(item if isinstance(item, SourceId) else SourceId(str(item)))
            except ValueError:
                continue
    return [s for s in SOURCES if s.id in wanted]


def default_sources() -> list[Source]:
    """Sources enabled on first launch (all registered except DISABLED_BY_DEFAULT)."""
    return sources_for_ids(DEFAULT_SOURCE_IDS)


def _source_label(src: Source) -> str:
    return str(getattr(src, "label", None) or getattr(src, "id", "source"))


def _error_message(src: Source, exc: BaseException, *, max_len: int = 100) -> str:
    return f"{_source_label(src)}: {short_exc(exc, max_len=max_len)}"


async def iter_search(
    query: str,
    *,
    sources: Sequence[Source] | None = None,
    limit_per_source: int = 50,
    timeout: float = SOURCE_TIMEOUT,
) -> AsyncIterator[tuple[str, list[TorrentResult] | None, str | None]]:
    """Yield ``(source_label, results_or_none, error_or_none)`` as each source finishes.

    Fast sources (e.g. apibay / YTS) surface first. Slow or hung sources are
    soft-failed via *timeout* so the rest of the search can continue.

    When *sources* is omitted, uses :func:`default_sources` (BitTorrented off).
    """
    q = query.strip()
    if not q:
        return

    srcs = list(sources) if sources is not None else default_sources()

    async def _one(src: Source) -> tuple[str, list[TorrentResult] | None, str | None]:
        label = _source_label(src)
        try:
            results = await asyncio.wait_for(
                src.search(q, limit=limit_per_source),
                timeout=timeout,
            )
            return label, results, None
        except asyncio.TimeoutError:
            msg = f"{label}: timed out after {timeout:g}s"
            log.warning("source soft-fail: %s", msg)
            return label, None, msg
        except Exception as exc:
            msg = _error_message(src, exc)
            log.warning("source soft-fail: %s", msg)
            return label, None, msg

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


async def search_all(
    query: str,
    *,
    sources: Sequence[Source] | None = None,
    limit_per_source: int = 50,
    use_cache: bool = True,
    timeout: float = SOURCE_TIMEOUT,
) -> tuple[list[TorrentResult], list[str]]:
    """Search all sources concurrently (collects from :func:`iter_search`).

    Returns ``(results, errors)`` where errors are short soft-fail messages per source.
    """
    q = query.strip()
    if not q:
        return [], []
    cache_key = q.lower()
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached, []

    merged: list[TorrentResult] = []
    errors: list[str] = []
    async for _label, batch, error in iter_search(
        q,
        sources=sources,
        limit_per_source=limit_per_source,
        timeout=timeout,
    ):
        if error:
            errors.append(error)
        if batch:
            merged.extend(batch)

    results = sort_by_seeders(dedupe_by_info_hash(merged))
    if use_cache and results:
        _cache.set(cache_key, results)
    return results, errors
