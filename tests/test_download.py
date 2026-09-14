"""MagnetBackend + DownloadQueue pause/resume/remove contract."""

from __future__ import annotations

from pathlib import Path

from pytorlink.download.magnet_backend import MagnetBackend
from pytorlink.download.queue import DownloadQueue
from pytorlink.download.types import DownloadState
from pytorlink.sources.magnet import build_magnet

HASH_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
HASH_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _magnet(h: str = HASH_A, name: str = "Demo") -> str:
    return build_magnet(h, name=name)


def test_magnet_start_is_magnet_only_and_saves_file(tmp_path: Path):
    backend = MagnetBackend()
    handle = backend.start(_magnet(), name="Demo", info_hash=HASH_A, save_path=str(tmp_path))
    assert handle.progress.state == DownloadState.MAGNET_ONLY
    assert "no real download" in handle.progress.message.lower()
    files = list(tmp_path.glob("*.magnet"))
    assert len(files) == 1
    assert "magnet:" in files[0].read_text(encoding="utf-8")


def test_magnet_pause_resume_cycle(tmp_path: Path):
    backend = MagnetBackend()
    handle = backend.start(_magnet(), name="Demo", info_hash=HASH_A, save_path=str(tmp_path))
    backend.pause(handle)
    paused = backend.poll(handle)
    assert paused.state == DownloadState.PAUSED
    backend.resume(handle)
    resumed = backend.poll(handle)
    assert resumed.state == DownloadState.MAGNET_ONLY
    assert "no real download" in resumed.message.lower()


def test_magnet_remove_keeps_files_by_default(tmp_path: Path):
    backend = MagnetBackend()
    handle = backend.start(_magnet(), name="KeepMe", info_hash=HASH_A, save_path=str(tmp_path))
    files = list(tmp_path.glob("*.magnet"))
    assert files and files[0].exists()
    backend.remove(handle)
    assert files[0].exists()
    assert handle.progress.state == DownloadState.REMOVED
    assert "files kept" in handle.progress.message.lower()
    polled = backend.poll(handle)
    assert polled.state == DownloadState.REMOVED


def test_magnet_remove_delete_files_true_unlinks_magnet(tmp_path: Path):
    backend = MagnetBackend()
    handle = backend.start(_magnet(), name="WipeMe", info_hash=HASH_A, save_path=str(tmp_path))
    files = list(tmp_path.glob("*.magnet"))
    assert files
    backend.remove(handle, delete_files=True)
    assert not files[0].exists()
    assert handle.progress.state == DownloadState.REMOVED


def test_queue_pause_resume_remove_keeps_files(tmp_path: Path):
    queue = DownloadQueue(backend=MagnetBackend(), save_path=tmp_path)
    handle = queue.add_info_hash(HASH_A, name="Queued")
    assert handle.id in {h.id for h in queue.items}
    assert handle.progress.state == DownloadState.MAGNET_ONLY

    paused = queue.pause(handle.id)
    assert paused is not None
    assert paused.progress.state == DownloadState.PAUSED

    resumed = queue.resume(handle.id)
    assert resumed is not None
    assert resumed.progress.state == DownloadState.MAGNET_ONLY

    magnet_files = list(tmp_path.glob("*.magnet"))
    assert magnet_files
    removed = queue.remove(handle.id)
    assert removed is not None
    assert removed.progress.state == DownloadState.REMOVED
    assert queue.items == []
    assert magnet_files[0].exists()
    assert "files kept" in removed.progress.message


def test_queue_remove_delete_files_true(tmp_path: Path):
    queue = DownloadQueue(backend=MagnetBackend(), save_path=tmp_path)
    handle = queue.add_info_hash(HASH_B, name="Gone")
    files = list(tmp_path.glob("*.magnet"))
    assert files
    queue.remove(handle.id, delete_files=True)
    assert not files[0].exists()
    assert queue.items == []


def test_queue_unknown_id_is_noop(tmp_path: Path):
    queue = DownloadQueue(backend=MagnetBackend(), save_path=tmp_path)
    assert queue.pause("missing") is None
    assert queue.resume("missing") is None
    assert queue.remove("missing") is None


def test_download_state_includes_required_values():
    needed = {
        "queued",
        "downloading",
        "paused",
        "seeding",
        "done",
        "error",
        "magnet_only",
        "removed",
    }
    assert needed <= {s.value for s in DownloadState}
