"""NASA image and video library search (public API, no HTML scraping).

Search returns an item id plus an asset-manifest URL; the concrete file is
picked in :meth:`NasaHttpSource.resolve`, like Archive.org items.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from pytorlink.httpdl.base import HttpSource
from pytorlink.httpdl.types import HTTP_API_HEADERS, HttpFileResult, HttpSourceId
from pytorlink.sources.http import make_client, short_exc

log = logging.getLogger(__name__)

SEARCH_URL = "https://images-api.nasa.gov/search"
ASSET_URL = "https://images-api.nasa.gov/asset/{nasa_id}"

MEDIA_TYPES = "video,audio"

NASA_HEADERS = dict(HTTP_API_HEADERS)

# Renditions worst-to-best; later entries win when both are present.
_QUALITY_ORDER = ("~preview", "~mobile", "~small", "~medium", "~large", "~orig")
_MEDIA_SUFFIXES = (".mp4", ".mov", ".m4v", ".mpg", ".mpeg", ".webm", ".mp3", ".wav", ".m4a")


def https_url(url: str) -> str:
    """The asset manifest still lists http:// URLs; upgrade them."""
    raw = (url or "").strip()
    if raw.startswith("http://"):
        return "https://" + raw[len("http://") :]
    return raw


def _quality_rank(url: str) -> int:
    lower = url.lower()
    for rank, marker in enumerate(_QUALITY_ORDER):
        if marker in lower:
            return rank + 1
    return 0


def pick_nasa_asset(urls: list[str]) -> str | None:
    """Choose the highest-quality playable file from an asset manifest."""
    best: tuple[int, str] | None = None
    for raw in urls:
        url = https_url(str(raw or ""))
        if not url:
            continue
        lower = url.rsplit("?", 1)[0].lower()
        if not lower.endswith(_MEDIA_SUFFIXES):
            continue
        rank = _quality_rank(url)
        if best is None or rank > best[0]:
            best = (rank, url)
    return best[1] if best else None


def items_to_results(payload: dict[str, Any]) -> list[HttpFileResult]:
    """Convert a NASA search response into unresolved HTTP results (testable)."""
    items = (payload.get("collection") or {}).get("items") or []
    if not isinstance(items, list):
        return []
    out: list[HttpFileResult] = []
    for item in items:
        data_list = item.get("data") or []
        if not isinstance(data_list, list) or not data_list:
            continue
        data = data_list[0]
        nasa_id = str(data.get("nasa_id") or "").strip()
        if not nasa_id:
            continue
        title = str(data.get("title") or nasa_id).strip()
        extra = {"identifier": nasa_id}
        manifest = https_url(str(item.get("href") or ""))
        if manifest:
            extra["manifest"] = manifest
        media_type = str(data.get("media_type") or "").strip()
        if media_type:
            extra["mediatype"] = media_type
        center = str(data.get("center") or "").strip()
        if center:
            extra["center"] = center
        out.append(
            HttpFileResult(
                name=title,
                url="",  # resolved from the asset manifest on download
                size_bytes=None,  # manifest carries no sizes; Content-Length fills in
                source=HttpSourceId.NASA,
                extra=extra,
            )
        )
    return out


async def search_nasa(
    query: str,
    *,
    limit: int = 50,
    client: httpx.AsyncClient | None = None,
) -> list[HttpFileResult]:
    q = query.strip()
    if not q:
        return []
    http, owns = make_client(headers=NASA_HEADERS, client=client)
    params = {
        "q": q,
        "media_type": MEDIA_TYPES,
        "page_size": str(max(1, min(limit, 100))),
    }
    try:
        response = await http.get(SEARCH_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("NASA search returned non-object JSON")
        return items_to_results(payload)
    except Exception as exc:
        log.warning("nasa search failed: %s", short_exc(exc))
        raise
    finally:
        if owns:
            await http.aclose()


def _manifest_urls(payload: Any) -> list[str]:
    """Asset manifests are a bare URL list; /asset/{id} wraps them in a collection."""
    if isinstance(payload, list):
        return [str(u) for u in payload]
    if isinstance(payload, dict):
        items = (payload.get("collection") or {}).get("items") or []
        if isinstance(items, list):
            return [str(i.get("href") or "") for i in items if isinstance(i, dict)]
    return []


async def resolve_nasa_item(
    result: HttpFileResult,
    *,
    client: httpx.AsyncClient | None = None,
) -> HttpFileResult:
    nasa_id = (result.extra or {}).get("identifier", "").strip()
    manifest = (result.extra or {}).get("manifest", "").strip()
    if not manifest:
        if not nasa_id:
            raise ValueError(f"Cannot resolve NASA result without an id: {result.name}")
        manifest = ASSET_URL.format(nasa_id=quote(nasa_id, safe=""))
    http, owns = make_client(headers=NASA_HEADERS, client=client)
    try:
        response = await http.get(manifest)
        response.raise_for_status()
        chosen = pick_nasa_asset(_manifest_urls(response.json()))
    finally:
        if owns:
            await http.aclose()
    if not chosen:
        raise ValueError(f"No downloadable file for NASA item {nasa_id or result.name}")
    return HttpFileResult(
        name=result.name,
        url=chosen,
        size_bytes=result.size_bytes,
        source=HttpSourceId.NASA,
        extra={**result.extra, "filename": chosen.rsplit("/", 1)[-1]},
    )


class NasaHttpSource(HttpSource):
    id = HttpSourceId.NASA
    label = "NASA"
    headers = NASA_HEADERS

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        client: httpx.AsyncClient | None = None,
    ) -> list[HttpFileResult]:
        return await search_nasa(query, limit=limit, client=client)

    async def resolve(
        self,
        result: HttpFileResult,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> HttpFileResult:
        if (result.url or "").strip():
            return result
        return await resolve_nasa_item(result, client=client)
