"""JavLib scraper — fetches AV metadata from javlib with fallback search."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.scraper.base import BaseScraper, ScrapedMetadata, ScrapingFailed

logger = logging.getLogger(__name__)

# Base URL — try both mirrors
_MIRRORS = [
    "https://www.javlibrary.com",
    "https://javlibrary.net",
]


class JavLibScraper(BaseScraper):
    """
    Scrape AV metadata from JavLib by product code.

    Workflow:
      1. Construct search URL from code (e.g. ABC-123)
      2. Parse search results page to find the detail page URL
      3. Parse the detail page for metadata
    """

    name = "javlib"
    label = "JavLib 刮削器"
    version = "1.0.0"
    priority = 20          # higher than demo, lower than future dedicated scrapers
    enabled = True
    requires_url = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_code(code: str) -> str:
        """ABC-123  →  ABC-123  (preserve dash, uppercase)."""
        return code.strip().upper()

    async def _search(self, code: str) -> str | None:
        """
        Search JavLib for *code* and return the detail page URL.

        Returns ``None`` if no match is found.
        """
        norm = self._normalize_code(code)
        for base in _MIRRORS:
            try:
                # JavLib search: /search?q=ABC-123
                url = f"{base}/search?q={norm}"
                soup = await self.fetch_soup(url)
                # Search results: first <a class="movie" href="...">
                link = soup.select_one('a.movie[href*="/video/"]')
                if link and link.get("href"):
                    return base + link["href"]
            except Exception as exc:
                logger.debug("JavLib search failed on %s: %s", base, exc)
                continue
        return None

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------

    async def can_handle(self, code: str, filename: str) -> bool:
        """Accept filenames / codes that look like an AV product code."""
        text = (code or "") + " " + (filename or "")
        # Pattern: 2+ letters, optional dash, 2+ digits  (e.g. ABC-123, DEF123)
        return bool(re.search(r"[A-Za-z]{2,}\s*-?\s*\d{2,}", text))

    async def scrape(
        self, code: str, filename: str, search_url: str | None = None
    ) -> ScrapedMetadata:
        norm = self._normalize_code(code)

        # If caller already provided a detail-page URL use it directly
        detail_url = search_url or await self._search(norm)
        if not detail_url:
            raise ScrapingFailed(self.name, f"找不到番号: {norm}")

        logger.info("JavLib scraping %s  →  %s", norm, detail_url)
        soup = await self.fetch_soup(detail_url)

        # ---- Title ----
        title = (
            self.safe_extract(soup, "h3.video-title", None)
            or self.safe_extract(soup, "title", None)
            or norm
        )
        # Clean trailing site name
        title = re.sub(r"\s*-\s*JavLib.*$", "", title, flags=re.I).strip()

        # ---- Poster ----
        poster_url = (
            self.safe_extract(soup, "img.video-cover", "src")
            or self.safe_extract(soup, "meta[property='og:image']", "content")
        )

        # ---- Plot ----
        plot = (
            self.safe_extract(soup, "div.video-plot", None)
            or self.safe_extract(soup, "meta[property='og:description']", "content")
        )

        # ---- Year / Premiered ----
        premiered = None
        year = None
        date_text = (
            self.safe_extract(soup, "span.video-date", None)
            or self.safe_extract(soup, "meta[itemprop='datePublished']", "content")
        )
        if date_text:
            m = re.search(r"(\d{4})", date_text)
            if m:
                year = int(m.group(1))
                premiered = f"{m.group(1)}-01-01"

        # ---- Runtime (minutes) ----
        runtime = None
        rt_text = self.safe_extract(soup, "span.video-length", None)
        if rt_text:
            m = re.search(r"(\d+)", rt_text)
            if m:
                runtime = int(m.group(1))

        # ---- Genres ----
        genres = self.safe_extract_all(soup, "span.video-genre", None)

        # ---- Actors ----
        actor_els = soup.select("span.video-actress a")
        actors: list[dict[str, Any]] = []
        for a in actor_els:
            actors.append({"name": a.get_text(strip=True)})

        # ---- Director ----
        director = self.safe_extract(soup, "span.video-director a", None)

        # ---- Studio ----
        studio = self.safe_extract(soup, "span.video-studio a", None)

        # ---- Rating ----
        rating = None
        rating_text = self.safe_extract(soup, "span.video-rating", None)
        if rating_text:
            m = re.search(r"(\d+(?:\.\d+)?)", rating_text)
            if m:
                rating = float(m.group(1))

        return ScrapedMetadata(
            title=title,
            original_title=None,
            plot=plot,
            poster_url=poster_url,
            fanart_urls=[],
            year=year,
            premiered=premiered,
            runtime=runtime,
            genres=genres,
            tags=[],
            actors=actors,
            director=director,
            studio=studio,
            rating=rating,
            source_plugin=self.name,
            source_url=detail_url,
            raw_data={},
        )
