"""Abstract base class and data models for scraper plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.config import config


# ======================================================================
# Data Transfer Objects
# ======================================================================

@dataclass
class ScrapedMetadata:
    """Structured metadata produced by a scraper plugin."""

    title: str = ""
    original_title: str | None = None
    plot: str | None = None
    poster_url: str | None = None
    fanart_urls: list[str] = field(default_factory=list)
    year: int | None = None
    premiered: str | None = None       # YYYY-MM-DD
    runtime: int | None = None         # minutes
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    actors: list[dict[str, Any]] = field(default_factory=list)
    director: str | None = None
    studio: str | None = None
    maker: str | None = None           # maker/distributor may differ from studio
    label: str | None = None
    set_name: str | None = None        # series/set name
    rating: float | None = None
    samples: list[str] = field(default_factory=list)   # sample image URLs
    source_plugin: str = ""
    source_url: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """A single search result from a scraper's search capability."""

    title: str
    url: str
    poster_url: str | None = None
    year: int | None = None
    snippet: str | None = None
    confidence: float = 0.0


# ======================================================================
# Exception Hierarchy — 6 fine-grained exceptions
# ======================================================================

class ScraperError(Exception):
    """Base exception for all scraper-related errors."""
    def __init__(self, plugin_name: str, message: str, url: str = "") -> None:
        self.plugin_name = plugin_name
        self.message = message
        self.url = url
        super().__init__(f"[{plugin_name}] {message}")


class ScraperNotApplicable(ScraperError):
    """Raised when a scraper determines it cannot handle the given file/code."""


class NetworkError(ScraperError):
    """Network-level failure: DNS, connection refused, timeout, SSL error."""


class RateLimitedError(ScraperError):
    """Source is rate-limiting or IP is temporarily blocked."""


class NotFoundError(ScraperError):
    """Code confirmed as not existing on the source (404 or equivalent)."""


class ParseError(ScraperError):
    """HTML parsing failure: page structure changed, missing elements."""


class AuthError(ScraperError):
    """Authentication required: age verification, login wall, CAPTCHA."""


class ScraperConfigError(ScraperError):
    """Configuration error: missing required settings, invalid URL format."""


# Backward-compatible alias
ScrapingFailed = ScraperError


class AllScrapersFailed(ScraperError):
    """Raised when every scraper in the fallback chain fails."""

    def __init__(self, failures: list[ScraperError]) -> None:
        self.failures = failures
        msg = "; ".join(str(f) for f in failures)
        super().__init__("engine", f"All scrapers failed: {msg}")


# ======================================================================
# Abstract Base Scraper
# ======================================================================

