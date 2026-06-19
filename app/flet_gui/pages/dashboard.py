"""Dashboard page — real DB stats + quick actions + recent activity."""
import flet as ft
import logging
from app.database.engine import async_session_factory
from app.flet_gui.theme import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BORDER,
    TEXT_PRIMARY, TEXT_SECONDARY, ACCENT,
    SUCCESS, WARNING, DANGER,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG, FONT_XL, FONT_XXL,
    PAD_XS, PAD_SM, PAD_MD, PAD_LG, PAD_XL,
    pad_all, pad_symmetric, border_only,
)

logger = logging.getLogger(__name__)


class DashboardPage:
    def __init__(self, app):
        self.app = app
        self._total_val = ft.Text("0", size=FONT_XXL, weight=ft.FontWeight.BOLD, color=SUCCESS)
        self._done_val = ft.Text("0", size=FONT_XXL, weight=ft.FontWeight.BOLD, color=ACCENT)
        self._pending_val = ft.Text("0", size=FONT_XXL, weight=ft.FontWeight.BOLD, color=WARNING)
        self._failed_val = ft.Text("0", size=FONT_XXL, weight=ft.FontWeight.BOLD, color=DANGER)

    def build(self) -> ft.Control:
        self._log_view = ft.ListView(spacing=4, expand=True, controls=[
            ft.Text("加载中...", size=FONT_SM, color=TEXT_SECONDARY, italic=True),
        ])

        self.app.page.run_task(self._load_stats)

        return ft.Container(
            bgcolor=BG_PRIMARY,
            padding=pad_all(PAD_LG),
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=PAD_MD,
                controls=[
                    ft.Row(
                        spacing=PAD_SM,
                        controls=[
                            self._card("总文件数", self._total_val, SUCCESS),
                            self._card("已刮削", self._done_val, ACCENT),
                            self._card("待处理", self._pending_val, WARNING),
                            self._card("失败", self._failed_val, DANGER),
                        ],
                    ),
                    ft.Row(spacing=PAD_SM, controls=[
                        ft.ElevatedButton(
                            content=ft.Text("扫描目录"),
                            icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                            style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff",
                                                padding=pad_symmetric(16, 10)),
                            on_click=lambda e: self._scan(),
                        ),
                        ft.OutlinedButton(
                            content=ft.Text("批量刮削"),
                            icon=ft.Icons.DOWNLOADING_ROUNDED,
                            style=ft.ButtonStyle(side=ft.BorderSide(1, BORDER),
                                                color=TEXT_PRIMARY,
                                                padding=pad_symmetric(16, 10)),
                            on_click=lambda e: self._batch_scrape(),
                        ),
                        ft.OutlinedButton(
                            content=ft.Text("导出 NFO"),
                            icon=ft.Icons.DESCRIPTION_ROUNDED,
                            style=ft.ButtonStyle(side=ft.BorderSide(1, BORDER),
                                                color=TEXT_PRIMARY,
                                                padding=pad_symmetric(16, 10)),
                            on_click=lambda e: self._export_nfo(),
                        ),
                    ]),
                    ft.Text("最近活动", size=FONT_MD, weight=ft.FontWeight.BOLD,
                           color=TEXT_SECONDARY),
                    ft.Container(
                        bgcolor=BG_TERTIARY, border_radius=8,
                        padding=pad_all(PAD_MD), expand=True,
                        content=self._log_view,
                    ),
                ],
            ),
        )

    def _card(self, label: str, value_widget: ft.Text, color: str) -> ft.Control:
        return ft.Container(
            bgcolor=BG_TERTIARY, border_radius=10,
            border=border_only(left=ft.BorderSide(3, color)),
            padding=pad_all(PAD_LG), expand=True,
            content=ft.Column(spacing=2, controls=[
                ft.Text(label, size=FONT_SM, color=TEXT_SECONDARY),
                value_widget,
            ]),
        )

    # ==================================================================
    # Data loading
    # ==================================================================

    async def _load_stats(self) -> None:
        from sqlalchemy import text
        try:
            async with async_session_factory() as session:
                result = await session.execute(text(
                    "SELECT status, COUNT(*) FROM video_files GROUP BY status"
                ))
                counts = {row[0]: row[1] for row in result.fetchall()}
                total = sum(counts.values())
                done = counts.get("done", 0)
                pending = counts.get("pending", 0)
                failed = counts.get("failed", 0)

                self._total_val.value = str(total)
                self._done_val.value = str(done)
                self._pending_val.value = str(pending)
                self._failed_val.value = str(failed)

                # Load recent activity from BatchTask
                activity_lines = [
                    ft.Text(f"数据库中共 {total} 个视频文件", size=FONT_SM, color=TEXT_PRIMARY),
                    ft.Text(f"已刮削完成: {done} 个", size=FONT_SM, color=SUCCESS),
                    ft.Text(f"待处理: {pending} 个", size=FONT_SM, color=WARNING),
                    ft.Text(f"失败: {failed} 个", size=FONT_SM, color=DANGER) if failed else ft.Text(""),
                    ft.Divider(height=1, color=BORDER),
                ]
                self._log_view.controls = activity_lines

                self.app.page.update()
                # Load real BatchTask activity
                self.app.page.run_task(self._load_recent_activity)
        except Exception as exc:
            logger.exception("Load stats failed: %s", exc)
            self._log_view.controls = [
                ft.Text(f"加载失败: {exc}", size=FONT_SM, color=DANGER),
            ]
            self.app.page.update()

    async def _load_recent_activity(self) -> None:
        from sqlalchemy import text
        try:
            async with async_session_factory() as session:
                result = await session.execute(text(
                    "SELECT task_type, status, completed, total, created_at "
                    "FROM batch_tasks ORDER BY created_at DESC LIMIT 20"
                ))
                rows = result.fetchall()
                if rows:
                    lines = []
                    for row in rows:
                        ttype_map = {"scan": "扫描", "scrape": "刮削", "export": "导出"}
                        status_map = {"completed": "完成", "failed": "失败",
                                      "running": "进行中", "pending": "等待"}
                        ttype = ttype_map.get(row[0], row[0])
                        status = status_map.get(row[1], row[1])
                        ts = row[4].strftime("%H:%M") if row[4] else ""
                        lines.append(ft.Text(
                            f"[{ts}] {ttype} — {status} ({row[2]}/{row[3]})",
                            size=FONT_XS, color=TEXT_SECONDARY
                        ))
                    self._log_view.controls = lines
                else:
                    self._log_view.controls = [
                        ft.Text("暂无活动记录", size=FONT_SM, color=TEXT_SECONDARY, italic=True),
                    ]
                self.app.page.update()
        except Exception:
            pass  # batch_tasks table may not exist

    def refresh(self):
        self.app.page.run_task(self._load_stats)

    # ==================================================================
    # Actions
    # ==================================================================

    def _scan(self):
        async def _do_scan():
            from app.services.scan_service import ScanService
            try:
                self.app.snack("正在扫描目录...", WARNING)
                async with async_session_factory() as session:
                    svc = ScanService(session)
                    result = await svc.scan()
                self.app.snack(
                    f"扫描完成: 新增 {result.get('added', 0)} 个文件",
                    SUCCESS,
                )
                self.refresh()
            except Exception as exc:
                logger.exception("Scan failed: %s", exc)
                self.app.snack(f"扫描失败: {exc}", DANGER)
        self.app.page.run_task(_do_scan)

    def _batch_scrape(self):
        """Switch to scraper tab."""
        self.app._switch_tab(3)  # scraper tab index
        self.app.snack("请在刮削控制页选择刮削范围", TEXT_SECONDARY)

    def _export_nfo(self):
        async def _do_export():
            try:
                from app.database.repository import MetadataRepository, VideoFileRepository
                from app.nfo.generator import NFOGenerator
                from app.nfo.writer import NFOWriter
                async with async_session_factory() as session:
                    vrepo = VideoFileRepository(session)
                    mrepo = MetadataRepository(session)
                    gen = NFOGenerator()
                    items, _ = await vrepo.list_paginated(page=1, size=9999, status="done")
                    count = 0
                    for video in items:
                        meta = await mrepo.get_by_video_id(video.id)
                        if meta:
                            try:
                                xml = gen.generate(meta)
                                NFOWriter.write(video.filepath, xml)
                                count += 1
                            except Exception:
                                pass
                self.app.snack(f"NFO 导出完成: {count} 个文件", SUCCESS)
            except Exception as exc:
                logger.exception("NFO export failed: %s", exc)
                self.app.snack(f"导出失败: {exc}", DANGER)
        self.app.page.run_task(_do_export)
