"""Scraper plugin registry — discovery, registration, and management."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any

from app.scraper.base import BaseScraper

logger = logging.getLogger(__name__)

# Known plugin module names (fallback for PyInstaller where pkgutil can't scan)
_KNOWN_PLUGINS = ["javbus", "javdb", "avsox", "javlib"]


class ScraperRegistry:
    """
    Registry for all scraper plugins.

    Plugins are discovered automatically from ``app/scraper/plugins/``.
    Each plugin is a Python module containing one ``BaseScraper`` subclass.
    """

    def __init__(self) -> None:
        self._scrapers: dict[str, type[BaseScraper]] = {}
        self._instances: dict[str, BaseScraper] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, scraper_cls: type[BaseScraper]) -> None:
        """Register a scraper class by its ``name`` class variable."""
        name = scraper_cls.name
        self._scrapers[name] = scraper_cls

    def _import_plugin(self, module_name: str, plugin_package: str) -> bool:
        """Import a single plugin module and register its scraper class.
        
        Returns True if a scraper class was registered.
        """
        try:
            module = importlib.import_module(f"{plugin_package}.{module_name}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseScraper)
                    and attr is not BaseScraper
                ):
                    self.register(attr)
                    return True
        except ImportError as exc:
            logger.debug("Failed to import plugin %s: %s", module_name, exc)
        return False

    def discover(self, plugin_package: str = "app.scraper.plugins") -> int:
        """
        Auto-discover all scraper plugins in the given package.

        Uses ``pkgutil.iter_modules`` in standard Python; falls back to
        explicit imports in PyInstaller (where modules are in a PYZ archive
        and not discoverable via filesystem scanning).

        Returns the number of plugins discovered.
        """
        count = 0

        # ── Primary: filesystem-based discovery (works in dev / venv) ──
        try:
            package = importlib.import_module(plugin_package)
        except ImportError:
            package = None

        if package is not None and package.__file__ is not None:
            package_path = Path(package.__file__).parent
            for _, module_name, is_pkg in pkgutil.iter_modules([str(package_path)]):
                if is_pkg or module_name.startswith("_"):
                    continue
                if self._import_plugin(module_name, plugin_package):
                    count += 1

        # ── Fallback: explicit import for PyInstaller (no filesystem modules) ──
        if count == 0:
            logger.info("No plugins found via filesystem scan, using explicit imports")
            for module_name in _KNOWN_PLUGINS:
                if self._import_plugin(module_name, plugin_package):
                    count += 1

        return count

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> type[BaseScraper] | None:
        """Get a scraper class by name."""
        return self._scrapers.get(name)

    def get_all(self) -> list[type[BaseScraper]]:
        """Return all registered scraper classes sorted by priority."""
        return sorted(self._scrapers.values(), key=lambda cls: cls.priority)

    def get_enabled(self) -> list[type[BaseScraper]]:
        """Return only enabled scrapers, sorted by priority."""
        return [cls for cls in self.get_all() if cls.enabled]

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def enable(self, name: str) -> None:
        cls = self._scrapers.get(name)
        if cls:
            cls.enabled = True  # type: ignore[misc]

    def disable(self, name: str) -> None:
        cls = self._scrapers.get(name)
        if cls:
            cls.enabled = False  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Serialization (for API)
    # ------------------------------------------------------------------

    def to_dict(self) -> list[dict[str, Any]]:
        """Serialize all scrapers to a list of dicts for API responses."""
        return [
            {
                "name": cls.name,
                "label": cls.label,
                "version": cls.version,
                "priority": cls.priority,
                "enabled": cls.enabled,
                "requires_url": cls.requires_url,
            }
            for cls in self.get_all()
        ]
