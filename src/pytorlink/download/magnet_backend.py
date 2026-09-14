"""Fallback backend: persist magnet URI and optionally copy to clipboard.

This backend does **not** download torrent data. pause/resume/remove only
update local queue state (and optionally delete the saved .magnet file).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pytorlink.download.types import (
    DownloadHandle,
    DownloadProgress,
    DownloadState,
)


def _try_clipboard(text: str) -> bool:
    """Best-effort clipboard copy; returns True on success."""
    if shutil.which("wl-copy"):
        try:
            subprocess.run(["wl-copy"], input=text.encode(), check=True, timeout=2)
            return True
        except Exception:
            pass
    if shutil.which("xclip"):
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode(),
                check=True,
                timeout=2,
            )
            return True
        except Exception:
            pass
    if shutil.which("pbcopy"):
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=2)
            return True
        except Exception:
            pass
    return False


_NO_DOWNLOAD = "Magnet-only: no real download is happening"


class MagnetBackend:
    """Does not download; writes magnet to a file and reports magnet_only status."""

    name = "magnet"

    def __init__(self) -> None:
        self._handles: dict[str, DownloadHandle] = {}
        self._messages: dict[str, str] = {}

    def start(self, magnet: str, *, name: str, info_hash: str, save_path: str) -> DownloadHandle:
        Path(save_path).mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:80] or info_hash
        out = Path(save_path) / f"{safe}.magnet"
        out.write_text(magnet + "\n", encoding="utf-8")
        clipped = _try_clipboard(magnet)
        msg = (
            f"{_NO_DOWNLOAD}. Saved {out}. "
            "Install libtorrent or set QBIT_HOST for a real download."
        )
        if clipped:
            msg += " Copied to clipboard."
        else:
            msg += " Paste the magnet into a torrent client."
        handle = DownloadHandle(
            id=info_hash.lower(),
            name=name,
            info_hash=info_hash.lower(),
            magnet=magnet,
            progress=DownloadProgress(
                state=DownloadState.MAGNET_ONLY,
                progress=0.0,
                message=msg,
                save_path=str(out),
            ),
        )
        self._handles[handle.id] = handle
        self._messages[handle.id] = msg
        return handle

    def poll(self, handle: DownloadHandle) -> DownloadProgress:
        live = self._handles.get(handle.id)
        if live is None:
            return DownloadProgress(
                state=DownloadState.REMOVED,
                message="Removed from queue; files kept",
                save_path=handle.progress.save_path,
            )
        return live.progress

    def pause(self, handle: DownloadHandle) -> None:
        live = self._handles.get(handle.id, handle)
        live.progress = DownloadProgress(
            state=DownloadState.PAUSED,
            progress=live.progress.progress,
            message=f"Paused — {_NO_DOWNLOAD.lower()}",
            save_path=live.progress.save_path,
        )
        handle.progress = live.progress

    def resume(self, handle: DownloadHandle) -> None:
        live = self._handles.get(handle.id, handle)
        msg = self._messages.get(handle.id) or (
            f"{_NO_DOWNLOAD}. Paste the .magnet file into a torrent client."
        )
        live.progress = DownloadProgress(
            state=DownloadState.MAGNET_ONLY,
            progress=live.progress.progress,
            message=msg,
            save_path=live.progress.save_path,
        )
        handle.progress = live.progress

    def remove(self, handle: DownloadHandle, *, delete_files: bool = False) -> None:
        live = self._handles.pop(handle.id, handle)
        path = live.progress.save_path
        if delete_files and path:
            p = Path(path)
            if p.is_file():
                p.unlink(missing_ok=True)
        msg = (
            "Removed and magnet file deleted"
            if delete_files
            else "Removed from queue; files kept"
        )
        progress = DownloadProgress(
            state=DownloadState.REMOVED,
            progress=live.progress.progress,
            message=msg,
            save_path=None if delete_files else path,
        )
        live.progress = progress
        handle.progress = progress
        self._messages.pop(handle.id, None)

    def stop(self, handle: DownloadHandle) -> None:
        self.remove(handle, delete_files=False)
