"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pytorlink import __version__

MODE_MENU = """\
pytorlink — choose a mode
  1  torrent   Search torrent indexes (YTS, Nyaa, TPB, …)
  2  http      Direct HTTP downloads (Archive.org, Wikimedia, NASA / paste URL)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pytorlink",
        description="Terminal torrent search or HTTP direct download (separate modes).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pytorlink {__version__}",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("torrent", "http"),
        help="torrent = magnet/index search; http = open-archive search / paste URL. "
        "Omit to pick interactively when stdin is a TTY.",
    )
    parser.add_argument(
        "--download-dir",
        default=None,
        help="Override download directory "
        "(torrent default: ~/Downloads/pytorlink; "
        "http default: ~/Downloads/pytorlink/http)",
    )
    return parser


def prompt_mode(
    *,
    stdin=None,
    stdout=None,
    input_fn=None,
) -> str:
    """Ask for torrent vs http. Used when `pytorlink` is run with no mode."""
    out = stdout if stdout is not None else sys.stdout
    out.write(MODE_MENU)
    out.flush()
    read = input_fn
    if read is None:
        def read(prompt: str) -> str:
            out.write(prompt)
            out.flush()
            stream = stdin if stdin is not None else sys.stdin
            line = stream.readline()
            if line == "":
                raise EOFError
            return line

    while True:
        try:
            raw = read("Mode [1/2]: ").strip().lower()
        except EOFError as exc:
            raise SystemExit("No mode selected.") from exc
        if raw in {"1", "t", "torrent"}:
            return "torrent"
        if raw in {"2", "h", "http", "direct"}:
            return "http"
        out.write("Enter 1 (torrent) or 2 (http).\n")
        out.flush()


def resolve_mode(mode: str | None, *, interactive: bool | None = None) -> str:
    if mode in {"torrent", "http"}:
        return mode
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise SystemExit("Specify a mode: pytorlink torrent  or  pytorlink http")
    return prompt_mode()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    download_dir = Path(args.download_dir).expanduser() if args.download_dir else None
    mode = resolve_mode(args.mode)

    if mode == "http":
        from pytorlink.ui.http_app import HttpPytorlinkApp

        HttpPytorlinkApp(download_dir=download_dir).run()
        return 0

    from pytorlink.ui.app import PytorlinkApp

    PytorlinkApp(download_dir=download_dir).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
