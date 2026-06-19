"""Global configuration for FilmVault.

Settings can be overridden via environment variables (prefix: FV_).
Database-stored settings take precedence over defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# ---- Project root ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class AppConfig:
    """Application-wide configuration with sensible defaults."""

    # ---- Paths ----
    video_directories: list[str] = field(default_factory=list)
    """Directories to scan for video files (semicolon-separated in env)."""

    # ---- Database ----
    database_url: str = field(default_factory=lambda: f"sqlite+aiosqlite:///{DATA_DIR / 'scraper.db'}")

    # ---- Scraping ----
    scraper_concurrency: int = 3
    """Maximum concurrent scraper tasks."""

    scraper_timeout: float = 30.0
    """HTTP request timeout in seconds."""

    scraper_retry: int = 2
    """Number of retries on scrape failure."""

    scraper_interval: float = 0.5
    """Minimum delay between requests in seconds."""

    scraper_jitter: float = 1.5
    """Random jitter added to interval in seconds."""

    cache_ttl_days: int = 7
    """Days before cached metadata is considered stale."""

    scraper_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    # ---- NFO ----
    nfo_alongside_video: bool = True
    """If True, write .nfo next to the video file; otherwise use nfo_output_dir."""

    nfo_output_dir: str = ""
    """Alternative NFO output directory (only used when nfo_alongside_video=False)."""

    # ---- Proxy ----
    proxy_url: str = ""
    """Optional HTTP/SOCKS proxy URL."""

    # ---- Supported video extensions ----
    video_extensions: set[str] = field(
        default_factory=lambda: {".mp4", ".mkv", ".avi", ".wmv", ".mov", ".flv", ".ts", ".m4v", ".webm"}
    )

    def update(self, **kwargs: Any) -> None:
        """Update config fields at runtime (called from Settings page)."""
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build config from environment variables, falling back to defaults."""
        env_dirs = os.getenv("VMS_VIDEO_DIRS", "")
        return cls(
            video_directories=[d.strip() for d in env_dirs.split(";") if d.strip()],
            scraper_concurrency=int(os.getenv("VMS_CONCURRENCY", "3")),
            scraper_timeout=float(os.getenv("VMS_TIMEOUT", "30")),
            cache_ttl_days=int(os.getenv("VMS_CACHE_TTL", "7")),
            proxy_url=os.getenv("VMS_PROXY", ""),
            nfo_output_dir=os.getenv("VMS_NFO_DIR", ""),
        )


# Global singleton — loaded once at startup
config = AppConfig.from_env()
