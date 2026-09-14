"""Torrent search sources."""

from pytorlink.sources.registry import (
    DEFAULT_SOURCE_IDS,
    DISABLED_BY_DEFAULT,
    SOURCES,
    SOURCE_TIMEOUT,
    default_sources,
    get_source,
    iter_search,
    search_all,
    sources_for_ids,
)
from pytorlink.sources.types import SourceId, TorrentResult

__all__ = [
    "DEFAULT_SOURCE_IDS",
    "DISABLED_BY_DEFAULT",
    "SOURCES",
    "SOURCE_TIMEOUT",
    "SourceId",
    "TorrentResult",
    "default_sources",
    "get_source",
    "iter_search",
    "search_all",
    "sources_for_ids",
]
