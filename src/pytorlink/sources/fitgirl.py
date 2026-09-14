"""FitGirl Repacks via WordPress RSS search."""

from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from pytorlink.sources.http import make_client
from pytorlink.sources.rss import rss_magnets_to_results
from pytorlink.sources.types import SourceId, TorrentResult

FITGIRL_HOME = "https://fitgirl-repacks.site"


def fitgirl_rss_to_results(xml_text: str, *, source: SourceId = SourceId.FITGIRL) -> list[TorrentResult]:
    """Parse FitGirl WordPress RSS into torrent rows."""
    return rss_magnets_to_results(xml_text, source=source, category="Games")


class FitGirlSource:
    id = SourceId.FITGIRL
    label = "FitGirl"

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
        home: str = FITGIRL_HOME,
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.home = home.rstrip("/")

    def _feed_url(self, query: str) -> str:
        q = query.strip()
        if q:
            return f"{self.home}/?s={quote_plus(q)}&feed=rss2"
        return f"{self.home}/feed/"

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        client, owns = make_client(
            timeout=self.timeout,
            headers={"Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8"},
            client=self._client,
        )
        try:
            resp = await client.get(self._feed_url(query))
            resp.raise_for_status()
            body = resp.text
            stripped = body.lstrip()
            ct = (resp.headers.get("content-type") or "").lower()
            if ("html" in ct and "xml" not in ct) or stripped.lower().startswith("<!doctype html"):
                # Still try if it looks like RSS despite content-type.
                if "<rss" not in body[:500].lower() and "<rdf" not in body[:500].lower():
                    raise RuntimeError("FitGirl: blocked or non-RSS response (HTML)")
            return fitgirl_rss_to_results(body)[:limit]
        finally:
            if owns:
                await client.aclose()
