"""EZTV JSON API source (latest feed + light text filter / imdb expand)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from pytorlink.sources.http import make_client
from pytorlink.sources.magnet import build_magnet, normalize_info_hash
from pytorlink.sources.types import SourceId, TorrentResult

log = logging.getLogger(__name__)

EZTV_API = "https://eztvx.to/api/get-torrents"
PAGE_LIMIT = 100
INDEX_PAGES = 3
MAX_IMDB_SHOWS = 2


def eztv_torrents_to_results(
    rows: list[dict[str, Any]],
    *,
    source: SourceId = SourceId.EZTV,
) -> list[TorrentResult]:
    """Map EZTV API torrent rows to results (testable)."""
    out: list[TorrentResult] = []
    seen: set[str] = set()
    for t in rows:
        raw_hash = str(t.get("hash") or "").strip()
        if not raw_hash:
            continue
        try:
            info_hash = normalize_info_hash(raw_hash)
        except ValueError:
            continue
        key = info_hash.lower()
        if key in seen:
            continue
        seen.add(key)
        name = str(t.get("title") or t.get("filename") or info_hash)
        magnet = str(t.get("magnet_url") or "") or build_magnet(info_hash, name=name)
        try:
            size_bytes = int(t.get("size_bytes") or 0) or None
        except (TypeError, ValueError):
            size_bytes = None
        try:
            seeders = int(t["seeds"]) if t.get("seeds") is not None else None
        except (TypeError, ValueError):
            seeders = None
        try:
            leechers = int(t["peers"]) if t.get("peers") is not None else None
        except (TypeError, ValueError):
            leechers = None
        out.append(
            TorrentResult(
                name=name,
                info_hash=info_hash,
                size_bytes=size_bytes,
                seeders=seeders,
                leechers=leechers,
                source=source,
                magnet=magnet,
                category="TV",
                extra={"imdb_id": str(t.get("imdb_id") or "")},
            )
        )
    return out


def _matches(row: dict[str, Any], tokens: list[str]) -> bool:
    hay = f"{row.get('title') or ''} {row.get('filename') or ''}".lower()
    return all(tok in hay for tok in tokens)


class EztvSource:
    id = SourceId.EZTV
    label = "EZTV"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
        api_url: str = EZTV_API,
        index_pages: int = INDEX_PAGES,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.api_url = api_url
        self.index_pages = index_pages

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        *,
        page: int = 1,
        imdb_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"limit": str(PAGE_LIMIT), "page": str(page)}
        if imdb_id:
            params["imdb_id"] = imdb_id
        resp = await client.get(self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("torrents") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        q = query.strip()
        client, owns = make_client(timeout=self.timeout, client=self._client)
        try:
            # Page 1 is required; deeper pages soft-fail to keep the source usable.
            pages: list[list[dict[str, Any]]] = []
            first = await self._fetch_page(client, page=1)
            pages.append(first)
            for page in range(2, self.index_pages + 1):
                try:
                    pages.append(await self._fetch_page(client, page=page))
                except Exception as exc:
                    log.debug("EZTV page %s soft-fail: %s", page, exc)
                    break
            recent = [r for batch in pages for r in batch]

            if not q:
                return eztv_torrents_to_results(recent)[:limit]

            tokens = [t for t in q.lower().split() if t]
            hits = [r for r in recent if _matches(r, tokens)]

            imdb_ids: list[str] = []
            for row in hits:
                iid = str(row.get("imdb_id") or "").strip()
                if iid and iid != "0" and iid not in imdb_ids:
                    imdb_ids.append(iid)
                if len(imdb_ids) >= MAX_IMDB_SHOWS:
                    break

            catalogue: list[dict[str, Any]] = []
            for iid in imdb_ids:
                try:
                    catalogue.extend(await self._fetch_page(client, page=1, imdb_id=iid))
                except Exception as exc:
                    log.debug("EZTV imdb %s soft-fail: %s", iid, exc)

            merged = hits + [r for r in catalogue if _matches(r, tokens)]
            return eztv_torrents_to_results(merged)[:limit]
        finally:
            if owns:
                await client.aclose()
