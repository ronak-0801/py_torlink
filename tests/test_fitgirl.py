"""FitGirl RSS fixture parsing."""

from __future__ import annotations

from pathlib import Path

from pytorlink.sources.fitgirl import fitgirl_rss_to_results

FIXTURE = Path(__file__).parent / "fixtures" / "fitgirl_sample.xml"


def test_fitgirl_rss_extracts_unique_magnets():
    xml_text = FIXTURE.read_text(encoding="utf-8")
    results = fitgirl_rss_to_results(xml_text)
    assert len(results) == 2
    hashes = {r.info_hash for r in results}
    assert "e" * 40 in hashes
    assert "f" * 40 in hashes
    eg = next(r for r in results if r.info_hash == "e" * 40)
    assert "magnet:?" in eg.magnet
    assert "&" in eg.magnet  # entities unescaped
    assert "&#038;" not in eg.magnet
