"""EXT.to (ext.to) HTML torrent search.

Soft-fail friendly. Prefer parsing magnets / info-hashes from HTML when
present; optionally resolve magnets via the site AJAX helper when tokens
are available. Cloudflare challenges raise so the registry soft-fails.

Primary host: https://ext.to
Mirrors (same branding): https://extto.com
Search paths tried: /browse/?q=… then /search/?q=…
"""

from __future__ import annotations

import hashlib
import html as html_mod
import json
import logging
import re
import time
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx

from pytorlink.sources.http import make_client
from pytorlink.sources.magnet import build_magnet, normalize_info_hash, parse_magnet
from pytorlink.sources.types import SourceId, TorrentResult

log = logging.getLogger(__name__)

EXT_TO_HOME = "https://ext.to"
EXT_TO_MIRRORS = ("https://ext.to", "https://extto.com")

_MAGNET_HREF = re.compile(r"""href=["'](magnet:\?[^"']+)["']""", re.I)
_MAGNET_BARE = re.compile(r"(magnet:\?xt=urn:btih:[^\s\"'<>]+)", re.I)
_DATA_HASH = re.compile(
    r"""data-(?:hash|infohash|btih)=["']([0-9a-fA-F]{40}|[2-7A-Za-z]{32})["']""",
    re.I,
)
_BTN_ROW = re.compile(
    r"""<a\b[^>]*\b(?:search-magnet-btn|download-btn-magnet)\b[^>]*\bdata-id=["'](\d+)["'][^>]*>""",
    re.I,
)
_TITLE_LINK = re.compile(
    r"""<a\b[^>]*\btorrent-title-link\b[^>]*>(.*?)</a>""",
    re.I | re.S,
)
_TITLE_TOOLTIP = re.compile(
    r"""data-tooltip=["']([^"']+)["']""",
    re.I,
)
_SIZE_RE = re.compile(
    r"""(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB|B)\b""",
    re.I,
)
_SEED_RE = re.compile(
    r"""class=["'][^"']*text-success[^"']*["'][^>]*>\s*([\d,]+)""",
    re.I,
)
_LEECH_RE = re.compile(
    r"""class=["'][^"']*text-danger[^"']*["'][^>]*>\s*([\d,]+)""",
    re.I,
)
_PAGE_TOKEN = re.compile(
    r"""window\.(?:searchPageToken|pageToken)\s*=\s*['"]([A-Za-z0-9_-]+)['"]""",
    re.I,
)
_CSRF_TOKEN = re.compile(
    r"""window\.csrfToken\s*=\s*['"]([A-Za-z0-9_-]+)['"]""",
    re.I,
)
_TR_SPLIT = re.compile(r"<tr\b", re.I)


def _unescape(text: str) -> str:
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = html_mod.unescape(cur)
    return cur


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_size(text: str) -> int | None:
    m = _SIZE_RE.search(text)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2).upper()
    mult = {
        "B": 1,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
    }.get(unit)
    if mult is None:
        return None
    return int(num * mult)


def _looks_like_challenge(body: str) -> bool:
    lower = body[:4000].lower()
    return (
        "just a moment" in lower
        or "cf-browser-verification" in lower
        or "checking your browser" in lower
        or "performing security verification" in lower
    )


def _ext_hmac(torrent_id: str, timestamp: int, page_token: str) -> str:
    raw = f"{torrent_id}|{timestamp}|{page_token}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _result_from_magnet(
    magnet: str,
    *,
    name: str | None = None,
    size_bytes: int | None = None,
    seeders: int | None = None,
    leechers: int | None = None,
) -> TorrentResult | None:
    try:
        parsed = parse_magnet(magnet)
        info_hash = normalize_info_hash(str(parsed["info_hash"]))
    except ValueError:
        return None
    display = name or (str(parsed.get("name")) if parsed.get("name") else None) or info_hash
    return TorrentResult(
        name=display,
        info_hash=info_hash,
        size_bytes=size_bytes,
        seeders=seeders,
        leechers=leechers,
        source=SourceId.EXT_TO,
        magnet=magnet if magnet.lower().startswith("magnet:") else build_magnet(info_hash, name=display),
        category=None,
    )


def _row_blobs(html: str) -> list[str]:
    parts = _TR_SPLIT.split(html)
    if len(parts) <= 1:
        return [html]
    return ["<tr" + p for p in parts[1:]]


