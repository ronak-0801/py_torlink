"""User config helpers (enabled search sources)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pytorlink.sources.types import SourceId

log = logging.getLogger(__name__)

CONFIG_DIR_NAME = "pytorlink"
SOURCES_FILENAME = "sources.json"


def config_dir() -> Path:
    """Return XDG-ish config directory: ``$XDG_CONFIG_HOME/pytorlink`` or ``~/.config/pytorlink``."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser() / CONFIG_DIR_NAME
    return Path.home() / ".config" / CONFIG_DIR_NAME


def sources_config_path() -> Path:
    return config_dir() / SOURCES_FILENAME


def load_enabled_source_ids(default: set[SourceId]) -> set[SourceId]:
    """Load enabled source ids from config; fall back to *default* on missing/invalid."""
    path = sources_config_path()
    try:
        if not path.is_file():
            return set(default)
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("enabled") if isinstance(data, dict) else None
        if not isinstance(raw, list) or not raw:
            return set(default)
        out: set[SourceId] = set()
        for item in raw:
            try:
                out.add(SourceId(str(item)))
            except ValueError:
                continue
        return out if out else set(default)
    except Exception as exc:
        log.debug("sources config load failed: %s", exc)
        return set(default)


def save_enabled_source_ids(enabled: set[SourceId] | set[str]) -> None:
    """Persist enabled source ids (best-effort)."""
    path = sources_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ids = sorted(
            {
                (e.value if isinstance(e, SourceId) else str(e))
                for e in enabled
            }
        )
        path.write_text(
            json.dumps({"enabled": ids}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        log.debug("sources config save failed: %s", exc)
