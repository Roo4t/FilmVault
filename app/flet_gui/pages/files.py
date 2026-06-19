"""Files page — DataTable with real DB + status/name filter + scan/scrape/export + detail."""
import asyncio, os, subprocess, json as _json, logging
import flet as ft
from app.database.engine import async_session_factory
from app.flet_gui.theme import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BORDER,
    TEXT_PRIMARY, TEXT_SECONDARY, ACCENT,
    SUCCESS, WARNING, DANGER,
    FONT_XS, FONT_SM, FONT_MD,
    PAD_XS, PAD_SM, PAD_MD, PAD_LG,
    pad_all, pad_only, pad_symmetric, border_all, radius_only,
)

logger = logging.getLogger(__name__)

STATUS_LABELS = {"pending": "待刮削", "scraping": "刮削中", "done": "已完成", "failed": "失败"}
STATUS_REVERSE = {"待刮削": "pending", "刮削中": "scraping", "已完成": "done", "失败": "failed"}
STATUS_COLORS = {"done": SUCCESS, "pending": WARNING, "scraping": ACCENT, "failed": DANGER}
STATUS_BG = {
    "done": ft.Colors.with_opacity(0.10, SUCCESS),
    "pending": ft.Colors.with_opacity(0.10, WARNING),
    "scraping": ft.Colors.with_opacity(0.10, ACCENT),
    "failed": ft.Colors.with_opacity(0.10, DANGER),
}

PAGE_SIZES = [30, 50, 80, 100, 200]


def _status_tag(status: str) -> ft.Control:
    """Render a status as a rounded colored tag."""
    label = STATUS_LABELS.get(status, status)
    color = STATUS_COLORS.get(status, TEXT_SECONDARY)
    bg = STATUS_BG.get(status, ft.Colors.with_opacity(0.08, TEXT_SECONDARY))
    return ft.Container(
        content=ft.Text(label, size=10, color=color, weight=ft.FontWeight.W_600),
        bgcolor=bg, border_radius=10,
        padding=ft.Padding(left=8, top=2, right=8, bottom=2),
    )


