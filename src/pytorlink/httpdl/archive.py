"""Internet Archive search + file resolve (public API, no HTML scraping)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from pytorlink.httpdl.base import HttpSource
from pytorlink.httpdl.types import HTTP_API_HEADERS, HttpFileResult, HttpSourceId
from pytorlink.sources.http import short_exc

log = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
METADATA_URL = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{filename}"

# Skip obvious non-payload files when picking what to download.
_SKIP_SUFFIXES = (
    ".xml",
    ".sqlite",
    ".sqlite3",
    ".torrent",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".json",
    ".txt",
)
_SKIP_FORMATS = {"metadata", "thumbnail", "animated gif", "jpeg", "png", "item tile"}
_SKIP_MEDIATYPES = {"collection", "search", "web", "data"}

ARCHIVE_HEADERS = dict(HTTP_API_HEADERS)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def docs_to_results(payload: dict[str, Any]) -> list[HttpFileResult]:
    """Convert Archive advancedsearch JSON into HTTP results (testable)."""
    response = payload.get("response") or {}
    docs = response.get("docs") or []
    out: list[HttpFileResult] = []
    for doc in docs:
        identifier = str(doc.get("identifier") or "").strip()
        if not identifier:
            continue
        mediatype = str(doc.get("mediatype") or "").strip().lower()
        if mediatype in _SKIP_MEDIATYPES:
            continue
        title = str(doc.get("title") or identifier).strip()
        size_bytes = _as_int(doc.get("item_size"))
        extra = {"identifier": identifier}
        if mediatype:
            extra["mediatype"] = mediatype
        out.append(
            HttpFileResult(
                name=title,
                url="",
                size_bytes=size_bytes,
                source=HttpSourceId.ARCHIVE,
                extra=extra,
            )
        )
    return out


def pick_archive_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose the best downloadable file from an Archive metadata `files` list."""
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for item in files:
        name = str(item.get("name") or "").strip()
        if not name or name.endswith("/") or name.startswith("."):
            continue
        lower = name.lower()
        if any(lower.endswith(suf) for suf in _SKIP_SUFFIXES):
            continue
        fmt = str(item.get("format") or "").strip().lower()
        if fmt in _SKIP_FORMATS:
            continue
        size = _as_int(item.get("size")) or 0
        original = 1 if str(item.get("source") or "").lower() == "original" else 0
        scored.append((original, size, item))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return scored[0][2]


def archive_file_url(identifier: str, filename: str) -> str:
    return DOWNLOAD_URL.format(identifier=identifier, filename=quote(filename, safe="/()[]_.-"))


def resolved_from_metadata(identifier: str, payload: dict[str, Any]) -> HttpFileResult:
    """Turn metadata JSON into a concrete downloadable file."""
    files = payload.get("files") or []
    if not isinstance(files, list):
        raise ValueError("Archive metadata has no files list")
    chosen = pick_archive_file(files)
    if chosen is None:
        raise ValueError(f"No downloadable file on Archive item {identifier}")
    filename = str(chosen.get("name") or "").strip()
    title = str((payload.get("metadata") or {}).get("title") or identifier)
    name = filename or title
    extra = {"identifier": identifier, "filename": filename}
    fmt = str(chosen.get("format") or "").strip()
    if fmt:
        extra["format"] = fmt
    return HttpFileResult(
        name=name,
        url=archive_file_url(identifier, filename),
        size_bytes=_as_int(chosen.get("size")),
        source=HttpSourceId.ARCHIVE,
        extra=extra,
    )


async def search_archive(
    query: str,
    *,
    limit: int = 50,
    client: httpx.AsyncClient | None = None,
) -> list[HttpFileResult]:
    q = query.strip()
    if not q:
        return []
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=ARCHIVE_HEADERS)
    assert client is not None
    params: list[tuple[str, str]] = [
        ("q", q),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "mediatype"),
        ("fl[]", "item_size"),
        ("output", "json"),
        ("rows", str(max(1, min(limit, 100)))),
        ("sort[]", "downloads desc"),
    ]
    try:
        response = await client.get(SEARCH_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Archive search returned non-object JSON")
        return docs_to_results(payload)
    except Exception as exc:
        log.warning("archive search failed: %s", short_exc(exc))
        raise
    finally:
        if owns:
            await client.aclose()


async def resolve_archive_identifier(
    identifier: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> HttpFileResult:
    ident = identifier.strip()
    if not ident:
        raise ValueError("Empty Archive identifier")
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=ARCHIVE_HEADERS)
    assert client is not None
    try:
        response = await client.get(METADATA_URL.format(identifier=quote(ident, safe="")))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Archive metadata returned non-object JSON")
        return resolved_from_metadata(ident, payload)
    finally:
        if owns:
            await client.aclose()


async def resolve_http_result(
    result: HttpFileResult,
    *,
    client: httpx.AsyncClient | None = None,
) -> HttpFileResult:
    """Return a result with a concrete http(s) URL."""
    if (result.url or "").strip():
        return result
    identifier = (result.extra or {}).get("identifier", "")
    if not identifier:
        raise ValueError(f"Cannot resolve HTTP result without url or identifier: {result.name}")
    resolved = await resolve_archive_identifier(identifier, client=client)
    # Keep the search title if the file name is opaque.
    name = result.name if result.name else resolved.name
    return HttpFileResult(
        name=name,
        url=resolved.url,
        size_bytes=resolved.size_bytes or result.size_bytes,
        source=resolved.source,
        extra={**result.extra, **resolved.extra},
    )


class ArchiveHttpSource(HttpSource):
    id = HttpSourceId.ARCHIVE
    label = "Archive.org"
    headers = ARCHIVE_HEADERS

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        client: httpx.AsyncClient | None = None,
    ) -> list[HttpFileResult]:
        return await search_archive(query, limit=limit, client=client)

    async def resolve(
        self,
        result: HttpFileResult,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> HttpFileResult:
        return await resolve_http_result(result, client=client)
