"""Pattern definitions and registry for filename parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PatternDefinition:
    """A single regex pattern for matching video filenames."""

    name: str
    """Unique pattern identifier (e.g. 'standard-code')."""

    regex: re.Pattern[str]
    """Compiled regex with named groups."""

    groups: list[str] = field(default_factory=list)
    """Ordered list of expected group names."""

    priority: int = 50
    """Lower number = higher priority (tried first)."""

    description: str = ""
    """Human-readable description of what this pattern matches."""


# ---------------------------------------------------------------------------
# Built-in patterns (ordered by priority)
# ---------------------------------------------------------------------------

BUILTIN_PATTERNS: list[PatternDefinition] = [
    # 1. ABC-123  — most common code format with optional extra info
    PatternDefinition(
        name="standard-code",
        regex=re.compile(
            r"^(?P<prefix>[A-Za-z]{2,6})[-_\s]+"
            r"(?P<number>\d{2,6})"
            r"(?:[-_\s]+(?P<extra>.*?))?$",
            re.IGNORECASE,
        ),
        groups=["prefix", "number", "extra"],
        priority=1,
        description="标准番号: ABC-123, XYZ_456",
    ),

    # 2. ABC123  — compact variant without separator
    PatternDefinition(
        name="compact-code",
        regex=re.compile(
            r"^(?P<prefix>[A-Za-z]{2,6})"
            r"(?P<number>\d{2,6})"
            r"(?:[-_\s]+(?P<extra>.*?))?$",
            re.IGNORECASE,
        ),
        groups=["prefix", "number", "extra"],
        priority=2,
        description="紧凑番号: ABC123, Xyz0456",
    ),

    # 3. [Group] Title - Episode  — fansub release format
    PatternDefinition(
        name="fansub-format",
        regex=re.compile(
            r"^\[(?P<group>[^\]]+)\]\s*"
            r"(?P<title>.+?)\s*[-_]\s*"
            r"(?P<episode>\d{1,3})"
            r"(?:\s*[-_]\s*(?P<extra>.*?))?$",
            re.IGNORECASE,
        ),
        groups=["group", "title", "episode", "extra"],
        priority=3,
        description="字幕组格式: [Group] Title - 01",
    ),

    # 4. Title S01E01  — TV episode format
    PatternDefinition(
        name="tv-episode",
        regex=re.compile(
            r"^(?P<title>.+?)\s*"
            r"[Ss](?P<season>\d{1,2})"
            r"[Ee](?P<episode>\d{1,3})"
            r"(?:\s*[-_\.]\s*(?P<extra>.*?))?$",
        ),
        groups=["title", "season", "episode", "extra"],
        priority=4,
        description="剧集格式: Title S01E01",
    ),

    # 5. Title Resolution Source Codec  — encoder release
    PatternDefinition(
        name="encode-format",
        regex=re.compile(
            r"^(?P<title>.+?)\s+"
            r"(?P<resolution>\d{3,4}[Pp])?\s*"
            r"(?P<source>BluRay|WEB-DL|WEBRip|HDTV|BDRip|DVDRip)?\s*"
            r"(?P<codec>[Hh]\.?264|[Hh]\.?265|[Xx]264|[Xx]265|HEVC|AVC|AV1)?"
            r"(?:\s+(?P<extra>.*?))?$",
        ),
        groups=["title", "resolution", "source", "codec", "extra"],
        priority=5,
        description="压制组格式: Title 1080p BluRay x264",
    ),

    # 6. [Group]Title-Code  — nico-style hybrid format
    PatternDefinition(
        name="nico-format",
        regex=re.compile(
            r"^(?:(?:\[(?P<group>[^\]]+)\])?\s*)?"
            r"(?P<title>.+?)\s*"
            r"[-_\.]?\s*"
            r"(?:[\[\(]?(?P<code>[A-Za-z]+\d+)[\]\)]?)"
            r"(?:\s*[-_\.]\s*(?P<extra>.*?))?$",
        ),
        groups=["group", "title", "code", "extra"],
        priority=6,
        description="混合格式: [Group]Title-ABC123",
    ),

    # 7. 123456  — numeric-only (e.g. JAV codes, library IDs)
    PatternDefinition(
        name="numeric-only",
        regex=re.compile(
            r"^(?P<number>\d{4,8})"
            r"(?:[-_\s]+(?P<extra>.*?))?$",
        ),
        groups=["number", "extra"],
        priority=7,
        description="纯数字: 123456",
    ),

    # 99. Free-form fallback  — last resort, best-effort
    PatternDefinition(
        name="free-form",
        regex=re.compile(
            r"^(?P<code>[A-Za-z0-9]{3,12})"
            r"(?:[-_\s]*(?P<title>.+?))?"
            r"(?:\s*[-_]\s*(?P<extra>.*?))?$",
            re.IGNORECASE,
        ),
        groups=["code", "title", "extra"],
        priority=99,
        description="自由格式回退: 尽力匹配",
    ),
]


# ---------------------------------------------------------------------------
# Pattern Registry
# ---------------------------------------------------------------------------

class PatternRegistry:
    """Manages a collection of PatternDefinition instances sorted by priority."""

    def __init__(self) -> None:
        self._patterns: dict[str, PatternDefinition] = {}

    def register(self, pattern: PatternDefinition) -> None:
        self._patterns[pattern.name] = pattern

    def register_all(self, patterns: list[PatternDefinition]) -> None:
        for p in patterns:
            self.register(p)

    def get(self, name: str) -> PatternDefinition | None:
        return self._patterns.get(name)

    def get_all(self) -> list[PatternDefinition]:
        """Return all patterns sorted by priority (lowest first)."""
        return sorted(self._patterns.values(), key=lambda p: p.priority)

    def get_enabled(self) -> list[PatternDefinition]:
        """Return all patterns (currently all are enabled by default)."""
        return self.get_all()

    def remove(self, name: str) -> None:
        self._patterns.pop(name, None)
