"""Unit tests for TUI display helpers."""

from __future__ import annotations

from pytorlink.sources.types import SourceId, TorrentResult
from pytorlink.ui.app import _name_cell, _row_key_for, format_selection_detail


def test_name_cell_no_truncate() -> None:
    assert _name_cell("short", 10) == "short"


def test_name_cell_truncate() -> None:
    assert _name_cell("abcdefghij", 5) == "abcd…"
    assert _name_cell("ab", 1) == "…"
    assert _name_cell("anything", 0) == ""


def test_format_selection_detail_empty() -> None:
    assert format_selection_detail(None) == "Selected: —"


def test_format_selection_detail_full_name() -> None:
    long_name = "Very Long Torrent Name That Must Appear In Full On The Detail Strip"
    result = TorrentResult(
        name=long_name,
        info_hash="a" * 40,
        size_bytes=1024 * 1024 * 700,
        seeders=42,
        source=SourceId.YTS,
        magnet="magnet:?xt=urn:btih:" + "a" * 40,
    )
    detail = format_selection_detail(result)
    assert detail.startswith(f"Selected: {long_name}")
    assert "700.0 MB" in detail or "MB" in detail
    assert "42 seeds" in detail
    assert "YTS" in detail
    # Full name is present (not truncated with ellipsis mid-name)
    assert "…" not in detail.split(" · ")[0]


def test_row_key_for_unique_on_collision() -> None:
    used: set[str] = set()
    k1 = _row_key_for("abc", used, 0)
    k2 = _row_key_for("abc", used, 1)
    k3 = _row_key_for("", used, 2)
    assert k1 == "abc"
    assert k2 == "abc#1"
    assert k3.startswith("row-")
    assert len({k1, k2, k3}) == 3
