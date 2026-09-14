"""BitTorrented JSON search API (video).

Optional / paywalled: free clients often receive HTTP 402 Payment Required.
Kept in the registry but **disabled by default** — enable via the TUI source picker (`s`).
Soft-fail if the index is down or returns an error status.
"""

from __future__ import annotations

from typing import Any

import httpx

from pytorlink.sources.http import make_client
from pytorlink.sources.magnet import build_magnet, normalize_info_hash
from pytorlink.sources.types import SourceId, TorrentResult

BITTORRENTED_API = "https://bittorrented.com/api/search/torrents"
MIN_QUERY = 3


def bittorrented_payload_to_results(
    payload: dict[str, Any] | list[Any],
    *,
    source: SourceId = SourceId.BITTORRENTED,
) -> list[TorrentResult]:
    """Map BitTorrented search JSON to results."""
    if isinstance(payload, list):
        rows = payload
    else:
        rows = payload.get("results") or []
    if not isinstance(rows, list):
        return []
    out: list[TorrentResult] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("torrent_infohash") or "").strip()
        if not raw:
            continue
        try:
            info_hash = normalize_info_hash(raw)
        except ValueError:
            continue
        name = str(row.get("torrent_name") or info_hash)
        try:
            size_bytes = int(row["torrent_total_size"]) if row.get("torrent_total_size") is not None else None
        except (TypeError, ValueError):
            size_bytes = None
        try:
            seeders = int(row["torrent_seeders"]) if row.get("torrent_seeders") is not None else None
        except (TypeError, ValueError):
            seeders = None
        try:
            leechers = int(row["torrent_leechers"]) if row.get("torrent_leechers") is not None else None
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
                magnet=build_magnet(info_hash, name=name),
                category="Video",
            )
        )
    return out


class BitTorrentedSource:
    id = SourceId.BITTORRENTED
    label = "BitTorrented"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
        api_url: str = BITTORRENTED_API,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.api_url = api_url

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        q = query.strip()
        if len(q) < MIN_QUERY:
            return []
        params = {
            "q": q,
            "type": "video",
            "limit": str(min(limit, 50)),
            "sortBy": "seeders",
            "sortOrder": "desc",
        }
        client, owns = make_client(
            timeout=self.timeout,
            headers={"Accept": "application/json"},
            client=self._client,
        )
        try:
            resp = await client.get(self.api_url, params=params)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, (dict, list)):
                return []
            return bittorrented_payload_to_results(payload)[:limit]
        finally:
            if owns:
                await client.aclose()
