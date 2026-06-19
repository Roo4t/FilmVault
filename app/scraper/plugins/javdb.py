"""
JavDB 刮削插件
从 https://javdb.com 抓取影片元数据

使用 BeautifulSoup + 两步流程（搜索 → 详情页），
搜索结果按编辑距离排序取最佳匹配。

反爬策略：
- 先访问首页获取 Cloudflare cookie
- 完整的浏览器请求头（Accept / Sec-Fetch / Referer / Origin）
- base_urls 域名热切换（主站挂了自动切镜像）
"""
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from app.scraper.base import BaseScraper, ScrapedMetadata, ScrapingFailed
from app.config import config

logger = logging.getLogger(__name__)

BASE_URL = "https://javdb.com"


class JavDBScraper(BaseScraper):
    """JavDB 刮削器 — 两步流程: 首页获取 cookie → 搜索 → 详情页"""

    name = "javdb"
    label = "JavDB 刮削器"
    priority = 15
    version = "2.1.0"
    enabled = True
    requires_url = False
    base_urls = [
        "https://javdb.com",
        "https://javdb8.com",
        "https://javdb47.com",
    ]

    # JavDB-specific headers that bypass Cloudflare bot detection
    _WEB_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    # Track which base URL actually works
    _active_base: str = ""

    _cookie_ready: bool = False

    # ------------------------------------------------------------------

    def _get_base_url(self) -> str:
        """Use the active mirror if available, fallback to BASE_URL."""
        if self._active_base:
            return self._active_base
        urls = self._get_base_urls()
        self._active_base = urls[0] if urls else BASE_URL
        return self._active_base

    # ------------------------------------------------------------------
    # Cookie warmup — visit homepage to get Cloudflare cookie
    # ------------------------------------------------------------------

    async def _warmup_cookie(self) -> bool:
        """Visit JavDB homepage to obtain session and Cloudflare cookies."""
        base = self._get_base_url()
        logger.info("[javdb] 预热 cookie: %s", base)
        try:
            resp = await self.client.get(
                base,
                headers={**self._WEB_HEADERS, "Referer": base},
            )
            if resp.status_code in (200, 301, 302):
                cookies = dict(resp.cookies)
                logger.info("[javdb] cookie 预热成功, cookies=%s", list(cookies.keys()))
                self._cookie_ready = True
                return True
            logger.warning("[javdb] cookie 预热失败: HTTP %s", resp.status_code)
        except Exception as e:
            logger.warning("[javdb] cookie 预热异常: %s", e)
        return False

    async def _switch_mirror(self) -> bool:
        """Try the next base URL in the list and warm up its cookie."""
        urls = self._get_base_urls()
        for url in urls:
            if url == self._active_base:
                continue
            self._active_base = url
            logger.info("[javdb] 切换镜像: %s", url)
            if await self._warmup_cookie():
                return True
        # Reset to first URL and try again
        self._active_base = urls[0] if urls else BASE_URL
        return False

    # ------------------------------------------------------------------

    async def can_handle(self, code: str, filename: str) -> bool:
        return bool(code) and len(code) >= 3

    async def scrape(
        self, code: str, filename: str, search_url: str | None = None
    ) -> ScrapedMetadata:
        result = ScrapedMetadata(source_plugin=self.name)
        code_upper = code.upper()
        base = self._get_base_url()

        # ── Cookie warmup (only once per session) ──
        if not self._cookie_ready:
            ok = await self._warmup_cookie()
            if not ok:
                switched = await self._switch_mirror()
                if not switched:
                    raise ScrapingFailed(self.name, "所有 JavDB 镜像均不可达 (Cookie 预热失败)", base)

        # ── Step 1: 搜索 ──
        result = await self._scrape_with_fallback(code_upper, result, base)
        return result

    async def _scrape_with_fallback(
        self, code_upper: str, result: ScrapedMetadata, base: str
    ) -> ScrapedMetadata:
        """Attempt scrape with mirror fallback on 403/connection failure."""
        last_error = None
        urls_tried = [base]
        all_urls = self._get_base_urls()

        for attempt, url in enumerate(urls_tried + [u for u in all_urls if u not in urls_tried]):
            if attempt > 0:
                logger.info("[javdb] 切换镜像重试: %s", url)
                self._active_base = url
                if not await self._warmup_cookie():
                    continue

            try:
                return await self._do_scrape(code_upper, result, url)
            except ScrapingFailed as e:
                last_error = e
                logger.warning("[javdb] %s 失败: %s", url, e)
                continue
            except Exception as e:
                last_error = ScrapingFailed(self.name, str(e), url)
                logger.warning("[javdb] %s 异常: %s", url, e)
                continue

        raise last_error or ScrapingFailed(self.name, "所有 JavDB 镜像均刮削失败", base)

    async def _do_scrape(
        self, code_upper: str, result: ScrapedMetadata, base: str
    ) -> ScrapedMetadata:
        # Step 1: 搜索
        search_url = f"{base}/search?q={code_upper}&f=all"
        try:
            resp = await self.client.get(
                search_url,
                headers={**self._WEB_HEADERS, "Referer": base + "/"},
            )
            if resp.status_code == 403:
                raise ScrapingFailed(self.name, f"HTTP 403 Forbidden (Cloudflare 拦截)", search_url)
            if resp.status_code != 200:
                raise ScrapingFailed(self.name, f"HTTP {resp.status_code}", search_url)
            search_soup = BeautifulSoup(resp.text, "lxml")
        except ScrapingFailed:
            raise
        except Exception as e:
            raise ScrapingFailed(self.name, str(e), search_url) from e

        # 从搜索结果提取视频链接
        candidates: list[tuple[str, str]] = []  # [(url, title)]
        for item in search_soup.select(".item, .movie-list .item, .grid-item"):
            a = item.select_one("a[href*='/v/']")
            title_el = item.select_one(".video-title, .uid, strong")
            if a:
                url = self._resolve_url(a.get("href", ""))
                title = title_el.get_text(strip=True) if title_el else ""
                candidates.append((url, title))

        if not candidates:
            raise ScrapingFailed(self.name, f"搜索不到番号: {code_upper}", search_url)

        # 用编辑距离选最佳匹配
        best_url, best_title = self._pick_best_match(code_upper, candidates)
        logger.info("[javdb] 选中: %s — %s", best_url, best_title)

        # Step 2: 抓取详情页
        detail_url = best_url
        try:
            resp2 = await self.client.get(
                detail_url,
                headers={**self._WEB_HEADERS, "Referer": search_url,
                        "Sec-Fetch-Site": "same-origin"},
            )
            if resp2.status_code != 200:
                raise ScrapingFailed(self.name, f"HTTP {resp2.status_code}", detail_url)
            detail_soup = BeautifulSoup(resp2.text, "lxml")
            result.source_url = detail_url
        except ScrapingFailed:
            raise
        except Exception as e:
            raise ScrapingFailed(self.name, str(e), detail_url) from e

        try:
            self._parse_detail(detail_soup, code_upper, result)
        except Exception as e:
            logger.error("[javdb] 解析失败: %s — %s", code, e)
            raise ScrapingFailed(self.name, str(e), detail_url) from e

        logger.info("[javdb] 刮削成功: %s — %s", code, result.title)
        return result

    # ------------------------------------------------------------------
    # Detail page parsing
    # ------------------------------------------------------------------

    def _parse_detail(self, soup: BeautifulSoup, code: str, result: ScrapedMetadata) -> None:
        """Parse JavDB detail page."""
        # 标题 — h2 或 .title
        h2 = soup.select_one("h2")
        title_el = soup.select_one(".title, .video-title")
        title_el = h2 or title_el
        if title_el:
            raw = title_el.get_text(strip=True)
            result.title = raw
            result.original_title = raw

        # 封面
        cover = soup.select_one("[itemprop='image'], img.cover, .video-cover img")
        if cover:
            src = cover.get("src") or cover.get("content", "")
            result.poster_url = self._resolve_url(src)
            result.fanart_urls = [result.poster_url] if result.poster_url else []

        # 信息面板 (JavDB 常用 panel-body 或 video-panel)
        info_area = (
            soup.select_one(".panel-body")
            or soup.select_one(".video-panel")
            or soup.select_one(".movie-info")
        )
        if info_area:
            # 按中文标签提取（兼容两种标点冒号）
            for label in ["發行日期", "日期", "番號", "時長", "導演", "製作商", "系列"]:
                val = self._parse_info_item(info_area, label)
                if not val:
                    continue
                if label in ("發行日期", "日期"):
                    result.premiered = val
                    try:
                        result.year = int(val.split("-")[0])
                    except ValueError:
                        pass
                elif label == "時長":
                    try:
                        result.runtime = int(val.replace("分鐘", "").strip())
                    except ValueError:
                        pass
                elif label == "導演":
                    result.director = val
                elif label == "製作商":
                    result.studio = val
                elif label == "系列":
                    result.set_name = val

        # 分类标签
        tag_els = soup.select(".tag, .tags a, .genre a")
        result.genres = list(dict.fromkeys(
            t.get_text(strip=True) for t in tag_els if t.get_text(strip=True)
        ))

        # 演员
        actor_containers = [
            soup.select_one(".actor-list"),
            soup.select_one(".star-list"),
        ]
        result.actors = []
        for ac in actor_containers:
            if ac:
                for a in ac.select(".actor, .star, a[href*='/actors/'], a[href*='/star/']"):
                    name = a.get_text(strip=True)
                    if name:
                        img = a.select_one("img, .avatar img")
                        thumb = img.get("src", "") if img else ""
                        result.actors.append({"name": name, "thumb": thumb})

        # 评分
        rating_el = soup.select_one(".rating, .score, [itemprop='ratingValue']")
        if rating_el:
            try:
                result.rating = float(rating_el.get_text(strip=True))
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Best match selection
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_best_match(
        target: str, candidates: list[tuple[str, str]]
    ) -> tuple[str, str]:
        """从候选列表中选择与目标番号最匹配的结果。"""
        if len(candidates) == 1:
            return candidates[0]

        # 精确匹配优先
        target_norm = target.upper().replace("-", "").replace("_", "")
        for url, title in candidates:
            if target_norm in url.upper().replace("-", "").replace("_", ""):
                return url, title

        # 标题包含目标番号
        for url, title in candidates:
            if target in title.upper():
                return url, title

        # 编辑距离回退
        from app.parser.number import levenshtein_distance
        best = min(
            candidates,
            key=lambda c: levenshtein_distance(
                target_norm,
                c[0].upper().replace("-", "").replace("_", "")
            )
        )
        return best

    # ------------------------------------------------------------------

    async def search(self, query: str):
        return []
