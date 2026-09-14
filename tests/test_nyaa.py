"""Nyaa RSS fixture parsing and HTML rejection."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pytorlink.sources.nyaa import NyaaSource, rss_xml_to_results

FIXTURE = Path(__file__).parent / "fixtures" / "nyaa_sample.xml"


def test_nyaa_rss_fixture_to_results():
    xml_text = FIXTURE.read_text(encoding="utf-8")
    results = rss_xml_to_results(xml_text)
    assert len(results) == 2
    assert results[0].info_hash == "a" * 40
    assert results[0].seeders == 42
    assert results[0].size_bytes is not None
    assert results[0].size_bytes > 0
    assert results[1].info_hash == "b" * 40
    assert results[1].seeders == 7
    assert all(r.magnet.startswith("magnet:?") for r in results)


def test_nyaa_invalid_rss_wrapped():
    with pytest.raises(RuntimeError, match="Nyaa: invalid RSS"):
        rss_xml_to_results("<not-xml")


@pytest.mark.asyncio
async def test_nyaa_rejects_html_body():
    html = "<!DOCTYPE html><html><body>cf</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        src = NyaaSource(client=client)
        with pytest.raises(RuntimeError, match="blocked or non-RSS"):
            await src.search("test")
