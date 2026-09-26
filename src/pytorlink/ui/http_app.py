"""Textual TUI for HTTP / direct downloads (separate from torrent mode)."""

from __future__ import annotations

from pathlib import Path
import time

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalScroll, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane

from pytorlink.download.http_backend import HttpDownloadHandle
from pytorlink.download.http_queue import HttpDownloadQueue
from pytorlink.download.types import format_rate
from pytorlink.httpdl.registry import (
    default_http_sources,
    resolve_http_result,
    search_http_all,
)
from pytorlink.httpdl.types import HttpFileResult, looks_like_http_url
from pytorlink.ui.common import (
    DOWNLOAD_NAME_COL_WIDTH,
    NAME_COL_WIDTH,
    SHARED_CSS,
    TORLINK_THEME,
    name_cell,
    row_key_for,
    summarize_download_counts,
    sync_download_rows,
)

HELP_TEXT = """\
[b]HTTP mode[/b]
  Direct file downloads. This is [b]not[/b] torrent search.

[b]Search[/b]
  Enter          Search all sources, or queue a pasted http(s) URL
  Ctrl+r         Retry the last search query
  ↑ / ↓ / click  Highlight a result (does [b]not[/b] download)
  d              Download the highlighted result
  1 or [         Search tab
  2 or ]         Downloads tab

[b]Downloads[/b]
  p              Pause highlighted download
  r              Resume highlighted download
  x / Delete     Remove from queue (files kept on disk)

[b]Global[/b]
  ?              Toggle this help
  q              Quit

[b]Sources[/b]
  Internet Archive · Wikimedia Commons · NASA — all public APIs.
  Each hosts only public-domain or openly licensed media.
  Paste any direct https URL to enqueue it without searching.

[b]Legal[/b]
  Only download content you have the rights to obtain.
"""


def format_http_selection_detail(result: HttpFileResult | None) -> str:
    if result is None:
        return "Selected: —"
    extra = result.extra or {}
    parts = [result.name, result.size_label, result.source_label]
    for key in ("duration", "license", "identifier"):
        value = extra.get(key)
        if value:
            parts.append(value)
    return "Selected: " + " · ".join(parts)


def format_result_type(result: HttpFileResult) -> str:
    """Short Type-column text from a mediatype or MIME string."""
    raw = (result.extra or {}).get("mediatype", "").strip()
    if not raw:
        return "file"
    # Commons reports MIME ("video/webm"); Archive and NASA report a bare kind.
    return raw.rsplit("/", 1)[-1] if "/" in raw else raw


def format_source_chips(labels: list[str]) -> str:
    joined = " · ".join(labels) if labels else "none"
    return f"Sources: {joined}   [dim](HTTP mode — not torrents)[/]"


def format_search_summary(count: int, elapsed: float, errors: list[str]) -> str:
    if count:
        text = f"{count} result(s) in {elapsed:.1f}s"
    else:
        text = "No results"
    if errors:
        text += f"  ·  {len(errors)} source(s) failed: " + "; ".join(errors)
    return text


