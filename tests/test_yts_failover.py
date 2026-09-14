"""YTS multi-host failover behavior (mocked httpx)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from pytorlink.sources.yts import YtsSource

FIXTURE = Path(__file__).parent / "fixtures" / "yts_sample.json"


@pytest.fixture(autouse=True)
def _reset_last_host():
    YtsSource._last_working_host = None
    yield
    YtsSource._last_working_host = None


@pytest.mark.asyncio
async def test_yts_failover_skips_5xx_and_remembers_host():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        calls.append(host)
        if host == "yts.mx":
            return httpx.Response(500, text="boom")
        if host == "yts.lt":
            return httpx.Response(200, json=payload)
        return httpx.Response(503, text="nope")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        src = YtsSource(hosts=("yts.mx", "yts.lt", "yts.am"), client=client)
        results = await src.search("example")
    assert len(results) == 2
    assert YtsSource._last_working_host == "yts.lt"
    # First host 5xx is retried once before rotating.
    assert calls.count("yts.mx") == 2
    assert "yts.lt" in calls

    calls.clear()

    async with httpx.AsyncClient(transport=transport) as client:
        src = YtsSource(hosts=("yts.mx", "yts.lt", "yts.am"), client=client)
        await src.search("example")
    # Last working host tried first.
    assert calls[0] == "yts.lt"


@pytest.mark.asyncio
async def test_yts_all_mirrors_failed_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="err")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        src = YtsSource(hosts=("yts.rs",), client=client)
        with pytest.raises(RuntimeError) as ei:
            await src.search("x")
    msg = str(ei.value)
    assert msg.startswith("YTS: all mirrors failed")
    assert "500 from yts.rs" in msg
