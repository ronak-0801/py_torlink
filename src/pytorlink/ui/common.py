"""Shared TUI chrome: theme, CSS, and table helpers used by torrent and HTTP apps."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.text import Text
from textual.theme import Theme

from pytorlink.download.types import DownloadProgress, DownloadState

TORLINK_THEME = Theme(
    name="torlink",
    dark=True,
    background="#120c1c",
    foreground="#f3eefc",
    primary="#8b5cf6",
    secondary="#6d28d9",
    accent="#c4b5fd",
    warning="#e879f9",
    error="#fb7185",
    success="#6ee7b7",
    surface="#1a1326",
    panel="#21182f",
    boost="#2a2038",
    variables={"text-muted": "#9b8fb0"},
)

SHARED_CSS = """
    Screen {
        background: $background;
        layout: vertical;
    }
    Header {
        background: $panel;
        text-style: bold;
        dock: top;
    }
    #chrome {
        height: auto;
        padding: 0 1;
        background: $background;
    }
    #banner {
        height: auto;
        min-height: 1;
        margin: 1 0 0 0;
        padding: 0 2;
        color: $accent;
        background: $boost;
        text-style: italic;
        border: round $primary 30%;
    }
    #banner.magnet {
        color: #f5d0fe;
        background: #3b2248;
        text-style: bold italic;
        border: round #c084fc 60%;
    }
    #search {
        margin: 1 0 0 0;
        background: $surface;
        border: tall $primary 35%;
        height: 3;
        padding: 0 1;
    }
    #search:focus {
        border: tall $accent;
    }
    #status {
        height: 1;
        margin: 0 0 0 0;
        color: $text-muted;
        padding: 0 2;
    }
    #status.searching {
        color: $accent;
        text-style: italic;
    }
    #status.error {
        color: $error;
    }
    #downloads-summary {
        height: 1;
        margin: 0 0 1 0;
        padding: 0 2;
        color: $accent;
        text-style: bold;
        background: $boost;
        border: round $secondary 25%;
    }
    #tabs {
        height: 1fr;
        padding: 0 1 0 1;
    }
    TabbedContent > ContentSwitcher {
        height: 1fr;
    }
    TabPane {
        height: 1fr;
        padding: 0 0 0 0;
    }
    #results-pane, #downloads-pane {
        height: 1fr;
        background: $surface;
        padding: 0;
        border: round $primary 40%;
    }
    #results-pane {
        border: round $accent 45%;
    }
    #downloads-pane {
        border: round $secondary 45%;
    }
    #results-pane:focus-within, #downloads-pane:focus-within {
        border: round $accent;
    }
    #selection-scroll {
        height: auto;
        min-height: 1;
        max-height: 3;
        margin: 1 0 0 0;
        background: $boost;
        border: round $primary 25%;
        padding: 0 1;
    }
    #selection-detail {
        height: auto;
        min-height: 1;
        width: auto;
        color: $accent;
        padding: 0 1;
        text-style: bold;
    }
    .pane-empty {
        height: 5;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
        padding: 1 2;
    }
    .pane-empty.hidden {
        display: none;
        height: 0;
    }
    DataTable {
        height: 1fr;
        background: transparent;
        scrollbar-color: $primary 45%;
        scrollbar-background: $surface;
    }
    DataTable > .datatable--header {
        text-style: bold;
        color: $accent;
        background: $boost;
        text-align: left;
    }
    DataTable > .datatable--cursor {
        background: $primary 35%;
        color: $foreground;
        text-style: bold;
    }
    DataTable > .datatable--hover {
        background: $boost;
    }
    DataTable > .datatable--odd-row {
        background: $surface;
    }
    DataTable > .datatable--even-row {
        background: $panel 35%;
    }
    #help-panel {
        height: auto;
        max-height: 45%;
        border: round $warning 45%;
        background: $panel;
        padding: 0 2 1 2;
        margin: 0 1 1 1;
        display: none;
        color: $foreground;
    }
    #help-panel.visible {
        display: block;
    }
    #source-picker {
        height: auto;
        max-height: 50%;
        border: round $accent 50%;
        background: $panel;
        padding: 0 2 1 2;
        margin: 0 1 1 1;
        display: none;
        color: $foreground;
    }
    #source-picker.visible {
        display: block;
    }
    #source-chips {
        height: auto;
        margin: 0 0 0 0;
        padding: 0 2;
        color: $text-muted;
    }
    Footer {
        background: $panel;
    }
    Tabs {
        background: $panel;
        padding: 0 1;
    }
    Tab {
        color: $text-muted;
        padding: 0 2;
    }
    Tab.--highlight {
        color: $accent;
        text-style: bold;
    }
    Underline > .underline--bar {
        background: $primary;
        color: $accent;
    }
