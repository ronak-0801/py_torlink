"""SubsPlease JSON API source."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

import httpx

from pytorlink.sources.http import make_client
from pytorlink.sources.magnet import parse_magnet
from pytorlink.sources.types import SourceId, TorrentResult

SUBSPLEASE_API = "https://subsplease.org/api/"
RES_PREFERENCE = ("1080", "720", "480")
_XL_RE = re.compile(r"[?&]xl=(\d+)", re.I)


def _pick_best(downloads: list[dict[str, Any]]) -> dict[str, Any] | None:
    for res in RES_PREFERENCE:
        for d in downloads:
            if str(d.get("res") or "") == res and d.get("magnet"):
                return d
    for d in downloads:
        if d.get("magnet"):
            return d
    return None


def subsplease_payload_to_results(
    payload: Any,
    *,
    source: SourceId = SourceId.SUBSPLEASE,
) -> list[TorrentResult]:
    """Map SubsPlease search/latest JSON object to results."""
    if not payload or isinstance(payload, list):
        return []
    if not isinstance(payload, dict):
        return []
    out: list[TorrentResult] = []
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        downloads = entry.get("downloads") or []
        if not isinstance(downloads, list):
            continue
        best = _pick_best([d for d in downloads if isinstance(d, dict)])
        if not best or not best.get("magnet"):
            continue
        magnet = unquote(str(best["magnet"]))
        try:
            parsed = parse_magnet(magnet)
            info_hash = str(parsed["info_hash"])
        except ValueError:
            continue
        show = str(entry.get("show") or "Unknown")
        ep = entry.get("episode")
        res = str(best.get("res") or "?")
        name = f"{show} - {ep} [{res}p]" if ep else f"{show} [{res}p]"
        xl = _XL_RE.search(magnet)
        size_bytes = int(xl.group(1)) if xl else None
        out.append(
            TorrentResult(
                name=name,
                info_hash=info_hash,
                size_bytes=size_bytes,
                seeders=None,  # API has no swarm data
                leechers=None,
                source=source,
                magnet=magnet,
                category="Anime",
                extra={"resolution": res},
            )
        )
    return out


class SubsPleaseSource:
    id = SourceId.SUBSPLEASE
    label = "SubsPlease"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
        api_url: str = SUBSPLEASE_API,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.api_url = api_url

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        q = query.strip()
        params: dict[str, str] = {"tz": "UTC"}
        if q:
            params["f"] = "search"
            params["s"] = q
        else:
            params["f"] = "latest"
        client, owns = make_client(
            timeout=self.timeout,
            headers={"Accept": "application/json, text/plain, */*"},
            client=self._client,
        )
        try:
            resp = await client.get(self.api_url, params=params)
            resp.raise_for_status()
            # SubsPlease sometimes advertises text/html while returning JSON.
            try:
                payload = resp.json()
            except ValueError as exc:
                body = resp.text.lstrip()
                if body.lower().startswith("<!doctype") or body.lower().startswith("<html"):
                    raise RuntimeError("SubsPlease: blocked or non-JSON response (HTML)") from exc
                raise RuntimeError("SubsPlease: invalid JSON") from exc
            return subsplease_payload_to_results(payload)[:limit]
        finally:
            if owns:
                await client.aclose()
