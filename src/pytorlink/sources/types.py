"""Source protocol and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class SourceId(str, Enum):
    YTS = "yts"
    NYAA = "nyaa"
    PIRATEBAY = "piratebay"
    EZTV = "eztv"
    SUBSPLEASE = "subsplease"
    BITTORRENTED = "bittorrented"
    FITGIRL = "fitgirl"
    EXT_TO = "ext_to"


SOURCE_LABELS: dict[SourceId, str] = {
    SourceId.YTS: "YTS",
    SourceId.NYAA: "Nyaa",
    SourceId.PIRATEBAY: "TPB",
    SourceId.EZTV: "EZTV",
    SourceId.SUBSPLEASE: "SubsPlease",
    SourceId.BITTORRENTED: "BitTorrented",
    SourceId.FITGIRL: "FitGirl",
    SourceId.EXT_TO: "EXT",
}


def source_label(source: SourceId | str) -> str:
    if isinstance(source, SourceId):
        return SOURCE_LABELS.get(source, source.value)
    try:
        return SOURCE_LABELS.get(SourceId(source), str(source))
    except ValueError:
        return str(source)


@dataclass(frozen=True, slots=True)
class TorrentResult:
    """A single searchable torrent hit from any source."""

    name: str
    info_hash: str
    size_bytes: int | None
    seeders: int | None
    source: SourceId
    magnet: str
    leechers: int | None = None
    category: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def size_label(self) -> str:
        if self.size_bytes is None:
            return "?"
        n = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024.0 or unit == "TB":
                if unit == "B":
                    return f"{int(n)} {unit}"
                return f"{n:.1f} {unit}"
            n /= 1024.0
        return f"{self.size_bytes} B"

    @property
    def seeders_label(self) -> str:
        if self.seeders is None:
            return "?"
        return str(self.seeders)

    @property
    def source_label(self) -> str:
        return source_label(self.source)


@runtime_checkable
class Source(Protocol):
    """Async search source contract."""

    id: SourceId
    label: str

    async def search(self, query: str, *, limit: int = 50) -> list[TorrentResult]:
        """Return results for *query*; raise on hard failure (caller soft-fails)."""
        ...


def dedupe_by_info_hash(results: list[TorrentResult]) -> list[TorrentResult]:
    """Keep the highest-seeder hit per normalized info hash."""
    best: dict[str, TorrentResult] = {}
    for item in results:
        key = item.info_hash.lower()
        prev = best.get(key)
        if prev is None:
            best[key] = item
            continue
        prev_seeds = prev.seeders if prev.seeders is not None else -1
        cur_seeds = item.seeders if item.seeders is not None else -1
        if cur_seeds > prev_seeds:
            best[key] = item
    return list(best.values())


def sort_by_seeders(results: list[TorrentResult]) -> list[TorrentResult]:
    """Sort descending by seeders; unknown seeders last."""
    return sorted(
        results,
        key=lambda r: (r.seeders is not None, r.seeders or 0),
        reverse=True,
    )
