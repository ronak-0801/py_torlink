"""Shared HTTP helpers for torrent index sources."""

from __future__ import annotations

import httpx

# Browser-ish UA used by indexers that gate empty/bot UAs.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def make_client(
    *,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[httpx.AsyncClient, bool]:
    """Return ``(client, owns_client)``. Reuses *client* when provided."""
    if client is not None:
        return client, False
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    return (
        httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=merged),
        True,
    )


def short_exc(exc: BaseException, *, max_len: int = 120) -> str:
    """One-line error reason suitable for soft-fail aggregation."""
    text = str(exc).strip().replace("\n", " ")
    if not text:
        text = type(exc).__name__
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text