class HttpPytorlinkApp(App[None]):
    """Search Internet Archive and enqueue HTTP downloads."""

    CSS = SHARED_CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "toggle_help", "Help"),
        Binding("d", "download_selected", "Download"),
        Binding("p", "pause_selected", "Pause"),
        Binding("r", "resume_selected", "Resume"),
        Binding("x", "remove_selected", "Remove"),
        Binding("delete", "remove_selected", "Remove", show=False),
        Binding("ctrl+r", "retry_search", "Retry"),
        Binding("1", "show_search_tab", "Search", show=False),
        Binding("2", "show_downloads_tab", "Downloads", show=False),
        Binding("left_square_bracket", "show_search_tab", "Search tab"),
        Binding("right_square_bracket", "show_downloads_tab", "Downloads tab"),
        Binding("escape", "close_overlays", "Close", show=False),
    ]
    TITLE = "pytorlink"
    SUB_TITLE = "http · direct download"

    def __init__(self, download_dir: Path | None = None) -> None:
        super().__init__()
        self.queue = HttpDownloadQueue(save_path=download_dir)
        self.sources = default_http_sources()
        self._results: list[HttpFileResult] = []
        self._help_visible = False
        self._active_tab = "search-tab"
        self._last_query: str = ""
        self._searching = False
        self.register_theme(TORLINK_THEME)
        self.theme = "torlink"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="chrome"):
            yield Static(self.queue.notice, id="banner", markup=True)
            yield Input(
                placeholder="Search Archive.org, Wikimedia, NASA… or paste an https URL  ·  Enter",
                id="search",
            )
            yield Static(
                format_source_chips([s.label for s in self.sources]),
                id="source-chips",
                markup=True,
            )
            yield Static("Ready — type a query or paste a URL and press Enter", id="status")
            yield Static("0 active", id="downloads-summary")
        with TabbedContent(initial="search-tab", id="tabs"):
            with TabPane("Search", id="search-tab"):
                with Vertical(id="results-pane"):
                    yield Static(
                        "Type a query above and press Enter to search all sources",
                        id="results-empty",
                        classes="pane-empty",
                    )
                    yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
                with HorizontalScroll(id="selection-scroll"):
                    yield Static(format_http_selection_detail(None), id="selection-detail")
            with TabPane("Downloads", id="downloads-tab"):
                with Vertical(id="downloads-pane"):
                    yield Static(
                        "No downloads yet — press d on a result, or paste a URL",
                        id="downloads-empty",
                        classes="pane-empty",
                    )
                    yield DataTable(id="downloads", cursor_type="row", zebra_stripes=True)
        yield Static(HELP_TEXT, id="help-panel", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"http  ·  0 active  ·  {self.queue.save_path}"
        results_pane = self.query_one("#results-pane", Vertical)
        results_pane.border_title = "Results"
        results_pane.border_subtitle = "↑↓ select · d download"
        downloads_pane = self.query_one("#downloads-pane", Vertical)
        downloads_pane.border_title = "Downloads"
        downloads_pane.border_subtitle = "p pause · r resume · x keep files"

        results = self.query_one("#results", DataTable)
        results.add_column("Name", width=NAME_COL_WIDTH, key="name")
        results.add_column("Size", width=10, key="size")
        results.add_column("Type", width=12, key="type")
        results.add_column("Source", width=14, key="source")

        downloads = self.query_one("#downloads", DataTable)
        downloads.add_column("Name", width=DOWNLOAD_NAME_COL_WIDTH, key="name")
        downloads.add_column("Status", width=12, key="status")
        downloads.add_column("Progress", width=18, key="progress")
        downloads.add_column("Speed", width=10, key="speed")

        self.query_one("#search", Input).focus()
        self._set_status(self.queue.notice)
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

    def _update_selection_detail(self, result: HttpFileResult | None = None) -> None:
        if result is None:
            result = self._highlighted_result()
        self.query_one("#selection-detail", Static).update(format_http_selection_detail(result))

    def _highlighted_result(self) -> HttpFileResult | None:
        table = self.query_one("#results", DataTable)
        if not self._results or table.row_count == 0:
            return None
        idx = table.cursor_row
        if idx < 0 or idx >= len(self._results):
            return None
        return self._results[idx]

    def action_toggle_help(self) -> None:
        panel = self.query_one("#help-panel", Static)
        self._help_visible = not self._help_visible
        panel.set_class(self._help_visible, "visible")

    def action_close_overlays(self) -> None:
        if self._help_visible:
            self._help_visible = False
            self.query_one("#help-panel", Static).remove_class("visible")

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
            self._set_status("Enter a search query or an http(s) URL", error=True)
            return
        if looks_like_http_url(text):
            try:
                handle = self.queue.add_url(text)
            except Exception as exc:
                self._set_status(f"Could not queue URL: {exc}", error=True)
                return
            self._refresh_downloads()
            msg = f"Queued: {handle.name}"
            self._set_status(msg)
            self.notify(msg, title="HTTP", timeout=3.0)
            event.input.value = ""
            return
        self._begin_search(text)

    def _begin_search(self, query: str) -> None:
        self._last_query = query
        names = ", ".join(s.label for s in self.sources)
        self._set_status(f"Searching {names} for '{query}'…", searching=True)
        table = self.query_one("#results", DataTable)
        table.clear()
        self._results = []
        empty = self.query_one("#results-empty", Static)
        empty.update(f"Searching '{query}'…")
        empty.remove_class("hidden")
        self._update_selection_detail(None)
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            if tabs.active != "search-tab":
                tabs.active = "search-tab"
        except Exception:
            pass
        self.run_search(query)

    def _fill_results_table(self, results: list[HttpFileResult]) -> None:
        table = self.query_one("#results", DataTable)
        self._results = results
        table.clear()
        used_keys: set[str] = set()
        for i, item in enumerate(results):
            ident = (item.extra or {}).get("identifier") or item.url or f"row-{i}"
            key = row_key_for(f"{item.source}:{ident}", used_keys, i)
            try:
                table.add_row(
                    name_cell(item.name, NAME_COL_WIDTH),
                    item.size_label,
                    format_result_type(item),
                    item.source_label,
                    key=key,
                )
            except Exception:
                continue
        empty = self.query_one("#results-empty", Static)
        if results:
            empty.add_class("hidden")
            self._update_selection_detail(results[0])
        else:
            empty.remove_class("hidden")
            self._update_selection_detail(None)

    @work(exclusive=True)
    async def run_search(self, query: str) -> None:
        self._searching = True
        self.refresh_bindings()
        empty = self.query_one("#results-empty", Static)
        started = time.monotonic()
        try:
            results, errors = await search_http_all(query, sources=self.sources)
            self._fill_results_table(results)
            elapsed = time.monotonic() - started
            summary = format_search_summary(len(results), elapsed, errors)
            if results:
                self._set_status(summary, error=bool(errors))
                try:
                    self.query_one("#results", DataTable).focus()
                except Exception:
                    pass
            else:
                empty.update("No results")
                empty.remove_class("hidden")
                self._set_status(summary, error=bool(errors))
                self.query_one("#search", Input).focus()
        except Exception as exc:
            self._results = []
            table = self.query_one("#results", DataTable)
            table.clear()
            empty.update("Search failed")
            empty.remove_class("hidden")
            self._update_selection_detail(None)
            self._set_status(f"Search error: {exc}", error=True)
            self.query_one("#search", Input).focus()
        finally:
            self._searching = False
            self.refresh_bindings()

    def action_download_selected(self) -> None:
        if self._active_tab != "search-tab":
            return
        item = self._highlighted_result()
        if item is None:
            self._set_status("No result selected", error=True)
            return
        self._enqueue_result(item)

    def _enqueue_result(self, item: HttpFileResult) -> None:
        if item.url and not item.needs_resolve:
            try:
                handle = self.queue.add_url(item.url, name=item.name, size_bytes=item.size_bytes)
            except Exception as exc:
                self._set_status(f"Could not queue: {exc}", error=True)
                return
            self._refresh_downloads()
            msg = f"Queued: {handle.name}"
            self._set_status(msg)
            self.notify(msg, title="HTTP", timeout=3.0)
            return
        self._set_status(
            f"Resolving {item.source_label} file for '{item.name}'…", searching=True
        )
        self.resolve_and_queue(item)

    @work(exclusive=True)
    async def resolve_and_queue(self, item: HttpFileResult) -> None:
        try:
            resolved = await resolve_http_result(item)
            handle = self.queue.add_url(
                resolved.url,
                name=resolved.name,
                size_bytes=resolved.size_bytes,
            )
        except Exception as exc:
            self._set_status(f"Could not resolve download: {exc}", error=True)
            return
        self._refresh_downloads()
        msg = f"Queued: {handle.name}"
        self._set_status(msg)
        self.notify(msg, title="HTTP", timeout=3.0)

    @on(DataTable.RowHighlighted, "#results")
    def on_results_highlighted(self, event: DataTable.RowHighlighted) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._results):
            self._update_selection_detail(self._results[idx])
        else:
            self._update_selection_detail(None)

    @on(DataTable.RowSelected, "#results")
    def on_results_selected(self, event: DataTable.RowSelected) -> None:
        idx = event.cursor_row
        if 0 <= idx < len(self._results):
            self._update_selection_detail(self._results[idx])
        else:
            self._update_selection_detail(None)

    def _selected_download(self) -> HttpDownloadHandle | None:
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
        for handle in items:
            if handle.id == key:
                return handle
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
        items = self.queue.items
        empty.set_class(bool(items), "hidden")
        sync_download_rows(table, items, format_rate=format_rate)
        summary = summarize_download_counts(items)
        self.query_one("#downloads-summary", Static).update(summary)
        pane = self.query_one("#downloads-pane", Vertical)
        total = len(items)
        pane.border_title = f"Downloads ({total})"
        pane.border_subtitle = f"{summary}  ·  p pause · r resume · x keep files"
        # Only rewrite the tab label when the text changes — constant updates
        # re-layout Tabs and can snap the DataTable cursor back to the top.
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            pane_tab = tabs.get_pane("downloads-tab")
            new_label = f"Downloads — {summary}" if total else "Downloads"
            if str(pane_tab.label) != new_label:
                pane_tab.label = new_label
        except Exception:
            pass
        self.sub_title = f"http  ·  {summary}  ·  {self.queue.save_path}"