def _title_from_row(row: str) -> str:
    tip = _TITLE_TOOLTIP.search(row)
    if tip:
        return _unescape(tip.group(1)).strip() or "Unknown"
    m = _TITLE_LINK.search(row)
    if m:
        return _unescape(_strip_tags(m.group(1))) or "Unknown"
    for am in re.finditer(
        r"""<a\b[^>]*href=["'](?!magnet:)[^"']+["'][^>]*>(.*?)</a>""",
        row,
        re.I | re.S,
    ):
        t = _unescape(_strip_tags(am.group(1)))
        if t and len(t) > 2:
            return t
    return "Unknown"


def _row_seeders_leechers(row: str) -> tuple[int | None, int | None]:
    seeders = None
    leechers = None
    sm = _SEED_RE.search(row)
    if sm:
        try:
            seeders = int(sm.group(1).replace(",", ""))
        except ValueError:
            seeders = None
    lm = _LEECH_RE.search(row)
    if lm:
        try:
            leechers = int(lm.group(1).replace(",", ""))
        except ValueError:
            leechers = None
    return seeders, leechers


def ext_to_html_to_results(html_text: str, *, limit: int = 50) -> list[TorrentResult]:
    """Parse EXT.to search HTML into torrent rows (fixture-friendly).

    Prefers table-row parsing (title / size / seeders), then document-level
    magnets and ``data-hash`` attributes for leftovers.
    """
    out: list[TorrentResult] = []
    seen: set[str] = set()

    def _add(item: TorrentResult | None) -> None:
        if item is None:
            return
        key = item.info_hash.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(item)

    for row in _row_blobs(html_text):
        if len(out) >= limit:
            break
        title = _title_from_row(row)
        size_bytes = _parse_size(row)
        seeders, leechers = _row_seeders_leechers(row)

        row_magnets = [_unescape(m.group(1)) for m in _MAGNET_HREF.finditer(row)]
        if not row_magnets:
            row_magnets = [_unescape(m.group(1)) for m in _MAGNET_BARE.finditer(row)]
        for mag in row_magnets:
            _add(
                _result_from_magnet(
                    mag,
                    name=title,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                )
            )
            if len(out) >= limit:
                break

        if len(out) >= limit:
            break
        for hm in _DATA_HASH.finditer(row):
            try:
                ih = normalize_info_hash(hm.group(1))
            except ValueError:
                continue
            _add(
                TorrentResult(
                    name=title if title != "Unknown" else ih,
                    info_hash=ih,
                    size_bytes=size_bytes,
                    seeders=seeders,
                    leechers=leechers,
                    source=SourceId.EXT_TO,
                    magnet=build_magnet(ih, name=title if title != "Unknown" else None),
                )
            )
            if len(out) >= limit:
                break

    if len(out) >= limit:
        return out[:limit]

    for m in _MAGNET_HREF.finditer(html_text):
        _add(_result_from_magnet(_unescape(m.group(1))))
        if len(out) >= limit:
            return out[:limit]
    for m in _MAGNET_BARE.finditer(html_text):
        _add(_result_from_magnet(_unescape(m.group(1))))
        if len(out) >= limit:
            return out[:limit]
    for m in _DATA_HASH.finditer(html_text):
        try:
            ih = normalize_info_hash(m.group(1))
        except ValueError:
            continue
        _add(
            TorrentResult(
                name=ih,
                info_hash=ih,
                size_bytes=None,
                seeders=None,
                source=SourceId.EXT_TO,
                magnet=build_magnet(ih),
            )
        )
        if len(out) >= limit:
            return out[:limit]

    return out[:limit]


