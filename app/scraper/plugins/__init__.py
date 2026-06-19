"""Scraper plugins — auto-discovered by ScraperRegistry.

Explicit imports below ensure PyInstaller bundles all plugin modules
so they are available for dynamic import at runtime.
"""
from app.scraper.plugins import javbus, javdb, avsox, javlib  # noqa: F401
