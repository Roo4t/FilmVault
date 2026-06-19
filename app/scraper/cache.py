"""
404 NotFound cache — avoids repeated requests to known-missing codes.

Reference: avbook 404 record table design
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

CACHE_FILE = DATA_DIR / "not_found_cache.json"
TTL_SECONDS = 7 * 24 * 3600  # 7 天过期（网站可能新增数据）


class NotFoundCache:
    """
    Tracks which codes have been confirmed as 404 / not found.

    Structure::
        {"ABC-123": {"ts": 1723600000, "source": "javbus", "url": "https://..."}}

    Entries expire after ``TTL_SECONDS`` to allow re-checking.
    """

    def __init__(self, ttl: float = TTL_SECONDS) -> None:
        self._ttl = ttl
        self._cache: dict[str, dict] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def is_not_found(self, code: str, source: str = "") -> bool:
        """Check if this code was previously confirmed 404 and hasn't expired."""
        self._ensure_loaded()
        key = code.upper().strip()
        entry = self._cache.get(key)
        if not entry:
            return False
        age = time.time() - entry.get("ts", 0)
        if age > self._ttl:
            del self._cache[key]
            self._save()
            return False
        # If source specified, only match if the source matches
        if source and entry.get("source", "") != source:
            return False
        return True

    def mark_not_found(self, code: str, source: str = "", url: str = "") -> None:
        """Mark a code as not found for a given source."""
        self._ensure_loaded()
        key = code.upper().strip()
        existing = self._cache.get(key, {})
        sources = set((existing.get("source") or "").split(",")) if existing.get("source") else set()
        sources.add(source)

        self._cache[key] = {
            "ts": int(time.time()),
            "source": ",".join(sorted(s for s in sources if s)),
            "url": url or existing.get("url", ""),
        }
        self._save()

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()
        self._save()

    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        self._ensure_loaded()
        now = time.time()
        active = sum(1 for e in self._cache.values() if now - e.get("ts", 0) < self._ttl)
        expired = len(self._cache) - active
        return {"active": active, "expired": expired, "total": len(self._cache)}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load()
            self._loaded = True

    def _load(self) -> None:
        try:
            if CACHE_FILE.exists():
                data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                self._cache = data if isinstance(data, dict) else {}
            else:
                self._cache = {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load not_found_cache: %s", exc)
            self._cache = {}

    def _save(self) -> None:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to save not_found_cache: %s", exc)


# Process-level singleton
not_found_cache = NotFoundCache()
