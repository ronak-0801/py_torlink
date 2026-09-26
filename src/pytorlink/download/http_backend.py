"""Direct HTTP(S) download backend (separate from torrent backends)."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from pytorlink.download.types import DownloadProgress, DownloadState
from pytorlink.httpdl.types import HTTP_USER_AGENT, filename_from_url, looks_like_http_url

_CHUNK = 64 * 1024


def url_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def safe_filename(name: str, fallback: str = "download") -> str:
    cleaned = re.sub(r"[^\w.\- ()[\]]+", "_", name).strip("._ ")
    return (cleaned[:160] or fallback)


@dataclass(slots=True)
class HttpDownloadHandle:
    id: str
    name: str
    url: str
    dest_path: str
    progress: DownloadProgress = field(
        default_factory=lambda: DownloadProgress(DownloadState.QUEUED)
    )


class _Job:
    def __init__(self, handle: HttpDownloadHandle, total: int | None) -> None:
        self.handle = handle
        self.total = total
        self.written = 0
        self.pause = threading.Event()
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.last_bytes = 0
        self.last_time = time.monotonic()
        self.rate = 0.0
        self.error: str | None = None


class HttpBackend:
    """Stream a URL to disk with pause (Range resume) / cancel."""

    name = "http"

    def __init__(self, *, timeout: float = 60.0) -> None:
        self._timeout = timeout
        self._jobs: dict[str, _Job] = {}

    def start(
        self,
        url: str,
        *,
        name: str,
        save_path: str,
        size_bytes: int | None = None,
    ) -> HttpDownloadHandle:
        if not looks_like_http_url(url):
            raise ValueError(f"Not an http(s) URL: {url}")
        dest_dir = Path(save_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname = safe_filename(name or filename_from_url(url))
        dest = dest_dir / fname
        handle = HttpDownloadHandle(
            id=url_id(url),
            name=fname,
            url=url,
            dest_path=str(dest),
            progress=DownloadProgress(
                state=DownloadState.QUEUED,
                save_path=str(dest),
                message="Queued HTTP download",
            ),
        )
        existing = self._jobs.get(handle.id)
        if existing is not None:
            return existing.handle
        job = _Job(handle, size_bytes)
        if dest.exists():
            job.written = dest.stat().st_size
        self._jobs[handle.id] = job
        self._spawn(job)
        return handle

    def poll(self, handle: HttpDownloadHandle) -> DownloadProgress:
        job = self._jobs.get(handle.id)
        if job is None:
            return handle.progress
        with job.lock:
            progress = _progress_from_job(job)
            handle.progress = progress
            return progress

    def pause(self, handle: HttpDownloadHandle) -> None:
        job = self._jobs.get(handle.id)
        if job is None:
            return
        job.pause.set()

    def resume(self, handle: HttpDownloadHandle) -> None:
        job = self._jobs.get(handle.id)
        if job is None:
            return
        if job.cancel.is_set():
            return
        job.pause.clear()
        thread = job.thread
        if thread is None or not thread.is_alive():
            self._spawn(job)

    def remove(self, handle: HttpDownloadHandle, *, delete_files: bool = False) -> None:
        job = self._jobs.get(handle.id)
        if job is None:
            return
        job.cancel.set()
        job.pause.clear()
        thread = job.thread
        if thread is not None:
            thread.join(timeout=2.0)
        dest = Path(handle.dest_path)
        part = dest.with_suffix(dest.suffix + ".part")
        if delete_files:
            dest.unlink(missing_ok=True)
            part.unlink(missing_ok=True)
            message = "Removed and files deleted"
            save_path = None
        else:
            message = "Removed from queue; files kept"
            save_path = handle.progress.save_path
        handle.progress = DownloadProgress(
            state=DownloadState.REMOVED,
            progress=handle.progress.progress,
            message=message,
            save_path=save_path,
        )
        self._jobs.pop(handle.id, None)

    def _spawn(self, job: _Job) -> None:
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        job.thread = thread
        thread.start()

    def _run(self, job: _Job) -> None:
        handle = job.handle
        dest = Path(handle.dest_path)
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            with job.lock:
                if dest.exists() and not part.exists():
                    job.written = dest.stat().st_size
                    job.handle.progress = DownloadProgress(
                        state=DownloadState.DONE,
                        progress=1.0,
                        save_path=str(dest),
                        message="Already downloaded",
                    )
                    return
            self._download(job, dest, part)
        except Exception as exc:
            with job.lock:
                job.error = str(exc)
                job.handle.progress = DownloadProgress(
                    state=DownloadState.ERROR,
                    progress=_ratio(job.written, job.total),
                    message=str(exc),
                    save_path=str(part if part.exists() else dest),
                )


    def _download(self, job: _Job, dest: Path, part: Path) -> None:
        headers = {"User-Agent": HTTP_USER_AGENT, "Accept": "*/*"}
        if part.exists():
            job.written = part.stat().st_size
        elif dest.exists():
            job.written = dest.stat().st_size
            return
        if job.written > 0:
            headers["Range"] = f"bytes={job.written}-"

        with job.lock:
            job.handle.progress = DownloadProgress(
                state=DownloadState.DOWNLOADING,
                progress=_ratio(job.written, job.total),
                save_path=str(part),
                message="Downloading",
            )

        with httpx.Client(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            with client.stream("GET", job.handle.url, headers=headers) as response:
                if response.status_code == 416:
                    with job.lock:
                        job.handle.progress = DownloadProgress(
                            state=DownloadState.DONE,
                            progress=1.0,
                            save_path=str(dest),
                            message="Complete",
                        )
                    if part.exists() and not dest.exists():
                        part.replace(dest)
                    return
                response.raise_for_status()
                total_from_headers = _total_from_headers(response, job.written)
                if total_from_headers is not None:
                    job.total = total_from_headers
                mode = "ab" if job.written > 0 and response.status_code == 206 else "wb"
                if mode == "wb":
                    job.written = 0
                with part.open(mode) as fh:
                    for chunk in response.iter_bytes(chunk_size=_CHUNK):
                        if job.cancel.is_set():
                            return
                        if job.pause.is_set():
                            with job.lock:
                                job.handle.progress = DownloadProgress(
                                    state=DownloadState.PAUSED,
                                    progress=_ratio(job.written, job.total),
                                    save_path=str(part),
                                    message="Paused",
                                )
                            return
                        if not chunk:
                            continue
                        fh.write(chunk)
                        now = time.monotonic()
                        with job.lock:
                            job.written += len(chunk)
                            dt = max(now - job.last_time, 1e-6)
                            job.rate = (job.written - job.last_bytes) / dt
                            job.last_bytes = job.written
                            job.last_time = now
                            job.handle.progress = DownloadProgress(
                                state=DownloadState.DOWNLOADING,
                                progress=_ratio(job.written, job.total),
                                download_rate=job.rate,
                                save_path=str(part),
                                message="Downloading",
                            )

        if job.cancel.is_set() or job.pause.is_set():
            return
        part.replace(dest)
        with job.lock:
            job.handle.progress = DownloadProgress(
                state=DownloadState.DONE,
                progress=1.0,
                save_path=str(dest),
                message="Complete",
            )


def _ratio(written: int, total: int | None) -> float:
    if not total or total <= 0:
        return 0.0
    return max(0.0, min(1.0, written / total))


def _total_from_headers(response: httpx.Response, already: int) -> int | None:
    content_range = response.headers.get("Content-Range")
    if content_range and "/" in content_range:
        tail = content_range.rsplit("/", 1)[-1].strip()
        if tail.isdigit():
            return int(tail)
    length = response.headers.get("Content-Length")
    if length and length.isdigit():
        n = int(length)
        if response.status_code == 206:
            return already + n
        return n
    return None


def _progress_from_job(job: _Job) -> DownloadProgress:
    current = job.handle.progress
    if current.state in {DownloadState.DONE, DownloadState.ERROR, DownloadState.REMOVED}:
        return current
    if job.pause.is_set() and current.state != DownloadState.DOWNLOADING:
        return DownloadProgress(
            state=DownloadState.PAUSED,
            progress=_ratio(job.written, job.total),
            save_path=current.save_path,
            message="Paused",
        )
    return DownloadProgress(
        state=current.state,
        progress=_ratio(job.written, job.total) if current.state != DownloadState.DONE else current.progress,
        download_rate=job.rate if current.state == DownloadState.DOWNLOADING else 0.0,
        save_path=current.save_path,
        message=current.message,
    )
