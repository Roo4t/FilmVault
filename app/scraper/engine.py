"""Scraper engine — orchestrates scraping with fallback chains, retry, and rate limiting."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Callable, Coroutine

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import config
from app.scraper.base import (
    AllScrapersFailed,
    BaseScraper,
    ScrapedMetadata,
    ScraperError,
    NetworkError,
    ParseError,
    NotFoundError,
)
from app.scraper.cache import not_found_cache
from app.scraper.fallback import FallbackChain, _is_not_found_failure
from app.scraper.registry import ScraperRegistry

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str | None, int, int], Coroutine[Any, Any, None]]
"""Progress callback signature: (task_id, completed, total) -> awaitable."""


class ScrapeEngine:
    """
    Orchestrates scraping operations with retry and rate limiting.

    - Single-file scraping with optional scraper override
    - Batch scraping with semaphore-controlled concurrency + progress tracking
    - Exponential backoff retry on transient failures
    - Rate limiting to avoid IP bans
    """

    def __init__(self, registry: ScraperRegistry, session: AsyncSession):
        self._registry = registry
        self._session = session
        self._request_timestamps: list[float] = []
        self._rate_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape_single(
        self, code: str, filename: str, scraper_name: str | None = None
    ) -> tuple[ScrapedMetadata, BaseScraper]:
        """
        Scrape metadata for a single file.

        Args:
            code: Parsed identifier code.
            filename: Original filename.
            scraper_name: If provided, use this specific scraper instead of fallback chain.

        Returns:
            (metadata, scraper_instance)

        Raises:
            AllScrapersFailed: if no scraper can handle the file.
        """
        if scraper_name:
            return await self._scrape_with_specific(code, filename, scraper_name)

        return await self._scrape_with_retry(code, filename)

    async def scrape_parallel(
        self, code: str, filename: str, *, max_concurrent: int = 3
    ) -> tuple[ScrapedMetadata, BaseScraper]:
        """
        Multi-source parallel aggregation — launch all enabled scrapers
        simultaneously, return the first successful result.

        Reference: Emby.Plugins.JavScraper Task.WhenAll aggregation.

        Args:
            code: Parsed identifier code.
            filename: Original filename.
            max_concurrent: Maximum concurrent scrapers.

        Returns:
            (metadata, scraper_instance) from the fastest successful scraper.

        Raises:
            AllScrapersFailed: if every scraper fails or times out.
        """
        enabled_cls = self._registry.get_enabled()
        if not enabled_cls:
            raise ScraperError("engine", "No scrapers registered or enabled")

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _try_scrape(cls: type[BaseScraper]) -> tuple[ScrapedMetadata, BaseScraper] | None:
            """Attempt to scrape with one scraper (returns None if fails)."""
            async with semaphore:
                # Skip cache
                if not_found_cache.is_not_found(code, cls.name):
                    logger.debug("[parallel] skip cached: %s", cls.name)
                    return None

                try:
                    await self._rate_limit()
                    async with cls() as scraper:
                        if not await scraper.can_handle(code, filename):
                            return None
                        metadata = await scraper.scrape(code, filename)
                        if metadata and metadata.title:
                            logger.info("[parallel] won via %s: %s", cls.name, metadata.title)
                            return metadata, scraper
                except ScraperError as exc:
                    logger.debug("[parallel] %s failed: %s", cls.name, exc.message)
                    if _is_not_found_failure(exc):
                        not_found_cache.mark_not_found(code, cls.name, exc.url or "")
                except Exception as exc:
                    logger.debug("[parallel] %s exception: %s", cls.name, exc)
                return None

        # Launch all in parallel, race to completion
        tasks = {asyncio.create_task(_try_scrape(cls)): cls for cls in enabled_cls}
        failures: list[ScraperError] = []

        try:
            while tasks:
                done, pending = await asyncio.wait(
                    tasks.keys(), return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    del tasks[task]  # remove from tracking
                    try:
                        result = task.result()
                        if result is not None:
                            # Cancel remaining tasks
                            for p in tasks:
                                if not p.done():
                                    p.cancel()
                            return result
                    except Exception:
                        failures.append(ScraperError("parallel", f"Task error: {task.exception()}"))
        finally:
            # Clean up any uncancelled tasks
            for t in list(tasks.keys()):
                if not t.done():
                    t.cancel()

        raise AllScrapersFailed(failures)

    async def scrape_batch(
        self,
        items: list[dict[str, Any]],
        *,
        concurrency: int = 3,
        on_progress: ProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        """
        Scrape metadata for multiple files concurrently.

        Args:
            items: List of {'video_id': int, 'code': str, 'filename': str} dicts.
            concurrency: Max concurrent scraping tasks (overridden by config if set).
            on_progress: Optional callback(task_id, completed, total).

        Returns:
            List of result dicts with status, title, error, etc.
        """
        concurrency = concurrency or config.scraper_concurrency or 3
        semaphore = asyncio.Semaphore(concurrency)
        total = len(items)
        # Fix: use list comprehension instead of [{}] * total (shallow copy bug)
        results: list[dict[str, Any] | None] = [None] * total

        async def _worker(index: int, item: dict[str, Any]) -> None:
            async with semaphore:
                vid = item["video_id"]
                start = time.monotonic()
                try:
                    metadata, scraper = await self.scrape_single(
                        code=item.get("code", ""),
                        filename=item.get("filename", ""),
                    )
                    duration_ms = int((time.monotonic() - start) * 1000)
                    results[index] = {
                        "video_id": vid,
                        "status": "ok",
                        "title": metadata.title,
                        "plugin": metadata.source_plugin,
                        "duration_ms": duration_ms,
                        "metadata": metadata,
                    }
                except (ScraperError, AllScrapersFailed) as exc:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    results[index] = {
                        "video_id": vid,
                        "status": "failed",
                        "error": str(exc),
                        "duration_ms": duration_ms,
                    }
                except Exception as exc:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    results[index] = {
                        "video_id": vid,
                        "status": "failed",
                        "error": f"Unexpected: {exc}",
                        "duration_ms": duration_ms,
                    }

            if on_progress:
                completed = sum(1 for r in results if r is not None)
                await on_progress(None, completed, total)

        tasks = [_worker(i, item) for i, item in enumerate(items)]
        await asyncio.gather(*tasks)

        # Ensure all entries are dicts (should never be None at this point)
        return [r if r is not None else {"video_id": 0, "status": "failed", "error": "internal: missing result"}
                for r in results]

    # ------------------------------------------------------------------
    # Retry & rate limiting
    # ------------------------------------------------------------------

    async def _scrape_with_retry(
        self, code: str, filename: str
    ) -> tuple[ScrapedMetadata, BaseScraper]:
        """
        Run fallback chain with per-scraper retry.

        Each scraper in the chain gets up to ``config.scraper_retry`` attempts
        before the chain moves to the next scraper.
        """
        max_retries = config.scraper_retry
        enabled_cls = self._registry.get_enabled()
        if not enabled_cls:
            raise ScraperError("engine", "No scrapers registered or enabled")

        for cls in enabled_cls:
            # 404 缓存跳过
            if not_found_cache.is_not_found(code, cls.name):
                logger.info("[%s] 跳过 (404缓存): %s", cls.name, code)
                continue

            for attempt in range(max_retries + 1):
                try:
                    await self._rate_limit()

                    async with cls() as scraper:
                        if not await scraper.can_handle(code, filename):
                            logger.debug("[%s] can_handle=False, skip", cls.name)
                            break  # 跳出retry循环，进入下一个scraper

                        metadata = await scraper.scrape(code, filename)
                        if metadata and metadata.title:
                            logger.info(
                                "[%s] 刮削成功 (attempt %d/%d): %s",
                                cls.name, attempt + 1, max_retries + 1, metadata.title,
                            )
                            return metadata, scraper

                        logger.warning("[%s] 返回数据缺少标题 (attempt %d)", cls.name, attempt + 1)

                except ScraperError as exc:
                    logger.warning(
                        "[%s] 刮削失败 (attempt %d/%d): %s",
                        cls.name, attempt + 1, max_retries + 1, exc.message,
                    )
                    # 如果是明确的"未找到"错误，记录到404缓存
                    if _is_not_found_failure(exc):
                        not_found_cache.mark_not_found(code, cls.name, exc.url or "")
                        break  # 不重试，直接尝试下一个scraper
                except Exception as exc:
                    logger.warning(
                        "[%s] 异常 (attempt %d/%d): %s",
                        cls.name, attempt + 1, max_retries + 1, exc,
                    )

                if attempt < max_retries:
                    # 指数退避 + 随机抖动
                    delay = min(2 ** attempt + random.uniform(0, 1), 10)
                    logger.debug("[%s] %.1fs 后重试...", cls.name, delay)
                    await asyncio.sleep(delay)

        raise AllScrapersFailed([ScraperError("engine", f"All scrapers failed for code: {code}")])

    async def _rate_limit(self) -> None:
        """Rate limiting with random jitter: 500ms-1500ms base + ±200ms jitter."""
        base_min = 0.5   # 500ms minimum
        base_max = 1.5   # 1500ms (prevent too-fast bursts)
        async with self._rate_lock:
            now = time.monotonic()
            if self._request_timestamps:
                elapsed = now - self._request_timestamps[-1]
                # Random interval between base_min and base_max with jitter
                required = base_min + random.uniform(0, base_max - base_min)
                if elapsed < required:
                    await asyncio.sleep(required - elapsed)
            self._request_timestamps.append(time.monotonic())
            # Keep only last 50 timestamps to prevent unbounded growth
            if len(self._request_timestamps) > 50:
                self._request_timestamps = self._request_timestamps[-25:]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _scrape_with_specific(
        self, code: str, filename: str, scraper_name: str
    ) -> tuple[ScrapedMetadata, BaseScraper]:
        """Use a specific named scraper with retry."""
        cls = self._registry.get(scraper_name)
        if cls is None:
            raise ScraperError("engine", f"Scraper '{scraper_name}' not found")
        if not cls.enabled:
            raise ScraperError("engine", f"Scraper '{scraper_name}' is disabled")

        max_retries = config.scraper_retry

        for attempt in range(max_retries + 1):
            await self._rate_limit()

            async with cls() as scraper:
                try:
                    if not await scraper.can_handle(code, filename):
                        raise ScraperError(
                            scraper_name, f"Scraper cannot handle code '{code}'"
                        )
                    metadata = await scraper.scrape(code, filename)
                    if metadata and metadata.title:
                        return metadata, scraper
                except ScraperError:
                    raise  # 指定scraper失败不重试（调用方期望精确行为）
                except Exception as exc:
                    if attempt < max_retries:
                        delay = min(2 ** attempt + random.uniform(0, 1), 10)
                        logger.debug("[%s] retry %.1fs...", scraper_name, delay)
                        await asyncio.sleep(delay)
                    else:
                        raise ScraperError(scraper_name, str(exc)) from exc

        raise ScraperError(scraper_name, f"All {max_retries + 1} attempts failed for '{code}'")
