"""YTS JSON API source with host failover."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from pytorlink.sources.http import make_client, short_exc
from pytorlink.sources.magnet import build_magnet, normalize_info_hash
from pytorlink.sources.types import SourceId, TorrentResult

log = logging.getLogger(__name__)

# Prefer historically stable mirrors first; rotate on 5xx/timeouts.
YTS_HOSTS: tuple[str, ...] = ("yts.mx", "yts.lt", "yts.am", "yts.rs")


def movie_payload_to_results(payload: dict[str, Any], *, source: SourceId = SourceId.YTS) -> list[TorrentResult]:
    """Convert a YTS list_movies JSON body into TorrentResult rows (testable)."""
    data = payload.get("data") or {}
    movies = data.get("movies") or []
    out: list[TorrentResult] = []
    for movie in movies:
        title = str(movie.get("title_long") or movie.get("title") or "Unknown")
        year = movie.get("year")
        base_name = f"{title}" if year is None else f"{title}"
        for tor in movie.get("torrents") or []:
            raw_hash = tor.get("hash")
            if not raw_hash:
                continue
            try:
                info_hash = normalize_info_hash(str(raw_hash))
            except ValueError:
                continue
            quality = str(tor.get("quality") or "")
            video_type = str(tor.get("type") or "")
            bits = [base_name]
            if quality:
                bits.append(f"[{quality}]")
            if video_type:
                bits.append(f"({video_type})")
            name = " ".join(bits)
            size_bytes = tor.get("size_bytes")
            if isinstance(size_bytes, str) and size_bytes.isdigit():
                size_bytes = int(size_bytes)
            if not isinstance(size_bytes, int):
                size_bytes = _human_size_to_bytes(tor.get("size"))
            seeds = tor.get("seeds")
            peers = tor.get("peers")
            try:
                seeders = int(seeds) if seeds is not None else None
            except (TypeError, ValueError):
                seeders = None
            try:
                leechers = int(peers) if peers is not None else None
            except (TypeError, ValueError):
                leechers = None
            magnet = build_magnet(info_hash, name=name)
            out.append(
                TorrentResult(
                    name=name,
                    info_hash=info_hash,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    source=source,
                    magnet=magnet,
                    category="Movies",
                    extra={"quality": quality, "type": video_type},
                )
            )
    return out


def _human_size_to_bytes(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().upper().replace(",", "")
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    parts = text.split()
    if len(parts) != 2:
        for u in ("TB", "GB", "MB", "KB", "B"):
            if text.endswith(u):
                num = text[: -len(u)].strip()
                try:
                    return int(float(num) * units[u])
                except ValueError:
                    return None
        return None
    num_s, unit = parts
    unit = unit.upper()
    if unit not in units:
        return None
    try:
        return int(float(num_s) * units[unit])
    except ValueError:
        return None


class YtsSource:
    id = SourceId.YTS
    label = "YTS"

    # Remembered for the process lifetime across instances.
    _last_working_host: str | None = None

    def __init__(
        self,
        hosts: tuple[str, ...] = YTS_HOSTS,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.hosts = hosts
        self.timeout = timeout
        self._client = client

    def _ordered_hosts(self) -> list[str]:
        hosts = list(self.hosts)
        last = type(self)._last_working_host
        if last and last in hosts:
            hosts.remove(last)
            hosts.insert(0, last)
        return hosts

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        host: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"https://{host}/api/v2/list_movies.json"
        last_status: int | None = None
        for attempt in range(2):
            try:
                resp = await client.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise RuntimeError(f"timeout from {host}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"{short_exc(exc)} from {host}") from exc

            if resp.status_code >= 500:
                last_status = resp.status_code
                if attempt == 0:
                    log.debug("YTS %s returned %s; retrying once", host, resp.status_code)
                    continue
                raise RuntimeError(f"{resp.status_code} from {host}")

            if resp.status_code >= 400:
                raise RuntimeError(f"{resp.status_code} from {host}")

            try:
                payload = resp.json()
            except ValueError as exc:
                raise RuntimeError(f"invalid JSON from {host}") from exc
            if not isinstance(payload, dict):
                raise RuntimeError(f"unexpected response from {host}")
            if payload.get("status") != "ok" and "data" not in payload:
                raise RuntimeError(f"unexpected response from {host}")
            return payload

        raise RuntimeError(f"{last_status or 'error'} from {host}")

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        last_detail = "no hosts"
        client, owns = make_client(timeout=self.timeout, client=self._client)
        params = {"query_term": query, "limit": min(limit, 50)}
        try:
            for host in self._ordered_hosts():
                try:
                    payload = await self._get_json(client, host, params)
                    type(self)._last_working_host = host
                    return movie_payload_to_results(payload)
                except Exception as exc:
                    last_detail = short_exc(exc)
                    log.debug("YTS host %s failed: %s", host, last_detail)
                    continue
        finally:
            if owns:
                await client.aclose()
        raise RuntimeError(f"YTS: all mirrors failed (last: {last_detail})")
