"""Enabled-sources defaults and config persistence."""

from __future__ import annotations

from pathlib import Path

import pytorlink.config as cfg
from pytorlink.sources.registry import (
    DEFAULT_SOURCE_IDS,
    DISABLED_BY_DEFAULT,
    SOURCES,
    default_sources,
    sources_for_ids,
)
from pytorlink.sources.types import SourceId


def test_bittorrented_disabled_by_default() -> None:
    assert SourceId.BITTORRENTED in DISABLED_BY_DEFAULT
    assert SourceId.BITTORRENTED not in DEFAULT_SOURCE_IDS
    ids = {s.id for s in default_sources()}
    assert SourceId.BITTORRENTED not in ids
    assert SourceId.EXT_TO in ids
    assert SourceId.YTS in ids


def test_ext_to_registered() -> None:
    labels = {s.label for s in SOURCES}
    assert "EXT" in labels
    assert any(s.id == SourceId.EXT_TO for s in SOURCES)


def test_sources_for_ids_filters() -> None:
    srcs = sources_for_ids([SourceId.YTS, SourceId.EXT_TO])
    assert [s.id for s in srcs] == [SourceId.YTS, SourceId.EXT_TO]


def test_sources_config_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    enabled = {SourceId.YTS, SourceId.NYAA, SourceId.EXT_TO}
    cfg.save_enabled_source_ids(enabled)
    path = cfg.sources_config_path()
    assert path.is_file()
    loaded = cfg.load_enabled_source_ids(set(DEFAULT_SOURCE_IDS))
    assert loaded == enabled
