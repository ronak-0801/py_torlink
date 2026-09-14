"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from pytorlink import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pytorlink",
        description="Terminal torrent search & download (TUI by default).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pytorlink {__version__}",
    )
    parser.add_argument(
        "--download-dir",
        default=None,
        help="Override download directory (default: ~/Downloads/pytorlink)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from pathlib import Path

    from pytorlink.ui.app import PytorlinkApp

    download_dir = Path(args.download_dir).expanduser() if args.download_dir else None
    app = PytorlinkApp(download_dir=download_dir)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