class BaseScraper(ABC):
    """
    Abstract base class for all scraper plugins.

    Subclasses must implement ``can_handle`` and ``scrape``.
    Place implementations in ``app/scraper/plugins/`` for auto-discovery.
    """

    # ---- Class-level metadata ----
    name: ClassVar[str]
    """Unique plugin identifier (e.g. 'javbus')."""

    label: ClassVar[str]
    """Human-readable display name (e.g. 'JavBus')."""

    version: ClassVar[str] = "1.0.0"
    priority: ClassVar[int] = 100
    """Lower number = higher priority in the fallback chain."""

    enabled: ClassVar[bool] = True
    requires_url: ClassVar[bool] = False
    """If True, user must provide a URL for this scraper to work."""

    base_urls: ClassVar[list[str]] = []
    """List of base URLs for domain hot-swap (first is default)."""

    # ---- Default headers ----
    DEFAULT_HEADERS: ClassVar[dict[str, str]] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._own_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BaseScraper":
        if self._client is None:
            self._own_client = self._build_client()
            self._client = self._own_client
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._own_client:
            await self._own_client.aclose()
            self._own_client = None
            self._client = None

    def _build_client(self) -> httpx.AsyncClient:
        """
        Build the httpx client with default settings.
        Subclasses can override to customize headers, timeout, etc.
        """
        proxy = config.proxy_url.strip() or None
        return httpx.AsyncClient(
            headers={
                "User-Agent": config.scraper_user_agent,
                "Accept-Language": self._get_accept_language(),
            },
            timeout=httpx.Timeout(config.scraper_timeout),
            follow_redirects=True,
            proxy=proxy,
        )

    def _get_accept_language(self) -> str:
        """Override in subclasses for language preferences."""
        return "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7"

    def _get_base_url(self) -> str:
        """Override in subclasses to return the base URL for relative URL resolution."""
        return self._get_active_base_url()

    def _get_base_urls(self) -> list[str]:
        """
        Get all base URLs for domain hot-swap.

        Priority: site_config.json > ClassVar base_urls > _get_base_url override.
        Each listed URL is tried in order on connection failure.
        """
        # Try loading from site config JSON first
        try:
            from app.scraper.site_config import site_configs
            cfg = site_configs.get(self.name)
            if cfg and cfg.base_urls:
                return list(cfg.base_urls)
        except Exception:
            pass

        # Fall back to ClassVar
        if self.base_urls:
            return list(self.base_urls)

        # Ultimate fallback: the single _get_base_url value
        single = self._get_base_url()
        return [single] if single else []

    def _get_active_base_url(self) -> str:
        """Return the currently active base URL (first from the list)."""
        urls = self._get_base_urls()
        return urls[0] if urls else ""

    @property
    def client(self) -> httpx.AsyncClient:
        """Access the shared HTTP client (must be inside an async context)."""
        if self._client is None:
            raise RuntimeError(
                f"Scraper '{self.name}' not initialized. Use 'async with' context."
            )
        return self._client

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def can_handle(self, code: str, filename: str) -> bool:
        """
        Determine whether this scraper can handle the given file.

        Args:
            code: Parsed identifier code from the filename (e.g. 'ABC-123').
            filename: Original filename (for additional heuristics).

        Returns:
            True if this scraper should attempt to scrape this file.
        """
        ...

    @abstractmethod
    async def scrape(
        self, code: str, filename: str, search_url: str | None = None
    ) -> ScrapedMetadata:
        """
        Execute the scraping operation.

        Args:
            code: Parsed identifier code.
            filename: Original filename.
            search_url: Optional user-provided URL to scrape directly.

        Returns:
            Structured metadata.

        Raises:
            ScrapingFailed: If scraping cannot complete.
        """
        ...

    # ------------------------------------------------------------------
    # Optional methods
    # ------------------------------------------------------------------

    async def search(self, query: str) -> list[SearchResult]:
        """Optional: search the data source and return candidates."""
        return []

    async def health_check(self) -> bool:
        """Optional: verify the data source is reachable."""
        return True

    # ------------------------------------------------------------------
    # Utility methods for subclasses
    # ------------------------------------------------------------------

    async def fetch_page(self, url: str) -> str:
        """Fetch a web page and return its HTML text."""
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.text

    async def fetch_soup(self, url: str) -> BeautifulSoup:
        """Fetch a web page and parse it into a BeautifulSoup object."""
        html = await self.fetch_page(url)
        try:
            return BeautifulSoup(html, "lxml")
        except Exception:
            # Fallback to built-in parser if lxml is not available
            return BeautifulSoup(html, "html.parser")

    def _resolve_url(self, raw: str) -> str:
        """Resolve a potentially relative URL to absolute using base URL."""
        if not raw:
            return raw
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if raw.startswith("//"):
            return "https:" + raw
        base = self._get_base_url()
        if raw.startswith("/") and base:
            return base.rstrip("/") + raw
        return raw

    # --- Safe extraction helpers (use BeautifulSoup selectors, not regex) ---

    @staticmethod
    def safe_extract(
        soup: BeautifulSoup | Tag | None, selector: str, attr: str | None = None
    ) -> str | None:
        """Safely extract text or attribute from a CSS selector match."""
        if soup is None:
            return None
        el = soup.select_one(selector)
        if not el:
            return None
        if attr:
            return el.get(attr)
        return el.get_text(strip=True)

    @staticmethod
    def safe_extract_all(
        soup: BeautifulSoup | Tag | None, selector: str, attr: str | None = None
    ) -> list[str]:
        """Safely extract multiple text/attribute values from CSS selector matches."""
        if soup is None:
            return []
        els = soup.select(selector)
        if attr:
            return [el.get(attr, "") for el in els if el.get(attr)]
        return [el.get_text(strip=True) for el in els]

    # --- Higher-level parsing utilities (reduce plugin boilerplate) ---

    @staticmethod
    def _parse_info_item(info_area: Tag | None, label: str) -> str:
        """Extract value after a label in an info area.
        Matches patterns like: 發行日期: 2024-01-01  or  導演: Name"""
        if not info_area:
            return ""
        # Try <p> with label: pattern first
        for p in info_area.select("p"):
            text = p.get_text(strip=True)
            if label in text:
                return text.replace(label, "").replace(":", "").strip()
        # Fallback: regex pattern across the whole info area
        import re
        m = re.search(re.escape(label) + r'\s*:?\s*([^<\n]+)', info_area.get_text())
        return m.group(1).strip() if m else ""

    @staticmethod
    def _parse_genre_areas(*areas: Tag | None) -> list[str]:
        """Extract genre names from one or more genre container areas."""
        genres: list[str] = []
        for area in areas:
            if area is None:
                continue
            for a in area.select("a[href]"):
                text = a.get_text(strip=True)
                if text and text not in genres:
                    genres.append(text)
        return genres

    @staticmethod
    def _parse_actor_nodes(*containers: Tag | None) -> list[dict[str, str]]:
        """Extract actor info (name + optional thumb) from actor containers."""
        actors: list[dict[str, str]] = []
        seen: set[str] = set()
        for container in containers:
            if container is None:
                continue
            for a in container.select("a[href]"):
                name = a.get_text(strip=True)
                if not name or name in seen:
                    continue
                seen.add(name)
                img = a.select_one("img")
                thumb = img.get("src", "") if img else ""
                actors.append({"name": name, "thumb": thumb})
        return actors
