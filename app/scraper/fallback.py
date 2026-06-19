"""Fallback chain — tries a sequence of scrapers until one succeeds."""

from __future__ import annotations

import logging

import httpx

from app.scraper.base import (
    AllScrapersFailed, BaseScraper, ScrapedMetadata, ScraperError,
    NotFoundError, ParseError, NetworkError,
)
from app.scraper.cache import not_found_cache

logger = logging.getLogger(__name__)


class FallbackChain:
    """
    Executes a priority-ordered chain of scrapers.

    Each scraper is asked ``can_handle(code, filename)``. The first scraper
    that returns ``True`` is used. If it fails with ``ScraperError``, the
    chain continues to the next scraper.

    **404 Cache Integration**: Before trying a scraper, the chain checks
    ``NotFoundCache`` to skip sources that previously returned 404 for this code.

    If all scrapers fail, ``AllScrapersFailed`` is raised.
    """

    def __init__(self, scraper_classes: list[type[BaseScraper]]) -> None:
        self._scraper_classes = scraper_classes

    async def execute(self, code: str, filename: str) -> tuple[ScrapedMetadata, BaseScraper]:
        """
        Run the fallback chain.

        Returns:
            (metadata, scraper_instance) on first success.

        Raises:
            AllScrapersFailed: if every scraper fails.
        """
        failures: list[ScraperError] = []

        for cls in self._scraper_classes:
            # Skip if this source previously 404'd for this code
            if not_found_cache.is_not_found(code, cls.name):
                logger.info("[%s] 跳过 (404缓存): %s", cls.name, code)
                continue

            async with cls() as scraper:
                # Check applicability
                try:
                    applicable = await scraper.can_handle(code, filename)
                except Exception as exc:
                    logger.debug("can_handle error [%s]: %s", cls.name, exc)
                    failures.append(ScraperError(cls.name, f"can_handle error: {exc}"))
                    continue

                if not applicable:
                    logger.debug("Skipping %s (can_handle=False)", cls.name)
                    continue

                # Attempt scraping
                try:
                    metadata = await scraper.scrape(code, filename)
                    logger.info("Scraped via %s: '%s'", cls.name, metadata.title)
                    return metadata, scraper

                except ScraperError as exc:
                    logger.warning("Scraper %s failed: %s", cls.name, exc.message)
                    failures.append(exc)
                    # Cache 404-like failures per source
                    if _is_not_found_failure(exc):
                        not_found_cache.mark_not_found(code, cls.name, exc.url or "")
                    continue

                except httpx.HTTPError as exc:
                    logger.warning("Scraper %s HTTP error: %s", cls.name, exc)
                    failures.append(ScraperError(cls.name, str(exc)))
                    continue

                except Exception as exc:
                    logger.exception("Scraper %s unexpected error", cls.name)
                    failures.append(ScraperError(cls.name, f"Unexpected: {exc}"))
                    continue

        raise AllScrapersFailed(failures)


def _is_not_found_failure(exc: ScraperError) -> bool:
    """Heuristic: does this ScraperError indicate the code truly doesn't exist?"""
    msg = exc.message.lower() if exc.message else ""
    indicators = [
        "not found", "not found", "notfound",
        "番号未找到", "找不到", "不存在",
        "未找到", "not exist",
    ]
    return any(ind in msg for ind in indicators)

