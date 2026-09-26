"""HTTP / direct-download result types (separate from torrent search)."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from pytorlink import __version__

# Direct-download hosts get an agent that identifies the client. Wikimedia's
# robot policy rejects both spoofed browser agents and library defaults, so the
# browser UA in pytorlink.sources.http (needed to get past bot-gating on some
# torrent indexes) must not be reused here.
HTTP_USER_AGENT = f"pytorlink/{__version__} (https://github.com/ronak-0801/py_torlink)"

HTTP_API_HEADERS = {
    "User-Agent": HTTP_USER_AGENT,
    "Accept": "application/json",
}


class HttpSourceId:
    ARCHIVE = "archive"
    COMMONS = "commons"
    NASA = "nasa"
    URL = "url"


_SOURCE_LABELS = {
    HttpSourceId.ARCHIVE: "Archive.org",
    HttpSourceId.COMMONS: "Wikimedia",
    HttpSourceId.NASA: "NASA",
    HttpSourceId.URL: "URL",
}


def http_source_label(source: str) -> str:
    return _SOURCE_LABELS.get(source, source)


@dataclass(frozen=True, slots=True)
class HttpFileResult:
    """A direct HTTP file (or an Archive.org item that still needs file resolve)."""

    name: str
    url: str
    size_bytes: int | None
    source: str
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
    def source_label(self) -> str:
        return http_source_label(self.source)

    @property
    def needs_resolve(self) -> bool:
        return not (self.url or "").strip() and bool(self.extra.get("identifier"))


def looks_like_http_url(text: str) -> bool:
    """True for http(s) URLs with a host. Rejects other schemes."""
    raw = (text or "").strip()
    try:
        parsed = urlparse(raw)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    return True


def filename_from_url(url: str, fallback: str = "download") -> str:
    path = unquote(urlparse(url).path or "")
    name = path.rsplit("/", 1)[-1].strip()
    return name or fallback
