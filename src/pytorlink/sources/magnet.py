"""Magnet URI helpers and default public trackers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlparse

# Well-known public trackers used when building magnets from bare hashes.
DEFAULT_TRACKERS: tuple[str, ...] = (
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
)

_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
_HEX32_B32 = re.compile(r"^[2-7A-Za-z]{32}$")  # base32 info-hash (rare)


def normalize_info_hash(value: str) -> str:
    """Normalize a hex info-hash to lowercase 40-char hex.

    Accepts bare hex, ``urn:btih:...``, or magnet ``xt`` values.
    Base32 hashes are returned lowercased as-is (32 chars) for magnet use.
    """
    raw = value.strip()
    if raw.lower().startswith("urn:btih:"):
        raw = raw[9:]
    raw = raw.strip()
    if _HEX40.match(raw):
        return raw.lower()
    if _HEX32_B32.match(raw):
        return raw.upper()  # btih base32 conventionally upper
    raise ValueError(f"invalid info hash: {value!r}")


def build_magnet(
    info_hash: str,
    *,
    name: str | None = None,
    trackers: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Build a magnet URI from an info-hash and optional display name."""
    digest = normalize_info_hash(info_hash)
    xt = f"urn:btih:{digest}"
    parts = [f"magnet:?xt={xt}"]
    if name:
        parts.append(f"dn={quote(name, safe='')}")
    for tr in trackers if trackers is not None else DEFAULT_TRACKERS:
        parts.append(f"tr={quote(tr, safe='')}")
    return "&".join(parts)


def parse_magnet(uri: str) -> dict[str, object]:
    """Parse a magnet URI into info_hash, name, and trackers.

    Returns ``{"info_hash": str, "name": str | None, "trackers": list[str]}``.
    """
    text = uri.strip()
    if not text.lower().startswith("magnet:"):
        raise ValueError("not a magnet URI")
    # urlparse handles magnet:?xt=...
    parsed = urlparse(text)
    qs = parse_qs(parsed.query)
    xt_list = qs.get("xt") or []
    if not xt_list:
        raise ValueError("magnet missing xt")
    info_hash = None
    for xt in xt_list:
        lower = xt.lower()
        if lower.startswith("urn:btih:"):
            info_hash = normalize_info_hash(xt)
            break
    if info_hash is None:
        raise ValueError("magnet missing btih xt")
    name = None
    if qs.get("dn"):
        name = unquote(qs["dn"][0])
    trackers = [unquote(t) for t in qs.get("tr", [])]
    return {"info_hash": info_hash, "name": name, "trackers": trackers}


def looks_like_magnet(text: str) -> bool:
    return text.strip().lower().startswith("magnet:?")


def looks_like_info_hash(text: str) -> bool:
    raw = text.strip()
    return bool(_HEX40.match(raw) or _HEX32_B32.match(raw))
