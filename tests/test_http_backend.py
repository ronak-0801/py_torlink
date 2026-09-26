"""HttpBackend + HttpDownloadQueue against a local HTTP server."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from pytorlink.download.http_backend import HttpBackend
from pytorlink.download.http_queue import HttpDownloadQueue
from pytorlink.download.types import DownloadState

PAYLOAD = b"abcdefghijklmnopqrstuvwxyz" * 40  # 1040 bytes

SEEN_USER_AGENTS: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        SEEN_USER_AGENTS.append(self.headers.get("User-Agent") or "")
        data = PAYLOAD
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            start_s = range_header.split("=", 1)[1].split("-", 1)[0]
            start = int(start_s or 0)
            chunk = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@pytest.fixture()
def http_file_server():
    SEEN_USER_AGENTS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    url = f"http://{host}:{port}/blob.bin"
    yield url
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _wait_done(backend: HttpBackend, handle, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        progress = backend.poll(handle)
        if progress.state in {DownloadState.DONE, DownloadState.ERROR}:
            return progress
        time.sleep(0.05)
    return backend.poll(handle)


def test_http_backend_downloads_file(tmp_path: Path, http_file_server: str) -> None:
    backend = HttpBackend(timeout=5.0)
    handle = backend.start(http_file_server, name="blob.bin", save_path=str(tmp_path))
    progress = _wait_done(backend, handle)
    assert progress.state == DownloadState.DONE
    dest = Path(handle.dest_path)
    assert dest.read_bytes() == PAYLOAD


def test_http_queue_pause_resume_remove(tmp_path: Path, http_file_server: str) -> None:
    queue = HttpDownloadQueue(backend=HttpBackend(timeout=5.0), save_path=tmp_path)
    handle = queue.add_url(http_file_server, name="blob.bin")
    progress = _wait_done(queue.backend, handle)
    assert progress.state == DownloadState.DONE

    paused = queue.pause(handle.id)
    assert paused is not None
    resumed = queue.resume(handle.id)
    assert resumed is not None

    dest = Path(handle.dest_path)
    assert dest.exists()
    removed = queue.remove(handle.id, delete_files=False)
    assert removed is not None
    assert dest.exists()
    assert handle.id not in {h.id for h in queue.items}


def test_http_backend_rejects_non_http(tmp_path: Path) -> None:
    backend = HttpBackend()
    with pytest.raises(ValueError):
        backend.start("file:///etc/passwd", name="x", save_path=str(tmp_path))


def test_http_backend_identifies_itself(tmp_path: Path, http_file_server: str) -> None:
    """Wikimedia 403s spoofed browser agents, so downloads must identify the client."""
    backend = HttpBackend(timeout=5.0)
    handle = backend.start(http_file_server, name="blob.bin", save_path=str(tmp_path))
    assert _wait_done(backend, handle).state == DownloadState.DONE
    assert SEEN_USER_AGENTS
    for agent in SEEN_USER_AGENTS:
        assert agent.startswith("pytorlink/")
        assert "Mozilla" not in agent
