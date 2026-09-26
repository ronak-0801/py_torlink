"""HTTP / direct-download mode (separate from torrent search)."""

from pytorlink.httpdl.base import HttpSource
from pytorlink.httpdl.registry import (
    HTTP_SOURCES,
    default_http_sources,
    get_http_source,
    resolve_http_result,
    search_http_all,
)
from pytorlink.httpdl.types import HttpFileResult, HttpSourceId, looks_like_http_url

__all__ = [
    "HTTP_SOURCES",
    "HttpFileResult",
    "HttpSource",
    "HttpSourceId",
    "default_http_sources",
    "get_http_source",
    "looks_like_http_url",
    "resolve_http_result",
    "search_http_all",
]
