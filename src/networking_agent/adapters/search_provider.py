from __future__ import annotations

import logging
import time

import httpx

from networking_agent.adapters.base import SearchProvider
from networking_agent.config import Settings
from networking_agent.schemas.prospect import SearchResult

logger = logging.getLogger("networking_agent.search")


class GoogleCSEProvider(SearchProvider):
    """Google Programmable Search Engine (JSON API). Legitimate, ToS-compliant
    web search -- not scraping. Requires GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX."""

    BASE_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str, max_retries: int = 3, timeout: float = 10.0):
        self.api_key = api_key
        self.cx = cx
        self.max_retries = max_retries
        self.timeout = timeout

    def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        results: list[SearchResult] = []
        # Google CSE returns up to 10 results per page; paginate via `start`.
        for start in range(1, min(num_results, 30) + 1, 10):
            params = {
                "key": self.api_key,
                "cx": self.cx,
                "q": query,
                "start": start,
            }
            data = self._get_with_retry(params)
            if not data:
                break
            for item in data.get("items", []):
                results.append(
                    SearchResult(
                        url=item.get("link", ""),
                        title=item.get("title", ""),
                        snippet=item.get("snippet", ""),
                        query=query,
                    )
                )
            if len(results) >= num_results or "items" not in data:
                break
        return results[:num_results]

    def _get_with_retry(self, params: dict) -> dict | None:
        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                resp = httpx.get(self.BASE_URL, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                logger.warning("search request failed (attempt %d): %s", attempt + 1, e)
                time.sleep(delay)
                delay *= 2
        logger.error("search request failed after %d attempts: %s", self.max_retries, params.get("q"))
        return None


class MockSearchProvider(SearchProvider):
    """Deterministic offline provider for development/tests when no search
    API credentials are configured. Returns clearly-labeled synthetic
    results so nobody mistakes them for real prospects."""

    def search(self, query: str, num_results: int = 10) -> list[SearchResult]:
        logger.info("MockSearchProvider used (no GOOGLE_CSE_API_KEY configured) for query=%r", query)
        return []


def get_search_provider(settings: Settings) -> SearchProvider:
    if settings.google_cse_api_key and settings.google_cse_cx:
        return GoogleCSEProvider(settings.google_cse_api_key, settings.google_cse_cx)
    return MockSearchProvider()
