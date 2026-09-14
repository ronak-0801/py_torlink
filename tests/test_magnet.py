"""Magnet builder / parser tests."""

from __future__ import annotations

import pytest

from pytorlink.sources.magnet import (
    build_magnet,
    looks_like_info_hash,
    looks_like_magnet,
    normalize_info_hash,
    parse_magnet,
)


def test_normalize_info_hash_hex():
    h = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"
    assert normalize_info_hash(h) == h.lower()
    assert normalize_info_hash("urn:btih:" + h) == h.lower()


def test_normalize_rejects_bad():
    with pytest.raises(ValueError):
        normalize_info_hash("not-a-hash")


def test_build_and_parse_roundtrip():
    h = "abcdef0123456789abcdef0123456789abcdef01"
    uri = build_magnet(h, name="Test Film", trackers=("udp://tracker.example:80/announce",))
    assert uri.startswith("magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01")
    assert "dn=Test%20Film" in uri or "dn=Test+Film" in uri or "Test" in uri
    meta = parse_magnet(uri)
    assert meta["info_hash"] == h
    assert meta["name"] == "Test Film"
    assert "udp://tracker.example:80/announce" in meta["trackers"]


def test_looks_like_helpers():
    assert looks_like_magnet("magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01")
    assert looks_like_info_hash("abcdef0123456789abcdef0123456789abcdef01")
    assert not looks_like_magnet("hello")
    assert not looks_like_info_hash("short")
