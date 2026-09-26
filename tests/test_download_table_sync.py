"""Tests for download-table sync (cursor stability)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from pytorlink.download.types import DownloadProgress, DownloadState, format_rate
from pytorlink.ui.common import sync_download_rows, table_row_keys


@dataclass
class _FakeHandle:
    id: str
    name: str
    progress: DownloadProgress = field(
        default_factory=lambda: DownloadProgress(DownloadState.QUEUED)
    )


class _TableApp(App[None]):
    def compose(self) -> ComposeResult:
        yield DataTable(id="downloads")

    def on_mount(self) -> None:
        table = self.query_one("#downloads", DataTable)
        table.add_column("Name", key="name")
        table.add_column("Status", key="status")
        table.add_column("Progress", key="progress")
        table.add_column("Speed", key="speed")


@pytest.mark.asyncio
async def test_sync_download_rows_updates_in_place_without_resetting_cursor() -> None:
    items = [
        _FakeHandle("aaa", "one"),
        _FakeHandle("bbb", "two"),
        _FakeHandle("ccc", "three"),
    ]
    async with _TableApp().run_test() as pilot:
        table = pilot.app.query_one("#downloads", DataTable)
        sync_download_rows(table, items, format_rate=format_rate)
        table.move_cursor(row=2)
        assert table.cursor_row == 2

        items[2].progress = DownloadProgress(DownloadState.DOWNLOADING, progress=0.4)
        sync_download_rows(table, items, format_rate=format_rate)

        assert table.cursor_row == 2
        assert table_row_keys(table) == ["aaa", "bbb", "ccc"]
        # Progress cell was rewritten for the highlighted row.
        cells = table.get_row_at(2)
        assert "40.0%" in str(cells[2])


@pytest.mark.asyncio
async def test_sync_download_rows_rebuilds_when_items_change() -> None:
    async with _TableApp().run_test() as pilot:
        table = pilot.app.query_one("#downloads", DataTable)
        sync_download_rows(
            table,
            [_FakeHandle("aaa", "one"), _FakeHandle("bbb", "two")],
            format_rate=format_rate,
        )
        table.move_cursor(row=1)
        sync_download_rows(
            table,
            [_FakeHandle("aaa", "one"), _FakeHandle("ccc", "three")],
            format_rate=format_rate,
        )
        assert table_row_keys(table) == ["aaa", "ccc"]
        # Previous key gone → fall back to same row index (clamped).
        assert table.cursor_row == 1
