"""Settings page — load/save config with real DB persistence + plugin settings."""
import flet as ft
import logging
from app.flet_gui.theme import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BORDER,
    TEXT_PRIMARY, TEXT_SECONDARY, ACCENT,
    SUCCESS, DANGER,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG,
    PAD_XS, PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    pad_all, pad_symmetric, margin_only,
)

logger = logging.getLogger(__name__)


class SettingsPage:
    def __init__(self, app):
        self.app = app
        self._dir_field: ft.TextField = None
        self._timeout_field: ft.TextField = None
        self._retry_dd: ft.Dropdown = None
        self._concurrency_field: ft.TextField = None
        self._cache_field: ft.TextField = None
        self._interval_field: ft.TextField = None
        self._jitter_field: ft.TextField = None
        self._ua_field: ft.TextField = None
        self._proxy_field: ft.TextField = None
        self._nfo_sw: ft.Switch = None
        self._poster_sw: ft.Switch = None
        self._hotswap_sw: ft.Switch = None
        self._plugin_vars: dict[str, dict] = {}

    def build(self) -> ft.Control:
        self._dir_field = ft.TextField(
            hint_text="选择视频文件所在目录...",
            dense=True, border_color=BORDER, text_size=FONT_SM,
            expand=True, read_only=True,
        )
        self._dir_list = ft.Column(spacing=PAD_XS, controls=[])
        self._timeout_field = ft.TextField(
            value="30", dense=True, border_color=BORDER, text_size=FONT_SM, width=80,
            on_blur=lambda e: self._auto_save(),
        )
        self._retry_dd = ft.Dropdown(
            value="2",
            options=[ft.dropdown.Option(str(i)) for i in range(6)],
            width=70, dense=True, border_color=BORDER, text_size=FONT_SM,
            on_select=lambda e: self._auto_save(),
        )
        self._concurrency_field = ft.TextField(
            value="3", dense=True, border_color=BORDER, text_size=FONT_SM, width=70,
            on_blur=lambda e: self._auto_save(),
        )
        self._cache_field = ft.TextField(
            value="7", dense=True, border_color=BORDER, text_size=FONT_SM, width=70,
            on_blur=lambda e: self._auto_save(),
        )
        self._interval_field = ft.TextField(
            value="0.5", dense=True, border_color=BORDER, text_size=FONT_SM, width=80,
            on_blur=lambda e: self._auto_save(),
        )
        self._jitter_field = ft.TextField(
            value="1.5", dense=True, border_color=BORDER, text_size=FONT_SM, width=80,
            on_blur=lambda e: self._auto_save(),
        )
        self._ua_field = ft.TextField(
            hint_text="自定义 User-Agent（留空使用默认）",
            dense=True, border_color=BORDER, text_size=FONT_SM,
            on_blur=lambda e: self._auto_save(),
        )
        self._proxy_field = ft.TextField(
            hint_text="http://127.0.0.1:7890（留空则不使用代理）",
            dense=True, border_color=BORDER, text_size=FONT_SM,
            on_blur=lambda e: self._auto_save(),
        )
        self._nfo_sw = ft.Switch(value=True, active_color=ACCENT,
                                 on_change=lambda e: self._auto_save())
        self._poster_sw = ft.Switch(value=True, active_color=ACCENT,
                                    on_change=lambda e: self._auto_save())
        self._hotswap_sw = ft.Switch(value=True, active_color=ACCENT,
                                     on_change=lambda e: self._auto_save())

        # Plugin settings container (built after config loaded)
        self._plugin_list = ft.Column(spacing=PAD_XS, controls=[])

        self.app.page.run_task(self._load_config)

        return ft.Container(
            bgcolor=BG_PRIMARY,
            padding=pad_all(PAD_LG),
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO, spacing=PAD_MD,
                controls=[
                    ft.Text("应用设置", size=20, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),

                    self._section("视频目录"),
                    self._dir_list,
                    ft.Row(spacing=PAD_SM, controls=[
                        self._dir_field,
                        ft.ElevatedButton(
                            content=ft.Text("添加目录"), icon=ft.Icons.FOLDER_OPEN,
                            style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff"),
                            on_click=lambda e: self._pick_dir(),
                        ),
                    ]),

                    self._section("刮削设置"),
                    ft.Row(spacing=PAD_SM, controls=[
                        ft.Text("超时(秒):", size=FONT_SM, color=TEXT_SECONDARY),
                        self._timeout_field,
                        ft.Text("重试:", size=FONT_SM, color=TEXT_SECONDARY),
                        self._retry_dd,
                        ft.Text("并发:", size=FONT_SM, color=TEXT_SECONDARY),
                        self._concurrency_field,
                    ]),
                    ft.Row(spacing=PAD_SM, controls=[
                        ft.Text("缓存(天):", size=FONT_SM, color=TEXT_SECONDARY),
                        self._cache_field,
                    ]),
                    self._ua_field,

                    self._section("请求限速（防封禁）"),
                    ft.Row(spacing=PAD_SM, controls=[
                        ft.Text("最小间隔(秒):", size=FONT_SM, color=TEXT_SECONDARY),
                        self._interval_field,
                        ft.Text("随机上限(秒):", size=FONT_SM, color=TEXT_SECONDARY),
                        self._jitter_field,
                    ]),

                    self._section("高级选项"),
                    ft.Column(spacing=PAD_XS, controls=[
                        ft.Row(spacing=PAD_SM, controls=[
                            self._nfo_sw,
                            ft.Text("生成 NFO 文件", size=FONT_SM, color=TEXT_PRIMARY),
                        ]),
                        ft.Row(spacing=PAD_SM, controls=[
                            self._poster_sw,
                            ft.Text("下载封面图片", size=FONT_SM, color=TEXT_PRIMARY),
                        ]),
                        ft.Row(spacing=PAD_SM, controls=[
                            self._hotswap_sw,
                            ft.Text("域名热备切换", size=FONT_SM, color=TEXT_PRIMARY),
                        ]),
                    ]),

                    self._section("网络代理"),
                    self._proxy_field,

                    # Plugin settings
                    self._section("刮削插件设置"),
                    self._plugin_list,

                    ft.ElevatedButton(
                        content=ft.Text("保存设置"), icon=ft.Icons.SAVE_ROUNDED,
                        style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff",
                                            padding=pad_symmetric(20, 12)),
                        on_click=lambda e: self._save(),
                    ),
                ],
            ),
        )

    def _section(self, label: str) -> ft.Control:
        return ft.Container(
            margin=margin_only(top=PAD_SM),
            content=ft.Text(label, size=FONT_MD, weight=ft.FontWeight.BOLD,
                           color=TEXT_SECONDARY),
        )

    # ==================================================================
    # Directory management
    # ==================================================================

    def _get_dir_paths(self) -> list[str]:
        paths = []
        for ctrl in self._dir_list.controls:
            if isinstance(ctrl, ft.Row) and len(ctrl.controls) >= 2:
                text_ctrl = ctrl.controls[0]
                if isinstance(text_ctrl, ft.Text):
                    paths.append(text_ctrl.value)
        return paths

    def _add_dir_row(self, path: str):
        row = ft.Row(spacing=PAD_SM, controls=[
            ft.Text(path, size=FONT_SM, color=TEXT_PRIMARY, expand=True),
            ft.IconButton(ft.Icons.DELETE_ROUNDED, icon_size=16,
                         on_click=lambda e: self._remove_dir(row)),
        ])
        self._dir_list.controls.append(row)

    def _remove_dir(self, row):
        if row in self._dir_list.controls:
            self._dir_list.controls.remove(row)
            self._auto_save()

    def _rebuild_dir_list(self, dirs: list[str]):
        self._dir_list.controls.clear()
        for d in dirs:
            self._add_dir_row(d)

    # ==================================================================
    # Plugin settings
    # ==================================================================

    def _build_plugin_settings(self, db_settings: dict = None):
        """Build per-plugin enable/disable + priority controls."""
        from app.scraper.registry import ScraperRegistry
        db_settings = db_settings or {}
        reg = ScraperRegistry()
        reg.discover()
        self._plugin_vars.clear()
        self._plugin_list.controls.clear()

        controls = []
        for cls in reg.get_all():
            # Primary source: runtime class state (already synced from DB on first load).
            # Only use DB as fallback if class hasn't been touched yet.
            enabled = cls.enabled
            priority = cls.priority

            sw = ft.Switch(value=enabled, active_color=ACCENT,
                          on_change=lambda e, cls=cls: self._on_plugin_toggle(cls, e.control.value))
            priority_field = ft.TextField(
                value=str(priority), dense=True, border_color=BORDER,
                text_size=FONT_XS, width=60,
                on_blur=lambda e, cls=cls: self._on_plugin_priority(cls, e.control.value),
            )

            row = ft.Row(spacing=PAD_SM, controls=[
                sw,
                ft.Text(cls.label, size=FONT_SM, color=TEXT_PRIMARY, width=150),
                ft.Text("优先级:", size=FONT_XS, color=TEXT_SECONDARY),
                priority_field,
            ])
            controls.append(row)

            self._plugin_vars[cls.name] = {
                "enabled_sw": sw, "priority_field": priority_field,
                "cls": cls,
            }
        self._plugin_list.controls = controls

    def _sync_plugins_from_db(self, db_settings: dict):
        """Sync plugin runtime class state from DB (called once on page load)."""
        from app.scraper.registry import ScraperRegistry
        reg = ScraperRegistry()
        reg.discover()
        for cls in reg.get_all():
            enabled_key = f"plugin_enabled_{cls.name}"
            priority_key = f"plugin_priority_{cls.name}"
            cls.enabled = db_settings.get(enabled_key, "1") not in ("0", "false", "")
            try:
                cls.priority = int(db_settings.get(priority_key, str(cls.priority)))
            except ValueError:
                pass

    def _on_plugin_toggle(self, cls, enabled: bool):
        """Handle plugin enable/disable toggle — update runtime class + persist."""
        cls.enabled = enabled
        self._auto_save()

    def _on_plugin_priority(self, cls, value: str):
        """Handle plugin priority change — update runtime class + persist."""
        try:
            cls.priority = int(value)
        except ValueError:
            pass
        self._auto_save()

    # ==================================================================
    # Config load/save
    # ==================================================================

    async def _load_config(self):
        from app.config import config
        from app.database.engine import async_session_factory
        from sqlalchemy import text

        try:
            async with async_session_factory() as session:
                result = await session.execute(text(
                    "SELECT key, value FROM app_settings"
                ))
                db_settings = {row[0]: row[1] for row in result.fetchall()}

            # ── Apply DB settings to global config object FIRST ──
            dirs_str = db_settings.get("video_directories", "")
            if dirs_str:
                config.video_directories = [d.strip() for d in dirs_str.split(";") if d.strip()]
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
                if key in db_settings:
                    try:
                        setattr(config, attr, coerce(db_settings[key]))
                    except (ValueError, TypeError):
                        pass

            # ── Fill UI fields from config (now has DB values) ──
            dirs = config.video_directories
            self._rebuild_dir_list(dirs)
            self._timeout_field.value = str(config.scraper_timeout)
            self._retry_dd.value = str(config.scraper_retry)
            self._concurrency_field.value = str(config.scraper_concurrency)
            self._cache_field.value = str(config.cache_ttl_days)
            self._interval_field.value = str(config.scraper_interval)
            self._jitter_field.value = str(config.scraper_jitter)
            self._ua_field.value = config.scraper_user_agent or ""
            self._proxy_field.value = config.proxy_url or ""
            self._nfo_sw.value = bool(db_settings.get("nfo_enabled", "1") not in ("0", "false", ""))
            self._poster_sw.value = bool(db_settings.get("poster_enabled", "1") not in ("0", "false", ""))
            self._hotswap_sw.value = bool(db_settings.get("hotswap_enabled", "1") not in ("0", "false", ""))

            # Build plugin settings after config is loaded
            try:
                # Sync runtime class state from DB (one-time, before building UI)
                self._sync_plugins_from_db(db_settings)
                self._build_plugin_settings(db_settings)
            except Exception:
                logger.warning("Failed to build plugin settings", exc_info=True)

            self.app.page.update()
        except Exception as exc:
            logger.warning("Failed to load config: %s", exc)
            self._rebuild_dir_list(config.video_directories)
            try:
                self._sync_plugins_from_db({})
                self._build_plugin_settings({})
            except Exception:
                pass
            self.app.page.update()

    def _auto_save(self):
        """Silently persist all settings — no snack, no UI noise."""
        async def _do():
            await self._save_config(silent=True)
        self.app.page.run_task(_do)

    def _save(self):
        async def _do_save():
            await self._save_config(silent=False)
        self.app.page.run_task(_do_save)

    async def _save_config(self, silent: bool = False):
        from app.config import config
        from app.database.engine import async_session_factory
        from app.database.models import AppSettings
        from sqlalchemy import select

        dirs = self._get_dir_paths()

        try:
            async with async_session_factory() as session:
                settings_data = {
                    "video_directories": ";".join(dirs),
                    "scraper_timeout": self._timeout_field.value,
                    "scraper_retry": self._retry_dd.value,
                    "scraper_concurrency": self._concurrency_field.value,
                    "cache_ttl_days": self._cache_field.value,
                    "scraper_interval": self._interval_field.value,
                    "scraper_jitter": self._jitter_field.value,
                    "scraper_user_agent": self._ua_field.value or "",
                    "proxy_url": self._proxy_field.value or "",
                    "nfo_enabled": "1" if self._nfo_sw.value else "0",
                    "poster_enabled": "1" if self._poster_sw.value else "0",
                    "hotswap_enabled": "1" if self._hotswap_sw.value else "0",
                }
                # Persist plugin enable/disable states
                for name, vars_dict in self._plugin_vars.items():
                    settings_data[f"plugin_enabled_{name}"] = \
                        "1" if vars_dict["enabled_sw"].value else "0"
                    settings_data[f"plugin_priority_{name}"] = \
                        vars_dict["priority_field"].value
                for key, val in settings_data.items():
                    result = await session.execute(
                        select(AppSettings).where(AppSettings.key == key))
                    record = result.scalar_one_or_none()
                    if record:
                        record.value = val
                    else:
                        session.add(AppSettings(key=key, value=val))
                await session.commit()

            # Update runtime config
            config.video_directories = dirs
            try:
                config.scraper_timeout = float(self._timeout_field.value)
            except ValueError:
                pass
            try:
                config.scraper_retry = int(self._retry_dd.value)
            except ValueError:
                pass
            try:
                config.scraper_concurrency = max(1, min(10, int(self._concurrency_field.value)))
            except ValueError:
                pass
            try:
                config.cache_ttl_days = int(self._cache_field.value)
            except ValueError:
                pass
            try:
                config.scraper_interval = float(self._interval_field.value)
            except ValueError:
                pass
            try:
                config.scraper_jitter = float(self._jitter_field.value)
            except ValueError:
                pass
            config.scraper_user_agent = self._ua_field.value or config.scraper_user_agent
            config.proxy_url = self._proxy_field.value or ""

            # Plugins: runtime state was already updated by _on_plugin_toggle/_on_plugin_priority.
            # Just ensure cross-page sync picks up the current cls.enabled/cls.priority.

            # Sync plugin state across pages
            if hasattr(self.app, 'sync_plugins'):
                self.app.sync_plugins()

            # Refresh dashboard
            if hasattr(self.app, 'dashboard') and hasattr(self.app.dashboard, 'refresh'):
                self.app.dashboard.refresh()

            if not silent:
                self.app.snack("设置已保存", SUCCESS)
        except Exception as exc:
            logger.exception("Save config failed: %s", exc)
            if not silent:
                self.app.snack(f"保存失败: {exc}", DANGER)

    def _pick_dir(self):
        async def _do_pick():
            picker = ft.FilePicker()
            path = await picker.get_directory_path()
            if path:
                self._add_dir_row(path)
                self._auto_save()
        self.app.page.run_task(_do_pick)
