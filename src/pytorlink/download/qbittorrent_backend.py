"""Optional qBittorrent Web API backend (qbittorrent-api)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pytorlink.download.types import (
    DownloadHandle,
    DownloadProgress,
    DownloadState,
    InstallError,
    format_rate,
)


def qbittorrent_env_configured() -> bool:
    return bool(os.environ.get("QBIT_HOST"))


def _client():
    try:
        import qbittorrentapi
    except ImportError as exc:
        raise InstallError(
            "qbittorrent-api not installed. Install with: pip install pytorlink[qbittorrent]"
        ) from exc
    host = os.environ.get("QBIT_HOST", "http://127.0.0.1:8080")
    user = os.environ.get("QBIT_USER", "admin")
    password = os.environ.get("QBIT_PASS", "")
    client = qbittorrentapi.Client(host=host, username=user, password=password)
    client.auth_log_in()
    return client


class QBittorrentBackend:
    name = "qbittorrent"

    def __init__(self) -> None:
        self._client = _client()
        self._handles: dict[str, DownloadHandle] = {}
        self._paused: set[str] = set()

    def start(self, magnet: str, *, name: str, info_hash: str, save_path: str) -> DownloadHandle:
        Path(save_path).mkdir(parents=True, exist_ok=True)
        self._client.torrents_add(urls=magnet, save_path=save_path)
        hid = info_hash.lower()
        handle = DownloadHandle(
            id=hid,
            name=name,
            info_hash=hid,
            magnet=magnet,
            progress=DownloadProgress(
                state=DownloadState.QUEUED,
                message="added to qBittorrent",
                save_path=save_path,
            ),
        )
        self._handles[hid] = handle
        return handle

    def poll(self, handle: DownloadHandle) -> DownloadProgress:
        if handle.id not in self._handles and handle.info_hash not in self._handles:
            return DownloadProgress(
                state=DownloadState.REMOVED,
                message="Removed from queue; files kept",
                save_path=handle.progress.save_path,
            )
        try:
            torrents = self._client.torrents_info(torrent_hashes=handle.info_hash)
            if not torrents:
                if handle.id in self._paused:
                    handle.progress = DownloadProgress(
                        state=DownloadState.PAUSED,
                        progress=handle.progress.progress,
                        message="paused",
                        save_path=handle.progress.save_path,
                    )
                return handle.progress
            t = torrents[0]
            progress = float(getattr(t, "progress", 0) or 0)
            state_raw = str(getattr(t, "state", "")).lower()
            dls = float(getattr(t, "dlspeed", 0) or 0)
            uls = float(getattr(t, "upspeed", 0) or 0)
            peers = int(getattr(t, "num_leechs", 0) or 0) + int(getattr(t, "num_seeds", 0) or 0)
            state = _map_qbit_state(state_raw, progress, paused_override=handle.id in self._paused)
            handle.progress = DownloadProgress(
                state=state,
                progress=progress,
                download_rate=dls,
                upload_rate=uls,
                peers=peers,
                message=f"{progress * 100:.1f}%  {peers} peers  ↓{format_rate(dls)}  qBit:{state_raw}",
                save_path=handle.progress.save_path,
            )
            return handle.progress
        except Exception as exc:
            handle.progress = DownloadProgress(state=DownloadState.ERROR, message=str(exc))
            return handle.progress

    def pause(self, handle: DownloadHandle) -> None:
        self._paused.add(handle.id)
        self._call_torrents("torrents_pause", "torrents_stop", "pause", "stop", torrent_hashes=handle.info_hash)
        handle.progress = DownloadProgress(
            state=DownloadState.PAUSED,
            progress=handle.progress.progress,
            peers=handle.progress.peers,
            message="paused",
            save_path=handle.progress.save_path,
        )

    def resume(self, handle: DownloadHandle) -> None:
        self._paused.discard(handle.id)
        self._call_torrents("torrents_resume", "torrents_start", "resume", "start", torrent_hashes=handle.info_hash)
        handle.progress = DownloadProgress(
            state=DownloadState.DOWNLOADING,
            progress=handle.progress.progress,
            peers=handle.progress.peers,
            message="resumed",
            save_path=handle.progress.save_path,
        )

    def remove(self, handle: DownloadHandle, *, delete_files: bool = False) -> None:
        """Remove from qBit session. ``delete_files=False`` keeps data on disk.

        Uses torrents_delete(delete_files=...) — not delete_permanently —
        so the default path is qBit's non-destructive delete.
        """
        self._paused.discard(handle.id)
        try:
            self._client.torrents_delete(delete_files=delete_files, torrent_hashes=handle.info_hash)
        except Exception:
            torrents = getattr(self._client, "torrents", None)
            if torrents is not None and hasattr(torrents, "delete"):
                try:
                    torrents.delete(torrent_hashes=handle.info_hash, delete_files=delete_files)
                except Exception:
                    pass
        self._handles.pop(handle.id, None)
        handle.progress = DownloadProgress(
            state=DownloadState.REMOVED,
            progress=handle.progress.progress,
            message="Removed from queue; files kept" if not delete_files else "Removed and files deleted",
            save_path=handle.progress.save_path if not delete_files else None,
        )

    def stop(self, handle: DownloadHandle) -> None:
        self.remove(handle, delete_files=False)

    def _call_torrents(self, *names: str, **kwargs: Any) -> None:
        for name in names:
            fn = getattr(self._client, name, None)
            if callable(fn):
                try:
                    fn(**kwargs)
                    return
                except TypeError:
                    hashes = kwargs.get("torrent_hashes")
                    try:
                        fn(hashes)
                        return
                    except Exception:
                        continue
                except Exception:
                    continue
            nested = getattr(self._client, "torrents", None)
            if nested is None:
                continue
            short = name.split("_")[-1] if "_" in name else name
            fn = getattr(nested, short, None)
            if callable(fn):
                try:
                    fn(**kwargs)
                    return
                except Exception:
                    continue


def _map_qbit_state(state_raw: str, progress: float, *, paused_override: bool) -> DownloadState:
    raw = state_raw.lower()
    if "error" in raw or "missing" in raw:
        return DownloadState.ERROR
    if paused_override or "paused" in raw or "stopped" in raw:
        return DownloadState.PAUSED
    if any(tok in raw for tok in ("queued", "checking", "meta")):
        return DownloadState.QUEUED
    if progress >= 1.0 or any(tok in raw for tok in ("uploading", "stalledup", "forcedup")):
        return DownloadState.SEEDING
    return DownloadState.DOWNLOADING
