"""Browser page — responsive card grid with real DB data, sort, filter, play, context menu."""
import asyncio
import flet as ft
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from app.database.engine import async_session_factory
from app.genre_mapper import map_genres
from app.flet_gui.theme import (
    BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BORDER,
    TEXT_PRIMARY, TEXT_SECONDARY, ACCENT,
    SUCCESS, WARNING, DANGER,
    CARD_BG,
    FONT_XS, FONT_SM, FONT_MD, FONT_LG,
    PAD_XS, PAD_SM, PAD_MD, PAD_LG,
    CARD_SIZES, DEFAULT_SIZE, DEFAULT_PAGE_SIZE,
    pad_all, pad_only, border_all, radius_only, pad_symmetric,
    FIT_COVER, ALIGN_CENTER,
)

logger = logging.getLogger(__name__)


def _parse_json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def _find_poster(video_path: Path, vid: int) -> str:
    if not video_path or not video_path.parent.exists():
        return ""
    parent = video_path.parent
    stem = video_path.stem

    # Priority 1: metadata/ subdirectory — exact stem match, NOT wildcard glob
    meta_dir = parent / "metadata"
    if meta_dir.exists():
        for ext in [".jpg", ".png", ".webp"]:
            p = meta_dir / f"{stem}-poster{ext}"
            if p.exists():
                return str(p)

    # Priority 2: Kodi-style names in video dir
    for name in [f"{stem}-poster.jpg", "poster.jpg", "folder.jpg"]:
        p = parent / name
        if p.exists():
            return str(p)

    # Priority 3: data/posters/
    data_dir = parent.parent.parent / "data" / "posters"
    if data_dir.exists():
        for ext in [".jpg", ".png", ".webp"]:
            p = data_dir / f"{vid}{ext}"
            if p.exists():
                return str(p)

    return ""


