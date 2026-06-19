"""FilmVault — Flet GUI entry point."""
import asyncio
import atexit
import ctypes
import flet as ft
import logging
import os
import sys
import threading

from app.flet_gui.theme import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BORDER,
    TEXT_PRIMARY, TEXT_SECONDARY, ACCENT, ACCENT_HOVER,
    SUCCESS, WARNING, DANGER,
    FONT_MD, FONT_SM, FONT_LG,
    PAD_SM, PAD_LG,
    pad_only, border_only,
)
from app.flet_gui.pages.dashboard import DashboardPage
from app.flet_gui.pages.files import FilesPage
from app.flet_gui.pages.browser import BrowserPage
from app.flet_gui.pages.scraper import ScraperPage
from app.flet_gui.pages.settings import SettingsPage

logger = logging.getLogger(__name__)


class FilmVaultApp:
    """Main Flet application with Material Design tabs."""

    def __init__(self, page: ft.Page):
        self.page = page
        self._setup_page()

        # Load DB config into global config object BEFORE building pages
        self._init_config_sync()

        # ── Tab state — each tab caches its build result ──
        self.dashboard = DashboardPage(self)
        self.files = FilesPage(self)
        self.browser = BrowserPage(self)
        self.scraper = ScraperPage(self)
        self.settings = SettingsPage(self)

        self._build_ui()

    # ------------------------------------------------------------------
    # Page config
    # ------------------------------------------------------------------

    @staticmethod
    def _init_config_sync() -> None:
        """Load config from DB into global config object BEFORE pages are built.
        
        Uses synchronous sqlite3 because this runs in __init__ (before async loop).
        Also initializes database tables if they don't exist.
        """
        import sqlite3
        from pathlib import Path
        from app.config import config, DATA_DIR
        from app.database.engine import init_db_sync

        # Ensure database tables exist BEFORE trying to read from them
        try:
            init_db_sync()
        except Exception:
            pass

        db_path = DATA_DIR / "scraper.db"
        if not db_path.exists():
            return
        
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
            conn.close()
            db = {row[0]: row[1] for row in rows}

            # Video directories
            if db.get("video_directories"):
                config.video_directories = [
                    d.strip() for d in db["video_directories"].split(";") if d.strip()
                ]

            # Numeric + string settings
            for attr, key, coerce in [
                ("scraper_timeout",      "scraper_timeout",      float),
                ("scraper_retry",        "scraper_retry",        int),
                ("scraper_concurrency",  "scraper_concurrency",  int),
                ("cache_ttl_days",       "cache_ttl_days",       int),
                ("scraper_interval",     "scraper_interval",     float),
                ("scraper_jitter",       "scraper_jitter",       float),
                ("scraper_user_agent",   "scraper_user_agent",   str),
                ("proxy_url",            "proxy_url",             str),
            ]:
                if key in db:
                    try:
                        setattr(config, attr, coerce(db[key]))
                    except (ValueError, TypeError):
                        pass

            # Sync plugin runtime state from DB
            try:
                from app.scraper.registry import ScraperRegistry
                reg = ScraperRegistry()
                reg.discover()
                for cls in reg.get_all():
                    enabled_key = f"plugin_enabled_{cls.name}"
                    priority_key = f"plugin_priority_{cls.name}"
                    if enabled_key in db:
                        cls.enabled = db[enabled_key] not in ("0", "false", "")
                    if priority_key in db:
                        try:
                            cls.priority = int(db[priority_key])
                        except ValueError:
                            pass
            except Exception:
                pass
        except Exception:
            pass

    def _set_win32_startup(self) -> None:
        """Center window + set icon via Win32 API."""
        try:
            from PIL import Image
            import io
            import time
            import logging
            _log = logging.getLogger(__name__)

            user32 = ctypes.windll.user32

            hwnd = 0
            for _ in range(80):
                hwnd = user32.FindWindowW(None, "FilmVault")
                if hwnd:
                    break
                time.sleep(0.02)
            if not hwnd:
                return

            # 1. Center window immediately
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            x = (sw - self._win_width) // 2
            y = (sh - self._win_height) // 2
            # Use SetWindowPos for reliable positioning (SWP_NOZORDER | SWP_NOACTIVATE)
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_NOSENDCHANGING = 0x0400
            user32.SetWindowPos(hwnd, 0, x, y, self._win_width, self._win_height,
                              SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING)

            # 2. Set icon
            icon_path = self._icon_path
            if not os.path.exists(icon_path):
                return

            img = Image.open(icon_path)
            sizes = [(48, 48), (32, 32), (16, 16)]
            ico_buf = io.BytesIO()
            img.save(ico_buf, format="ICO", sizes=sizes)
            ico_buf.seek(0)

            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".ico", delete=False)
            tmp.write(ico_buf.read())
            tmp_name = tmp.name
            tmp.close()
            atexit.register(lambda: os.path.exists(tmp_name) and os.unlink(tmp_name))

            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            hicon = user32.LoadImageW(0, tmp_name, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if hicon:
                WM_SETICON = 0x0080
                user32.SendMessageW(hwnd, WM_SETICON, 1, hicon)
                user32.SendMessageW(hwnd, WM_SETICON, 0, hicon)
        except Exception:
            pass

    def _setup_page(self) -> None:
        self.page.title = "FilmVault"
        icon_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "assets", "icon.png"))
        ico_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "assets", "icon.ico"))
        self.page.window.icon = ico_path if os.path.exists(ico_path) else icon_path

        # Center window + set icon — both done in one shot, no top-left flash
        if sys.platform == "win32":
            self._icon_path = icon_path
            self._win_width = 1936
            self._win_height = 1080
            threading.Timer(0.05, self._set_win32_startup).start()
        self.page.window.width = 1936
        self.page.window.height = 1080
        self.page.window.min_width = 1936
        self.page.window.min_height = 1080
        # Set position both via Flet API AND Win32 for fastest result
        if sys.platform == "win32":
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            self.page.window.left = (sw - 1936) // 2
            self.page.window.top = (sh - 1080) // 2
        self.page.window.title_bar_hidden = True
        self.page.window.title_bar_buttons_hidden = True
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = BG_PRIMARY
        self.page.padding = 0

        # Dark theme color scheme
        self.page.dark_theme = ft.Theme(
            color_scheme_seed=ACCENT,
            font_family="Microsoft YaHei",
            color_scheme=ft.ColorScheme(
                primary=ACCENT,
                on_primary="#ffffff",
                surface=BG_SECONDARY,
                on_surface=TEXT_PRIMARY,
                outline=BORDER,
                error=DANGER,
            ),
        )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Custom dark title bar ──
        title_bar = ft.Container(
            bgcolor=BG_SECONDARY,
            padding=ft.Padding(left=PAD_LG, top=5, right=8, bottom=5),
            content=ft.Row([
                # Left: logo icon + app name
                ft.Row([
                    ft.Container(
                        content=ft.Image(
                            src=os.path.normpath(os.path.join(
                                os.path.dirname(__file__), "..", "..", "assets", "icon_titlebar.png")),
                            width=50, height=50, fit=ft.BoxFit.COVER),
                        width=50, height=50, border_radius=10,
                        alignment=ft.Alignment(0, 0),
                    ),
                    ft.Text("FilmVault", size=16, color=TEXT_PRIMARY,
                           weight=ft.FontWeight.W_600),
                ], spacing=8),
                # Center: draggable area
                ft.WindowDragArea(
                    content=ft.Container(height=30),
                    expand=True,
                ),
                # Right: window control buttons
                ft.Row([
                    self._win_btn(ft.Icons.MINIMIZE_ROUNDED, "最小化",
                                  lambda e: setattr(self.page.window, 'minimized', True)),
                    self._win_btn(ft.Icons.CROP_SQUARE_ROUNDED, "最大化/还原",
                                  lambda e: setattr(self.page.window, 'maximized',
                                                    not self.page.window.maximized)),
                    self._win_btn(ft.Icons.CLOSE_ROUNDED, "关闭",
                                  lambda e: asyncio.ensure_future(
                                      self.page.window.close()),
                                  danger=True),
                ], spacing=4),
            ], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            border=border_only(bottom=ft.BorderSide(1, BORDER)),
        )

        # ── Navigation row ──
        self._content_area = ft.Container(expand=True)
        self._nav_buttons: list[ft.TextButton] = []

        nav_items = [
            ("仪表盘", ft.Icons.DASHBOARD_ROUNDED, 0),
            ("文件浏览", ft.Icons.FOLDER_ROUNDED, 1),
            ("视频浏览", ft.Icons.GRID_VIEW_ROUNDED, 2),
            ("刮削控制", ft.Icons.DOWNLOADING_ROUNDED, 3),
            ("设置", ft.Icons.SETTINGS_ROUNDED, 4),
        ]

        for label, icon, idx in nav_items:
            btn = ft.TextButton(
                content=ft.Row([
                    ft.Icon(icon, size=16),
                    ft.Text(label, size=FONT_SM),
                ], spacing=6),
                style=ft.ButtonStyle(
                    color=TEXT_SECONDARY,
                    padding=ft.Padding(left=PAD_LG, top=8, right=PAD_LG, bottom=8),
                    shape=ft.RoundedRectangleBorder(radius=6),
                ),
                on_click=lambda e, i=idx: self._switch_tab(i),
            )
            self._nav_buttons.append(btn)

        nav_row = ft.Row(
            spacing=0,
            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
            controls=self._nav_buttons,
        )

        nav_container = ft.Container(
            bgcolor=BG_SECONDARY,
            padding=ft.Padding(left=0, top=4, right=0, bottom=4),
            border=border_only(bottom=ft.BorderSide(1, BORDER)),
            content=ft.Row([
                nav_row,
            ], expand=True),
        )

        # ── Page body ──
        self._pages = [
            self.dashboard.build(),
            self.files.build(),
            self.browser.build(),
            self.scraper.build(),
            self.settings.build(),
        ]

        ui = ft.Column(
            spacing=0,
            controls=[
                title_bar,
                nav_container,
                self._content_area,
            ],
            expand=True,
        )
        self.page.add(ui)
        self._switch_tab(2)  # default: browser

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_async(self, coro_func):
        """Run a coroutine function in the background (Flet 0.85 compatible)."""
        self.page.run_task(coro_func)

    def _switch_tab(self, idx: int) -> None:
        """Switch active tab and update button styles."""
        self._content_area.content = self._pages[idx]
        for i, btn in enumerate(self._nav_buttons):
            active = (i == idx)
            btn.style = ft.ButtonStyle(
                color=ACCENT if active else TEXT_SECONDARY,
                padding=ft.Padding(left=PAD_LG, top=8, right=PAD_LG, bottom=8),
                shape=ft.RoundedRectangleBorder(radius=6),
                overlay_color=ft.Colors.with_opacity(0.06, ACCENT) if active else \
                              ft.Colors.with_opacity(0.04, TEXT_PRIMARY),
                bgcolor=ft.Colors.with_opacity(0.08, ACCENT) if active else None,
            )
        # Sync plugin settings when switching to scraper or settings tab
        if idx in (3, 4):
            self.page.run_task(self._sync_plugins_async)
        self.page.update()

    def sync_plugins(self):
        """Refresh plugin UI on both settings and scraper pages."""
        self.page.run_task(self._sync_plugins_async)

    async def _sync_plugins_async(self):
        """Reload plugins on both settings and scraper pages."""
        from app.scraper.registry import ScraperRegistry
        reg = ScraperRegistry()
        reg.discover()
        try:
            # Refresh settings page plugin list
            if hasattr(self.settings, '_build_plugin_settings'):
                self.settings._build_plugin_settings()
                self.settings.app = self  # ensure app reference intact
        except Exception:
            pass
        try:
            # Refresh scraper page plugin list
            if hasattr(self.scraper, '_load_plugins'):
                await self.scraper._load_plugins()
        except Exception:
            pass
        self.page.update()

    def _win_btn(self, icon: str, tooltip: str, on_click, danger: bool = False) -> ft.IconButton:
        """Stylized window control button with rounded hover feedback."""
        hover_bg = DANGER if danger else TEXT_PRIMARY
        return ft.IconButton(
            icon=icon, icon_size=18, icon_color=TEXT_SECONDARY,
            tooltip=tooltip,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                overlay_color=ft.Colors.with_opacity(0.12, hover_bg),
                padding=ft.Padding(left=8, top=6, right=8, bottom=6),
            ),
            on_click=on_click,
        )

    def set_status(self, text: str) -> None:
        """Update the persistent status bar (if needed)."""
        pass  # Flet doesn't have a native status bar; use snackbar

    def snack(self, text: str, color: str = TEXT_PRIMARY) -> None:
        self.page.snack_bar = ft.SnackBar(
            ft.Text(text, color=color),
            bgcolor=BG_TERTIARY,
            duration=3000,
        )
        self.page.snack_bar.open = True
        self.page.update()


def main(page: ft.Page):
    FilmVaultApp(page)


if __name__ == "__main__":
    ft.app(target=main)
