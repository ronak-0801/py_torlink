"""The Pirate Bay via apibay.org JSON API."""

from __future__ import annotations

from typing import Any

import httpx

from pytorlink.sources.http import make_client
from pytorlink.sources.magnet import build_magnet, normalize_info_hash
from pytorlink.sources.types import SourceId, TorrentResult

APIBAY_Q = "https://apibay.org/q.php"
ZERO_HASH = "0000000000000000000000000000000000000000"


def apibay_items_to_results(
    items: list[dict[str, Any]],
    *,
    source: SourceId = SourceId.PIRATEBAY,
) -> list[TorrentResult]:
    """Map apibay JSON rows to results; skip empty/sentinel rows."""
    out: list[TorrentResult] = []
    for it in items:
        if str(it.get("id", "")) == "0":
            continue
        raw_hash = str(it.get("info_hash") or "").strip()
        if not raw_hash or raw_hash.lower() == ZERO_HASH:
            continue
        try:
            info_hash = normalize_info_hash(raw_hash)
        except ValueError:
            continue
        name = str(it.get("name") or "Unknown")
        try:
            size_bytes = int(it.get("size") or 0) or None
        except (TypeError, ValueError):
            size_bytes = None
        try:
            seeders = int(it.get("seeders") or 0)
        except (TypeError, ValueError):
            seeders = None
        try:
            leechers = int(it.get("leechers") or 0)
        except (TypeError, ValueError):
            leechers = None
        category = str(it.get("category") or "") or None
        out.append(
            TorrentResult(
                name=name,
                info_hash=info_hash,
                size_bytes=size_bytes,
                seeders=seeders,
                leechers=leechers,
                source=source,
                magnet=build_magnet(info_hash, name=name),
                category=category,
            )
        )
    return out


def _is_sentinel(items: list[dict[str, Any]]) -> bool:
    return len(items) == 1 and str(items[0].get("id", "")) == "0"


class PirateBaySource:
    id = SourceId.PIRATEBAY
    label = "TPB"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
        api_url: str = APIBAY_Q,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.api_url = api_url

    async def _fetch(self, client: httpx.AsyncClient, params: dict[str, str]) -> list[dict[str, Any]]:
        resp = await client.get(self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        return [x for x in data if isinstance(x, dict)]

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        q = query.strip()
        if not q:
            return []
        client, owns = make_client(timeout=self.timeout, client=self._client)
        try:
            items = await self._fetch(client, {"q": q})
            # apibay returns a single id==0 sentinel for empty / sticky cache misses.
            if _is_sentinel(items):
                items = await self._fetch(client, {"q": q, "cat": "0"})
            return apibay_items_to_results(items)[:limit]
        finally:
            if owns:
                await client.aclose()
