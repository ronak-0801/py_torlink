"""Nyaa.si RSS search source."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import httpx

from pytorlink.sources.http import make_client
from pytorlink.sources.magnet import build_magnet, normalize_info_hash, parse_magnet
from pytorlink.sources.types import SourceId, TorrentResult

log = logging.getLogger(__name__)

NYAA_RSS = "https://nyaa.si/?page=rss"
_NS = {
    "nyaa": "https://nyaa.si/xmlns/nyaa",
}

_NYAA_HEADERS = {
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
}


def _text(el: ET.Element | None, default: str | None = None) -> str | None:
    if el is None or el.text is None:
        return default
    return el.text.strip()


def _find_nyaa(item: ET.Element, tag: str) -> str | None:
    el = item.find(f"nyaa:{tag}", _NS)
    if el is not None and el.text:
        return el.text.strip()
    for child in item:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == tag and child.text:
            return child.text.strip()
    return None


def _parse_size(size_str: str | None) -> int | None:
    if not size_str:
        return None
    text = size_str.strip().upper().replace(",", "")
    units = {
        "B": 1,
        "KIB": 1024,
        "MIB": 1024**2,
        "GIB": 1024**3,
        "TIB": 1024**4,
        "KB": 1000,
        "MB": 1000**2,
        "GB": 1000**3,
        "TB": 1000**4,
    }
    m = re.match(r"^([\d.]+)\s*([A-Z]+)$", text)
    if not m:
        return None
    num, unit = float(m.group(1)), m.group(2)
    if unit not in units:
        return None
    return int(num * units[unit])


def _looks_like_html(content_type: str, body: str) -> bool:
    ct = (content_type or "").lower()
    if "html" in ct and "xml" not in ct:
        return True
    stripped = body.lstrip()
    lower = stripped[:64].lower()
    return lower.startswith("<!doctype") or lower.startswith("<html")


def rss_xml_to_results(xml_text: str, *, source: SourceId = SourceId.NYAA) -> list[TorrentResult]:
    """Parse Nyaa RSS XML into TorrentResult rows (testable without network)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError("Nyaa: invalid RSS") from exc
    channel = root.find("channel")
    if channel is None:
        items = root.findall("item")
    else:
        items = channel.findall("item")
    out: list[TorrentResult] = []
    for item in items:
        title = _text(item.find("title")) or "Unknown"
        info_hash_raw = _find_nyaa(item, "infoHash")
        if not info_hash_raw:
            link = _text(item.find("link")) or ""
            if link.lower().startswith("magnet:"):
                try:
                    info_hash_raw = str(parse_magnet(link)["info_hash"])
                except ValueError:
                    continue
            else:
                continue
        try:
            info_hash = normalize_info_hash(info_hash_raw)
        except ValueError:
            continue
        seeders_s = _find_nyaa(item, "seeders")
        leechers_s = _find_nyaa(item, "leechers")
        size_s = _find_nyaa(item, "size")
        category = _find_nyaa(item, "category")
        try:
            seeders = int(seeders_s) if seeders_s is not None else None
        except ValueError:
            seeders = None
        try:
            leechers = int(leechers_s) if leechers_s is not None else None
        except ValueError:
            leechers = None
        size_bytes = _parse_size(size_s)
        magnet = build_magnet(info_hash, name=title)
        out.append(
            TorrentResult(
                name=title,
                info_hash=info_hash,
                size_bytes=size_bytes,
                seeders=seeders,
                leechers=leechers,
                source=source,
                magnet=magnet,
                category=category,
            )
        )
    return out


class NyaaSource:
    id = SourceId.NYAA
    label = "Nyaa"

    def __init__(
        self,
        base_url: str = NYAA_RSS,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._client = client

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        client, owns = make_client(
            timeout=self.timeout,
            headers=_NYAA_HEADERS,
            client=self._client,
        )
        params = {"q": query, "c": "0_0", "f": "0"}
        try:
            resp = await client.get(self.base_url, params=params)
            resp.raise_for_status()
            body = resp.text
            if _looks_like_html(resp.headers.get("content-type", ""), body):
                raise RuntimeError("Nyaa: blocked or non-RSS response (Cloudflare/HTML)")
            results = rss_xml_to_results(body)
            return results[:limit]
        finally:
            if owns:
                await client.aclose()
