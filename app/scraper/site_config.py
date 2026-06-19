"""
SiteConfig loader — reads selectors and URL templates from JSON.
Reference: JavSP configuration-driven scraper architecture.

Each plugin can optionally load its selectors from site_configs.json
instead of hardcoding CSS/XPath patterns in source code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

CONFIG_PATH = DATA_DIR / "site_configs.json"


# ======================================================================
# Data classes
# ======================================================================

@dataclass
class SiteSelector:
    """Single selector config entry."""
    name: str
    selector: str = ""
    attr: str | None = None              # extract attribute instead of text
    fallback: str = ""                   # fallback CSS selector
    regex: str = ""                      # post-processing regex
    required: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SiteSelector":
        return cls(
            name=d.get("name", ""),
            selector=d.get("selector", ""),
            attr=d.get("attr"),
            fallback=d.get("fallback", ""),
            regex=d.get("regex", ""),
            required=d.get("required", False),
        )


@dataclass
class SiteConfig:
    """Configuration for a single scraper site."""
    name: str
    label: str = ""
    base_urls: list[str] = field(default_factory=list)
    search_url_template: str = ""
    detail_url_template: str = ""
    priority: int = 100
    timeout: int = 30
    requires_search: bool = False
    selectors: dict[str, SiteSelector] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SiteConfig":
        selectors = {
            k: SiteSelector.from_dict(v)
            for k, v in d.get("selectors", {}).items()
        }
        return cls(
            name=d.get("name", ""),
            label=d.get("label", ""),
            base_urls=d.get("base_urls", []),
            search_url_template=d.get("search_url_template", ""),
            detail_url_template=d.get("detail_url_template", ""),
            priority=d.get("priority", 100),
            timeout=d.get("timeout", 30),
            requires_search=d.get("requires_search", False),
            selectors=selectors,
        )

    def get_selector(self, key: str) -> SiteSelector | None:
        """Get a named selector, or None if not defined."""
        return self.selectors.get(key)

    def get_css(self, key: str) -> str:
        """Get the CSS selector string for a named key."""
        sel = self.selectors.get(key)
        return sel.selector if sel else ""


# ======================================================================
# Loader
# ======================================================================

class SiteConfigLoader:
    """Loads site configurations from a JSON file."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._path = config_path or CONFIG_PATH
        self._sites: dict[str, SiteConfig] = {}
        self._loaded = False

    def load(self) -> dict[str, SiteConfig]:
        """Load and return all site configurations."""
        if self._loaded:
            return self._sites

        try:
            if not self._path.exists():
                logger.info("Site config file not found: %s", self._path)
                self._loaded = True
                return self._sites

            data = json.loads(self._path.read_text(encoding="utf-8"))
            version = data.get("version", "1.0")
            sites_data = data.get("sites", {})

            for name, site_dict in sites_data.items():
                try:
                    self._sites[name] = SiteConfig.from_dict(site_dict)
                except Exception as exc:
                    logger.warning("Failed to parse site config for '%s': %s", name, exc)

            logger.info(
                "Loaded %d site configs from %s (v%s)",
                len(self._sites), self._path.name, version,
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load site configs: %s", exc)
        finally:
            self._loaded = True

        return self._sites

    def get(self, site_name: str) -> SiteConfig | None:
        """Get configuration for a specific site by name."""
        self.load()
        return self._sites.get(site_name)

    def get_all(self) -> dict[str, SiteConfig]:
        """Get all loaded site configurations."""
        self.load()
        return dict(self._sites)


# Process-level singleton
site_configs = SiteConfigLoader()
