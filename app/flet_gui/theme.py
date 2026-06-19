"""FilmVault — Flet dark theme tokens + Flet 0.85 API compat."""

import flet as ft

# ======================================================================
# Color palette — warm violet dark theme
# ======================================================================

BG_PRIMARY = "#0f0f14"
BG_SECONDARY = "#1a1a24"
BG_TERTIARY = "#252536"
BORDER = "#35354a"
TEXT_PRIMARY = "#e4e4ec"
TEXT_SECONDARY = "#9494a4"
ACCENT = "#c084fc"
ACCENT_HOVER = "#d4a8fc"
SUCCESS = "#4ade80"
WARNING = "#fbbf24"
DANGER = "#f87171"

# Card hover
CARD_BG = "#1a1a24"
CARD_HOVER = "#2a2a3a"

# ======================================================================
# Spacing (4 px grid)
# ======================================================================

PAD_XS = 4
PAD_SM = 8
PAD_MD = 12
PAD_LG = 16
PAD_XL = 24

# ======================================================================
# Card size presets (poster_w, poster_h, card_w)
# ======================================================================

CARD_SIZES = {
    "small": (320, 213, 350),
    "medium": (430, 287, 460),
    "large": (570, 380, 600),
    "xlarge": (700, 467, 730),
}

DEFAULT_SIZE = "medium"
DEFAULT_PAGE_SIZE = 50
PAGE_SIZE_OPTIONS = [20, 30, 50, 80, 100, 200]
MIN_COLS = 5

# ======================================================================
# Font sizes
# ======================================================================

FONT_XS = 11
FONT_SM = 12
FONT_MD = 14
FONT_LG = 16
FONT_XL = 24
FONT_XXL = 32

# ======================================================================
# Flet 0.85 API compatibility helpers
# ======================================================================

def pad_all(v: int) -> ft.Padding:
    return ft.Padding(left=v, top=v, right=v, bottom=v)

def pad_only(*, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0) -> ft.Padding:
    return ft.Padding(left=left, top=top, right=right, bottom=bottom)

def pad_symmetric(horizontal: int, vertical: int) -> ft.Padding:
    return ft.Padding(left=horizontal, top=vertical, right=horizontal, bottom=vertical)

def border_all(width: int, color: str) -> ft.Border:
    s = ft.BorderSide(width, color)
    return ft.Border(left=s, top=s, right=s, bottom=s)

def border_only(*, left: ft.BorderSide | None = None, top: ft.BorderSide | None = None,
                right: ft.BorderSide | None = None, bottom: ft.BorderSide | None = None) -> ft.Border:
    zero = ft.BorderSide(0, "transparent")
    return ft.Border(
        left=left or zero, top=top or zero,
        right=right or zero, bottom=bottom or zero,
    )

def radius_only(*, top_left: int = 0, top_right: int = 0, bottom_left: int = 0, bottom_right: int = 0) -> ft.BorderRadius:
    return ft.BorderRadius(
        top_left=top_left, top_right=top_right,
        bottom_left=bottom_left, bottom_right=bottom_right,
    )

def margin_only(*, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0) -> ft.Margin:
    return ft.Margin(left=left, top=top, right=right, bottom=bottom)

# Alignment
ALIGN_CENTER = ft.Alignment(0, 0)

# Image fit constants
FIT_COVER = "COVER"
FIT_CONTAIN = "CONTAIN"
FIT_FILL = "FILL"
