"""libtorrent-based download backend (optional dependency)."""

from __future__ import annotations

from pathlib import Path

from pytorlink.download.types import (
    DownloadHandle,
    DownloadProgress,
    DownloadState,
    InstallError,
    format_rate,
)


def _import_libtorrent():
    try:
        import libtorrent as lt  # type: ignore
    except ImportError as exc:
        raise InstallError(
            "libtorrent is not installed. Install with `pip install libtorrent` "
            "or your OS package (e.g. Ubuntu: sudo apt install python3-libtorrent). "
            "Falling back to magnet-only mode is recommended if install fails."
        ) from exc
    return lt


class LibtorrentBackend:
    name = "libtorrent"

    def __init__(self) -> None:
        self._lt = _import_libtorrent()
        self._session = self._lt.session()
        try:
            settings = {
                "listen_interfaces": "0.0.0.0:6881",
                "enable_dht": True,
            }
            self._session.apply_settings(settings)
        except Exception:
            try:
                self._session.listen_on(6881, 6891)
                self._session.add_dht_router("router.bittorrent.com", 6881)
                self._session.start_dht()
            except Exception:
                pass
        self._handles: dict[str, object] = {}  # id -> torrent_handle
        self._meta: dict[str, DownloadHandle] = {}
        self._paused: set[str] = set()

    def start(self, magnet: str, *, name: str, info_hash: str, save_path: str) -> DownloadHandle:
        Path(save_path).mkdir(parents=True, exist_ok=True)
        hid = info_hash.lower()
        existing = self._meta.get(hid)
        if existing is not None and hid in self._handles:
            return existing
        params = {
            "save_path": save_path,
            "storage_mode": self._lt.storage_mode_t.storage_mode_sparse,
        }
        try:
            th = self._lt.add_magnet_uri(self._session, magnet, params)
        except Exception:
            atp = self._lt.parse_magnet_uri(magnet)
            atp.save_path = save_path
            th = self._session.add_torrent(atp)
        self._handles[hid] = th
        handle = DownloadHandle(
            id=hid,
            name=name,
            info_hash=hid,
            magnet=magnet,
            progress=DownloadProgress(
                state=DownloadState.QUEUED,
                message="libtorrent: added magnet",
                save_path=save_path,
            ),
        )
        self._meta[hid] = handle
        return handle

    def poll(self, handle: DownloadHandle) -> DownloadProgress:
        th = self._handles.get(handle.id)
        if th is None:
            return DownloadProgress(
                state=DownloadState.REMOVED if handle.id not in self._meta else DownloadState.ERROR,
                message="unknown handle",
                save_path=handle.progress.save_path,
            )
        try:
            s = th.status()
            progress = float(getattr(s, "progress", 0) or 0)
            rate_dl = float(getattr(s, "download_rate", 0) or 0)
            rate_ul = float(getattr(s, "upload_rate", 0) or 0)
            peers = int(getattr(s, "num_peers", 0) or 0)
            err = str(getattr(s, "error", "") or "")
            state_name = str(getattr(s, "state", "")).lower()
            is_paused = bool(getattr(s, "paused", False)) or handle.id in self._paused
            auto_managed = bool(getattr(s, "auto_managed", False))

            if err:
                state = DownloadState.ERROR
                msg = err
            elif is_paused and handle.id in self._paused:
                state = DownloadState.PAUSED
                msg = f"paused  {progress * 100:.1f}%"
            elif is_paused and auto_managed and progress < 1.0:
                state = DownloadState.QUEUED
                msg = "queued"
            elif is_paused:
                state = DownloadState.PAUSED
                msg = f"paused  {progress * 100:.1f}%"
            elif progress >= 1.0 or "seed" in state_name or "finished" in state_name:
                state = DownloadState.SEEDING if "seed" in state_name or progress >= 1.0 else DownloadState.DONE
                if "seed" in state_name or progress >= 1.0:
                    state = DownloadState.SEEDING
                else:
                    state = DownloadState.DONE
                msg = f"{progress * 100:.1f}%  {peers} peers  ↓{format_rate(rate_dl)} ↑{format_rate(rate_ul)}"
            elif any(tok in state_name for tok in ("queue", "check", "metadata", "allocat")):
                state = DownloadState.QUEUED
                msg = state_name.replace("_", " ") or "queued"
            else:
                state = DownloadState.DOWNLOADING
                msg = f"{progress * 100:.1f}%  {peers} peers  ↓{format_rate(rate_dl)} ↑{format_rate(rate_ul)}"

            handle.progress = DownloadProgress(
                state=state,
                progress=progress,
                download_rate=rate_dl,
                upload_rate=rate_ul,
                peers=peers,
                message=msg,
                save_path=handle.progress.save_path,
            )
            try:
                self._session.pop_alerts()
            except Exception:
                pass
            return handle.progress
        except Exception as exc:
            handle.progress = DownloadProgress(state=DownloadState.ERROR, message=str(exc))
            return handle.progress

    def pause(self, handle: DownloadHandle) -> None:
        th = self._handles.get(handle.id)
        if th is None:
            return
        self._paused.add(handle.id)
        try:
            flags = getattr(self._lt, "torrent_flags", None)
            if flags is not None and hasattr(th, "unset_flags") and hasattr(flags, "auto_managed"):
                th.unset_flags(flags.auto_managed)
            elif hasattr(th, "auto_managed"):
                th.auto_managed(False)
            th.pause()
        except Exception:
            pass
        handle.progress = DownloadProgress(
            state=DownloadState.PAUSED,
            progress=handle.progress.progress,
            peers=handle.progress.peers,
            message="paused",
            save_path=handle.progress.save_path,
        )

    def resume(self, handle: DownloadHandle) -> None:
        th = self._handles.get(handle.id)
        if th is None:
            return
        self._paused.discard(handle.id)
        try:
            flags = getattr(self._lt, "torrent_flags", None)
            if flags is not None and hasattr(th, "set_flags") and hasattr(flags, "auto_managed"):
                th.set_flags(flags.auto_managed)
            elif hasattr(th, "auto_managed"):
                th.auto_managed(True)
            th.resume()
        except Exception:
            pass
        handle.progress = DownloadProgress(
            state=DownloadState.DOWNLOADING,
            progress=handle.progress.progress,
            peers=handle.progress.peers,
            message="resumed",
            save_path=handle.progress.save_path,
        )

    def remove(self, handle: DownloadHandle, *, delete_files: bool = False) -> None:
        th = self._handles.pop(handle.id, None)
        self._paused.discard(handle.id)
        self._meta.pop(handle.id, None)
        if th is None:
            handle.progress = DownloadProgress(
                state=DownloadState.REMOVED,
                message="Removed from queue; files kept" if not delete_files else "Removed and files deleted",
                save_path=handle.progress.save_path if not delete_files else None,
            )
            return
        try:
            if delete_files:
                self._remove_torrent_delete(th)
            else:
                self._session.remove_torrent(th)
        except Exception:
            pass
        handle.progress = DownloadProgress(
            state=DownloadState.REMOVED,
            progress=handle.progress.progress,
            message="Removed from queue; files kept" if not delete_files else "Removed and files deleted",
            save_path=handle.progress.save_path if not delete_files else None,
        )

    def stop(self, handle: DownloadHandle) -> None:
        self.remove(handle, delete_files=False)

    def _remove_torrent_delete(self, th: object) -> None:
        flags = 1
        for getter in (
            lambda: getattr(self._lt.options_t, "delete_files", None),
            lambda: getattr(self._lt.session, "delete_files", None),
            lambda: getattr(getattr(self._lt, "session_flags_t", None), "delete_files", None),
        ):
            try:
                val = getter()
            except Exception:
                val = None
            if val is not None:
                flags = val
                break
        try:
            self._session.remove_torrent(th, flags)
        except TypeError:
            self._session.remove_torrent(th)


def is_libtorrent_available() -> bool:
    try:
        _import_libtorrent()
        return True
    except InstallError:
        return False
