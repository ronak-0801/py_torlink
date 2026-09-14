"""Textual TUI for pytorlink."""

from __future__ import annotations

from pathlib import Path
import time

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalScroll, Vertical
from textual.theme import Theme
from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane

from pytorlink.config import load_enabled_source_ids, save_enabled_source_ids
from pytorlink.download.queue import DownloadQueue
from pytorlink.download.types import DownloadHandle, DownloadProgress, DownloadState, format_rate
from pytorlink.sources.magnet import looks_like_info_hash, looks_like_magnet
from pytorlink.sources.registry import (
    DEFAULT_SOURCE_IDS,
    DISABLED_BY_DEFAULT,
    SOURCES,
    iter_search,
    sources_for_ids,
)
from pytorlink.sources.types import SourceId, TorrentResult, dedupe_by_info_hash, sort_by_seeders, source_label

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

HELP_TEXT = """\
[b]Layout[/b]
  Header, backend banner, search box, status, and download counts stay
  visible on every tab. Tabs only hold results / downloads tables.

[b]Search[/b]
  Enter          Run search (or queue magnet / info-hash from the input)
  Ctrl+r         Retry the last search query
  s              Open / close source picker (multi-select)
  ↑ / ↓ / click  Highlight a result (does [b]not[/b] download)
  d              Download the highlighted result
  1 or [         Stay on / switch to Search
  2 or ]         Switch to Downloads
  Tab            Move focus between search, tables, and tabs

[b]Sources[/b]
  Default: all sources ON except BitTorrented (often 402 / paywalled).
  Press [b]s[/b], then digit keys to toggle; Enter or s to close.
  Enabled set is saved under ~/.config/pytorlink/sources.json.
  EXT (ext.to) — HTML search; soft-fails on Cloudflare; mirrors: ext.to, extto.com.

[b]Downloads[/b]
  ↑ / ↓ / click  Highlight a download
  p              Pause highlighted download
  r              Resume highlighted download
  x / Delete     Remove from queue/session (files kept on disk)

[b]Global[/b]
  ?              Toggle this help
  q              Quit

[b]Backends[/b]
  qBittorrent if QBIT_HOST is set, else libtorrent if installed,
  else magnet-only (writes a .magnet file — no real download).

[b]Remove[/b]
  x drops the torrent from the client session but [b]keeps files[/b].

[b]Legal[/b]
  Only download content you have the rights to obtain.
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


def _name_cell(name: str, width: int = NAME_COL_WIDTH) -> str:
    """Truncate a display name to fit a table column (ellipsis if needed)."""
    if width <= 0:
        return ""
    if len(name) <= width:
        return name
    if width == 1:
        return "…"
    return name[: width - 1] + "…"


def format_selection_detail(result: TorrentResult | None) -> str:
    """One-line selection strip: full name plus size, seeds, and source."""
    if result is None:
        return "Selected: —"
    return (
        f"Selected: {result.name} · {result.size_label} · "
        f"{result.seeders_label} seeds · {result.source_label}"
    )


def _state_cell(state: DownloadState) -> Text:
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


def _progress_cell(progress: DownloadProgress) -> Text:
    pct = max(0.0, min(1.0, progress.progress))
    width = 10
    filled = int(round(pct * width))
    bar = "━" * filled + "─" * (width - filled)
    if progress.state == DownloadState.MAGNET_ONLY:
        label = "──────────  —"
    else:
        label = f"{bar} {pct * 100:5.1f}%"
    return Text(label, style=_STATE_STYLE.get(progress.state, ""))


def summarize_download_counts(items: list[DownloadHandle]) -> str:
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


def _row_key_for(info_hash: str, used: set[str], index: int) -> str:
    """Stable unique DataTable row key; avoid collisions aborting fill."""
    base = (info_hash or "").strip().lower() or f"row-{index}"
    key = base
    n = 1
    while key in used:
        key = f"{base}#{n}"
        n += 1
    used.add(key)
    return key


class PytorlinkApp(App[None]):
    """Search torrents and enqueue downloads."""

    CSS = """
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

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "toggle_help", "Help"),
        Binding("s", "toggle_source_picker", "Sources"),
        Binding("d", "download_selected", "Download"),
        Binding("p", "pause_selected", "Pause"),
        Binding("r", "resume_selected", "Resume"),
        Binding("x", "remove_selected", "Remove"),
        Binding("delete", "remove_selected", "Remove", show=False),
        Binding("ctrl+r", "retry_search", "Retry"),
        Binding("1", "digit_or_search_tab", "Search", show=False),
        Binding("2", "digit_or_downloads_tab", "Downloads", show=False),
        Binding("3", "toggle_source_digit('3')", "Src3", show=False),
        Binding("4", "toggle_source_digit('4')", "Src4", show=False),
        Binding("5", "toggle_source_digit('5')", "Src5", show=False),
        Binding("6", "toggle_source_digit('6')", "Src6", show=False),
        Binding("7", "toggle_source_digit('7')", "Src7", show=False),
        Binding("8", "toggle_source_digit('8')", "Src8", show=False),
        Binding("9", "toggle_source_digit('9')", "Src9", show=False),
        Binding("0", "toggle_source_digit('0')", "Src0", show=False),
        Binding("left_square_bracket", "show_search_tab", "Search tab"),
        Binding("right_square_bracket", "show_downloads_tab", "Downloads tab"),
        Binding("escape", "close_overlays", "Close", show=False),
    ]

    TITLE = "pytorlink"
    SUB_TITLE = "search · download"

    def __init__(self, download_dir: Path | None = None) -> None:
        super().__init__()
        self.queue = DownloadQueue(save_path=download_dir)
        self._results: list[TorrentResult] = []
        self._help_visible = False
        self._source_picker_visible = False
        self._active_tab = "search-tab"
        self._last_query: str = ""
        self._searching = False
        self._enabled_sources: set[SourceId] = load_enabled_source_ids(set(DEFAULT_SOURCE_IDS))
        known = {s.id for s in SOURCES}
        self._enabled_sources = {s for s in self._enabled_sources if s in known} or set(DEFAULT_SOURCE_IDS)
        self.register_theme(TORLINK_THEME)
        self.theme = "torlink"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="chrome"):
            yield Static(self.queue.notice, id="banner", markup=True)
            yield Input(placeholder="Search… or paste magnet / info-hash  ·  Enter to search  ·  s sources", id="search")
            yield Static(self._chips_text(), id="source-chips", markup=True)
            yield Static("Ready — type a query and press Enter", id="status")
            yield Static("0 active", id="downloads-summary")
        with TabbedContent(initial="search-tab", id="tabs"):
            with TabPane("Search", id="search-tab"):
                with Vertical(id="results-pane"):
                    yield Static(
                        "Type a query above and press Enter to search",
                        id="results-empty",
                        classes="pane-empty",
                    )
                    yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
                with HorizontalScroll(id="selection-scroll"):
                    yield Static(format_selection_detail(None), id="selection-detail")
            with TabPane("Downloads", id="downloads-tab"):
                with Vertical(id="downloads-pane"):
                    yield Static(
                        "No downloads yet — press d on a search result",
                        id="downloads-empty",
                        classes="pane-empty",
                    )
                    yield DataTable(id="downloads", cursor_type="row", zebra_stripes=True)
        yield Static(HELP_TEXT, id="help-panel", markup=True)
        yield Static(self._source_picker_text(), id="source-picker", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"{self.queue.backend.name}  ·  0 active  ·  {self.queue.save_path}"
        banner = self.query_one("#banner", Static)
        if self.queue.backend.name == "magnet" or "magnet-only" in self.queue.notice.lower():
            banner.add_class("magnet")
        results_pane = self.query_one("#results-pane", Vertical)
        results_pane.border_title = "Results"
        results_pane.border_subtitle = "↑↓ select · d download"
        downloads_pane = self.query_one("#downloads-pane", Vertical)
        downloads_pane.border_title = "Downloads"
        downloads_pane.border_subtitle = "p pause · r resume · x keep files"

        results = self.query_one("#results", DataTable)
        results.add_column("Name", width=NAME_COL_WIDTH, key="name")
        results.add_column("Size", width=10, key="size")
        results.add_column("Seeds", width=7, key="seeds")
        results.add_column("Source", width=14, key="source")

        downloads = self.query_one("#downloads", DataTable)
        downloads.add_column("Name", width=DOWNLOAD_NAME_COL_WIDTH, key="name")
        downloads.add_column("Status", width=12, key="status")
        downloads.add_column("Progress", width=18, key="progress")
        downloads.add_column("Speed", width=10, key="speed")

        self.query_one("#search", Input).focus()
        self._refresh_source_ui()
        n = len(self._enabled_sources)
        self._set_status(f"{self.queue.notice}  ·  {n} sources enabled")
        self.set_interval(1.0, self._tick_downloads)
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        on_search = self._active_tab == "search-tab"
        on_downloads = self._active_tab == "downloads-tab"
        if action == "download_selected":
            return on_search
        if action in {"pause_selected", "resume_selected", "remove_selected"}:
            return on_downloads
        if action == "retry_search":
            return bool(self._last_query) and not self._searching
        return True

    def _set_status(self, text: str, *, searching: bool = False, error: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.set_class(searching, "searching")
        status.set_class(error, "error")
        status.update(text)

    def _update_selection_detail(self, result: TorrentResult | None = None) -> None:
        if result is None:
            result = self._highlighted_result()
        self.query_one("#selection-detail", Static).update(format_selection_detail(result))

    def _highlighted_result(self) -> TorrentResult | None:
        table = self.query_one("#results", DataTable)
        if not self._results or table.row_count == 0:
            return None
        idx = table.cursor_row
        if idx < 0 or idx >= len(self._results):
            return None
        return self._results[idx]

    def _enabled_source_list(self):
        return sources_for_ids(self._enabled_sources)

    def _chips_text(self) -> str:
        parts: list[str] = []
        for src in SOURCES:
            on = src.id in self._enabled_sources
            mark = "●" if on else "○"
            note = " (opt)" if src.id in DISABLED_BY_DEFAULT else ""
            style = "bold $accent" if on else "dim"
            parts.append(f"[{style}]{mark} {src.label}{note}[/]")
        return "Sources: " + "  ".join(parts) + "   [dim](s to edit)[/]"

    def _source_picker_text(self) -> str:
        lines = [
            "[b]Source picker[/b]  —  digit toggle · s/Esc close · BitTorrented optional/paywalled",
            "",
        ]
        for i, src in enumerate(SOURCES, start=1):
            key = str(i % 10) if i <= 10 else "?"
            on = src.id in self._enabled_sources
            box = "[x]" if on else "[ ]"
            extra = ""
            if src.id == SourceId.BITTORRENTED:
                extra = "  [dim](disabled by default — often 402 Payment Required)[/]"
            elif src.id == SourceId.EXT_TO:
                extra = "  [dim](ext.to / extto.com HTML)[/]"
            lines.append(
                f"  [b]{key}[/b]  {box}  {src.label}  [dim]({src.id.value})[/]{extra}"
            )
        lines.append("")
        lines.append(f"[dim]Active: {len(self._enabled_sources)} / {len(SOURCES)}[/]")
        return "\n".join(lines)

    def _refresh_source_ui(self) -> None:
        try:
            self.query_one("#source-chips", Static).update(self._chips_text())
        except Exception:
            pass
        try:
            self.query_one("#source-picker", Static).update(self._source_picker_text())
        except Exception:
            pass

    def _persist_sources(self) -> None:
        save_enabled_source_ids(self._enabled_sources)

    def _toggle_source_at(self, index: int) -> None:
        if index < 1 or index > len(SOURCES):
            return
        src = SOURCES[index - 1]
        if src.id in self._enabled_sources:
            if len(self._enabled_sources) <= 1:
                self._set_status("Keep at least one source enabled", error=True)
                return
            self._enabled_sources.discard(src.id)
        else:
            self._enabled_sources.add(src.id)
        self._persist_sources()
        self._refresh_source_ui()
        state = "ON" if src.id in self._enabled_sources else "OFF"
        self._set_status(
            f"Sources: {len(self._enabled_sources)} enabled · {source_label(src.id)} {state}"
        )

    def action_toggle_help(self) -> None:
        if self._source_picker_visible:
            self._source_picker_visible = False
            self.query_one("#source-picker", Static).remove_class("visible")
        panel = self.query_one("#help-panel", Static)
        self._help_visible = not self._help_visible
        panel.set_class(self._help_visible, "visible")

    def action_toggle_source_picker(self) -> None:
        if self._help_visible:
            self._help_visible = False
            self.query_one("#help-panel", Static).remove_class("visible")
        self._source_picker_visible = not self._source_picker_visible
        panel = self.query_one("#source-picker", Static)
        panel.set_class(self._source_picker_visible, "visible")
        if self._source_picker_visible:
            self._refresh_source_ui()
            self._set_status("Source picker — press digit to toggle, s/Esc to close")

    def action_close_overlays(self) -> None:
        if self._help_visible:
            self._help_visible = False
            self.query_one("#help-panel", Static).remove_class("visible")
        if self._source_picker_visible:
            self._source_picker_visible = False
            self.query_one("#source-picker", Static).remove_class("visible")

    def action_digit_or_search_tab(self) -> None:
        if self._source_picker_visible:
            self._toggle_source_at(1)
            return
        self.action_show_search_tab()

    def action_digit_or_downloads_tab(self) -> None:
        if self._source_picker_visible:
            self._toggle_source_at(2)
            return
        self.action_show_downloads_tab()

    def action_toggle_source_digit(self, digit: str) -> None:
        if not self._source_picker_visible:
            return
        if digit == "0":
            self._toggle_source_at(10)
            return
        try:
            self._toggle_source_at(int(digit))
        except ValueError:
            return

    def action_show_search_tab(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "search-tab"
        self.query_one("#search", Input).focus()

    def action_show_downloads_tab(self) -> None:
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.active = "downloads-tab"
        downloads = self.query_one("#downloads", DataTable)
        if downloads.row_count:
            downloads.focus()

    def action_retry_search(self) -> None:
        query = self._last_query.strip()
        if not query or self._searching:
            return
        search = self.query_one("#search", Input)
        search.value = query
        self._begin_search(query)

    @on(TabbedContent.TabActivated, "#tabs")
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id if event.pane is not None else "search-tab"
        self._active_tab = pane_id or "search-tab"
        self.refresh_bindings()

    @on(Input.Submitted, "#search")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        if not text:
            self._set_status("Enter a search query, magnet, or info-hash", error=True)
            return
        if looks_like_magnet(text) or looks_like_info_hash(text):
            handle = self.queue.add_from_text(text)
            if handle:
                self._refresh_downloads()
                msg = f"Queued: {handle.name} via {self.queue.backend.name}"
                self._set_status(msg)
                self.notify(msg, title="Download", timeout=3.0)
            event.input.value = ""
            return
        self._begin_search(text)

    def _begin_search(self, query: str) -> None:
        """Kick off search with immediate UI feedback (outside TabbedContent)."""
        self._last_query = query
        n_sources = len(self._enabled_sources)
        self._set_status(f"Searching '{query}'… ({n_sources} sources)", searching=True)
        # Clear previous results / show loading empty state immediately
        table = self.query_one("#results", DataTable)
        table.clear()
        self._results = []
        empty = self.query_one("#results-empty", Static)
        empty.update(f"Searching '{query}'…")
        empty.remove_class("hidden")
        self._update_selection_detail(None)
        # Ensure Search tab is visible so results appear where expected
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            if tabs.active != "search-tab":
                tabs.active = "search-tab"
        except Exception:
            pass
        self.run_search(query)

    def _fill_results_table(self, results: list[TorrentResult]) -> None:
        """Replace results table rows; preserve cursor by info-hash when possible."""
        table = self.query_one("#results", DataTable)
        prev_hash: str | None = None
        if self._results and table.row_count:
            idx = table.cursor_row
            if 0 <= idx < len(self._results):
                prev_hash = (self._results[idx].info_hash or "").strip().lower() or None

        self._results = results
        table.clear()
        used_keys: set[str] = set()
        restore_row: int | None = None
        for i, r in enumerate(results):
            key = _row_key_for(r.info_hash, used_keys, i)
            try:
                table.add_row(
                    _name_cell(r.name, NAME_COL_WIDTH),
                    r.size_label,
                    r.seeders_label,
                    r.source_label,
                    key=key,
                )
            except Exception:
                continue
            if prev_hash and (r.info_hash or "").strip().lower() == prev_hash:
                restore_row = i

        empty = self.query_one("#results-empty", Static)
        if results:
            empty.add_class("hidden")
            if restore_row is not None:
                try:
                    table.move_cursor(row=restore_row)
                except Exception:
                    pass
            cur = self._highlighted_result() or results[0]
            self._update_selection_detail(cur)
        else:
            empty.remove_class("hidden")
            self._update_selection_detail(None)

    @work(exclusive=True)
    async def run_search(self, query: str) -> None:
        """Stream results as each source finishes; soft-fail timeouts."""
        self._searching = True
        self.refresh_bindings()
        active = self._enabled_source_list()
        n_sources = len(active)
        done = 0
        errors: list[str] = []
        merged: list[TorrentResult] = []
        last_ui = 0.0
        ui_throttle = 0.12  # ~120ms — avoid flicker on burst completions
        empty = self.query_one("#results-empty", Static)
        focused_once = False

        def _refresh_ui(*, force: bool = False) -> None:
            nonlocal last_ui, focused_once
            now = time.monotonic()
            if not force and (now - last_ui) < ui_throttle:
                return
            last_ui = now
            results = sort_by_seeders(dedupe_by_info_hash(list(merged)))
            self._fill_results_table(results)
            if results:
                empty.update("")
                empty.add_class("hidden")
                if not focused_once:
                    focused_once = True
                    try:
                        self.query_one("#results", DataTable).focus()
                    except Exception:
                        pass
            self._set_status(
                f"{len(results)} results · {done}/{n_sources} sources done",
                searching=True,
            )

        try:
            async for _label, batch, error in iter_search(query, sources=active):
                done += 1
                if error:
                    errors.append(error)
                if batch:
                    merged.extend(batch)
                _refresh_ui()
            _refresh_ui(force=True)
        except Exception as exc:
            self._results = []
            table = self.query_one("#results", DataTable)
            table.clear()
            empty.update("Search failed")
            empty.remove_class("hidden")
            self._update_selection_detail(None)
            self._set_status(f"Search error: {exc}", error=True)
            self.query_one("#search", Input).focus()
            return
        finally:
            self._searching = False
            self.refresh_bindings()

        results = self._results
        if results:
            msg = f"{len(results)} result(s) · {done}/{n_sources} sources"
            if errors:
                msg += " · soft-fail: " + "; ".join(errors[:5])
            self._set_status(msg)
            try:
                self.query_one("#results", DataTable).focus()
            except Exception:
                pass
            cur = self._highlighted_result()
            self._update_selection_detail(cur if cur is not None else results[0])
        else:
            if errors:
                empty.update("No results (all sources failed)")
                msg = "No results (all sources failed: " + "; ".join(errors[:5]) + ")"
                self._set_status(msg, error=True)
            else:
                empty.update("No results")
                self._set_status("No results")
            empty.remove_class("hidden")
            self._update_selection_detail(None)
            self.query_one("#search", Input).focus()

    def action_download_selected(self) -> None:
        if self._active_tab != "search-tab":
            return
        self._download_cursor_row()

    @on(DataTable.RowHighlighted, "#results")
    def on_results_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Click / arrows only select — never download.
        idx = event.cursor_row
        if 0 <= idx < len(self._results):
            self._update_selection_detail(self._results[idx])
        else:
            self._update_selection_detail(None)

    @on(DataTable.RowSelected, "#results")
    def on_results_selected(self, event: DataTable.RowSelected) -> None:
        # Enter on a result must NOT download; only refresh the detail strip.
        idx = event.cursor_row
        if 0 <= idx < len(self._results):
            self._update_selection_detail(self._results[idx])
        else:
            self._update_selection_detail(None)

    def _download_cursor_row(self) -> None:
        item = self._highlighted_result()
        if item is None:
            self._set_status("No result selected", error=True)
            return
        handle = self.queue.add_magnet(item.magnet, name=item.name)
        self._refresh_downloads()
        msg = f"Queued: {handle.name} ({self.queue.backend.name})"
        self._set_status(msg)
        self.notify(msg, title="Download", timeout=3.0)
        # Stay on Search tab (do not auto-focus downloads).

    def _selected_download(self) -> DownloadHandle | None:
        table = self.query_one("#downloads", DataTable)
        items = self.queue.items
        if not items or table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_key(table.cursor_coordinate).row_key
            key = str(getattr(row_key, "value", row_key))
        except Exception:
            idx = table.cursor_row
            if 0 <= idx < len(items):
                return items[idx]
            return None
        for h in items:
            if h.id == key:
                return h
        idx = table.cursor_row
        if 0 <= idx < len(items):
            return items[idx]
        return None

    def action_pause_selected(self) -> None:
        handle = self._selected_download()
        if handle is None:
            self._set_status("No download selected", error=True)
            return
        self.queue.pause(handle.id)
        self._refresh_downloads()
        self._set_status(f"Paused: {handle.name}")

    def action_resume_selected(self) -> None:
        handle = self._selected_download()
        if handle is None:
            self._set_status("No download selected", error=True)
            return
        self.queue.resume(handle.id)
        self._refresh_downloads()
        self._set_status(f"Resumed: {handle.name}")

    def action_remove_selected(self) -> None:
        handle = self._selected_download()
        if handle is None:
            self._set_status("No download selected", error=True)
            return
        self.queue.remove(handle.id, delete_files=False)
        self._refresh_downloads()
        self._set_status("Removed from queue; files kept")

    def _tick_downloads(self) -> None:
        if self.queue.items:
            self.queue.poll_all()
        self._refresh_downloads()

    def _refresh_downloads(self) -> None:
        table = self.query_one("#downloads", DataTable)
        empty = self.query_one("#downloads-empty", Static)
        prev_key: str | None = None
        try:
            if table.row_count:
                row_key = table.coordinate_to_key(table.cursor_coordinate).row_key
                prev_key = str(getattr(row_key, "value", row_key))
        except Exception:
            prev_key = None
        table.clear()
        items = self.queue.items
        empty.set_class(bool(items), "hidden")
        used_keys: set[str] = set()
        for i, h in enumerate(items):
            key = _row_key_for(h.id, used_keys, i)
            try:
                table.add_row(
                    _name_cell(h.name, DOWNLOAD_NAME_COL_WIDTH),
                    _state_cell(h.progress.state),
                    _progress_cell(h.progress),
                    format_rate(h.progress.download_rate),
                    key=key,
                )
            except Exception:
                continue
        if prev_key:
            try:
                table.move_cursor(row=table.get_row_index(prev_key))
            except Exception:
                pass
        summary = summarize_download_counts(items)
        self.query_one("#downloads-summary", Static).update(summary)
        pane = self.query_one("#downloads-pane", Vertical)
        total = len(items)
        pane.border_title = f"Downloads ({total})"
        pane.border_subtitle = f"{summary}  ·  p pause · r resume · x keep files"
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            pane_tab = tabs.get_pane("downloads-tab")
            pane_tab.label = f"Downloads — {summary}" if total else "Downloads"
        except Exception:
            pass
        # Header subtitle always shows quick counts (visible on either tab)
        self.sub_title = f"{self.queue.backend.name}  ·  {summary}  ·  {self.queue.save_path}"
