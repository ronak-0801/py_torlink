"""Simple download queue wrapping a backend."""

from __future__ import annotations

from pathlib import Path

from pytorlink.download.libtorrent_backend import LibtorrentBackend, is_libtorrent_available
from pytorlink.download.magnet_backend import MagnetBackend
from pytorlink.download.qbittorrent_backend import QBittorrentBackend, qbittorrent_env_configured
from pytorlink.download.types import (
    DownloadBackend,
    DownloadHandle,
    DownloadProgress,
    DownloadState,
)
from pytorlink.sources.magnet import build_magnet, looks_like_info_hash, looks_like_magnet, parse_magnet


def default_download_dir() -> Path:
    path = Path.home() / "Downloads" / "pytorlink"
    path.mkdir(parents=True, exist_ok=True)
    return path


def select_backend() -> tuple[DownloadBackend, str]:
    """Pick backend: qBittorrent if env set, else libtorrent, else magnet fallback.

    Returns ``(backend, notice)``.
    """
    notice = ""
    if qbittorrent_env_configured():
        try:
            return QBittorrentBackend(), "Using qBittorrent Web API (QBIT_HOST)."
        except Exception as exc:
            notice = f"qBittorrent configured but failed ({exc}); "

    if is_libtorrent_available():
        try:
            return LibtorrentBackend(), notice + "Using libtorrent backend."
        except Exception as exc:
            notice += f"libtorrent import ok but init failed ({exc}); "

    backend = MagnetBackend()
    notice += (
        "Magnet-only mode: no real download will happen. "
        "Install libtorrent (Ubuntu: sudo apt install python3-libtorrent) "
        "or set QBIT_HOST / QBIT_USER / QBIT_PASS for qBittorrent."
    )
    return backend, notice.strip()


class DownloadQueue:
    def __init__(self, backend: DownloadBackend | None = None, save_path: Path | None = None) -> None:
        if backend is None:
            backend, self.notice = select_backend()
        else:
            self.notice = f"Using backend: {backend.name}"
        self.backend = backend
        self.save_path = Path(save_path) if save_path else default_download_dir()
        self.save_path.mkdir(parents=True, exist_ok=True)
        self._items: list[DownloadHandle] = []

    @property
    def items(self) -> list[DownloadHandle]:
        return list(self._items)

    def _find(self, item_id: str) -> DownloadHandle | None:
        key = item_id.lower()
        for h in self._items:
            if h.id == key or h.info_hash == key:
                return h
        return None

    def add_magnet(self, magnet: str, *, name: str | None = None) -> DownloadHandle:
        meta = parse_magnet(magnet)
        info_hash = str(meta["info_hash"])
        display = name or (str(meta["name"]) if meta["name"] else info_hash)
        for existing in self._items:
            if existing.info_hash == info_hash.lower():
                return existing
        handle = self.backend.start(
            magnet,
            name=display,
            info_hash=info_hash,
            save_path=str(self.save_path),
        )
        self._items.append(handle)
        return handle

    def add_info_hash(self, info_hash: str, *, name: str | None = None) -> DownloadHandle:
        magnet = build_magnet(info_hash, name=name)
        return self.add_magnet(magnet, name=name)

    def add_from_text(self, text: str) -> DownloadHandle | None:
        raw = text.strip()
        if looks_like_magnet(raw):
            return self.add_magnet(raw)
        if looks_like_info_hash(raw):
            return self.add_info_hash(raw)
        return None

    def poll_all(self) -> list[DownloadProgress]:
        out: list[DownloadProgress] = []
        for h in self._items:
            h.progress = self.backend.poll(h)
            out.append(h.progress)
        return out

    def pause(self, item_id: str) -> DownloadHandle | None:
        handle = self._find(item_id)
        if handle is None:
            return None
        self.backend.pause(handle)
        handle.progress = self.backend.poll(handle)
        return handle

    def resume(self, item_id: str) -> DownloadHandle | None:
        handle = self._find(item_id)
        if handle is None:
            return None
        self.backend.resume(handle)
        handle.progress = self.backend.poll(handle)
        return handle

    def remove(self, item_id: str, delete_files: bool = False) -> DownloadHandle | None:
        """Remove from the client session. Default keeps downloaded files on disk."""
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
