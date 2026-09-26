"""CLI mode selection (torrent vs http)."""

from __future__ import annotations

import pytest

from pytorlink.cli import build_parser, prompt_mode, resolve_mode


def test_parser_accepts_torrent_and_http() -> None:
    parser = build_parser()
    torrent = parser.parse_args(["torrent", "--download-dir", "/tmp/t"])
    assert torrent.mode == "torrent"
    assert torrent.download_dir == "/tmp/t"
    http = parser.parse_args(["http"])
    assert http.mode == "http"
    bare = parser.parse_args([])
    assert bare.mode is None


def test_parser_rejects_unknown_mode() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["fmhy"])


def test_prompt_mode_accepts_aliases() -> None:
    assert prompt_mode(input_fn=lambda _: "1") == "torrent"
    assert prompt_mode(input_fn=lambda _: "http") == "http"
    assert prompt_mode(input_fn=lambda _: "2") == "http"


def test_prompt_mode_retries_then_accepts() -> None:
    answers = iter(["nope", "torrent"])

    def _read(_: str) -> str:
        return next(answers)

    assert prompt_mode(input_fn=_read) == "torrent"


def test_resolve_mode_explicit() -> None:
    assert resolve_mode("http") == "http"
    assert resolve_mode("torrent") == "torrent"


def test_resolve_mode_noninteractive_requires_flag() -> None:
    with pytest.raises(SystemExit):
        resolve_mode(None, interactive=False)