class BrowserPage:
    def __init__(self, app):
        self.app = app
        self._videos: list[dict] = []
        self._size_level = DEFAULT_SIZE
        self._page_size = DEFAULT_PAGE_SIZE
        self._page = 1
        self._total = 0
        self._search_text = ""
        self._sort_key = "recent"
        self._filter_genres: list[str] = []
        self._filter_actors: list[str] = []
        self._all_genres: list[str] = []
        self._all_actors: list[str] = []

    def build(self) -> ft.Control:
        # Sort dropdown
        self._sort_dd = ft.Dropdown(
            value="最近添加",
            options=[
                ft.dropdown.Option("最近添加"),
                ft.dropdown.Option("按标题"),
                ft.dropdown.Option("按演员"),
                ft.dropdown.Option("按类型"),
                ft.dropdown.Option("按日期"),
                ft.dropdown.Option("按评分"),
                ft.dropdown.Option("按时长"),
            ],
            width=120, dense=True, border_color=BORDER, text_size=FONT_SM,
            content_padding=ft.Padding(left=10, top=0, right=6, bottom=0),
            on_select=lambda e: self._on_sort_change(e.control.value),
        )
        # Size dropdown
        self._size_dd = ft.Dropdown(
            value="中等图标",
            options=[
                ft.dropdown.Option("小图标"),
                ft.dropdown.Option("中等图标"),
                ft.dropdown.Option("大图标"),
                ft.dropdown.Option("超大图标"),
            ],
            width=120, dense=True, border_color=BORDER, text_size=FONT_SM,
            content_padding=ft.Padding(left=10, top=0, right=6, bottom=0),
            on_select=lambda e: self._on_size_change(e.control.value),
        )
        # Page size dropdown
        self._page_size_dd = ft.Dropdown(
            value=str(DEFAULT_PAGE_SIZE),
            options=[ft.dropdown.Option(str(s)) for s in [20, 30, 50, 80, 100, 200]],
            width=80, dense=True, border_color=BORDER, text_size=FONT_SM,
            content_padding=ft.Padding(left=10, top=0, right=6, bottom=0),
            on_select=lambda e: self._on_page_size_change(e.control.value),
        )
        self._search_field = ft.TextField(
            hint_text="搜索标题/番号...",
            dense=True, border_color=BORDER, text_size=FONT_SM,
            prefix_icon=ft.Icons.SEARCH_ROUNDED, width=220,
            content_padding=ft.Padding(left=10, top=0, right=10, bottom=0),
            on_submit=lambda e: self._on_search(),
        )
        # Genre filter button
        self._genres_chips = ft.Row(spacing=4, controls=[])
        self._actors_chips = ft.Row(spacing=4, controls=[])
        # Grid area — Column of Rows avoids GridView image rendering bugs
        self._grid = ft.Column(
            expand=True, scroll=ft.ScrollMode.AUTO,
            spacing=PAD_SM, controls=[],
        )
        self._count_text = ft.Text("加载中...", size=FONT_SM, color=TEXT_SECONDARY)
        # Pagination arrow buttons (need refs for enabled/disabled state)
        self._prev_btn = ft.IconButton(
            ft.Icons.CHEVRON_LEFT_ROUNDED, icon_size=20,
            icon_color=TEXT_SECONDARY,
            disabled=True,
            on_click=lambda e: self._prev_page(),
        )
        self._next_btn = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT_ROUNDED, icon_size=20,
            icon_color=TEXT_PRIMARY,
            on_click=lambda e: self._next_page(),
        )
        self._refresh_btn = ft.IconButton(ft.Icons.REFRESH_ROUNDED, icon_size=18,
                                          icon_color=TEXT_SECONDARY,
                                          on_click=lambda e: self.refresh())
        self._last_cols = 0  # for debounced reflow

        # Window resize → card reflow (debounced)
        self.app.page.on_resize = lambda e: self._on_window_resize()

        # Load genre/actor lists + load data
        self.app.page.run_task(self._load_filter_lists)
        self.app.page.run_task(self._load_videos)

        return ft.Container(
            bgcolor=BG_PRIMARY,
            padding=pad_only(left=PAD_LG, right=PAD_LG, top=PAD_SM, bottom=0),
            content=ft.Column(
                spacing=PAD_SM,
                controls=[
                    # Row 1: search + sort + size + page_size
                    ft.Row(spacing=PAD_SM, controls=[
                        self._search_field,
                        self._sort_dd,
                        self._size_dd,
                        ft.Text("每页:", size=FONT_XS, color=TEXT_SECONDARY),
                        self._page_size_dd,
                    ]),
                    # Row 2: genre + actor filter buttons
                    ft.Row(spacing=PAD_SM, controls=[
                        ft.ElevatedButton(
                            content=ft.Text("类型筛选", size=FONT_XS),
                            icon=ft.Icons.FILTER_LIST,
                            style=ft.ButtonStyle(
                                bgcolor=BG_TERTIARY,
                                color=TEXT_PRIMARY,
                            ),
                            on_click=lambda e: self._safe_show_filter("genre"),
                        ),
                        ft.ElevatedButton(
                            content=ft.Text("演员筛选", size=FONT_XS),
                            icon=ft.Icons.PEOPLE,
                            style=ft.ButtonStyle(
                                bgcolor=BG_TERTIARY,
                                color=TEXT_PRIMARY,
                            ),
                            on_click=lambda e: self._safe_show_filter("actor"),
                        ),
                        ft.IconButton(ft.Icons.CLEAR, icon_size=18,
                                      tooltip="重置搜索/筛选/排序",
                                      on_click=lambda e: self._clear_filters()),
                    ]),
                    # Active chips
                    self._genres_chips,
                    self._actors_chips,
                    # Grid
                    self._grid,
                    # Pagination
                    ft.Row(spacing=PAD_SM, alignment=ft.MainAxisAlignment.CENTER, controls=[
                        self._prev_btn,
                        self._count_text,
                        self._next_btn,
                        self._refresh_btn,
                        ft.TextButton(
                            content=ft.Text("加载更多", size=FONT_XS),
                            on_click=lambda e: self._load_more(),
                            icon=ft.Icons.ADD_ROUNDED,
                            style=ft.ButtonStyle(color=TEXT_SECONDARY),
                        ),
                    ]),
                ],
            ),
        )

    # ==================================================================
    # Data loading
    # ==================================================================

    async def _load_filter_lists(self) -> None:
        """Load all available genres and actors from scraped metadata."""
        from sqlalchemy import text
        try:
            async with async_session_factory() as session:
                # Genres — from ALL metadata (match old GUI behavior)
                result = await session.execute(text(
                    "SELECT genres FROM metadata WHERE genres IS NOT NULL AND genres != ''"
                ))
                genre_set = set()
                for row in result.fetchall():
                    genres = _parse_json(row[0], [])
                    if isinstance(genres, list):
                        for g in genres:
                            if isinstance(g, str):
                                genre_set.add(g.strip())
                self._all_genres = sorted(genre_set)

                # Actors — from ALL metadata (match old GUI behavior)
                result = await session.execute(text(
                    "SELECT actors FROM metadata WHERE actors IS NOT NULL AND actors != ''"
                ))
                actor_set = set()
                for row in result.fetchall():
                    actors = _parse_json(row[0], [])
                    if isinstance(actors, list):
                        for a in actors:
                            if isinstance(a, dict) and "name" in a:
                                name = a["name"].strip()
                                if name:
                                    actor_set.add(name)
                            elif isinstance(a, str):
                                actor_set.add(a.strip())
                self._all_actors = sorted(actor_set)
        except Exception as exc:
            logger.warning("Load filter lists failed: %s", exc)

    async def _load_videos(self) -> None:
        from sqlalchemy import text

        query_filter = ""
        params: dict[str, Any] = {}

        if self._search_text:
            query_filter += (
                "AND (m.title LIKE :q OR m.original_title LIKE :q "
                "OR vf.filename LIKE :q OR vf.parsed_code LIKE :q) "
            )
            params["q"] = f"%{self._search_text}%"

        sort_map = {
            "最近添加": "vf.created_at DESC",
            "按标题": "m.title ASC",
            "按演员": "vf.created_at DESC",
            "按类型": "vf.created_at DESC",
            "按日期": "m.premiered DESC",
            "按评分": "m.rating DESC",
            "按时长": "m.runtime DESC",
        }
        order_clause = sort_map.get(self._sort_key, "vf.created_at DESC")

        # When genre/actor filters are active, load ALL matching rows
        # so that client-side filtering works across all pages.
        has_client_filter = bool(self._filter_genres or self._filter_actors)
        page_size = 99999 if has_client_filter else self._page_size
        page_offset = 0 if has_client_filter else (self._page - 1) * self._page_size

        try:
            async with async_session_factory() as session:
                sql = text(f"""
                    SELECT vf.id, vf.filepath, vf.filename, vf.parsed_code,
                           m.title, m.original_title, m.genres, m.actors,
                           m.poster_url, m.year, m.rating, m.premiered, m.runtime,
                           m.studio, m.director
                    FROM video_files vf
                    LEFT JOIN metadata m ON vf.id = m.video_id
                    WHERE vf.status = 'done' {query_filter}
                    ORDER BY {order_clause}
                    LIMIT :limit OFFSET :offset
                """)
                result = await session.execute(sql, {
                    "limit": page_size, "offset": page_offset, **params
                })
                rows = result.fetchall()

                count_sql = text(f"""
                    SELECT COUNT(*) FROM video_files vf
                    LEFT JOIN metadata m ON vf.id = m.video_id
                    WHERE vf.status = 'done' {query_filter}
                """)
                self._total = (await session.execute(count_sql, params)).scalar() or 0

                items = []
                for row in rows:
                    vid, fp = row[0], row[1]
                    poster = _find_poster(Path(fp) if fp else Path("."), vid) if fp else ""
                    genres_raw = _parse_json(row[6], [])
                    actors_raw = _parse_json(row[7], [])

                    items.append({
                        "id": vid, "filename": row[2], "code": row[3] or "",
                        "title": row[4] or row[2], "original_title": row[5],
                        "genres": map_genres(genres_raw),
                        "actors": [a.get("name", "") if isinstance(a, dict) else str(a)
                                  for a in actors_raw],
                        "poster": poster, "poster_url": row[8] or "",
                        "year": row[9], "rating": row[10],
                        "premiered": row[11], "runtime": row[12],
                        "studio": row[13], "director": row[14],
                        "filepath": fp or "",
                    })

                # Client-side filter by genre/actor
                if self._filter_genres:
                    gset = set(self._filter_genres)
                    items = [v for v in items if gset & set(v.get("genres", []))]
                if self._filter_actors:
                    aset = set(self._filter_actors)
                    items = [v for v in items if aset & set(v.get("actors", []))]

                # Post-query sort for actor/genre (name-based)
                if self._sort_key == "按演员":
                    items.sort(key=lambda x: (x.get("actors") or [""])[0].lower())
                elif self._sort_key == "按类型":
                    items.sort(key=lambda x: (x.get("genres") or [""])[0].lower())

                # Paginate locally when filters are active
                if has_client_filter:
                    filtered_total = len(items)
                    start = (self._page - 1) * self._page_size
                    items = items[start:start + self._page_size]
                    display_total = filtered_total
                else:
                    display_total = self._total

                self._videos = items
                self._grid.controls = self._build_cards()
                total_pages = max(1, (display_total + self._page_size - 1) // self._page_size)
                MAX_PAGES = 50
                total_pages = min(total_pages, MAX_PAGES)
                self._count_text.value = f"第 {self._page}/{total_pages} 页 · 总计 {display_total} 个资源"
                self._update_pagination_buttons(total_pages)
                self.app.page.update()

        except Exception as exc:
            logger.exception("Failed to load videos: %s", exc)
            self._grid.controls = [
                ft.Text(f"加载失败: {exc}", color=TEXT_SECONDARY)
            ]
            self._count_text.value = "加载失败"
            self.app.page.update()

    def refresh(self):
        self._page = 1
        self.app.page.run_task(self._load_videos)

    # ==================================================================
    # Card building
    # ==================================================================

    def _card_extent(self) -> int:
        size = CARD_SIZES.get(self._size_level, CARD_SIZES[DEFAULT_SIZE])
        return size[2]  # card width

    def _cards_per_row(self) -> int:
        """Estimate how many cards fit in the available width."""
        cw = self._card_extent() + PAD_SM
        aw = int(self.app.page.window.width) - 60
        return max(1, aw // cw)

    _resize_timer = 0

    def _on_window_resize(self):
        """Debounced reflow — fires 150ms after last resize event."""
        import time
        self._resize_timer = time.time()
        # Check again after 150ms; if no newer resize happened, do reflow
        self._last_cols = self._cards_per_row()
        async def _deferred():
            await asyncio.sleep(0.15)
            if time.time() - self._resize_timer >= 0.14:  # no newer resize
                self._grid.controls = self._build_cards()
                self.app.page.update()
        asyncio.ensure_future(_deferred())

    def _build_cards(self) -> list[ft.Control]:
        if not self._videos:
            return [ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.VIDEO_LIBRARY_ROUNDED, size=48, color=TEXT_SECONDARY),
                    ft.Text("暂无已刮削的视频", size=FONT_MD, color=TEXT_SECONDARY),
                    ft.ElevatedButton(
                        content=ft.Text("前往刮削控制", size=FONT_SM),
                        icon=ft.Icons.NAVIGATE_NEXT_ROUNDED,
                        style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff"),
                        on_click=lambda e: self.app._switch_tab(3),
                    ),
                ], spacing=PAD_MD,
                   alignment=ft.MainAxisAlignment.CENTER,
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ALIGN_CENTER,
            )]
        pw, ph, cw = CARD_SIZES.get(self._size_level, CARD_SIZES[DEFAULT_SIZE])
        cards = [self._make_card(v, pw, ph, cw) for v in self._videos]
        # Arrange into rows
        per_row = self._cards_per_row()
        rows = []
        for i in range(0, len(cards), per_row):
            row_items = cards[i:i+per_row]
            rows.append(ft.Row(spacing=PAD_SM, controls=row_items))
        return rows

    def _make_card(self, video: dict, pw: int, ph: int, cw: int) -> ft.Control:
        code = video.get("code", "") or video.get("filename", "")[:20]
        title = video.get("title", "") or "未知"
        original = video.get("original_title", "")
        genres = video.get("genres", [])
        actors = video.get("actors", [])
        poster_path = video.get("poster", "")
        rating = video.get("rating")
        year = video.get("year")
        runtime = video.get("runtime")
        filepath = video.get("filepath", "")

        # ── Poster area ──
        has_poster = poster_path and Path(poster_path).exists()
        if has_poster:
            poster = ft.Container(
                height=ph,
                image=ft.DecorationImage(
                    src=poster_path.replace('\\', '/'), fit="COVER",
                ),
                border_radius=radius_only(top_left=4, top_right=4),
            )
        else:
            poster = ft.Container(
                height=ph, bgcolor=BG_TERTIARY,
                border_radius=radius_only(top_left=4, top_right=4),
                content=ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_ROUNDED,
                               size=32, color=TEXT_SECONDARY),
                alignment=ALIGN_CENTER,
            )

        # Rating badge on poster (top-right)
        # Year + Runtime capsules on poster (bottom-left)
        poster_controls = [poster]
        if rating:
            poster_controls.append(ft.Container(
                content=ft.Text(f"★{rating:.1f}", size=9, color="#ffd700",
                               weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.with_opacity(0.75, "#000000"),
                border_radius=4,
                padding=ft.Padding(left=5, top=2, right=5, bottom=2),
                right=4, top=4,
            ))
        if year or runtime:
            year_runtime_items = []
            if year:
                year_runtime_items.append(ft.Container(
                    content=ft.Text(str(year), size=8, color="#e8e8f0",
                                   weight=ft.FontWeight.W_600),
                    bgcolor=ft.Colors.with_opacity(0.75, "#000000"),
                    border_radius=3,
                    padding=ft.Padding(left=5, top=1, right=5, bottom=1),
                ))
            if runtime:
                year_runtime_items.append(ft.Container(
                    content=ft.Text(f"{runtime}min", size=8, color="#e8e8f0",
                                   weight=ft.FontWeight.W_600),
                    bgcolor=ft.Colors.with_opacity(0.75, "#000000"),
                    border_radius=3,
                    padding=ft.Padding(left=5, top=1, right=5, bottom=1),
                ))
            poster_controls.append(ft.Container(
                content=ft.Row(spacing=3, controls=year_runtime_items),
                left=4, bottom=4,
            ))

        poster_stack = ft.Stack(height=ph, controls=poster_controls)

        # ── Info area: frosted-glass bottom panel ──
        # Row 1: code/number
        code_widget = ft.Text(
            code, size=9, color=ACCENT, weight=ft.FontWeight.W_600,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=ft.Tooltip(message=code, wait_duration=400),
        ) if code else ft.Text("")

        # Row 2: Title (bold, white, single-line)
        title_text = ft.Text(
            title, size=FONT_SM, color="#ffffff",
            weight=ft.FontWeight.BOLD,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=ft.Tooltip(message=title, wait_duration=400),
        )

        # Row 3: Actors (pink, single line, not mixed with code/genre)
        actor_text = " · ".join(actors[:3]) if actors else "—"
        actor_widget = ft.Text(
            actor_text, size=9, color="#f472b6",
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=ft.Tooltip(message=actor_text, wait_duration=400),
        )

        # Row 4: Genre color chips (left) + Play button (right)
        genre_chips = []
        for g in genres[:3]:
            genre_chips.append(ft.Container(
                content=ft.Text(g, size=8, color=ACCENT),
                bgcolor=ft.Colors.with_opacity(0.12, ACCENT),
                border_radius=4,
                padding=ft.Padding(left=6, top=1, right=6, bottom=1),
            ))

        play_btn = ft.Container(
            content=ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, size=18, color="#ffffff"),
            bgcolor=ACCENT,
            border_radius=20,
            width=32, height=32,
            alignment=ALIGN_CENTER,
            on_click=lambda e, fp=filepath: self._play(fp),
            tooltip="播放",
        )

        # ── Build info panel ──
        info_content = ft.Column(
            spacing=4,
            controls=[
                code_widget,
                title_text,
                actor_widget,
                ft.Row(
                    spacing=4,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(spacing=3, controls=genre_chips) if genre_chips else ft.Text(""),
                        play_btn,
                    ],
                ),
            ],
        )

        info_panel = ft.Container(
            content=info_content,
            padding=ft.Padding(left=8, top=6, right=8, bottom=6),
            border_radius=radius_only(bottom_left=4, bottom_right=4),
            gradient=ft.LinearGradient(
                begin=ft.Alignment(0, -1),
                end=ft.Alignment(0, 1),
                colors=["#1a1a28", "#14141e"],
            ),
        )

        # ── Card assembly ──
        _preview = lambda e, v=video: self._safe_preview(v)
        _ctx_menu = lambda e, v=video: self._show_context_menu(v)

        # Hover state tracking
        hover_container = ft.Container(
            width=cw, bgcolor=CARD_BG,
            border_radius=4, border=border_all(1, BORDER),
            padding=ft.Padding(left=0, top=0, right=0, bottom=0),
            on_click=_preview,
            animate_opacity=ft.Animation(150, "ease"),
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Container(
                        content=poster_stack,
                        border_radius=radius_only(top_left=4, top_right=4),
                        on_click=_preview,
                    ),
                    info_panel,
                ],
            ),
        )

        return ft.GestureDetector(
            width=cw,
            mouse_cursor=ft.MouseCursor.CLICK,
            on_secondary_tap=_ctx_menu,
            on_enter=lambda e: self._on_card_enter(hover_container),
            on_exit=lambda e: self._on_card_exit(hover_container),
            content=hover_container,
        )

    def _on_card_enter(self, container: ft.Container):
        container.border = border_all(1, ACCENT)
        container.opacity = 0.95
        self.app.page.update()

    def _on_card_exit(self, container: ft.Container):
        container.border = border_all(1, BORDER)
        container.opacity = 1.0
        self.app.page.update()

    # ==================================================================
    # Preview
    # ==================================================================

    def _safe_preview(self, video: dict):
        logger.info("Card clicked: %s", video.get("code", "?"))
        try:
            self._show_preview(video)
        except Exception as exc:
            logger.exception("Preview failed: %s", exc)
            self.app.snack(f"预览失败: {exc}", "danger")

    def _show_preview(self, video: dict) -> None:
        code = video.get("code", "")
        title = video.get("title", "")
        poster_path = video.get("poster", "")
        rating = video.get("rating")
        genres = video.get("genres", [])
        actors = video.get("actors", [])
        studio = video.get("studio", "")
        director = video.get("director", "")
        premiered = video.get("premiered", "")
        runtime = video.get("runtime")
        filepath = video.get("filepath", "")
        filename = video.get("filename", "")
        original_title = video.get("original_title", "")

        DIALOG_W = 980
        POSTER_H = 600   # fits 800x500 image at 1.2x (960x600) with CONTAIN

        def close(e=None):
            self.app.page.pop_dialog()

        # ── Poster image: CONTAIN preserves aspect ratio, no stretching ──
        if poster_path and Path(poster_path).exists():
            poster_img = ft.DecorationImage(
                src=poster_path.replace('\\', '/'), fit="CONTAIN",
            )
        else:
            poster_img = None

        # Gradient fade at bottom of poster
        poster_gradient = ft.Container(
            gradient=ft.LinearGradient(
                begin=ft.Alignment(0, 0.75),
                end=ft.Alignment(0, 1),
                colors=["#00000000", "#0c0c16f0"],
            ),
            height=POSTER_H,
        )

        # Floating play button
        play_size = 64
        floating_play = ft.Container(
            content=ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, size=44, color="#ffffff"),
            bgcolor=ft.Colors.with_opacity(0.5, ACCENT),
            border_radius=play_size // 2,
            width=play_size, height=play_size,
            alignment=ALIGN_CENTER,
            left=(DIALOG_W - 36 - play_size) // 2,
            top=(POSTER_H - play_size) // 2,
            on_click=lambda e, fp=filepath: self._play(fp),
            tooltip="播放",
        )

        # Year / runtime / rating tags
        tag_items = []
        if video.get("year"):
            tag_items.append(ft.Container(
                content=ft.Text(str(video["year"]), size=11, color="#ffffff", weight=ft.FontWeight.W_600),
                bgcolor=ft.Colors.with_opacity(0.5, "#000000"),
                border_radius=4, padding=ft.Padding(left=10, top=2, right=10, bottom=2),
            ))
        if runtime:
            tag_items.append(ft.Container(
                content=ft.Text(f"{runtime}min", size=11, color="#ffffff", weight=ft.FontWeight.W_600),
                bgcolor=ft.Colors.with_opacity(0.5, "#000000"),
                border_radius=4, padding=ft.Padding(left=10, top=2, right=10, bottom=2),
            ))
        if rating:
            tag_items.append(ft.Container(
                content=ft.Text(f"★{rating:.1f}", size=11, color="#ffd700", weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.with_opacity(0.5, "#000000"),
                border_radius=4, padding=ft.Padding(left=10, top=2, right=10, bottom=2),
            ))

        # Poster Stack
        poster_stack_controls = []
        if poster_img:
            poster_stack_controls.append(ft.Container(
                image=poster_img, height=POSTER_H,
                bgcolor="#0c0c16",
                alignment=ALIGN_CENTER,
                border_radius=radius_only(top_left=16, top_right=16),
            ))
        else:
            poster_stack_controls.append(ft.Container(
                height=POSTER_H, bgcolor=BG_TERTIARY,
                border_radius=radius_only(top_left=16, top_right=16),
                content=ft.Icon(ft.Icons.IMAGE, size=64, color=TEXT_SECONDARY),
                alignment=ALIGN_CENTER,
            ))
        poster_stack_controls.append(poster_gradient)
        poster_stack_controls.append(floating_play)
        if tag_items:
            poster_stack_controls.append(ft.Container(
                content=ft.Row(spacing=6, controls=tag_items),
                left=20, bottom=20,
            ))

        poster_section = ft.Stack(
            height=POSTER_H,
            controls=poster_stack_controls,
        )

        # ── Info area ──
        info = []

        # Close button
        info.append(ft.Row([
            ft.Container(expand=True),
            ft.IconButton(ft.Icons.CLOSE, icon_size=20, icon_color=TEXT_SECONDARY,
                         on_click=close, tooltip="关闭"),
        ]))

        # Title
        info.append(ft.Text(title or "未知标题", size=20, weight=ft.FontWeight.BOLD,
                            color=TEXT_PRIMARY, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
        if original_title and original_title != title:
            info.append(ft.Text(original_title, size=13, color=TEXT_SECONDARY,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))

        # Info bar
        bits = [code] if code else [filename[:20]]
        if studio: bits.append(studio)
        if director: bits.append(director)
        if premiered: bits.append(premiered)
        info.append(ft.Text(" · ".join(bits), size=12, color=TEXT_SECONDARY,
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
        info.append(ft.Divider(height=1, color=ft.Colors.with_opacity(0.12, ACCENT)))

        # Genres
        if genres:
            info.append(ft.Text("类型", size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600))
            info.append(ft.Row(wrap=True, spacing=4, run_spacing=4, controls=[
                ft.Container(
                    content=ft.Text(g, size=11, color=ACCENT),
                    bgcolor=ft.Colors.with_opacity(0.12, ACCENT),
                    border_radius=4, padding=ft.Padding(left=10, top=3, right=10, bottom=3),
                ) for g in genres[:12]
            ]))

        # Actors
        if actors:
            info.append(ft.Text("主演", size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600))
            info.append(ft.Row(wrap=True, spacing=4, run_spacing=4, controls=[
                ft.Container(
                    content=ft.Text(a, size=11, color="#f472b6"),
                    bgcolor=ft.Colors.with_opacity(0.08, "#f472b6"),
                    border_radius=16, padding=ft.Padding(left=12, top=4, right=12, bottom=4),
                ) for a in actors[:14]
            ]))

        # Plot summary
        info.append(ft.Text("简介", size=12, color=TEXT_SECONDARY, weight=ft.FontWeight.W_600))
        info.append(ft.Text(
            f"番号 {code}，共 {len(actors)} 位演员，{len(genres)} 种类型。" if code else "暂无更多信息",
            size=11, color=TEXT_SECONDARY, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS))

        # Collapsible file info
        info.append(ft.Divider(height=1, color=ft.Colors.with_opacity(0.08, ACCENT)))

        ftoggle = ft.Icon(ft.Icons.EXPAND_MORE, size=16, color=TEXT_SECONDARY)
        def _toggle(e):
            fpanel.visible = not fpanel.visible
            ftoggle.name = ft.Icons.EXPAND_LESS if fpanel.visible else ft.Icons.EXPAND_MORE
            self.app.page.update()

        info.append(ft.Container(
            content=ft.Row([ft.Text("文件信息", size=12, color=TEXT_SECONDARY,
                                    weight=ft.FontWeight.W_600), ftoggle], spacing=4),
            on_click=_toggle, padding=ft.Padding(left=0, top=4, right=0, bottom=4),
        ))

        fpanel = ft.Column(visible=True, spacing=2, controls=[
            ft.Text(f"文件名: {filename}", size=10, color=TEXT_SECONDARY),
            ft.Text(f"路径: {filepath}", size=10, color=TEXT_SECONDARY,
                   max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ])
        info.append(fpanel)

        # Action buttons
        info.append(ft.Container(height=4))
        info.append(ft.Row(spacing=8, controls=[
            ft.ElevatedButton(
                content=ft.Text("播放"), icon=ft.Icons.PLAY_ARROW_ROUNDED,
                style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff",
                                    padding=pad_symmetric(24, 10)),
                on_click=lambda e, fp=filepath: self._play(fp),
            ),
            ft.OutlinedButton(
                content=ft.Text("选择播放器"), icon=ft.Icons.VIDEO_FILE,
                style=ft.ButtonStyle(side=ft.BorderSide(1, BORDER), color=TEXT_PRIMARY),
                on_click=lambda e, fp=filepath: self._play_with_chooser(fp),
            ),
            ft.OutlinedButton(
                content=ft.Text("打开文件夹"), icon=ft.Icons.FOLDER_OPEN,
                style=ft.ButtonStyle(side=ft.BorderSide(1, BORDER), color=TEXT_PRIMARY),
                on_click=lambda e, fp=filepath: self._open_folder(fp),
            ),
        ]))

        # ── Assemble ──
        dlg = ft.AlertDialog(
            content=ft.Container(
                width=DIALOG_W,
                bgcolor="#12121a",
                border_radius=16,
                padding=ft.Padding(left=0, top=0, right=0, bottom=0),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Column(spacing=0, controls=[
                    poster_section,
                    ft.Container(
                        padding=ft.Padding(left=28, top=16, right=28, bottom=20),
                        content=ft.Column(scroll=ft.ScrollMode.AUTO, spacing=14,
                                         controls=info),
                        expand=True,
                    ),
                ]),
            ),
            bgcolor="#00000000",
            inset_padding=ft.Padding(left=16, top=20, right=16, bottom=20),
            open=True,
        )
        self.app.page.show_dialog(dlg)
    # ==================================================================
    # Play actions
    # ==================================================================

    def _play(self, filepath: str):
        if filepath and os.path.exists(filepath):
            os.startfile(filepath)

    def _play_with_chooser(self, filepath: str):
        """Let user pick a media player executable, then play the video."""
        self._choose_player(filepath)

    def _open_folder(self, filepath: str):
        """Open the containing folder and highlight/select the target file."""
        if filepath and os.path.exists(filepath):
            # explorer /select,"path" opens the folder with the file selected
            subprocess.Popen(f'explorer /select,"{filepath}"')

    def _regen_nfo(self, filepath: str, code: str):
        """Regenerate NFO file for a video."""
        async def _do():
            try:
                from app.database.engine import async_session_factory
                from app.database.repository import MetadataRepository, VideoFileRepository
                from app.nfo.generator import NFOGenerator
                from app.nfo.writer import NFOWriter
                async with async_session_factory() as session:
                    vrepo = VideoFileRepository(session)
                    mrepo = MetadataRepository(session)
                    all_videos, _ = await vrepo.list_paginated(page=1, size=9999, status="done")
                    for vf in all_videos:
                        if vf.filepath == filepath:
                            meta = await mrepo.get_by_video_id(vf.id)
                            if meta:
                                NFOWriter.write(filepath, NFOGenerator().generate(meta))
                                self.app.snack(f"NFO 已重新生成: {vf.filename}", SUCCESS)
                                return
                self.app.snack("未找到对应元数据", WARNING)
            except Exception as exc:
                self.app.snack(f"NFO 生成失败: {exc}", DANGER)
        self.app.page.run_task(_do)

    # ==================================================================
    # Context menu (right-click)
    # ==================================================================

    def _show_context_menu(self, video: dict):
        """Show right-click context menu for a card."""
        code = video.get("code", "")
        title = video.get("title", "")
        filepath = video.get("filepath", "")

        def close_menu():
            self.app.page.pop_dialog()

        menu_items = [
            ft.Column(spacing=2, controls=[
                ft.TextButton(
                    content=ft.Text(f"📋 复制番号: {code}", size=FONT_XS, color=TEXT_PRIMARY),
                    on_click=lambda e, t=code: self._copy_text(t) or close_menu(),
                ),
                ft.TextButton(
                    content=ft.Text(f"📋 复制标题: {title}", size=FONT_XS, color=TEXT_PRIMARY),
                    on_click=lambda e, t=title: self._copy_text(t) or close_menu(),
                ),
                ft.TextButton(
                    content=ft.Text(f"▶ 播放", size=FONT_XS, color=TEXT_PRIMARY),
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=lambda e, fp=filepath: (
                        self._play(fp), close_menu()
                    ),
                ),
                ft.TextButton(
                    content=ft.Text("🎬 选择播放器播放", size=FONT_XS, color=TEXT_PRIMARY),
                    icon=ft.Icons.VIDEO_FILE,
                    on_click=lambda e, fp=filepath: (
                        self._choose_player(fp), close_menu()
                    ),
                ),
                ft.TextButton(
                    content=ft.Text("📁 打开文件夹", size=FONT_XS, color=TEXT_PRIMARY),
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda e, fp=filepath: (
                        self._open_folder(fp), close_menu()
                    ),
                ),
                ft.TextButton(
                    content=ft.Text("📝 重新生成 NFO", size=FONT_XS, color=TEXT_PRIMARY),
                    icon=ft.Icons.DESCRIPTION,
                    on_click=lambda e, fp=filepath, c=code: (
                        self._regen_nfo(fp, c), close_menu()
                    ),
                ),
                ft.TextButton(
                    content=ft.Text("关闭", size=FONT_XS, color=TEXT_SECONDARY),
                    on_click=lambda e: close_menu(),
                ),
            ]),
        ]

        dlg = ft.AlertDialog(
            title=ft.Text(code or title, size=FONT_SM, color=ACCENT,
                         weight=ft.FontWeight.BOLD),
            content=ft.Container(
                width=280,
                content=menu_items[0],
            ),
            bgcolor=BG_SECONDARY,
        )
        self.app.page.show_dialog(dlg)

    def _copy_text(self, text: str):
        """Copy text to clipboard."""
        self.app.page.set_clipboard(text)
        self.app.snack(f"已复制到剪贴板", SUCCESS)

    def _choose_player(self, filepath: str):
        """Show player selection dialog with auto-discovered Windows players."""
        if not filepath or not os.path.exists(filepath):
            self.app.snack("文件不存在", DANGER)
            return

        discovered = self._scan_media_players()

        def _play_with(p):
            self.app.page.pop_dialog()
            if p and os.path.exists(p):
                subprocess.Popen([p, filepath])
            else:
                self.app.snack("播放器路径无效，使用默认播放器", WARNING)
                os.startfile(filepath)

        player_rows = []
        for name, path in discovered:
            player_rows.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PLAY_CIRCLE_FILLED, size=20, color=ACCENT),
                        ft.Column([
                            ft.Text(name, size=FONT_SM, color=TEXT_PRIMARY,
                                   weight=ft.FontWeight.W_500),
                            ft.Text(path, size=9, color=TEXT_SECONDARY,
                                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=0),
                        ft.Container(expand=True),
                        ft.Icon(ft.Icons.CHEVRON_RIGHT, size=16, color=TEXT_SECONDARY),
                    ], spacing=10),
                    padding=ft.Padding(left=12, top=8, right=12, bottom=8),
                    border_radius=8,
                    bgcolor=BG_TERTIARY,
                    on_click=lambda e, p=path: _play_with(p),
                )
            )

        manual_field = ft.TextField(
            hint_text="或手动输入 exe 路径...",
            dense=True, border_color=BORDER, text_size=FONT_SM,
            prefix_icon=ft.Icons.EDIT,
            expand=True,
        )

        def _browse_file(e):
            """Open system file picker to select exe, auto-fill path."""
            async def _pick():
                picker = ft.FilePicker()
                result = await picker.pick_files(
                    dialog_title="选择播放器程序（.exe）",
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["exe"],
                    allow_multiple=False,
                )
                if result and result.files:
                    manual_field.value = result.files[0].path
                    self.app.page.update()
            self.app.page.run_task(_pick)

        def _manual_play(e):
            p = manual_field.value.strip()
            if p:
                _play_with(p)

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.VIDEO_FILE, color=ACCENT, size=24),
                ft.Text("选择播放器", size=FONT_MD, weight=ft.FontWeight.BOLD,
                       color=TEXT_PRIMARY),
            ]),
            content=ft.Container(
                width=520,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    spacing=8,
                    controls=[
                        ft.Text(f"发现 {len(discovered)} 个可用播放器", size=FONT_XS,
                               color=TEXT_SECONDARY),
                        *player_rows,
                        ft.Divider(height=1, color=ft.Colors.with_opacity(0.12, ACCENT)),
                        ft.Text("手动指定", size=FONT_XS, color=TEXT_SECONDARY,
                               weight=ft.FontWeight.W_600),
                        ft.Row([
                            manual_field,
                            ft.OutlinedButton(
                                content=ft.Text("浏览文件"),
                                icon=ft.Icons.FOLDER_OPEN,
                                style=ft.ButtonStyle(
                                    side=ft.BorderSide(1, BORDER),
                                    color=TEXT_PRIMARY,
                                ),
                                on_click=_browse_file,
                            ),
                        ], spacing=8),
                        ft.ElevatedButton(
                            content=ft.Text("使用此路径播放"),
                            icon=ft.Icons.CHECK,
                            style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff"),
                            on_click=_manual_play,
                        ),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("取消"),
                    on_click=lambda e: self.app.page.pop_dialog(),
                ),
            ],
            bgcolor=BG_SECONDARY,
        )
        self.app.page.show_dialog(dlg)

    @staticmethod
    def _scan_media_players():
        """Scan Windows common install paths for media players."""
        candidates = [
            ("VLC Media Player", [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
            ]),
            ("PotPlayer", [
                r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
                r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
            ]),
            ("MPC-HC", [
                r"C:\Program Files\MPC-HC\mpc-hc64.exe",
                r"C:\Program Files (x86)\MPC-HC\mpc-hc.exe",
            ]),
            ("MPC-BE", [
                r"C:\Program Files\MPC-BE x64\mpc-be64.exe",
            ]),
            ("KMPlayer", [
                r"C:\Program Files (x86)\KMPlayer\KMPlayer.exe",
                r"C:\KMPlayer\KMPlayer.exe",
            ]),
            ("SMPlayer", [
                r"C:\Program Files\SMPlayer\smplayer.exe",
            ]),
            ("GOM Player", [
                r"C:\Program Files\GRETECH\GOMPlayer\GOM.exe",
                r"C:\Program Files (x86)\GRETECH\GOMPlayer\GOM.exe",
            ]),
            ("Windows Media Player", [
                r"C:\Program Files\Windows Media Player\wmplayer.exe",
                r"C:\Program Files (x86)\Windows Media Player\wmplayer.exe",
            ]),
            ("QQ影音", [
                r"C:\Program Files\Tencent\QQPlayer\QQPlayer.exe",
                r"C:\Program Files (x86)\Tencent\QQPlayer\QQPlayer.exe",
            ]),
            ("暴风影音", [
                r"C:\Program Files\Baofeng\StormPlayer\StormPlayer.exe",
                r"C:\Program Files (x86)\Baofeng\StormPlayer\StormPlayer.exe",
            ]),
        ]
        found = []
        for name, paths in candidates:
            for p in paths:
                if os.path.exists(p):
                    found.append((name, p))
                    break
        return found

    # ==================================================================
    # Filter popups
    # ==================================================================

    def _safe_show_filter(self, ftype: str):
        """Wrapper with error handling for filter popup."""
        print(f"[DEBUG] _safe_show_filter called: ftype={ftype}", flush=True)
        logger.info("_safe_show_filter called: ftype=%s", ftype)
        try:
            self._show_filter_popup(ftype)
        except Exception as exc:
            logger.exception("Filter popup failed: %s", exc)
            self.app.snack(f"筛选失败: {exc}", DANGER)

    def _show_filter_loading_popup(self, ftype: str, label: str):
        """Show a minimal loading dialog while filter data loads."""
        def close(e):
            self.app.page.pop_dialog()

        dlg = ft.AlertDialog(
            title=ft.Text(f"{label}筛选", size=FONT_MD, weight=ft.FontWeight.BOLD,
                         color=TEXT_PRIMARY),
            content=ft.Column([
                ft.ProgressBar(color=ACCENT, bgcolor=BG_TERTIARY),
                ft.Container(height=8),
                ft.Text("正在加载筛选数据...", size=FONT_SM, color=TEXT_SECONDARY),
            ], width=250, spacing=4),
            actions=[
                ft.TextButton(content=ft.Text("取消"), on_click=close),
            ],
            bgcolor=BG_SECONDARY,
        )
        self.app.page.show_dialog(dlg)

    def _show_filter_popup(self, ftype: str):
        """Show checkbox filter popup for genre or actor.
        Always opens dialog — loads data async if not yet available."""
        items = self._all_genres if ftype == "genre" else self._all_actors
        label = "类型" if ftype == "genre" else "演员"

        if not items:
            # Data not loaded yet — show loading dialog, load async, then refresh
            self._show_filter_loading_popup(ftype, label)
            async def _load_then_show():
                await self._load_filter_lists()
                # Now data is ready — close loading dialog and show real popup
                self.app.page.pop_dialog()
                self._show_filter_popup(ftype)
            self.app.page.run_task(_load_then_show)
            return

        current = self._filter_genres if ftype == "genre" else self._filter_actors
        selected = set(current)
        search_field = ft.TextField(
            hint_text="搜索...", dense=True, border_color=BORDER,
            text_size=FONT_SM, width=200,
        )
        checkbox_list = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, height=400,
                                   controls=[])

        def _rebuild():
            q = search_field.value.strip().lower()
            filtered = [x for x in items if q in x.lower()] if q else items
            checkbox_list.controls.clear()
            for name in filtered:
                cb = ft.Checkbox(
                    label=name, value=name in selected,
                    label_style=ft.TextStyle(size=FONT_XS, color=TEXT_PRIMARY),
                    on_change=lambda e, n=name: (
                        selected.add(n) if e.control.value else selected.discard(n)
                    ),
                )
                checkbox_list.controls.append(cb)
            self.app.page.update()

        search_field.on_change = lambda e: _rebuild()
        _rebuild()

        def _apply(e):
            if ftype == "genre":
                self._filter_genres = list(selected)
                self._rebuild_chips("genre")
            else:
                self._filter_actors = list(selected)
                self._rebuild_chips("actor")
            self.app.page.pop_dialog()
            self._page = 1
            self.app.page.run_task(self._load_videos)

        dlg = ft.AlertDialog(
            title=ft.Text(f"{'类型' if ftype == 'genre' else '演员'}筛选", size=FONT_MD,
                         weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
            content=ft.Column([
                search_field,
                ft.Container(height=8),
                ft.Row([
                    ft.TextButton(content=ft.Text("全选"), on_click=lambda e: [
                        selected.add(n) for n in items[:200]
                    ]),
                    ft.TextButton(content=ft.Text("取消全选"), on_click=lambda e: selected.clear()),
                ]),
                checkbox_list,
            ], width=300, spacing=4),
            actions=[
                ft.ElevatedButton(
                    content=ft.Text("应用"), on_click=_apply,
                    style=ft.ButtonStyle(bgcolor=ACCENT, color="#ffffff"),
                ),
                ft.TextButton(content=ft.Text("取消"), on_click=lambda e: self.app.page.pop_dialog()),
            ],
            bgcolor=BG_SECONDARY,
        )
        self.app.page.show_dialog(dlg)

    def _rebuild_chips(self, ftype: str):
        items = self._filter_genres if ftype == "genre" else self._filter_actors
        chips = []
        for name in items[:10]:
            chips.append(ft.Chip(
                label=ft.Text(name, size=10),
                delete_icon=ft.Icons.CLOSE,
                bgcolor=ft.Colors.with_opacity(0.2, ACCENT),
                on_delete=lambda e, n=name: self._remove_filter(ftype, n),
            ))
        if ftype == "genre":
            self._genres_chips.controls = chips
        else:
            self._actors_chips.controls = chips
        self.app.page.update()

    def _remove_filter(self, ftype: str, name: str):
        if ftype == "genre":
            self._filter_genres = [g for g in self._filter_genres if g != name]
            self._rebuild_chips("genre")
        else:
            self._filter_actors = [a for a in self._filter_actors if a != name]
            self._rebuild_chips("actor")
        self._page = 1
        self.app.page.run_task(self._load_videos)

    def _clear_filters(self):
        """Reset all filters, search, sort, and pagination to defaults."""
        self._filter_genres.clear()
        self._filter_actors.clear()
        self._genres_chips.controls.clear()
        self._actors_chips.controls.clear()
        self._search_text = ""
        self._search_field.value = ""
        self._sort_key = "最近添加"
        self._sort_dd.value = "最近添加"
        self._page = 1
        self._page_size = DEFAULT_PAGE_SIZE
        self._page_size_dd.value = str(DEFAULT_PAGE_SIZE)
        self.app.page.run_task(self._load_videos)

    # ==================================================================
    # Events
    # ==================================================================

    def _on_size_change(self, label: str) -> None:
        size_map = {"小图标": "small", "中等图标": "medium",
                     "大图标": "large", "超大图标": "xlarge"}
        self._size_level = size_map.get(label, DEFAULT_SIZE)
        self._grid.controls = self._build_cards()
        self.app.page.update()

    def _on_sort_change(self, label: str):
        self._sort_key = label
        self._page = 1
        self.app.page.run_task(self._load_videos)

    def _on_page_size_change(self, value: str):
        self._page_size = int(value)
        self._page = 1
        self.app.page.run_task(self._load_videos)

    _search_timer = 0

    def _on_search(self) -> None:
        """Debounced search — fires 300ms after last keypress."""
        import time
        self._search_text = self._search_field.value.strip()
        self._search_timer = time.time()
        async def _deferred():
            await asyncio.sleep(0.3)
            if time.time() - self._search_timer >= 0.29:
                self._page = 1
                self.app.page.run_task(self._load_videos)
        asyncio.ensure_future(_deferred())

    def _prev_page(self) -> None:
        if self._page > 1:
            self._page -= 1
            self.app.page.run_task(self._load_videos)

    def _next_page(self) -> None:
        MAX_PAGES = 50
        total_pages = max(1, (self._total + self._page_size - 1) // self._page_size)
        if self._page < min(total_pages, MAX_PAGES):
            self._page += 1
            self.app.page.run_task(self._load_videos)

    def _load_more(self) -> None:
        """Incremental load: increase page_size and reload."""
        self._page_size += DEFAULT_PAGE_SIZE
        self._page = 1
        self.app.page.run_task(self._load_videos)

    def _update_pagination_buttons(self, total_pages: int) -> None:
        """Enable/disable prev/next arrows based on current page."""
        self._prev_btn.disabled = (self._page <= 1)
        self._next_btn.disabled = (self._page >= total_pages)
        self._prev_btn.icon_color = TEXT_SECONDARY if self._prev_btn.disabled else TEXT_PRIMARY
        self._next_btn.icon_color = TEXT_SECONDARY if self._next_btn.disabled else TEXT_PRIMARY