class FilesPage:
    def __init__(self, app):
        self.app = app
        self._all_files: list[dict] = []   # all loaded files
        self._filtered: list[dict] = []    # after filter
        self._status_filter = ""
        self._search_text = ""
        self._selected_ids: set[int] = set()
        self._page = 1
        self._page_size = PAGE_SIZES[0]

    def build(self) -> ft.Control:
        # ── Filter bar ──
        self._status_dd = ft.Dropdown(
            value="全部",
            options=[ft.dropdown.Option("全部", "全部"),
                     ft.dropdown.Option("pending", "待刮削"),
                     ft.dropdown.Option("scraping", "刮削中"),
                     ft.dropdown.Option("done", "已完成"),
                     ft.dropdown.Option("failed", "失败")],
            width=120, dense=True, border_color=BORDER, text_size=FONT_SM,
            border_radius=6,
            content_padding=ft.Padding(left=10, top=0, right=6, bottom=0),
            on_select=lambda e: self._on_filter_change(),
        )
        self._search_field = ft.TextField(
            hint_text="搜索文件名/番号...", dense=True,
            border_color=BORDER, text_size=FONT_SM, width=240,
            border_radius=6, prefix_icon=ft.Icons.SEARCH_ROUNDED,
            content_padding=ft.Padding(left=10, top=0, right=10, bottom=0),
            on_submit=lambda e: self._on_search(),
        )
        # Reset button (replaces old C button)
        reset_btn = ft.IconButton(
            ft.Icons.FILTER_LIST_OFF, icon_size=18, icon_color=TEXT_SECONDARY,
            tooltip="重置筛选",
            style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.06, ACCENT)),
            on_click=lambda e: self._reset_filters(),
        )

        # ── Action buttons ──
        self._scan_btn = ft.OutlinedButton(
            content=ft.Text("扫描目录"), icon=ft.Icons.FOLDER_OPEN,
            style=ft.ButtonStyle(
                side=ft.BorderSide(1, BORDER), color=TEXT_PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            on_click=lambda e: self._scan(),
        )
        self._batch_scrape_btn = ft.ElevatedButton(
            content=ft.Text("开始刮削"), icon=ft.Icons.DOWNLOADING,
            disabled=True,
            style=ft.ButtonStyle(
                bgcolor="#3a3a4a", color="#7a7a8a",
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            on_click=lambda e: self._batch_scrape(),
        )
        self._export_btn = ft.OutlinedButton(
            content=ft.Text("导出 NFO"), icon=ft.Icons.DESCRIPTION,
            style=ft.ButtonStyle(
                side=ft.BorderSide(1, BORDER), color=TEXT_PRIMARY,
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            on_click=lambda e: self._export_nfo(),
        )

        # ── Select-all + invert selection ──
        self._select_all_cb = ft.Checkbox(
            value=False, active_color=ACCENT, check_color="#ffffff",
            on_change=lambda e: self._do_select_all(e.control.value),
        )
        self._select_all_btn = ft.TextButton(
            content=ft.Text("全选", size=FONT_XS, color=TEXT_SECONDARY),
            on_click=lambda e: self._do_select_all(not self._select_all_cb.value),
            style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.04, ACCENT)),
        )
        self._invert_btn = ft.TextButton(
            content=ft.Text("反选", size=FONT_XS, color=TEXT_SECONDARY),
            on_click=lambda e: self._invert_selection(),
            style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.04, ACCENT)),
        )

        # ── Custom table with sticky header ──
        # Column config: (header_text, alignment, expand_weight, fixed_width)
        # expand_weight=0 → fixed_width; expand_weight>0 → weighted expand
        self._col_config = [
            ("",        "center", 0, 44),   # 0: checkbox
            ("文件名",  "center", 0, 200),  # 1: filename — fixed width, centered
            ("识别码",  "center", 0, 85),   # 2: code
            ("状态",    "center", 0, 80),   # 3: status tag
            ("标题",    "left",   1, 0),    # 4: title — expand (all remaining space)
            ("分类",    "center", 0, 130),  # 5: genres
            ("更新时间","center", 0, 130),  # 6: updated
            ("",        "right",  0, 48),   # 7: menu
        ]

        def _header_cell(text: str, align: str, weight: int, w: int) -> ft.Control:
            return ft.Container(
                expand=weight if weight > 0 else None,
                width=w if weight == 0 else None,
                alignment=ft.Alignment(
                    -1 if align == "left" else (1 if align == "right" else 0), 0),
                padding=ft.Padding(left=8, top=0, right=8, bottom=0),
                content=ft.Text(text, size=FONT_XS, weight=ft.FontWeight.BOLD, color=TEXT_SECONDARY),
            )

        self._header_row = ft.Container(
            bgcolor=BG_SECONDARY,
            border_radius=radius_only(top_left=8, top_right=8),
            padding=ft.Padding(left=4, top=8, right=4, bottom=8),
            border=border_all(1, BORDER),
            content=ft.Row(spacing=0, controls=[
                _header_cell(t, a, e, w) for t, a, e, w in self._col_config
            ]),
        )

        # Scrollable body rows
        self._body_list = ft.ListView(spacing=0, expand=True, controls=[])
        self._table_body = ft.Container(
            bgcolor=BG_PRIMARY,
            border=border_all(1, BORDER),
            border_radius=radius_only(bottom_left=8, bottom_right=8),
            content=self._body_list,
            expand=True,
        )

        # ── Pagination (bottom) ──
        self._page_field = ft.Dropdown(
            value=str(PAGE_SIZES[0]),
            options=[ft.dropdown.Option(str(s)) for s in PAGE_SIZES],
            width=80, dense=True, border_color=BORDER, text_size=FONT_XS,
            border_radius=6,
            content_padding=ft.Padding(left=10, top=0, right=6, bottom=0),
            on_select=lambda e: self._on_page_size_change(int(e.control.value)),
        )
        self._page_text = ft.Text("", size=FONT_XS, color=TEXT_SECONDARY)
        self._first_btn = ft.IconButton(ft.Icons.FIRST_PAGE_ROUNDED, icon_size=16,
                                        icon_color=TEXT_SECONDARY, disabled=True,
                                        on_click=lambda e: self._go_page(1),
                                        style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.06, ACCENT)))
        self._prev_btn = ft.IconButton(ft.Icons.CHEVRON_LEFT_ROUNDED, icon_size=16,
                                       icon_color=TEXT_SECONDARY, disabled=True,
                                       on_click=lambda e: self._go_page(self._page - 1),
                                       style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.06, ACCENT)))
        self._next_btn = ft.IconButton(ft.Icons.CHEVRON_RIGHT_ROUNDED, icon_size=16,
                                       icon_color=TEXT_SECONDARY, disabled=True,
                                       on_click=lambda e: self._go_page(self._page + 1),
                                       style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.06, ACCENT)))
        self._last_btn = ft.IconButton(ft.Icons.LAST_PAGE_ROUNDED, icon_size=16,
                                       icon_color=TEXT_SECONDARY, disabled=True,
                                       on_click=lambda e: self._go_page(999),
                                       style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.06, ACCENT)))
        self._refresh_btn = ft.IconButton(ft.Icons.REFRESH_ROUNDED, icon_size=18,
                                          icon_color=TEXT_SECONDARY,
                                          on_click=lambda e: self.refresh(),
                                          style=ft.ButtonStyle(overlay_color=ft.Colors.with_opacity(0.06, ACCENT)))

        pagination_row = ft.Row(spacing=4, alignment=ft.MainAxisAlignment.CENTER, controls=[
            ft.Text("每页:", size=FONT_XS, color=TEXT_SECONDARY),
            self._page_field,
            self._first_btn, self._prev_btn,
            self._page_text,
            self._next_btn, self._last_btn,
            self._refresh_btn,
        ])

        # ── Empty placeholder ──
        self._empty_placeholder = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.SEARCH_OFF_ROUNDED, size=48, color=TEXT_SECONDARY),
                ft.Text("没有匹配的文件记录", size=FONT_MD, color=TEXT_SECONDARY),
                ft.Text("请调整筛选条件或扫描目录添加新文件", size=FONT_XS,
                       color=TEXT_SECONDARY),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
            alignment=ft.Alignment(0, 0), expand=True, visible=False,
        )

        self.app.page.run_task(self._load_files)

        return ft.Container(
            bgcolor=BG_PRIMARY,
            padding=pad_all(PAD_LG),
            content=ft.Column(spacing=PAD_SM, controls=[
                # Row 1: filter bar
                ft.Row(spacing=PAD_SM, controls=[
                    ft.Text("状态:", size=FONT_SM, color=TEXT_SECONDARY),
                    self._status_dd,
                    self._search_field,
                    reset_btn,
                ]),
                # Row 2: actions
                ft.Row(spacing=PAD_SM, controls=[
                    self._scan_btn,
                    self._batch_scrape_btn,
                    self._export_btn,
                ]),
                # Select-all row
                ft.Row(spacing=PAD_XS, controls=[
                    self._select_all_cb,
                    self._select_all_btn,
                    self._invert_btn,
                ]),
                # Table: fixed header + scrollable body
                ft.Stack(expand=True, controls=[
                    ft.Column(spacing=0, expand=True, controls=[
                        self._header_row,
                        self._table_body,
                    ]),
                    self._empty_placeholder,
                ]),
                # Row 4: pagination
                pagination_row,
            ]),
        )

    # ==================================================================
    # Data loading
    # ==================================================================

    async def _load_files(self) -> None:
        from sqlalchemy import text, delete
        from app.database.models import VideoFile
        try:
            async with async_session_factory() as session:
                sql = text("""
                    SELECT vf.id, vf.filepath, vf.filename, vf.parsed_code, vf.status,
                           m.title, m.original_title, m.genres, m.actors,
                           m.rating, m.premiered, m.runtime, m.studio, m.director,
                           m.poster_url, m.source_url, vf.updated_at
                    FROM video_files vf LEFT JOIN metadata m ON vf.id = m.video_id
                    ORDER BY vf.updated_at DESC
                """)
                result = await session.execute(sql)
                rows = result.fetchall()

                self._all_files = []
                missing_ids = []

                for row in rows:
                    filepath = row[1] or ""
                    # Verify file exists on disk
                    if filepath and not os.path.exists(filepath):
                        missing_ids.append(row[0])
                        continue  # skip non-existent files

                    genres_raw = row[7]
                    if isinstance(genres_raw, str):
                        try: genres_raw = _json.loads(genres_raw)
                        except: genres_raw = []
                    genres_list = genres_raw if isinstance(genres_raw, list) else []

                    actors_raw = row[8]
                    if isinstance(actors_raw, str):
                        try: actors_raw = _json.loads(actors_raw)
                        except: actors_raw = []
                    actors_list = []
                    if isinstance(actors_raw, list):
                        for a in actors_raw:
                            actors_list.append(a.get("name", "") if isinstance(a, dict) else str(a))

                    self._all_files.append({
                        "id": row[0], "filepath": filepath, "filename": row[2],
                        "code": row[3] or "", "status": row[4],
                        "title": row[5] or "", "original_title": row[6] or "",
                        "genres": genres_list, "actors": actors_list,
                        "rating": row[9], "premiered": row[10], "runtime": row[11],
                        "studio": row[12] or "", "director": row[13] or "",
                        "poster_url": row[14] or "", "source_url": row[15] or "",
                        "updated_at": str(row[16])[:16] if row[16] else "",
                    })

                # Clean up missing file records from DB
                if missing_ids:
                    await session.execute(
                        delete(VideoFile).where(VideoFile.id.in_(missing_ids)))
                    await session.commit()
                    logger.info("Removed %d stale file records", len(missing_ids))

                self._apply_filters()
                self._page = 1
                self._refresh_table()
        except Exception as exc:
            logger.exception("Failed to load files: %s", exc)
            self._page_text.value = f"加载失败: {exc}"
            self.app.page.update()

    def _apply_filters(self):
        """Filter all_files → _filtered based on status and search text."""
        items = self._all_files

        # Get dropdown value: key is English status or "全部"
        status_val = self._status_dd.value if hasattr(self, '_status_dd') else "全部"
        if status_val and status_val != "全部":
            items = [f for f in items if f["status"] == status_val]

        if self._search_text:
            q = self._search_text.lower()
            items = [f for f in items
                     if q in f["filename"].lower() or q in f.get("code", "").lower()]

        self._filtered = items

    def _filtered_display(self) -> list[dict]:
        """Return the current page slice of filtered files."""
        start = (self._page - 1) * self._page_size
        return self._filtered[start:start + self._page_size]

    def _refresh_table(self):
        self._body_list.controls = self._build_rows()
        total_pages = max(1, (len(self._filtered) + self._page_size - 1) // self._page_size)
        self._page_text.value = f"第 {self._page}/{total_pages} 页 · 共 {len(self._filtered)} 个"
        self._update_pagination_buttons(total_pages)
        self._empty_placeholder.visible = (len(self._filtered) == 0)
        has_sel = len(self._selected_ids) > 0
        self._batch_scrape_btn.disabled = not has_sel
        self._batch_scrape_btn.style = ft.ButtonStyle(
            bgcolor=ACCENT if has_sel else "#3a3a4a",
            color="#ffffff" if has_sel else "#7a7a8a",
            shape=ft.RoundedRectangleBorder(radius=6),
        )
        self.app.page.update()

    def _update_batch_btn(self):
        """Refresh batch scrape button state based on current selection."""
        has_sel = len(self._selected_ids) > 0
        self._batch_scrape_btn.disabled = not has_sel
        self._batch_scrape_btn.style = ft.ButtonStyle(
            bgcolor=ACCENT if has_sel else "#3a3a4a",
            color="#ffffff" if has_sel else "#7a7a8a",
            shape=ft.RoundedRectangleBorder(radius=6),
        )
        self._batch_scrape_btn.update()

    def _build_rows(self) -> list[ft.Control]:
        """Build custom table rows with proper alignment and column widths."""
        return [self._build_single_row(f, i) for i, f in enumerate(self._filtered_display())]

    def _build_single_row(self, f: dict, index: int) -> ft.Control:
        """Build a single table row (used for both full rebuild and single-row update)."""
        file_id = f["id"]
        selected = file_id in self._selected_ids
        bg_base = BG_TERTIARY if index % 2 == 0 else BG_PRIMARY
        bg = ft.Colors.with_opacity(0.12, ACCENT) if selected else bg_base

        def _cell(content, align: str, weight: int, w: int) -> ft.Control:
            a = ft.Alignment(-1 if align == "left" else (1 if align == "right" else 0), 0)
            return ft.Container(
                expand=weight if weight > 0 else None,
                width=w if weight == 0 else None,
                alignment=a,
                padding=ft.Padding(left=8, top=0, right=8, bottom=0),
                content=content,
            )

        menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT, icon_size=14,
            items=[
                ft.PopupMenuItem(content=ft.Text("默认播放器播放", size=FONT_XS),
                                on_click=lambda e, fid=file_id: self._play_default(fid)),
                ft.PopupMenuItem(content=ft.Text("打开文件夹", size=FONT_XS),
                                on_click=lambda e, fid=file_id: self._open_folder(fid)),
                ft.PopupMenuItem(content=ft.Text("刮削此文件", size=FONT_XS),
                                on_click=lambda e, fid=file_id: self._scrape_one(fid)),
                ft.PopupMenuItem(content=ft.Text("重新刮削", size=FONT_XS),
                                on_click=lambda e, fid=file_id: self._re_scrape(fid)),
                ft.PopupMenuItem(content=ft.Text("查看详情", size=FONT_XS),
                                on_click=lambda e, fid=file_id: self._show_detail(fid)),
                ft.PopupMenuItem(content=ft.Text("导出 NFO", size=FONT_XS),
                                on_click=lambda e, fid=file_id: self._export_one_nfo(fid)),
            ],
        )

        selected = file_id in self._selected_ids
        cells = [
            _cell(
                ft.Container(
                    width=20, height=20,
                    border_radius=3,
                    bgcolor=ACCENT if selected else None,
                    border=border_all(1.5, ACCENT if selected else BORDER),
                    alignment=ft.Alignment(0, 0),
                    content=ft.Icon(ft.Icons.CHECK, size=14, color="#ffffff")
                            if selected else None,
                ),
                "center", 0, 44),
            _cell(
                ft.Text(f["filename"], size=FONT_XS, color=TEXT_PRIMARY,
                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                       text_align=ft.TextAlign.CENTER,
                       tooltip=ft.Tooltip(message=f["filename"], wait_duration=300)),
                "center", 0, 200),
            _cell(
                ft.Text(f["code"] or "—", size=FONT_XS, color=ACCENT,
                       weight=ft.FontWeight.W_600, text_align=ft.TextAlign.CENTER),
                "center", 0, 85),
            _cell(_status_tag(f["status"]), "center", 0, 80),
            _cell(
                ft.Text(f["title"] or "—", size=FONT_XS, color=TEXT_PRIMARY,
                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                       tooltip=ft.Tooltip(message=f.get("title", "—"), wait_duration=300)),
                "left", 1, 0),
            _cell(
                ft.Text(" / ".join(f["genres"][:3]) or "—", size=FONT_XS,
                       color=TEXT_SECONDARY, max_lines=1,
                       overflow=ft.TextOverflow.ELLIPSIS,
                       text_align=ft.TextAlign.CENTER),
                "center", 0, 130),
            _cell(
                ft.Text(f["updated_at"] or "—", size=FONT_XS, color=TEXT_SECONDARY,
                       text_align=ft.TextAlign.CENTER),
                "center", 0, 130),
            _cell(menu, "right", 0, 48),
        ]

        container = ft.Container(
            bgcolor=bg,
            animate=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
            padding=ft.Padding(left=4, top=6, right=4, bottom=6),
            content=ft.Row(spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                          controls=cells),
        )
        return ft.GestureDetector(
            on_tap=lambda e, fid=file_id: self._toggle_row_selection(fid),
            on_double_tap=lambda e, fid=file_id: self._show_detail(fid),
            on_secondary_tap=lambda e, fid=file_id: self._show_row_context(fid),
            content=container,
        )

    # ==================================================================
    # Pagination
    # ==================================================================

    def _update_pagination_buttons(self, total_pages: int):
        self._first_btn.disabled = (self._page <= 1)
        self._prev_btn.disabled = (self._page <= 1)
        self._next_btn.disabled = (self._page >= total_pages)
        self._last_btn.disabled = (self._page >= total_pages)

    def _go_page(self, page: int):
        total_pages = max(1, (len(self._filtered) + self._page_size - 1) // self._page_size)
        page = max(1, min(page, total_pages))
        self._page = page
        self._refresh_table()

    def _on_page_size_change(self, size: int):
        self._page_size = size
        self._page = 1
        self._refresh_table()

    # ==================================================================
    # Row actions
    # ==================================================================

    def _play_default(self, file_id: int):
        """Play video with default system player."""
        f = next((x for x in self._all_files if x["id"] == file_id), None)
        if f and f.get("filepath") and os.path.exists(f["filepath"]):
            os.startfile(f["filepath"])

    def _show_row_context(self, file_id: int):
        """Show popup menu on right-click of a row."""
        # Find the PopupMenuButton for this row and trigger it
        # Reuse the same menu items
        f = next((x for x in self._all_files if x["id"] == file_id), None)
        if not f: return

        def close():
            self.app.page.pop_dialog()

        items = ft.Column(spacing=2, controls=[
            ft.TextButton(
                content=ft.Text("默认播放器播放", size=FONT_XS, color=TEXT_PRIMARY),
                icon=ft.Icons.PLAY_ARROW,
                on_click=lambda e: (self._play_default(file_id), close()),
            ),
            ft.TextButton(
                content=ft.Text("打开文件夹", size=FONT_XS, color=TEXT_PRIMARY),
                icon=ft.Icons.FOLDER_OPEN,
                on_click=lambda e: (self._open_folder(file_id), close()),
            ),
            ft.TextButton(
                content=ft.Text("刮削此文件", size=FONT_XS, color=TEXT_PRIMARY),
                icon=ft.Icons.DOWNLOADING,
                on_click=lambda e: (self._scrape_one(file_id), close()),
            ),
            ft.TextButton(
                content=ft.Text("重新刮削", size=FONT_XS, color=TEXT_PRIMARY),
                icon=ft.Icons.REPLAY,
                on_click=lambda e: (self._re_scrape(file_id), close()),
            ),
            ft.TextButton(
                content=ft.Text("查看详情", size=FONT_XS, color=TEXT_PRIMARY),
                icon=ft.Icons.INFO,
                on_click=lambda e: (self._show_detail(file_id), close()),
            ),
            ft.TextButton(
                content=ft.Text("导出 NFO", size=FONT_XS, color=TEXT_PRIMARY),
                icon=ft.Icons.DESCRIPTION,
                on_click=lambda e: (self._export_one_nfo(file_id), close()),
            ),
            ft.TextButton(
                content=ft.Text("关闭", size=FONT_XS, color=TEXT_SECONDARY),
                on_click=lambda e: close(),
            ),
        ])

        dlg = ft.AlertDialog(
            title=ft.Text(f.get("filename", ""), size=FONT_SM, color=ACCENT,
                         weight=ft.FontWeight.BOLD),
            content=ft.Container(width=260, content=items),
            bgcolor=BG_SECONDARY,
        )
        self.app.page.show_dialog(dlg)

    def _toggle_row_selection(self, file_id: int):
        """Toggle single row selection on left-click — only rebuilds the clicked row."""
        if file_id in self._selected_ids:
            self._selected_ids.discard(file_id)
        else:
            self._selected_ids.add(file_id)
        self._sync_select_all_cb()
        self._update_batch_btn()
        # Only rebuild the one row that changed — no full page refresh
        display = self._filtered_display()
        for idx, row_data in enumerate(display):
            if row_data["id"] == file_id:
                self._body_list.controls[idx] = self._build_single_row(row_data, idx)
                self.app.page.update()
                return

    def _invert_selection(self):
        """Toggle selection state for all currently displayed rows."""
        display_ids = {f["id"] for f in self._filtered_display()}
        to_add = display_ids - self._selected_ids
        to_remove = self._selected_ids & display_ids
        self._selected_ids -= to_remove
        self._selected_ids |= to_add
        self._sync_select_all_cb()
        self._refresh_table()

    def _do_select_all(self, select: bool):
        """Select or deselect all displayed rows."""
        if select:
            self._selected_ids |= {f["id"] for f in self._filtered_display()}
        else:
            self._selected_ids -= {f["id"] for f in self._filtered_display()}
        self._sync_select_all_cb()
        self._refresh_table()

    def _sync_select_all_cb(self):
        """Sync select-all checkbox state: checked if all displayed rows are selected."""
        display_ids = {f["id"] for f in self._filtered_display()}
        all_selected = display_ids and display_ids <= self._selected_ids
        self._select_all_cb.value = all_selected
        self._select_all_cb.update()

    def _show_detail(self, file_id: int):
        f = next((x for x in self._all_files if x["id"] == file_id), None)
        if not f: return

        def close(e):
            self.app.page.pop_dialog()

        info = [
            ft.Text(f"文件名: {f['filename']}", size=FONT_SM, color=TEXT_PRIMARY),
            ft.Text(f"识别码: {f.get('code') or '—'}", size=FONT_SM, color=ACCENT),
            ft.Text(f"标题: {f.get('title') or '—'}", size=FONT_SM, color=TEXT_PRIMARY),
        ]
        if f.get("original_title"):
            info.append(ft.Text(f"原标题: {f['original_title']}", size=FONT_SM, color=TEXT_SECONDARY))
        if f.get("rating"):
            info.append(ft.Text(f"评分: {f['rating']}", size=FONT_SM, color="#ffd700"))
        if f.get("premiered"):
            info.append(ft.Text(f"发行日期: {f['premiered']}", size=FONT_SM, color=TEXT_SECONDARY))
        if f.get("runtime"):
            info.append(ft.Text(f"时长: {f['runtime']} 分钟", size=FONT_SM, color=TEXT_SECONDARY))
        if f.get("studio"):
            info.append(ft.Text(f"制作商: {f['studio']}", size=FONT_SM, color=TEXT_SECONDARY))
        if f.get("director"):
            info.append(ft.Text(f"导演: {f['director']}", size=FONT_SM, color=TEXT_SECONDARY))
        if f.get("actors"):
            info.append(ft.Text(f"演员: {', '.join(f['actors'][:10])}", size=FONT_SM, color=TEXT_SECONDARY))
        if f.get("genres"):
            info.append(ft.Text(f"分类: {' / '.join(f['genres'][:10])}", size=FONT_SM, color=TEXT_SECONDARY))
        if f.get("source_url"):
            info.append(ft.Text(f"来源: {f['source_url']}", size=FONT_XS, color=TEXT_SECONDARY))

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Text(f"{f.get('code') or f['filename']} — 详情", size=FONT_MD,
                       weight=ft.FontWeight.BOLD, color=ACCENT),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.CLOSE, on_click=close),
            ]),
            content=ft.Container(
                width=500, padding=ft.Padding(left=0, top=8, right=0, bottom=0),
                content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=6, controls=info),
            ),
            actions=[ft.TextButton(content=ft.Text("关闭"), on_click=close)],
            bgcolor=BG_SECONDARY,
        )
        self.app.page.show_dialog(dlg)

    def _scrape_one(self, file_id: int):
        self.app._switch_tab(3)
        self.app.snack(f"请在刮削控制页预览输入: #{file_id}", TEXT_SECONDARY)

    def _re_scrape(self, file_id: int):
        async def _do():
            try:
                from app.scraper.engine import ScrapeEngine
                from app.flet_gui.pages.scraper import _get_registry, _download_poster
                from app.database.repository import MetadataRepository
                from sqlalchemy import select
                from app.database.models import VideoFile

                async with async_session_factory() as session:
                    result = await session.execute(select(VideoFile).where(VideoFile.id == file_id))
                    video = result.scalar_one_or_none()
                    if not video:
                        self.app.snack("文件不存在", DANGER)
                        return
                    self.app.snack(f"正在重新刮削: {video.filename}", WARNING)
                    engine = ScrapeEngine(_get_registry(), session)
                    metadata, scraper = await engine.scrape_single(
                        video.parsed_code or "", video.filename)
                    mrepo = MetadataRepository(session)
                    await mrepo.upsert(video_id=video.id, title=metadata.title,
                        original_title=metadata.original_title, plot=metadata.plot,
                        poster_url=metadata.poster_url, year=metadata.year,
                        premiered=metadata.premiered, runtime=metadata.runtime,
                        genres=metadata.genres, actors=metadata.actors,
                        director=metadata.director, studio=metadata.studio,
                        rating=metadata.rating, source_plugin=scraper.name,
                        source_url=metadata.source_url, raw_data=metadata.raw_data)
                    video.status = "done"
                    try:
                        from app.nfo.generator import NFOGenerator
                        from app.nfo.writer import NFOWriter
                        meta_record = await mrepo.get_by_video_id(video.id)
                        if meta_record:
                            NFOWriter.write(video.filepath, NFOGenerator().generate(meta_record))
                    except: pass
                    if metadata.poster_url:
                        try: await _download_poster(metadata.poster_url, video.id, video.filepath)
                        except: pass
                    await session.commit()
                self.app.snack(f"重新刮削完成: {video.filename}", SUCCESS)
                self.refresh()
            except Exception as exc:
                logger.exception("Re-scrape failed: %s", exc)
                self.app.snack(f"刮削失败: {exc}", DANGER)
        self.app.page.run_task(_do)

    def _export_one_nfo(self, file_id: int):
        async def _do():
            try:
                from app.database.repository import MetadataRepository
                from app.nfo.generator import NFOGenerator
                from app.nfo.writer import NFOWriter
                from sqlalchemy import select
                from app.database.models import VideoFile
                async with async_session_factory() as session:
                    result = await session.execute(select(VideoFile).where(VideoFile.id == file_id))
                    video = result.scalar_one_or_none()
                    if not video:
                        self.app.snack("文件不存在", DANGER)
                        return
                    mrepo = MetadataRepository(session)
                    meta = await mrepo.get_by_video_id(video.id)
                    if meta:
                        NFOWriter.write(video.filepath, NFOGenerator().generate(meta))
                        self.app.snack(f"NFO 已导出: {video.filename}", SUCCESS)
                    else:
                        self.app.snack("无元数据可导出", WARNING)
            except Exception as exc:
                self.app.snack(f"导出失败: {exc}", DANGER)
        self.app.page.run_task(_do)

    def _open_folder(self, file_id: int):
        f = next((x for x in self._all_files if x["id"] == file_id), None)
        if f and f.get("filepath"):
            subprocess.Popen(f'explorer /select,"{f["filepath"]}"')

    # ==================================================================
    # Toolbar actions
    # ==================================================================

    def _scan(self):
        async def _do():
            from app.services.scan_service import ScanService
            from app.config import config
            from app.database.engine import async_session_factory as asf
            from sqlalchemy import text
            try:
                self.app.snack("正在扫描目录...", WARNING)
                # Ensure video directories are loaded from DB
                if not config.video_directories:
                    async with asf() as session:
                        result = await session.execute(text(
                            "SELECT value FROM app_settings WHERE key = 'video_directories'"))
                        row = result.fetchone()
                        if row and row[0]:
                            config.video_directories = [d.strip() for d in row[0].split(";") if d.strip()]
                async with async_session_factory() as session:
                    svc = ScanService(session)
                    result = await svc.scan()
                self.app.snack(f"扫描完成: 新增 {result.get('added', 0)} 个", SUCCESS)
                self.refresh()
            except Exception as exc:
                self.app.snack(f"扫描失败: {exc}", DANGER)
        self.app.page.run_task(_do)

    def _batch_scrape(self):
        if self._selected_ids:
            ids = list(self._selected_ids)
        else:
            ids = [f["id"] for f in self._filtered if f["status"] in ("pending", "failed")]
        if not ids:
            self.app.snack("没有待刮削或失败的文件", WARNING)
            return
        # Pass IDs to scraper page and trigger auto-scrape
        self.app._switch_tab(3)
        if hasattr(self.app, 'scraper') and hasattr(self.app.scraper, 'start_scrape_for_ids'):
            self.app.scraper.start_scrape_for_ids(ids)
        self.app.snack(f"已传递 {len(ids)} 个文件至刮削队列", SUCCESS)

    def _export_nfo(self):
        async def _do():
            try:
                from app.database.repository import MetadataRepository
                from app.nfo.generator import NFOGenerator
                from app.nfo.writer import NFOWriter
                from sqlalchemy import select
                from app.database.models import VideoFile
                async with async_session_factory() as session:
                    done_ids = [f["id"] for f in self._all_files if f["status"] == "done"]
                    if not done_ids:
                        self.app.snack("没有已完成刮削的文件可导出", WARNING)
                        return
                    count = 0
                    for fid in done_ids:
                        result = await session.execute(select(VideoFile).where(VideoFile.id == fid))
                        video = result.scalar_one_or_none()
                        if not video: continue
                        mrepo = MetadataRepository(session)
                        meta = await mrepo.get_by_video_id(video.id)
                        if meta:
                            try:
                                NFOWriter.write(video.filepath, NFOGenerator().generate(meta))
                                count += 1
                            except: pass
                self.app.snack(f"NFO 导出完成: {count} 个文件", SUCCESS)
            except Exception as exc:
                self.app.snack(f"导出失败: {exc}", DANGER)
        self.app.page.run_task(_do)

    # ==================================================================
    # Events
    # ==================================================================

    def _on_filter_change(self):
        self._apply_filters()
        self._page = 1
        self._refresh_table()

    _search_timer = 0

    def _on_search(self):
        import time
        self._search_text = self._search_field.value.strip()
        self._search_timer = time.time()
        async def _deferred():
            await asyncio.sleep(0.3)
            if time.time() - self._search_timer >= 0.29:
                self._apply_filters()
                self._page = 1
                self._refresh_table()
        asyncio.ensure_future(_deferred())

    def _reset_filters(self):
        """Reset all filters, search, and pagination to defaults."""
        self._status_dd.value = "全部"
        self._search_field.value = ""
        self._search_text = ""
        self._status_filter = ""
        self._selected_ids.clear()
        self._select_all_cb.value = False
        self._page = 1
        self._apply_filters()
        self._refresh_table()

    def refresh(self):
        self.app.page.run_task(self._load_files)