def parse_ext_to_candidates(html_text: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Extract search-magnet-btn candidates (torrent_id + metadata) for AJAX enrich."""
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in _row_blobs(html_text):
        bm = _BTN_ROW.search(row)
        if not bm:
            continue
        tid = bm.group(1)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        title = _title_from_row(row)
        seeders, leechers = _row_seeders_leechers(row)
        candidates.append(
            {
                "torrent_id": tid,
                "name": title,
                "size_bytes": _parse_size(row),
                "seeders": seeders,
                "leechers": leechers,
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def extract_ext_to_tokens(html_text: str) -> tuple[str | None, str | None]:
    """Return ``(page_token, csrf_token)`` from search/detail HTML."""
    page = _PAGE_TOKEN.search(html_text)
    csrf = _CSRF_TOKEN.search(html_text)
    return (page.group(1) if page else None, csrf.group(1) if csrf else None)


class ExtToSource:
    """EXT.to HTML search source (optional AJAX magnet resolve)."""

    id = SourceId.EXT_TO
    label = "EXT"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
        home: str = EXT_TO_HOME,
        ajax_limit: int = 12,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.home = home.rstrip("/")
        self.ajax_limit = max(0, ajax_limit)

    def _search_urls(self, query: str) -> list[str]:
        q = quote_plus(query.strip())
        return [
            f"{self.home}/browse/?q={q}&with_adult=1&page_size=50",
            f"{self.home}/search/?q={q}",
        ]

    async def _fetch_html(self, client: httpx.AsyncClient, url: str) -> str:
        resp = await client.get(url)
        resp.raise_for_status()
        body = resp.text
        if _looks_like_challenge(body):
            raise RuntimeError("EXT: Cloudflare challenge / blocked")
        return body

    async def _ajax_magnet(
        self,
        client: httpx.AsyncClient,
        *,
        torrent_id: str,
        page_token: str,
        csrf_token: str,
    ) -> str | None:
        """Try getSearchMagnet then getTorrentMagnet; return magnet URI or None."""
        timestamp = int(time.time())
        hmac = _ext_hmac(torrent_id, timestamp, page_token)
        data = {
            "torrent_id": torrent_id,
            "download_type": "magnet",
            "timestamp": str(timestamp),
            "hmac": hmac,
            "sessid": csrf_token,
        }
        for endpoint in ("ajax/getSearchMagnet.php", "ajax/getTorrentMagnet.php"):
            url = urljoin(self.home + "/", endpoint)
            try:
                resp = await client.post(
                    url,
                    data=data,
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": self.home + "/",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                if resp.status_code >= 400:
                    continue
                text = resp.text.strip()
                payload: Any
                try:
                    payload = resp.json()
                except Exception:
                    m = re.search(r"\{[^{}]+\}", text)
                    if not m:
                        continue
                    payload = json.loads(m.group(0))
                if not isinstance(payload, dict):
                    continue
                magnet = payload.get("url") or payload.get("magnet") or payload.get("link")
                if isinstance(magnet, str) and magnet.lower().startswith("magnet:"):
                    return magnet
            except Exception as exc:
                log.debug("EXT ajax soft-fail %s: %s", endpoint, exc)
                continue
        return None

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        q = query.strip()
        if not q:
            return []
        client, owns = make_client(
            timeout=self.timeout,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
            client=self._client,
        )
        try:
            body: str | None = None
            last_exc: Exception | None = None
            for url in self._search_urls(q):
                try:
                    body = await self._fetch_html(client, url)
                    break
                except Exception as exc:
                    last_exc = exc
                    log.debug("EXT fetch failed %s: %s", url, exc)
            if body is None:
                raise last_exc or RuntimeError("EXT: no response")

            results = ext_to_html_to_results(body, limit=limit)
            if len(results) >= limit:
                return results[:limit]

            page_token, csrf_token = extract_ext_to_tokens(body)
            if not page_token or not csrf_token or self.ajax_limit <= 0:
                return results[:limit]

            seen = {r.info_hash.lower() for r in results}
            for cand in parse_ext_to_candidates(body, limit=self.ajax_limit):
                if len(results) >= limit:
                    break
                magnet = await self._ajax_magnet(
                    client,
                    torrent_id=str(cand["torrent_id"]),
                    page_token=page_token,
                    csrf_token=csrf_token,
                )
                if not magnet:
                    continue
                item = _result_from_magnet(
                    magnet,
                    name=str(cand.get("name") or "Unknown"),
                    size_bytes=cand.get("size_bytes"),  # type: ignore[arg-type]
                    seeders=cand.get("seeders"),  # type: ignore[arg-type]
                    leechers=cand.get("leechers"),  # type: ignore[arg-type]
                )
                if item is None or item.info_hash.lower() in seen:
                    continue
                seen.add(item.info_hash.lower())
                results.append(item)
            return results[:limit]
        finally:
            if owns:
                await client.aclose()
