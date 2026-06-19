"""Scraper page — plugin list + params panel + preview + batch scraping with NFO/log."""
import flet as ft
import logging
import time
import os
from pathlib import Path

from app.database.engine import async_session_factory
from app.flet_gui.theme import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BORDER,
    TEXT_PRIMARY, TEXT_SECONDARY, ACCENT,
    SUCCESS, WARNING, DANGER,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG,
    PAD_XS, PAD_SM, PAD_MD, PAD_LG,
    pad_all, pad_symmetric, margin_only, border_all,
)

logger = logging.getLogger(__name__)

_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        from app.scraper.registry import ScraperRegistry
        _registry = ScraperRegistry()
        _registry.discover()
    return _registry


async def _download_poster(poster_url: str, video_id: int, video_filepath: str = "") -> str | None:
    """Download poster from URL and save alongside the video file."""
    if not poster_url or not poster_url.startswith(("http://", "https://")):
        return None
    import httpx
    from app.config import config

    if video_filepath:
        video_path = Path(video_filepath)
        meta_dir = video_path.parent / "metadata"
        meta_dir.mkdir(parents=True, exist_ok=True)
        ext = os.path.splitext(poster_url.split("?")[0])[1] or ".jpg"
        ext = ext if ext.lower() in (".jpg", ".jpeg") else ".jpg"
        local_path = meta_dir / f"{video_path.stem}-poster{ext}"
    else:
        from app.config import DATA_DIR
        poster_dir = DATA_DIR / "posters"
        poster_dir.mkdir(parents=True, exist_ok=True)
        ext = os.path.splitext(poster_url.split("?")[0])[1] or ".jpg"
        ext = ext if ext.lower() in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
        local_path = poster_dir / f"{video_id}{ext}"

    if local_path.exists() and local_path.stat().st_size > 0:
        return str(local_path)

    try:
        base = "/".join(poster_url.split("/")[:3])
        headers = {
            "User-Agent": config.scraper_user_agent,
            "Referer": f"{base}/en/",
            "Origin": base,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(poster_url)
            if resp.status_code == 403:
                headers["Referer"] = base + "/"
                resp = await client.get(poster_url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return None
            local_path.write_bytes(resp.content)
            return str(local_path)
    except Exception as exc:
        logger.warning("Failed to download poster %s: %s", poster_url, exc)
        return None


class ScraperPage:
    def __init__(self, app):
        self.app = app
        self._plugins: list[dict] = []
        self._running = False
        self._batch_ids: list[int] = []
        self._pending_items: list[dict] = []   # {code, title, status}
        self._completed_items: list[dict] = [] # {code, title, status, scraper}

    def build(self) -> ft.Control:
        # Progress
        self._progress_bar = ft.ProgressBar(value=0.0, bgcolor=BG_TERTIARY, color=ACCENT, expand=True)
        self._progress_pct = ft.Text("0%", size=FONT_SM, color=ACCENT)
        self._progress_label = ft.Text("就绪", size=FONT_SM, color=TEXT_SECONDARY)

        # Column 1: Log
        self._log_view = ft.ListView(
            spacing=2, expand=True,
            controls=[ft.Text("刮削日志将在此显示...", size=FONT_XS, color=TEXT_SECONDARY, italic=True)],
        )

        # Column 2: Pending queue
        self._pending_view = ft.ListView(
            spacing=4, expand=True,
            controls=[ft.Text("暂无待刮削任务", size=FONT_SM, color=TEXT_SECONDARY, italic=True)],
        )

        # Column 3: Completed list
        self._completed_view = ft.ListView(
            spacing=4, expand=True,
            controls=[ft.Text("暂无已完成任务", size=FONT_SM, color=TEXT_SECONDARY, italic=True)],
        )

        # Plugin list
        self._plugin_list = ft.Column(spacing=PAD_XS, controls=[])

        # Preview
        self._code_field = ft.TextField(
            hint_text="输入番号...", dense=True, border_color=BORDER,
            text_size=FONT_SM, expand=True,
        )

        # Params panel
        from app.config import config
        self._timeout_field = ft.TextField(value=str(config.scraper_timeout), dense=True,
                                            border_color=BORDER, text_size=FONT_SM, width=70)
        self._retry_field = ft.TextField(value=str(config.scraper_retry), dense=True,
                                          border_color=BORDER, text_size=FONT_SM, width=50)
        self._ua_field = ft.TextField(value=config.scraper_user_agent, dense=True,
                                       border_color=BORDER, text_size=FONT_XS,
                                       hint_text="自定义 User-Agent")
        self._ua_default = True  # use default UA by default

        self.app.page.run_task(self._load_plugins)

        # ── Action buttons (saved as instance attrs for disable/enable control) ──
        btn_pending = self._scrape_pending_btn = ft.ElevatedButton(
            content=ft.Text("刮削待处理"),
            icon=ft.Icons.PLAY_ARROW_ROUNDED,
            style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff"),
            on_click=lambda e: self._scrape_pending(),
        )
        btn_failed = self._rescrape_failed_btn = ft.OutlinedButton(
            content=ft.Text("重刮失败"),
            icon=ft.Icons.WARNING_AMBER_ROUNDED,
            style=ft.ButtonStyle(side=ft.BorderSide(1, WARNING), color=WARNING),
            on_click=lambda e: self._rescrape_failed(),
        )
        btn_all = self._scrape_all_btn = ft.OutlinedButton(
            content=ft.Text("全部重刮"),
            icon=ft.Icons.REPLAY_ROUNDED,
            style=ft.ButtonStyle(side=ft.BorderSide(1, BORDER), color=TEXT_PRIMARY),
            on_click=lambda e: self._scrape_all(),
        )
        btn_stop = self._stop_btn = ft.OutlinedButton(
            content=ft.Text("停止"), icon=ft.Icons.STOP_ROUNDED,
            style=ft.ButtonStyle(side=ft.BorderSide(1, DANGER), color=DANGER),
            on_click=lambda e: self._stop(),
        )

        return ft.Container(
            bgcolor=BG_PRIMARY,
            padding=pad_all(PAD_LG),
            content=ft.Row(
                spacing=PAD_LG, expand=True,
                controls=[
                    # Left column
                    ft.Container(
                        width=360,
                        content=ft.Column(
                            spacing=PAD_SM, scroll=ft.ScrollMode.AUTO,
                            controls=[
                                # Plugins
                                ft.Text("刮削器插件", size=FONT_MD, weight=ft.FontWeight.BOLD,
                                       color=TEXT_SECONDARY),
                                ft.Container(
                                    bgcolor=BG_TERTIARY, border_radius=8,
                                    padding=pad_all(PAD_SM),
                                    content=self._plugin_list,
                                ),
                                # Preview
                                ft.Text("预览刮削", size=FONT_MD, weight=ft.FontWeight.BOLD,
                                       color=TEXT_SECONDARY),
                                ft.Row(spacing=PAD_SM, controls=[
                                    self._code_field,
                                    ft.ElevatedButton(
                                        content=ft.Text("预览"), icon=ft.Icons.SEARCH,
                                        style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff"),
                                        on_click=lambda e: self._preview(),
                                    ),
                                ]),
                                # Scrape params
                                ft.Divider(height=1, color=BORDER),
                                ft.Text("刮削参数", size=FONT_MD, weight=ft.FontWeight.BOLD,
                                       color=TEXT_SECONDARY),
                                ft.Row(spacing=PAD_SM, controls=[
                                    ft.Text("超时(秒):", size=FONT_SM, color=TEXT_SECONDARY),
                                    self._timeout_field,
                                    ft.Text("重试:", size=FONT_SM, color=TEXT_SECONDARY),
                                    self._retry_field,
                                ]),
                                ft.Row(spacing=PAD_SM, controls=[
                                    ft.Text("UA:", size=FONT_SM, color=TEXT_SECONDARY),
                                    ft.Switch(
                                        value=True, active_color=ACCENT,
                                        label="使用默认 UA",
                                        on_change=lambda e: self._on_ua_toggle(e.control.value),
                                    ),
                                ]),
                                self._ua_field,
                                ft.ElevatedButton(
                                    content=ft.Text("保存参数"),
                                    style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff"),
                                    on_click=lambda e: self._save_params(),
                                ),
                            ],
                        ),
                    ),
                    # Right column: 3-panel layout (log | pending | completed)
                    ft.Container(
                        expand=True,
                        content=ft.Column(
                            spacing=PAD_SM,
                            controls=[
                                ft.Text("任务进度", size=FONT_MD, weight=ft.FontWeight.BOLD,
                                       color=TEXT_SECONDARY),
                                ft.Row(spacing=PAD_SM, controls=[
                                    self._progress_bar,
                                    self._progress_pct,
                                ]),
                                self._progress_label,
                                # Three-column log area
                                ft.Row(spacing=PAD_SM, expand=True, controls=[
                                    # Column 1: 日志
                                    ft.Container(
                                        expand=1,
                                        content=ft.Column(spacing=PAD_XS, controls=[
                                            ft.Text("日志", size=FONT_SM, weight=ft.FontWeight.BOLD,
                                                   color=ACCENT),
                                            ft.Container(
                                                bgcolor=BG_TERTIARY, border_radius=8,
                                                padding=pad_all(PAD_SM), expand=True,
                                                content=self._log_view,
                                            ),
                                        ]),
                                    ),
                                    # Column 2: 待刮削
                                    ft.Container(
                                        expand=1,
                                        content=ft.Column(spacing=PAD_XS, controls=[
                                            ft.Text("待刮削", size=FONT_SM, weight=ft.FontWeight.BOLD,
                                                   color=WARNING),
                                            ft.Container(
                                                bgcolor=BG_TERTIARY, border_radius=8,
                                                padding=pad_all(PAD_SM), expand=True,
                                                content=self._pending_view,
                                            ),
                                        ]),
                                    ),
                                    # Column 3: 已完成
                                    ft.Container(
                                        expand=1,
                                        content=ft.Column(spacing=PAD_XS, controls=[
                                            ft.Text("已完成", size=FONT_SM, weight=ft.FontWeight.BOLD,
                                                   color=SUCCESS),
                                            ft.Container(
                                                bgcolor=BG_TERTIARY, border_radius=8,
                                                padding=pad_all(PAD_SM), expand=True,
                                                content=self._completed_view,
                                            ),
                                        ]),
                                    ),
                                ]),
                                # Action buttons
                                ft.Row(spacing=PAD_SM, controls=[
                                    btn_pending,
                                    btn_failed,
                                    btn_all,
                                    btn_stop,
                                ]),
                            ],
                        ),
                    ),
                ],
            ),
        )

    # ==================================================================
    # Plugin management
    # ==================================================================

    async def _load_plugins(self):
        registry = _get_registry()
        self._plugins = registry.to_dict()
        self._plugin_list.controls = [self._make_plugin_row(p) for p in self._plugins]
        self.app.page.update()

    def _make_plugin_row(self, p: dict) -> ft.Control:
        name = p["name"]
        enabled = p["enabled"]
        priority = p["priority"]
        return ft.Row(spacing=PAD_SM, controls=[
            ft.Switch(value=enabled, active_color=ACCENT,
                      on_change=lambda e, n=name: self._toggle_plugin(n, e.control.value)),
            ft.Text(p["label"], size=FONT_SM, color=TEXT_PRIMARY if enabled else TEXT_SECONDARY),
            ft.Container(expand=True),
            ft.Text(f"优先 {priority}", size=FONT_XS, color=TEXT_SECONDARY),
        ])

    def _toggle_plugin(self, name: str, enable: bool):
        registry = _get_registry()
        if enable:
            registry.enable(name)
        else:
            registry.disable(name)
        self.app.page.run_task(self._load_plugins)
        # Sync settings page plugin state
        if hasattr(self.app, 'sync_plugins'):
            self.app.sync_plugins()

    # ==================================================================
    # Params
    # ==================================================================

    def _save_params(self):
        from app.config import config
        try:
            config.scraper_timeout = float(self._timeout_field.value)
        except ValueError:
            pass
        try:
            config.scraper_retry = max(0, min(5, int(self._retry_field.value)))
        except ValueError:
            pass
        if not self._ua_default:
            ua = self._ua_field.value.strip()
            if ua:
                config.scraper_user_agent = ua

        # Persist to DB
        async def _persist():
            from app.database.engine import async_session_factory
            from app.database.models import AppSettings
            from sqlalchemy import select
            try:
                async with async_session_factory() as session:
                    for key, val in [
                        ("scraper_timeout", self._timeout_field.value),
                        ("scraper_retry", self._retry_field.value),
                        ("scraper_user_agent", self._ua_field.value or ""),
                    ]:
                        result = await session.execute(
                            select(AppSettings).where(AppSettings.key == key))
                        record = result.scalar_one_or_none()
                        if record:
                            record.value = val
                        else:
                            session.add(AppSettings(key=key, value=val))
                    await session.commit()
            except Exception:
                pass
        self.app.page.run_task(_persist)
        self.app.snack("刮削参数已保存", SUCCESS)

    def _on_ua_toggle(self, use_default: bool):
        """Enable/disable custom UA field."""
        self._ua_default = use_default
        self._ua_field.disabled = use_default
        self.app.page.update()

    # ==================================================================
    # Preview
    # ==================================================================

    def _preview(self):
        code = self._code_field.value.strip()
        if not code:
            self.app.snack("请输入番号", WARNING)
            return
        async def _run():
            await self._do_preview(code)
        self.app.page.run_task(_run)

    async def _do_preview(self, code: str):
        from app.scraper.engine import ScrapeEngine
        self._log(f"预览刮削: {code} ...")
        try:
            async with async_session_factory() as session:
                engine = ScrapeEngine(_get_registry(), session)
                metadata, scraper = await engine.scrape_single(code, code + ".mp4")
                info = (
                    f"✅ 刮削成功\n"
                    f"  插件: {scraper.label}\n"
                    f"  标题: {metadata.title}\n"
                    f"  演员: {', '.join(metadata.actors or [])}\n"
                    f"  分类: {', '.join(metadata.genres or [])}\n"
                    f"  日期: {metadata.premiered or 'N/A'}\n"
                    f"  时长: {metadata.runtime or 'N/A'} min\n"
                    f"  评分: {metadata.rating or 'N/A'}"
                )
                self._log(info)
        except Exception as exc:
            self._log(f"❌ 刮削失败: {exc}")

    # ==================================================================
    # Batch scraping
    # ==================================================================

    def _scrape_pending(self):
        if self._running:
            self.app.snack("已有刮削任务在运行", WARNING)
            return
        ids = [p["id"] for p in self._pending_items if p["status"] != "scraping"]
        if not ids:
            self.app.snack("没有待刮削的任务", WARNING)
            return
        async def _run():
            await self._do_batch(ids)
        self.app.page.run_task(_run)

    def _scrape_all(self):
        if self._running:
            self.app.snack("已有刮削任务在运行", WARNING)
            return
        if not self._completed_items:
            self.app.snack("没有已完成的条目可重刮", WARNING)
            return
        ids = [c["id"] for c in self._completed_items]
        # Confirmation dialog
        def _confirm(e):
            self.app.page.pop_dialog()
            self._completed_items.clear()  # re-scraping: clear old completed list
            async def _run():
                await self._do_batch(ids, clear_pending=False)  # don't wipe pending list
            self.app.page.run_task(_run)

        def _cancel(e):
            self.app.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text("确认重新刮削", size=FONT_MD, weight=ft.FontWeight.BOLD,
                         color=TEXT_PRIMARY),
            content=ft.Text(f"确定要重新刮削这 {len(ids)} 个已完成文件吗？\n这将替换已有的刮削数据。",
                           size=FONT_SM, color=TEXT_SECONDARY),
            actions=[
                ft.ElevatedButton(
                    content=ft.Text("确定"), icon=ft.Icons.CHECK,
                    style=ft.ButtonStyle(bgcolor=DANGER, color="#ffffff"),
                    on_click=_confirm,
                ),
                ft.TextButton(content=ft.Text("取消"), on_click=_cancel),
            ],
            bgcolor=BG_SECONDARY,
        )
        self.app.page.show_dialog(dlg)

    def _rescrape_failed(self):
        """Re-scrape only failed items in the pending list."""
        if self._running:
            self.app.snack("已有刮削任务在运行", WARNING)
            return
        ids = [p["id"] for p in self._pending_items if p["status"] == "failed"]
        if not ids:
            self.app.snack("没有失败的条目可重刮", WARNING)
            return
        async def _run():
            await self._do_batch(ids)
        self.app.page.run_task(_run)

    def _set_buttons_disabled(self, disabled: bool):
        """Enable/disable scrape action buttons during batch run."""
        self._scrape_pending_btn.disabled = disabled
        self._rescrape_failed_btn.disabled = disabled
        self._scrape_all_btn.disabled = disabled
        self.app.page.update()

    def start_scrape_for_ids(self, ids: list[int]):
        """Called by files page to scrape specific IDs."""
        if not ids:
            return
        self._batch_ids = ids
        if self._running:
            self.app.snack("已有刮削任务在运行", WARNING)
            return
        async def _run():
            await self._do_scrape_ids(ids)
        self.app.page.run_task(_run)

    async def _do_batch(self, ids: list[int], clear_pending: bool = True):
        from sqlalchemy import select
        from app.database.models import VideoFile
        from app.database.repository import MetadataRepository, ScrapeLogRepository
        from app.scraper.engine import ScrapeEngine

        self._running = True
        self._set_buttons_disabled(True)
        self._log("🚀 开始批量刮削...")
        start_time = time.time()
        success = 0
        failed = 0
        completed = 0

        try:
            async with async_session_factory() as session:
                stmt = select(VideoFile).where(VideoFile.id.in_(ids))
                result = await session.execute(stmt)
                files = result.scalars().all()

                if not files:
                    self._log("没有找到指定文件")
                    self._running = False
                    self._update_progress_ui()
                    return

                total = len(files)
                self._log(f"共 {total} 个文件待刮削")
                self._init_pending_queue(files, clear_first=clear_pending)
                engine = ScrapeEngine(_get_registry(), session)

                for f in files:
                    if not self._running:
                        self._log("⏹ 用户停止刮削")
                        break

                    code = f.parsed_code or ""
                    if not code:
                        self._log(f"⏭ 跳过 (无识别码): {f.filename}")
                        continue

                    self._mark_scraping(code, f.id)
                    self._update_progress(completed, total, f"刮削中 [{completed+1}/{total}]: {code}")
                    print(f"[SCRAPER] before scrape_single: code={code}")
                    try:
                        metadata, scraper = await engine.scrape_single(code, f.filename)
                        print(f"[SCRAPER] after scrape_single SUCCESS: code={code}")
                        self._move_to_completed(code, metadata.title or code, scraper.label, f.id)

                        # Save metadata
                        mrepo = MetadataRepository(session)
                        await mrepo.upsert(
                            video_id=f.id, title=metadata.title,
                            original_title=metadata.original_title, plot=metadata.plot,
                            poster_url=metadata.poster_url, fanart_urls=metadata.fanart_urls,
                            year=metadata.year, premiered=metadata.premiered,
                            runtime=metadata.runtime, genres=metadata.genres,
                            tags=metadata.tags, actors=metadata.actors,
                            director=metadata.director, studio=metadata.studio,
                            rating=metadata.rating, source_plugin=scraper.name,
                            source_url=metadata.source_url, raw_data=metadata.raw_data,
                        )

                        # Scrape log
                        log_repo = ScrapeLogRepository(session)
                        await log_repo.log(f.id, scraper.name, "success",
                                          source_url=metadata.source_url)

                        f.status = "done"
                        success += 1
                        self._log(f"  ✅ {scraper.label} — {metadata.title or code}")

                        # NFO generation
                        try:
                            from app.nfo.generator import NFOGenerator
                            from app.nfo.writer import NFOWriter
                            meta_record = await mrepo.get_by_video_id(f.id)
                            if meta_record:
                                gen = NFOGenerator()
                                xml = gen.generate(meta_record)
                                nfo_path = NFOWriter.write(f.filepath, xml)
                                self._log(f"  ✓ NFO: {nfo_path.name}")
                        except Exception as nfo_exc:
                            self._log(f"  ✗ NFO: {nfo_exc}")

                        # Poster download
                        if metadata.poster_url:
                            try:
                                poster_path = await _download_poster(
                                    metadata.poster_url, f.id, f.filepath)
                                if poster_path:
                                    self._log(f"  ✓ 海报: {Path(poster_path).name}")
                            except Exception as poster_exc:
                                self._log(f"  ✗ 海报: {poster_exc}")

                    except Exception as exc:
                        f.status = "failed"
                        failed += 1
                        self._log(f"  ❌ {code}: {exc}")
                        self._mark_failed(code, f.id, str(exc))
                        try:
                            await ScrapeLogRepository(session).log(
                                f.id, "chain", "failed", error_message=str(exc))
                        except Exception:
                            pass

                    completed += 1
                    await session.flush()

                await session.commit()

        except Exception as exc:
            logger.exception("Batch scrape failed")
            self._log(f"❌ 批量刮削异常: {exc}")
        finally:
            elapsed = time.time() - start_time
            self._log(f"🏁 刮削完成 · {elapsed:.1f}s · 成功 {success} · 失败 {failed}")
            self._running = False
            self._set_buttons_disabled(False)
            self._update_progress(completed, completed, "完成")
            self._refresh_all_pages()
            self.app.page.update()

    async def _do_scrape_ids(self, ids: list[int]):
        from sqlalchemy import select
        from app.database.models import VideoFile
        from app.database.repository import MetadataRepository, ScrapeLogRepository
        from app.scraper.engine import ScrapeEngine

        self._running = True
        self._set_buttons_disabled(True)
        self._log(f"🚀 刮削指定文件: {len(ids)} 个")
        start_time = time.time()
        success = 0
        failed = 0
        completed = 0

        try:
            async with async_session_factory() as session:
                stmt = select(VideoFile).where(VideoFile.id.in_(ids))
                result = await session.execute(stmt)
                files = result.scalars().all()

                if not files:
                    self._log("没有找到指定文件")
                    self._running = False
                    return

                total = len(files)
                self._init_pending_queue(files)
                engine = ScrapeEngine(_get_registry(), session)

                for f in files:
                    if not self._running:
                        self._log("⏹ 用户停止刮削")
                        break

                    code = f.parsed_code or ""
                    self._mark_scraping(code, f.id)
                    self._update_progress(completed, total, f"刮削中 [{completed+1}/{total}]: {code}")
                    print(f"[SCRAPER] before scrape_single: code={code}")
                    try:
                        metadata, scraper = await engine.scrape_single(code, f.filename)
                        print(f"[SCRAPER] after scrape_single SUCCESS: code={code}")
                        self._move_to_completed(code, metadata.title or code, scraper.label, f.id)
                        mrepo = MetadataRepository(session)
                        await mrepo.upsert(
                            video_id=f.id, title=metadata.title,
                            original_title=metadata.original_title, plot=metadata.plot,
                            poster_url=metadata.poster_url, fanart_urls=metadata.fanart_urls,
                            year=metadata.year, premiered=metadata.premiered,
                            runtime=metadata.runtime, genres=metadata.genres,
                            actors=metadata.actors, director=metadata.director,
                            studio=metadata.studio, rating=metadata.rating,
                            source_plugin=scraper.name, source_url=metadata.source_url,
                            raw_data=metadata.raw_data,
                        )
                        await ScrapeLogRepository(session).log(
                            f.id, scraper.name, "success", source_url=metadata.source_url)
                        f.status = "done"
                        success += 1
                        self._log(f"  ✅ {scraper.label} — {metadata.title or code}")

                        try:
                            from app.nfo.generator import NFOGenerator
                            from app.nfo.writer import NFOWriter
                            meta_record = await mrepo.get_by_video_id(f.id)
                            if meta_record:
                                NFOWriter.write(f.filepath, NFOGenerator().generate(meta_record))
                        except Exception:
                            pass

                        if metadata.poster_url:
                            try:
                                await _download_poster(metadata.poster_url, f.id, f.filepath)
                            except Exception:
                                pass

                    except Exception as exc:
                        f.status = "failed"
                        failed += 1
                        self._log(f"  ❌ {code}: {exc}")
                        self._mark_failed(code, f.id, str(exc))
                        try:
                            await ScrapeLogRepository(session).log(
                                f.id, "chain", "failed", error_message=str(exc))
                        except Exception:
                            pass

                    completed += 1
                    await session.flush()

                await session.commit()

        except Exception as exc:
            logger.exception("Scrape by IDs failed: %s", exc)
            self._log(f"❌ 刮削异常: {exc}")
        finally:
            elapsed = time.time() - start_time
            self._log(f"🏁 刮削完成 · {elapsed:.1f}s · 成功 {success} · 失败 {failed}")
            self._running = False
            self._set_buttons_disabled(False)
            self._update_progress(completed, completed, "完成")
            self._refresh_all_pages()
            self.app.page.update()

    def _update_progress(self, done: int, total: int, msg: str):
        pct = done / total if total > 0 else 0.0
        self._progress_bar.value = pct
        self._progress_pct.value = f"{int(pct * 100)}%"
        self._progress_label.value = msg
        self.app.page.update()

    def _update_progress_ui(self):
        self._progress_bar.value = 0.0
        self._progress_pct.value = "0%"
        self._progress_label.value = "就绪"
        self.app.page.update()

    def _refresh_all_pages(self):
        """Refresh dashboard, files, and browser after scrape."""
        if hasattr(self.app, 'dashboard') and hasattr(self.app.dashboard, 'refresh'):
            self.app.dashboard.refresh()
        if hasattr(self.app, 'files') and hasattr(self.app.files, 'refresh'):
            self.app.files.refresh()
        if hasattr(self.app, 'browser') and hasattr(self.app.browser, 'refresh'):
            self.app.browser.refresh()

    def _stop(self):
        self._running = False
        self._log("⏹ 正在停止...")
        self.app.snack("刮削任务已停止")

    def _log(self, msg: str):
        color = TEXT_PRIMARY if "✅" in msg or "🏁" in msg else (
            DANGER if "❌" in msg or "✗" in msg else TEXT_SECONDARY)
        self._log_view.controls.append(ft.Text(msg, size=FONT_XS, color=color))
        self.app.page.update()

    def _init_pending_queue(self, files: list, clear_first: bool = True):
        """Initialize pending queue. When clear_first=False, appends without clearing (for re-scrape)."""
        if clear_first:
            self._pending_items.clear()
        existing_ids = {p["id"] for p in self._pending_items}
        for f in files:
            if f.id in existing_ids:
                continue  # already in queue
            code = f.parsed_code or f.filename[:20]
            self._pending_items.append({"id": f.id, "code": code, "title": "", "status": "queued", "failed_reason": ""})
        print(f"[SCRAPER] _init_pending_queue: {len(self._pending_items)} items, ids={[p['id'] for p in self._pending_items]}")
        self._rebuild_pending_view()

    def _rebuild_pending_view(self):
        """Full rebuild of pending list view with styled card rows."""
        if not self._pending_items:
            self._pending_view.controls = [
                ft.Text("暂无待刮削任务", size=FONT_SM, color=TEXT_SECONDARY, italic=True)
            ]
            return

        rows = []
        for p in self._pending_items:
            status = p["status"]
            if status == "failed":
                icon = "✕"
                icon_color = DANGER
                text_color = DANGER
            elif status == "scraping":
                icon = "⟳"
                icon_color = WARNING
                text_color = WARNING
            else:
                icon = "○"
                icon_color = TEXT_SECONDARY
                text_color = TEXT_SECONDARY

            row_controls = [
                ft.Text(icon, size=FONT_SM, color=icon_color),
                ft.Text(p["code"], size=FONT_SM, color=text_color, weight=ft.FontWeight.W_600),
            ]

            tooltip = None
            if status == "failed" and p.get("failed_reason"):
                tooltip = p["failed_reason"]
                row_controls.append(ft.Container(expand=True))
                row_controls.append(ft.Text(
                    p["failed_reason"], size=FONT_XS, color=DANGER,
                    italic=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                ))

            rows.append(ft.Container(
                bgcolor=BG_TERTIARY,
                border_radius=6,
                border=border_all(1, BORDER),
                padding=pad_symmetric(PAD_SM, PAD_XS),
                margin=margin_only(bottom=4),
                tooltip=tooltip,
                content=ft.Row(spacing=PAD_SM, controls=row_controls,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        self._pending_view.controls = rows

    def _find_pending_idx(self, file_id: int) -> int | None:
        """Find pending item index by file_id. Returns None if not found."""
        for i, p in enumerate(self._pending_items):
            if p["id"] == file_id:
                return i
        return None

    def _mark_scraping(self, code: str, file_id: int):
        """Mark item in pending queue as currently scraping."""
        for p in self._pending_items:
            if p["id"] == file_id:
                p["status"] = "scraping"
                print(f"[SCRAPER] _mark_scraping OK: id={file_id} code={code}")
                break
        else:
            print(f"[SCRAPER] _mark_scraping NOT FOUND: id={file_id} code={code} pending_ids={[p['id'] for p in self._pending_items]}")
        self._rebuild_pending_view()
        self.app.page.update()

    def _move_to_completed(self, code: str, title: str, scraper: str, file_id: int):
        """Move item from pending to completed list."""
        before = len(self._pending_items)
        self._pending_items = [p for p in self._pending_items if p["id"] != file_id]
        after = len(self._pending_items)
        print(f"[SCRAPER] _move_to_completed: id={file_id} code={code} before={before} after={after}")
        display = title[:20] if title else code
        self._completed_items.append({"id": file_id, "code": code, "title": title, "scraper": scraper})

        self._rebuild_pending_view()
        self._completed_view.controls = [
            ft.Container(
                bgcolor=BG_TERTIARY,
                border_radius=6,
                border=border_all(1, BORDER),
                padding=pad_symmetric(PAD_SM, PAD_XS),
                margin=margin_only(bottom=4),
                content=ft.Row(spacing=PAD_SM, controls=[
                    ft.Text("✓", size=FONT_SM, color=SUCCESS),
                    ft.Text(item["code"], size=FONT_SM, color=SUCCESS, weight=ft.FontWeight.W_600),
                    ft.Text(item["title"][:20] if item["title"] else "", size=FONT_SM, color=TEXT_SECONDARY),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            for item in self._completed_items
        ] or [ft.Text("暂无已完成任务", size=FONT_SM, color=TEXT_SECONDARY, italic=True)]

        print(f"[SCRAPER] _move_to_completed rebuilt: pending={len(self._pending_view.controls)} completed={len(self._completed_view.controls)}")
        self.app.page.update()

    def _mark_failed(self, code: str, file_id: int, reason: str = ""):
        """Mark item as failed in pending queue with optional failure reason."""
        for p in self._pending_items:
            if p["id"] == file_id:
                p["status"] = "failed"
                p["failed_reason"] = reason[:80] if reason else ""
                print(f"[SCRAPER] _mark_failed OK: id={file_id} code={code} reason={reason[:40]}")
                break
        else:
            print(f"[SCRAPER] _mark_failed NOT FOUND: id={file_id} code={code}")
        self._rebuild_pending_view()
        self.app.page.update()
