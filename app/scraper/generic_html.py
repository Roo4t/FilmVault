"""Generic HTML scraper — extracts metadata from any public web page.

This is the ultimate fallback scraper (priority=999). It parses standard
web metadata formats: Open Graph tags, Twitter Cards, meta descriptions,
and JSON-LD structured data.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from app.scraper.base import BaseScraper, ScrapedMetadata, ScrapingFailed

logger = logging.getLogger(__name__)


class GenericHTMLScraper(BaseScraper):
    """
    Universal HTML metadata extractor.

    Handles:
    - Open Graph (og:title, og:image, og:description, og:video:duration)
    - Twitter Card (twitter:title, twitter:image)
    - Standard <meta> tags (description, keywords)
    - JSON-LD structured data (VideoObject, Movie schema)
    - Largest <img> as poster fallback
    """

    name = "generic_html"
    label = "通用HTML提取器"
    version = "1.0.0"
    priority = 999
    enabled = True
    requires_url = True
    """This scraper requires the user (or a site-specific plugin) to provide a URL."""

    async def can_handle(self, code: str, filename: str) -> bool:
        """Always returns True — this is the last-resort fallback."""
        return True

    async def scrape(
        self, code: str, filename: str, search_url: str | None = None
    ) -> ScrapedMetadata:
        """
        Scrape metadata from a web page.

        Requires ``search_url`` to be provided — without it, this scraper
        cannot function. Site-specific plugins should provide the URL.
        """
        if not search_url:
            raise ScrapingFailed(
                self.name,
                "GenericHTMLScraper requires a URL. Provide via search_url parameter "
                "or configure a site-specific plugin.",
            )

        soup = await self.fetch_soup(search_url)

        # ---- Extract from Open Graph ----
        title = (
            self.safe_extract(soup, 'meta[property="og:title"]', "content")
            or self.safe_extract(soup, 'meta[name="twitter:title"]', "content")
            or self.safe_extract(soup, "title")
        )

        if not title:
            raise ScrapingFailed(self.name, "No title found in page", search_url)

        # ---- Poster image ----
        poster = (
            self.safe_extract(soup, 'meta[property="og:image"]', "content")
            or self.safe_extract(soup, 'meta[name="twitter:image"]', "content")
            or self._find_largest_image(soup)
        )

        # ---- Description / Plot ----
        plot = (
            self.safe_extract(soup, 'meta[property="og:description"]', "content")
            or self.safe_extract(soup, 'meta[name="description"]', "content")
        )

        # ---- Duration (og:video:duration is in seconds) ----
        runtime = None
        duration_str = self.safe_extract(soup, 'meta[property="og:video:duration"]', "content")
        if duration_str:
            try:
                runtime = int(duration_str) // 60  # seconds → minutes
            except ValueError:
                pass

        # ---- Keywords / Tags ----
        keywords_str = self.safe_extract(soup, 'meta[name="keywords"]', "content")
        tags = [t.strip() for t in keywords_str.split(",") if t.strip()] if keywords_str else []

        # ---- JSON-LD structured data ----
        ld_data = self._extract_jsonld(soup)
        ld_title = ld_data.get("name", "")
        ld_description = ld_data.get("description", "")
        ld_thumbnail = ""
        ld_duration = None

        if isinstance(ld_data.get("thumbnailUrl"), list):
            ld_thumbnail = ld_data["thumbnailUrl"][0] if ld_data["thumbnailUrl"] else ""
        elif isinstance(ld_data.get("thumbnailUrl"), str):
            ld_thumbnail = ld_data["thumbnailUrl"]

        if ld_data.get("duration"):
            ld_duration = self._parse_iso_duration(ld_data["duration"])

        # ---- Merge (prefer OG over JSON-LD) ----
        return ScrapedMetadata(
            title=ld_title or title,
            original_title=None,
            plot=ld_description or plot,
            poster_url=poster or ld_thumbnail or None,
            year=self._extract_year(soup, ld_data),
            runtime=runtime or ld_duration,
            tags=tags,
            source_plugin=self.name,
            source_url=search_url,
            raw_data={"og_title": title, "jsonld": ld_data},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_jsonld(soup: BeautifulSoup) -> dict:
        """Extract JSON-LD structured data from <script type='application/ld+json'>."""
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
                # Handle @graph
                if isinstance(data, dict) and "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") in (
                            "VideoObject", "Movie", "CreativeWork"
                        ):
                            return item
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, TypeError):
                continue
        return {}

    @staticmethod
    def _find_largest_image(soup: BeautifulSoup) -> str | None:
        """Find the largest <img> by width/height attributes or natural dimensions."""
        imgs = soup.select("img[src]")
        best: tuple[int, str] = (0, "")
        for img in imgs:
            try:
                w = int(img.get("width", 0))
            except (ValueError, TypeError):
                w = 0
            try:
                h = int(img.get("height", 0))
            except (ValueError, TypeError):
                h = 0
            area = w * h
            if area > best[0]:
                src = img.get("src", "")
                if src:
                    best = (area, src)
        return best[1] if best[0] > 0 else None

    @staticmethod
    def _parse_iso_duration(duration: str) -> int | None:
        """Parse ISO 8601 duration (e.g. 'PT1H30M15S') into minutes."""
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not match:
            return None
        h, m, s = match.groups()
        total = (int(h) * 60 if h else 0) + (int(m) if m else 0)
        if s:
            total += 1  # round up
        return total or None

    @staticmethod
    def _extract_year(soup: BeautifulSoup, ld_data: dict) -> int | None:
        """Extract publication year from page or JSON-LD."""
        # Try JSON-LD first
        for key in ("datePublished", "uploadDate", "dateCreated"):
            val = ld_data.get(key, "")
            if val:
                m = re.search(r"(\d{4})", str(val))
                if m:
                    return int(m.group(1))

        # Try meta tags
        for selector in (
            'meta[property="article:published_time"]',
            'meta[name="date"]',
        ):
            val = GenericHTMLScraper.safe_extract(soup, selector, "content")
            if val:
                m = re.search(r"(\d{4})", val)
                if m:
                    return int(m.group(1))

        return None