"""

_STATE_STYLE = {
    DownloadState.DOWNLOADING: "#c4b5fd",
    DownloadState.PAUSED: "#a89bb8 italic",
    DownloadState.SEEDING: "#6ee7b7",
    DownloadState.DONE: "#6ee7b7",
    DownloadState.ERROR: "#fb7185 bold",
    DownloadState.QUEUED: "#93c5fd",
    DownloadState.MAGNET_ONLY: "#e879f9 italic",
    DownloadState.REMOVED: "#6b7280 dim",
}

NAME_COL_WIDTH = 64
DOWNLOAD_NAME_COL_WIDTH = 48


def name_cell(name: str, width: int = NAME_COL_WIDTH) -> str:
    """Truncate a display name to fit a table column (ellipsis if needed)."""
    if width <= 0:
        return ""
    if len(name) <= width:
        return name
    if width == 1:
        return "…"
    return name[: width - 1] + "…"


def state_cell(state: DownloadState) -> Text:
    label = {
        DownloadState.MAGNET_ONLY: "magnet only",
        DownloadState.SEEDING: "seeding",
        DownloadState.DOWNLOADING: "downloading",
        DownloadState.PAUSED: "paused",
        DownloadState.QUEUED: "queued",
        DownloadState.DONE: "done",
        DownloadState.ERROR: "error",
        DownloadState.REMOVED: "removed",
    }.get(state, state.value)
    return Text(label, style=_STATE_STYLE.get(state, ""))


def progress_cell(progress: DownloadProgress) -> Text:
    pct = max(0.0, min(1.0, progress.progress))
    width = 10
    filled = int(round(pct * width))
    bar = "━" * filled + "─" * (width - filled)
    if progress.state == DownloadState.MAGNET_ONLY:
        label = "──────────  —"
    else:
        label = f"{bar} {pct * 100:5.1f}%"
    return Text(label, style=_STATE_STYLE.get(progress.state, ""))


def summarize_download_counts(items: Sequence[Any]) -> str:
    """Human summary: "2 downloading · 3 seeding · 1 paused"."""
    downloading = seeding = paused = queued = other = 0
    for h in items:
        st = h.progress.state
        if st == DownloadState.DOWNLOADING:
            downloading += 1
        elif st in (DownloadState.SEEDING, DownloadState.DONE):
            seeding += 1
        elif st == DownloadState.PAUSED:
            paused += 1
        elif st == DownloadState.QUEUED:
            queued += 1
        elif st not in (DownloadState.REMOVED,):
            other += 1
    parts: list[str] = []
    if downloading:
        parts.append(f"{downloading} downloading")
    if seeding:
        parts.append(f"{seeding} seeding")
    if paused:
        parts.append(f"{paused} paused")
    if queued:
        parts.append(f"{queued} queued")
    if other:
        parts.append(f"{other} other")
    if not parts:
        return "0 active"
    return " · ".join(parts)


def row_key_for(info_hash: str, used: set[str], index: int) -> str:
    """Stable unique DataTable row key; avoid collisions aborting fill."""
    base = (info_hash or "").strip().lower() or f"row-{index}"
    key = base
    n = 1
    while key in used:
        key = f"{base}#{n}"
        n += 1
    used.add(key)
    return key


def table_row_keys(table: Any) -> list[str]:
    """Current DataTable row keys as strings, in display order."""
    try:
        return [str(getattr(k, "value", k)) for k in table.rows]
    except Exception:
        return []


def sync_download_rows(
    table: Any,
    items: Sequence[Any],
    *,
    format_rate,
    name_width: int = DOWNLOAD_NAME_COL_WIDTH,
) -> None:
    """Refresh download rows without yanking the cursor when the set is unchanged.

    A full clear()+rebuild every poll tick resets Textual's cursor to row 0, which
    feels like the highlight jumping to the top while arrow-navigating. When the
    queue ids (and order) match the table, only Status / Progress / Speed cells
    are updated in place.
    """
    used: set[str] = set()
    wanted_keys = [row_key_for(h.id, used, i) for i, h in enumerate(items)]
    current = table_row_keys(table)

    if current == wanted_keys and len(current) == len(items):
        for handle, key in zip(items, wanted_keys):
            try:
                table.update_cell(key, "status", state_cell(handle.progress.state))
                table.update_cell(key, "progress", progress_cell(handle.progress))
                table.update_cell(key, "speed", format_rate(handle.progress.download_rate))
            except Exception:
                continue
        return

    prev_key: str | None = None
    prev_row = 0
    try:
        if table.row_count:
            prev_row = max(0, int(table.cursor_row))
            row_key = table.coordinate_to_key(table.cursor_coordinate).row_key
            prev_key = str(getattr(row_key, "value", row_key))
    except Exception:
        prev_key = None

    table.clear()
    used = set()
    for i, handle in enumerate(items):
        key = row_key_for(handle.id, used, i)
        try:
            table.add_row(
                name_cell(handle.name, name_width),
                state_cell(handle.progress.state),
                progress_cell(handle.progress),
                format_rate(handle.progress.download_rate),
                key=key,
            )
        except Exception:
            continue

    if not items:
        return
    restore: int | None = None
    if prev_key:
        try:
            restore = table.get_row_index(prev_key)
        except Exception:
            restore = None
    if restore is None:
        restore = min(prev_row, table.row_count - 1)
    try:
        table.move_cursor(row=restore, scroll=False)
    except Exception:
        pass
