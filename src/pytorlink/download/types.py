"""Download backend protocol and progress types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class DownloadState(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    SEEDING = "seeding"
    DONE = "done"
    ERROR = "error"
    MAGNET_ONLY = "magnet_only"
    REMOVED = "removed"


@dataclass(slots=True)
class DownloadProgress:
    state: DownloadState
    progress: float = 0.0  # 0..1
    download_rate: float = 0.0  # bytes/s
    upload_rate: float = 0.0
    peers: int = 0
    message: str = ""
    save_path: str | None = None


@dataclass(slots=True)
class DownloadHandle:
    id: str
    name: str
    info_hash: str
    magnet: str
    progress: DownloadProgress = field(
        default_factory=lambda: DownloadProgress(DownloadState.QUEUED)
    )


@runtime_checkable
class DownloadBackend(Protocol):
    name: str

    def start(self, magnet: str, *, name: str, info_hash: str, save_path: str) -> DownloadHandle:
        ...

    def poll(self, handle: DownloadHandle) -> DownloadProgress:
        ...

    def pause(self, handle: DownloadHandle) -> None:
        ...

    def resume(self, handle: DownloadHandle) -> None:
        ...

    def remove(self, handle: DownloadHandle, *, delete_files: bool = False) -> None:
        """Stop the torrent / drop it from the client session.

        Default ``delete_files=False`` keeps downloaded files on disk.
        Pass ``delete_files=True`` to also delete data.
        """
        ...


class InstallError(RuntimeError):
    """Raised when an optional native dependency is missing."""


def format_rate(bps: float) -> str:
    """Human-readable byte rate; em dash when idle."""
    if bps <= 0:
        return "—"
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024**2:
        return f"{bps / 1024:.1f} KB/s"
    if bps < 1024**3:
        return f"{bps / 1024**2:.1f} MB/s"
    return f"{bps / 1024**3:.1f} GB/s"
