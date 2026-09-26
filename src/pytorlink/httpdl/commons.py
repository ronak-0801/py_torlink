"""Wikimedia Commons search (MediaWiki public API, no HTML scraping).

Search returns a direct upload.wikimedia.org URL, so results never need a
second resolve request.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from pytorlink.httpdl.base import HttpSource
from pytorlink.httpdl.types import HTTP_API_HEADERS, HttpFileResult, HttpSourceId
from pytorlink.sources.http import make_client, short_exc

log = logging.getLogger(__name__)

API_URL = "https://commons.wikimedia.org/w/api.php"

# CirrusSearch keyword restricting hits to playable media. The `|` form is the
# one Commons honours; `filetype:video OR filetype:audio` silently matches none.
MEDIA_FILTER = "filetype:video|audio"

COMMONS_HEADERS = dict(HTTP_API_HEADERS)


def clean_upload_url(url: str) -> str:
    """Drop the analytics query imageinfo appends to file URLs."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.query:
        return raw
    kept = [(k, v) for k, v in parse_qsl(parsed.query) if not k.startswith("utm_")]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def _title_to_name(title: str) -> str:
    """`File:Some Clip.webm` -> `Some Clip.webm`."""
    text = (title or "").strip()
    if text.lower().startswith("file:"):
        text = text[len("file:") :]
    return text.strip()


def build_search_params(query: str, limit: int) -> list[tuple[str, str]]:
    rows = max(1, min(limit, 50))
    return [
        ("action", "query"),
        ("format", "json"),
        ("formatversion", "2"),
        ("generator", "search"),
        ("gsrsearch", f"{query} {MEDIA_FILTER}"),
        ("gsrnamespace", "6"),  # File:
        ("gsrlimit", str(rows)),
        ("prop", "imageinfo"),
        ("iiprop", "url|size|mime|extmetadata"),
    ]


def _license_of(info: dict[str, Any]) -> str:
    meta = info.get("extmetadata") or {}
    if not isinstance(meta, dict):
        return ""
    entry = meta.get("LicenseShortName") or {}
    if isinstance(entry, dict):
        return str(entry.get("value") or "").strip()
    return ""


def _duration_label(info: dict[str, Any]) -> str:
    raw = info.get("duration")
    try:
        total = int(float(raw))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def pages_to_results(payload: dict[str, Any]) -> list[HttpFileResult]:
    """Convert a MediaWiki imageinfo response into HTTP results (testable)."""
    pages = (payload.get("query") or {}).get("pages") or []
    if not isinstance(pages, list):
        return []
    # `index` carries the search ranking; dict ordering does not.
    ordered = sorted(pages, key=lambda p: p.get("index") or 0)
    out: list[HttpFileResult] = []
    for page in ordered:
        infos = page.get("imageinfo") or []
        if not isinstance(infos, list) or not infos:
            continue
        info = infos[0]
        url = clean_upload_url(str(info.get("url") or ""))
        if not url:
            continue
        name = _title_to_name(str(page.get("title") or "")) or url.rsplit("/", 1)[-1]
        size = info.get("size")
        extra = {"pageid": str(page.get("pageid") or "")}
        mime = str(info.get("mime") or "").strip()
        if mime:
            extra["mediatype"] = mime
        license_name = _license_of(info)
        if license_name:
            extra["license"] = license_name
        duration = _duration_label(info)
        if duration:
            extra["duration"] = duration
        descriptionurl = str(info.get("descriptionurl") or "").strip()
        if descriptionurl:
            extra["page"] = descriptionurl
        out.append(
            HttpFileResult(
                name=name,
                url=url,
                size_bytes=size if isinstance(size, int) else None,
                source=HttpSourceId.COMMONS,
                extra=extra,
            )
        )
    return out


async def search_commons(
    query: str,
    *,
    limit: int = 50,
    client: httpx.AsyncClient | None = None,
) -> list[HttpFileResult]:
    q = query.strip()
    if not q:
        return []
    http, owns = make_client(headers=COMMONS_HEADERS, client=client)
    try:
        response = await http.get(API_URL, params=build_search_params(q, limit))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Commons search returned non-object JSON")
        error = payload.get("error")
        if isinstance(error, dict):
            raise ValueError(f"Commons API error: {error.get('info') or error.get('code')}")
        return pages_to_results(payload)
    except Exception as exc:
        log.warning("commons search failed: %s", short_exc(exc))
        raise
    finally:
        if owns:
            await http.aclose()


class CommonsHttpSource(HttpSource):
    id = HttpSourceId.COMMONS
    label = "Wikimedia Commons"
    headers = COMMONS_HEADERS

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        client: httpx.AsyncClient | None = None,
    ) -> list[HttpFileResult]:
        return await search_commons(query, limit=limit, client=client)
