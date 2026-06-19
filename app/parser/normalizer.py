"""Filename cleaning and normalization utilities."""

from __future__ import annotations

import re
from pathlib import Path

# Quality tags commonly found in release filenames
QUALITY_TAGS_PATTERN = re.compile(
    r"\b(2160[Pp]|1080[Pp]|720[Pp]|480[Pp]|4[Kk]|8[Kk]|"
    r"HDR10\+?|DolbyVision|DV|SDR|"
    r"60[fF][pP][sS]|30[fF][pP][sS]|24[fF][pP][sS])\b"
)

# Noise patterns — watermarks, ad text, site tags
NOISE_PATTERNS = [
    re.compile(r"@\S+"),                          # @handles
    re.compile(r"(?:www\.)?\S+\.(?:com|net|org|cc|tv)\b", re.IGNORECASE),
    re.compile(r"【.*?】"),                        # Chinese brackets
    re.compile(r"\(C\)", re.IGNORECASE),
    re.compile(r"all rights reserved", re.IGNORECASE),
    re.compile(r"-Obfuscated\b", re.IGNORECASE),
]

# Encoding garbage fixer
_MOJIBAAKE_MAP: dict[str, str] = {
    "\u00e2\u0080\u0099": "'",
    "\u00e2\u0080\u009c": "\u201c",
    "\u00e2\u0080\u009d": "\u201d",
    "\u00e2\u0080\u0093": "\u2013",
    "\u00e2\u0080\u0094": "\u2014",
    "\u00ef\u00bc\u0088": "\uff08",
    "\u00ef\u00bc\u0089": "\uff09",
}


class Normalizer:
    """Cleans and normalizes video filenames before pattern matching."""

    @staticmethod
    def extract_basename(filepath: str) -> str:
        """Extract filename without extension from a full path."""
        path = Path(filepath)
        return path.stem

    @staticmethod
    def clean(filename: str) -> str:
        """
        Full normalization pipeline:
        1. Strip extension
        2. Replace multiple separators
        3. Remove noise
        4. Collapse whitespace
        """
        name = Normalizer.extract_basename(filename)
        name = Normalizer.fix_encoding(name)
        name = name.replace(".", " ").replace("_", " ").replace("+", " ")
        name = Normalizer.remove_noise(name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    @staticmethod
    def fix_encoding(name: str) -> str:
        """Fix common mojibake / double-encoding artifacts."""
        for bad, good in _MOJIBAAKE_MAP.items():
            name = name.replace(bad, good)
        return name

    @staticmethod
    def remove_noise(name: str) -> str:
        """Remove advertising, watermarks, site tags from filename."""
        for pattern in NOISE_PATTERNS:
            name = pattern.sub("", name)
        return name

    @staticmethod
    def extract_quality_tags(name: str) -> list[str]:
        """Extract resolution / framerate / HDR tags from filename."""
        return QUALITY_TAGS_PATTERN.findall(name)
