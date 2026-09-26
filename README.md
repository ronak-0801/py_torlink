# pytorlink

A small **Python** terminal torrent search & download MVP, inspired by [baairon/torlink](https://github.com/baairon/torlink). Original Python code — not a port of the JS sources.

Search curated indexes concurrently from a Textual TUI, then enqueue magnets via libtorrent, qBittorrent, or a magnet-file fallback. A **separate HTTP mode** searches open media archives (or accepts a pasted file URL) and streams files over HTTP.

**Version:** 0.6.0

## Legal

**Only download content you have the rights to obtain.** This tool is for lawful use (public-domain / Creative Commons / content you own or are licensed to receive). You are responsible for complying with local law and site terms.

## Sources

| Source | ID | Protocol | Notes |
|--------|----|----------|-------|
| YTS | `yts` | JSON API | Multi-mirror failover (`yts.mx`, `yts.lt`, `yts.am`, `yts.rs`) |
| Nyaa | `nyaa` | RSS | Anime; rejects Cloudflare/HTML responses cleanly |
| The Pirate Bay | `piratebay` | apibay.org JSON | Sentinel empty-result handling |
| EZTV | `eztv` | JSON API | TV; filters recent feed + optional IMDb expand |
| SubsPlease | `subsplease` | JSON API | Anime; picks best resolution magnet |
| BitTorrented | `bittorrented` | JSON API | **Disabled by default** (often `402 Payment Required` / paywalled). Module kept; enable via source picker (`s`). |
| FitGirl | `fitgirl` | WordPress RSS | Games; magnets parsed from RSS items |
| EXT | `ext_to` | HTML (+ optional AJAX) | [ext.to](https://ext.to) search; mirrors `extto.com`. Soft-fails on Cloudflare. Magnets from HTML when present; AJAX enrich when tokens available. |

**1337x (`x1337`)** is deferred — HTML search/detail scraping is fragile across mirrors.

**Default enabled sources:** all of the above except BitTorrented. Press `s` in the TUI to multi-select sources; the set is persisted to `~/.config/pytorlink/sources.json`.

Indexes can be **geo-blocked, rate-limited, or temporarily down**. Search soft-fails per source and still returns whatever succeeded.

## Requirements

- Python **3.10+**
- Optional: **libtorrent** for in-process downloads
- Optional: **qBittorrent** Web UI + `qbittorrent-api` for client-backed downloads

## Install

```bash
cd /workspace/pytorlink   # or your clone path
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
# optional qBittorrent Web API:
# python -m pip install -e ".[qbittorrent]"
```

### Enabling libtorrent (Ubuntu)

Preferred (system package, most reliable):

```bash
sudo apt update
sudo apt install python3-libtorrent
```

A venv does **not** see the system package unless you created it with
`--system-site-packages`. Recreate if needed:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -c "import libtorrent; print('libtorrent ok')"
```

Alternatively try `pip install libtorrent` (wheels are not available on every
platform; the OS package is the usual path on Ubuntu).

### Enabling qBittorrent

1. Enable the Web UI in qBittorrent (default `http://127.0.0.1:8080`).
2. Install the extra: `python -m pip install -e ".[qbittorrent]"`.
3. Export:

```bash
export QBIT_HOST=http://127.0.0.1:8080
export QBIT_USER=admin
export QBIT_PASS=yourpassword
```

## Run

Modes are **separate**. Torrent search does not mix with HTTP downloads.

```bash
pytorlink              # interactive picker (TTY): 1 = torrent, 2 = http
pytorlink torrent      # torrent indexes + magnet / libtorrent / qBittorrent
pytorlink http         # open-archive search, or paste a direct http(s) URL
# or
python -m pytorlink.cli torrent
python -m pytorlink.cli http
```

- Torrent download dir: `~/Downloads/pytorlink` (created if needed)
- HTTP download dir: `~/Downloads/pytorlink/http`
- Override either: `pytorlink torrent --download-dir /path` or `pytorlink http --download-dir /path`
- Version: `pytorlink --version`

Non-interactive shells must pass `torrent` or `http` explicitly.

### Backend selection (torrent mode only)

1. If `QBIT_HOST` is set (and optionally `QBIT_USER` / `QBIT_PASS`), use **qBittorrent** Web API.
2. Else if **libtorrent** imports cleanly, use that.
3. Else **magnet-only**: writes a `.magnet` file under the download dir (and tries clipboard). **No torrent data is downloaded** in this mode — the TUI banner says so.

The selected backend’s notice is shown as a banner at the top of the TUI.

### HTTP mode

`pytorlink http` is a **separate TUI**: it does not query torrent indexes.

Sources are searched concurrently and results are interleaved, so no single
source dominates the top of the list. A source that errors or hangs is
soft-failed: the others still return, and the status line reports what broke.

| Source | API | Content |
| --- | --- | --- |
| Archive.org | `advancedsearch` + `metadata` | Public domain / openly licensed |
| Wikimedia Commons | MediaWiki `imageinfo` | Public domain / CC |
| NASA | images-api.nasa.gov | US government public domain |

- Press `d` on a hit → download it. Archive.org and NASA hits resolve to a
  concrete file first (best available rendition); Commons hits already carry a
  direct URL.
- Paste an `http://` or `https://` file URL and press Enter to enqueue it directly.
- Pause/resume uses HTTP `Range` when the server supports it.
- All three hosts are queried with a descriptive `User-Agent`; Wikimedia's robot
  policy rejects spoofed browser agents.

Adding a source means implementing `HttpSource` (`search`, plus `resolve` only
if search does not return a file URL) and appending it to `HTTP_SOURCES` in
`httpdl/registry.py`.

This is not a scraper for third-party “direct download” dump sites.

### Pause, resume, and remove

| Action | What it does |
|--------|----------------|
| Pause | Tells the client to pause that torrent (`torrent_handle.pause` / qBit pause). Magnet-only only updates local state. |
| Resume | Resumes the torrent in the client. |
| Remove (`x`) | Drops the torrent from the **session/queue**. **Downloaded files stay on disk.** Pass `delete_files=True` in the API (not bound in the TUI) to also delete data. |

qBittorrent uses `torrents_delete(delete_files=False)` — not a permanent/data-wiping delete — so files are kept. libtorrent calls `session.remove_torrent(handle)` without the delete-files flag.

## TUI keys

Chrome (header, backend banner, search box, status line, download counts) stays **outside** the tabs so search always works. Tabs hold only: **Search** = results table + selection detail; **Downloads** = downloads table. Click/arrow keys only highlight rows; downloads start only with `d`.

| Key | Action |
|-----|--------|
| Enter (search box) | Run search, or queue if the input is a magnet / info-hash |
| Ctrl+r | Retry the last search query |
| `s` | Open / close **source picker** (multi-select; digit keys toggle; Esc closes) |
| Enter / click (result row) | Highlight only — **does not** download; full name shown in the selection strip (scrolls horizontally if long) |
| `d` | Download highlighted result (Search tab) |
| `1` / `[` | Switch to Search tab |
| `2` / `]` | Switch to Downloads tab |
| Tab | Move focus between search, tables, and tabs |
| ↑ / ↓ | Move in the focused table |
| `p` | Pause highlighted download (Downloads tab) |
| `r` | Resume highlighted download (Downloads tab) |
| `x` / Delete | Remove from queue/session **without deleting files** (status: “Removed from queue; files kept”) |
| `?` | Help |
| `q` | Quit |

The footer bindings update with the active tab (Download / Retry / Sources on Search; Pause / Resume / Remove on Downloads). Status shows `Searching 'q'… (N sources)` using only **enabled** sources; empty all-source failures show a clear soft-fail message. Queuing a download shows a short toast and status line and **stays on the Search tab**. Download counts stay visible in the header subtitle and the chrome summary line on both tabs. A compact source chip row sits under the search box; `s` opens the checklist overlay.

## Architecture

```
src/pytorlink/
  cli.py                 # argparse → torrent | http TUI (picker if omitted)
  sources/
    types.py             # Source protocol, TorrentResult, dedupe/sort
    magnet.py            # build/parse magnet, default trackers
    http.py              # shared User-Agent / client helpers
    registry.py          # SOURCES + defaults + iter_search / search_all
    yts.py               # YTS JSON API + host failover
    nyaa.py              # Nyaa RSS
    piratebay.py         # apibay.org JSON
    eztv.py              # EZTV JSON API
    subsplease.py        # SubsPlease JSON API
    bittorrented.py      # BitTorrented JSON API (optional / paywalled)
    fitgirl.py           # FitGirl WordPress RSS
    ext_to.py            # EXT.to HTML search
    rss.py               # RSS magnet extraction helper
    cache.py             # in-memory TTL cache
  httpdl/
    types.py             # HttpFileResult, URL helpers, shared User-Agent
    base.py              # HttpSource interface (search / resolve)
    registry.py          # registered HTTP sources + concurrent search
    archive.py           # Internet Archive search + file resolve
    commons.py           # Wikimedia Commons search (direct URLs)
    nasa.py              # NASA library search + asset resolve
  config.py              # ~/.config/pytorlink/sources.json persistence
  download/
    types.py             # DownloadBackend protocol (start/poll/pause/resume/remove)
    queue.py             # torrent queue + backend auto-select
    http_backend.py      # threaded HTTP(S) file download
    http_queue.py        # HTTP queue (separate from torrents)
    libtorrent_backend.py
    qbittorrent_backend.py
    magnet_backend.py
  ui/app.py              # torrent Textual App
  ui/http_app.py         # HTTP Textual App
  ui/common.py           # shared theme / CSS / table helpers
```

### Concurrent / streaming search

`iter_search` runs each source concurrently and **yields as each source finishes** (via `asyncio.as_completed`), with a per-source timeout (default 8s) that soft-fails hung indexes. Fast sources (apibay / YTS) often surface in the TUI within 1–2s.

The TUI merges, dedupes, and re-sorts incrementally (`N results · K/M sources done`), throttling UI refreshes (~120ms) to avoid flicker. Soft-fail reasons appear in the final status line.

`search_all` still returns `(results, errors)` for tests/scripts — it collects from `iter_search`, dedupes by info-hash (keeps highest seeders), and sorts by seeders descending.

## How to add a source

1. Implement a class with `id: SourceId`, `label: str`, and `async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]`.
2. Add a `SourceId` enum member (and label) in `sources/types.py` if needed.
3. Append an instance to `SOURCES` in `sources/registry.py`. Add to `DISABLED_BY_DEFAULT` if it should be opt-in.
4. Prefer fixture-based unit tests that parse sample JSON/RSS/HTML without network.

## Tests

```bash
pytest
```

Tests cover magnet build/parse, dedupe, YTS JSON + multi-host failover (mocked), Nyaa RSS + HTML rejection, apibay/SubsPlease/FitGirl/EXT.to fixtures, Archive.org / Wikimedia / NASA fixtures, HTTP source registry fan-out and soft-fail, HTTP download against a local server, CLI mode selection, default source enablement + config persistence, and MagnetBackend/DownloadQueue pause/resume/remove — no external network required.

## License

MIT
