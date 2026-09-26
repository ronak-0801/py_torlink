"""Common interface for HTTP / direct-download sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from pytorlink.httpdl.types import HttpFileResult


class HttpSource(ABC):
    """A searchable provider of directly downloadable http(s) files.

    Sources come in two shapes. Some (Wikimedia Commons) return a concrete file
    URL straight from search. Others (Archive.org, NASA) return an item id that
    needs a second request to pick a file, and override :meth:`resolve`.
    """

    id: str
    label: str
    # Sent alongside the shared defaults in pytorlink.sources.http.
    headers: dict[str, str] = {}

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        client: httpx.AsyncClient | None = None,
    ) -> list[HttpFileResult]:
        """Return results for *query*. May raise; the registry soft-fails."""

    async def resolve(
        self,
        result: HttpFileResult,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> HttpFileResult:
        """Turn a search result into one with a concrete URL.

        The default suits sources whose search already returns a file URL.
        """
        if (result.url or "").strip():
            return result
        raise ValueError(f"{self.label} returned no URL for: {result.name}")
