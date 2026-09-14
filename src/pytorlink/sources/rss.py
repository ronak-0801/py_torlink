"""WordPress / generic RSS helpers for magnet extraction."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Callable

from pytorlink.sources.magnet import normalize_info_hash, parse_magnet
from pytorlink.sources.types import SourceId, TorrentResult

_MAGNET_HREF = re.compile(r"""href=["'](magnet:\?[^"']+)["']""", re.I)
_MAGNET_BARE = re.compile(r"(magnet:\?xt=urn:btih:[^\s\"'<>]+)", re.I)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


def unescape_entities(text: str) -> str:
    """Decode HTML entities commonly found in WordPress RSS magnet hrefs."""
    # WordPress often double-encodes ampersands as &#038;
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = html.unescape(cur)
    return cur


def _item_blobs(xml_text: str) -> list[str]:
    """Return raw XML snippets per <item> (tolerant of namespaces)."""
    parts = re.split(r"<item\b[^>]*>", xml_text, flags=re.I)
    blobs: list[str] = []
    for part in parts[1:]:
        end = re.search(r"</item>", part, flags=re.I)
        blobs.append(part if end is None else part[: end.start()])
    return blobs


def _title_from_blob(blob: str) -> str:
    m = _TITLE_RE.search(blob)
    if not m:
        return "Unknown"
    return unescape_entities(re.sub(r"<[^>]+>", "", m.group(1))).strip() or "Unknown"


def rss_magnets_to_results(
    xml_text: str,
    *,
    source: SourceId,
    category: str | None = None,
) -> list[TorrentResult]:
    """Parse RSS/Atom-ish XML and extract magnet links from each item.

    Prefer ``href="magnet:..."``; fall back to bare magnet URIs in the body.
    Dedupes by info-hash within and across items (first wins).
    """
    out: list[TorrentResult] = []
    seen: set[str] = set()
    for blob in _item_blobs(xml_text):
        title = _title_from_blob(blob)
        magnets: list[str] = []
        for m in _MAGNET_HREF.finditer(blob):
            magnets.append(unescape_entities(m.group(1)))
        if not magnets:
            for m in _MAGNET_BARE.finditer(blob):
                magnets.append(unescape_entities(m.group(1)))
        for magnet in magnets:
            try:
                parsed = parse_magnet(magnet)
                info_hash = normalize_info_hash(str(parsed["info_hash"]))
            except ValueError:
                continue
            key = info_hash.lower()
            if key in seen:
                continue
            seen.add(key)
            # Prefer display name from magnet dn when present.
            name = str(parsed.get("name") or title)
            out.append(
                TorrentResult(
                    name=name,
                    info_hash=info_hash,
                    size_bytes=None,
                    seeders=None,
                    leechers=None,
                    source=source,
                    magnet=magnet if magnet.lower().startswith("magnet:") else magnet,
                    category=category,
                )
            )
    return out


def parse_rss_or_raise(xml_text: str, *, invalid_message: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(invalid_message) from exc


# Re-export for callers that want a typed helper name.
RssMapper = Callable[[str], list[TorrentResult]]
