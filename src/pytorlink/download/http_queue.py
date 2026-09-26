"""Queue for HTTP / direct downloads (separate from torrent DownloadQueue)."""

from __future__ import annotations

from pathlib import Path

from pytorlink.download.http_backend import HttpBackend, HttpDownloadHandle
from pytorlink.download.types import DownloadProgress, DownloadState
from pytorlink.httpdl.types import filename_from_url, looks_like_http_url


def default_http_download_dir() -> Path:
    path = Path.home() / "Downloads" / "pytorlink" / "http"
    path.mkdir(parents=True, exist_ok=True)
    return path


class HttpDownloadQueue:
    def __init__(self, backend: HttpBackend | None = None, save_path: Path | None = None) -> None:
        self.backend = backend or HttpBackend()
        self.notice = "HTTP mode: Archive.org / Wikimedia / NASA search, or paste an https URL."
        self.save_path = Path(save_path) if save_path else default_http_download_dir()
        self.save_path.mkdir(parents=True, exist_ok=True)
        self._items: list[HttpDownloadHandle] = []

    @property
    def items(self) -> list[HttpDownloadHandle]:
        return list(self._items)

    def _find(self, item_id: str) -> HttpDownloadHandle | None:
        key = item_id.lower()
        for handle in self._items:
            if handle.id == key:
                return handle
        return None

    def add_url(
        self,
        url: str,
        *,
        name: str | None = None,
        size_bytes: int | None = None,
    ) -> HttpDownloadHandle:
        raw = url.strip()
        if not looks_like_http_url(raw):
            raise ValueError(f"Not an http(s) URL: {url}")
        display = name or filename_from_url(raw)
        for existing in self._items:
            if existing.url == raw:
                return existing
        handle = self.backend.start(
            raw,
            name=display,
            save_path=str(self.save_path),
            size_bytes=size_bytes,
        )
        if handle.id not in {h.id for h in self._items}:
            self._items.append(handle)
        return handle

    def poll_all(self) -> list[DownloadProgress]:
        out: list[DownloadProgress] = []
        for handle in self._items:
            handle.progress = self.backend.poll(handle)
            out.append(handle.progress)
        return out

    def pause(self, item_id: str) -> HttpDownloadHandle | None:
        handle = self._find(item_id)
        if handle is None:
            return None
        self.backend.pause(handle)
        handle.progress = self.backend.poll(handle)
        return handle

    def resume(self, item_id: str) -> HttpDownloadHandle | None:
        handle = self._find(item_id)
        if handle is None:
            return None
        self.backend.resume(handle)
        handle.progress = self.backend.poll(handle)
        return handle

    def remove(self, item_id: str, delete_files: bool = False) -> HttpDownloadHandle | None:
        handle = self._find(item_id)
        if handle is None:
            return None
        self.backend.remove(handle, delete_files=delete_files)
        self._items.remove(handle)
        if handle.progress.state != DownloadState.REMOVED:
            handle.progress = DownloadProgress(
                state=DownloadState.REMOVED,
                progress=handle.progress.progress,
                message="Removed from queue; files kept" if not delete_files else "Removed and files deleted",
                save_path=handle.progress.save_path if not delete_files else None,
            )
        return handle
