"""Filename parsing engine — extracts structured tokens from video filenames."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.parser.normalizer import Normalizer
from app.parser.patterns import BUILTIN_PATTERNS, PatternDefinition, PatternRegistry


@dataclass
class TokenizedName:
    """Result of parsing a video filename into structured tokens."""

    code: str | None = None
    """Standardized identifier code (e.g. 'ABC-123')."""

    prefix: str | None = None
    """Letter prefix extracted from the code (e.g. 'ABC')."""

    number: str | None = None
    """Numeric portion extracted from the code (e.g. '123')."""

    title_hints: list[str] = field(default_factory=list)
    """Fragments that may contain the title."""

    quality_tags: list[str] = field(default_factory=list)
    """Quality indicators (4K, FHD, 60fps, etc.)."""

    raw_name: str = ""
    """Original filename (without extension)."""

    matched_pattern: str = ""
    """Name of the PatternDefinition that matched."""

    confidence: float = 0.0
    """Confidence score 0.0 (no match) to 1.0 (perfect match)."""


class FilenameParser:
    """
    Parses video filenames into structured tokens using a priority-ordered
    set of regex patterns.

    Usage:
        parser = FilenameParser()
        result = parser.parse("/videos/ABC-123.mp4")
        print(result.code)  # 'ABC-123'
    """

    # Minimum confidence threshold for a match to be accepted
    MIN_CONFIDENCE = 0.3

    def __init__(self, registry: PatternRegistry | None = None) -> None:
        self._registry = registry or self._build_default_registry()
        self._normalizer = Normalizer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, filepath: str) -> TokenizedName:
        """
        Parse a single video filepath into a TokenizedName.

        Returns a result even on failure (confidence=0.0).
        """
        raw_name = self._normalizer.extract_basename(filepath)
        cleaned = self._normalizer.clean(filepath)
        quality_tags = self._normalizer.extract_quality_tags(raw_name)

        # Try each pattern in priority order
        for pattern in self._registry.get_enabled():
            match = pattern.regex.match(cleaned)
            if not match:
                continue

            groups = match.groupdict()
            confidence = self._calculate_confidence(pattern, groups)

            if confidence < self.MIN_CONFIDENCE:
                continue

            return self._build_result(groups, pattern, raw_name, quality_tags, confidence)

        # No pattern matched
        return TokenizedName(
            raw_name=raw_name,
            quality_tags=quality_tags,
            confidence=0.0,
        )

    def batch_parse(self, filepaths: list[str]) -> list[TokenizedName]:
        """Parse multiple filepaths in bulk."""
        return [self.parse(fp) for fp in filepaths]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_default_registry() -> PatternRegistry:
        registry = PatternRegistry()
        registry.register_all(BUILTIN_PATTERNS)
        return registry

    @staticmethod
    def _calculate_confidence(pattern: PatternDefinition, groups: dict[str, str]) -> float:
        """Score how confident we are in this match (0.0 - 1.0)."""
        prefix = groups.get("prefix", "")
        number = groups.get("number", "")
        code = groups.get("code", "")

        # Perfect: prefix + number both present
        if prefix and number:
            confidence = 0.90
            if len(prefix) >= 3 and len(number) >= 3:
                confidence += 0.05
            return min(confidence, 1.0)

        # Code present but no separate prefix/number
        if code and len(code) >= 5:
            return 0.60

        # Numeric-only
        if number and len(number) >= 4:
            return 0.50

        # Episode/season patterns (fansub, tv-episode, nico-format)
        episode = groups.get("episode", "")
        season = groups.get("season", "")
        title_val = groups.get("title", "")
        if episode and title_val:
            return 0.65
        if season and episode:
            return 0.70

        # Free-form fallback
        if pattern.name == "free-form":
            return 0.30

        # Any meaningful match (at least one non-empty group)
        if any(v for k, v in groups.items() if k not in ("extra",)):
            return 0.40

        return 0.25

    @staticmethod
    def _build_result(
        groups: dict[str, str],
        pattern: PatternDefinition,
        raw_name: str,
        quality_tags: list[str],
        confidence: float,
    ) -> TokenizedName:
        """Assemble a TokenizedName from match groups."""
        prefix = groups.get("prefix")
        number = groups.get("number")
        code = groups.get("code")

        # Build standardized code
        if prefix and number:
            standardized_code = f"{prefix.upper()}-{number}"
        elif code:
            standardized_code = code.upper()
        else:
            standardized_code = number or None

        # Collect title hints
        title_hints: list[str] = []
        for key in ("title", "extra", "group"):
            val = groups.get(key)
            if val:
                title_hints.append(val.strip())

        return TokenizedName(
            code=standardized_code,
            prefix=prefix.upper() if prefix else None,
            number=number,
            title_hints=title_hints,
            quality_tags=quality_tags,
            raw_name=raw_name,
            matched_pattern=pattern.name,
            confidence=min(confidence, 1.0),
        )
