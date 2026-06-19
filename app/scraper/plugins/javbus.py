"""
JavBus 刮削插件
从 https://www.javbus.com 抓取影片元数据

完全使用 BeautifulSoup CSS选择器解析，不再使用裸正则。
"""
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from app.scraper.base import (
    BaseScraper, ScrapedMetadata,
    NetworkError, NotFoundError, ParseError, ScraperError,
)
from app.config import config

logger = logging.getLogger(__name__)

BASE_URL = "https://www.javbus.com"


class JavBusScraper(BaseScraper):
    """JavBus 刮削器 — 核心插件，优先级最高"""

    name = "javbus"
    label = "JavBus 刮削器"
    priority = 10
    version = "2.0.0"
    enabled = True
    requires_url = False
    base_urls = [
        "https://www.javbus.com",
        "https://www.javbus.cc",
        "https://www.javbus.pw",
    ]

    # ------------------------------------------------------------------
    # Client customization (no more duplicate __aenter__/__aexit__!)
    # ------------------------------------------------------------------

    def _get_base_url(self) -> str:
        return BASE_URL

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    async def can_handle(self, code: str, filename: str) -> bool:
        return bool(code) and len(code) >= 3

    async def scrape(
        self, code: str, filename: str, search_url: str | None = None
    ) -> ScrapedMetadata:
        result = ScrapedMetadata(source_plugin=self.name)
        code_upper = code.upper()

        # 尝试多种 URL 格式：横杠 / 下划线
        urls_to_try = [
            f"{BASE_URL}/{code_upper}",
            f"{BASE_URL}/{code_upper.replace('-', '_')}",
        ]

        soup: BeautifulSoup | None = None
        for url in urls_to_try:
            try:
                resp = await self.client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    # 验证是否是有效视频页面（检查标志性元素）
                    if soup.select_one("h3") or soup.select_one(".bigImage"):
                        result.source_url = url
                        break
                elif resp.status_code == 404:
                    continue
                else:
                    raise NetworkError(self.name, f"HTTP {resp.status_code}", url)
            except ScraperError:
                raise
            except Exception as e:
                logger.warning("[javbus] 访问 %s 失败: %s", url, e)
                continue

        if soup is None:
            raise NotFoundError(self.name, f"番号未找到: {code}", urls_to_try[0])

        try:
            self._parse_detail(soup, code_upper, result)
        except ScraperError:
            raise
        except Exception as e:
            logger.error("[javbus] 解析失败: %s — %s", code, e)
            raise ParseError(self.name, str(e), result.source_url) from e

        logger.info("[javbus] 刮削成功: %s — %s", code, result.title)
        return result

    # ------------------------------------------------------------------
    # Parsing logic — all BeautifulSoup, zero raw regex
    # ------------------------------------------------------------------

    def _parse_detail(self, soup: BeautifulSoup, code: str, result: ScrapedMetadata) -> None:
        """Parse the JavBus detail page soup into ScrapedMetadata."""
        # --- 标题 ---
        h3 = soup.select_one("h3")
        if h3:
            raw = h3.get_text(strip=True)
            result.title = raw
            result.original_title = raw
        else:
            title_el = soup.select_one("title")
            if title_el:
                raw = title_el.get_text(strip=True)
                # 去除 " — JavBus" 后缀
                if " — " in raw or " - " in raw:
                    raw = raw.rsplit(" — ", 1)[0].rsplit(" - ", 1)[0]
                result.title = raw
                result.original_title = raw

        # --- 封面 ---
        big_img_link = soup.select_one(".bigImage")
        if big_img_link:
            poster = big_img_link.get("href", "")
            result.poster_url = self._resolve_url(poster)
            result.fanart_urls = [result.poster_url] if result.poster_url else []

        # --- 信息区域 (col-md-3 info) ---
        info_area = soup.select_one(".col-md-3.info")
        if info_area:
            # 发行日期
            date_val = self._parse_info_item(info_area, "發行日期")
            if date_val:
                result.premiered = date_val
                try:
                    result.year = int(date_val.split("-")[0])
                except ValueError:
                    pass

            # 时长
            dur_val = self._parse_info_item(info_area, "長度")
            if dur_val and "分鐘" in dur_val:
                try:
                    result.runtime = int(dur_val.replace("分鐘", "").strip())
                except ValueError:
                    pass

            # 导演
            dir_val = self._parse_info_item(info_area, "導演")
            if dir_val:
                result.director = dir_val

            # 制作商
            stu_val = self._parse_info_item(info_area, "製作商")
            if stu_val:
                result.studio = stu_val

            # 系列
            set_val = self._parse_info_item(info_area, "系列")
            if set_val:
                result.set_name = set_val

        # --- 分类标签 ---
        # JavBus 每个 genre 现在是独立的 <span class="genre">, 不再是单一容器.
        # 同时还夹杂着 star 链接和非 genre 的 span，需通过 href="/genre/" 过滤.
        genre_spans = soup.select("span.genre")
        if genre_spans:
            for span_a in genre_spans:
                for a in span_a.select("a[href]"):
                    if "/genre/" in (a.get("href") or ""):
                        text = a.get_text(strip=True)
                        if text and text not in result.genres:
                            result.genres.append(text)
        # 备用：info 区域后的 genre checkbox 标签
        if not result.genres:
            genre_checks = soup.select(".genre label")
            for g in genre_checks:
                text = g.get_text(strip=True)
                if text:
                    result.genres.append(text)

        # --- 演员 ---
        # JavBus 演员在 #avatar-waterfall 或 .star-box 区域
        star_box = soup.select_one(".star-box") or soup.select_one("#avatar-waterfall")
        avatar_boxes = soup.select(".avatar-box")
        result.actors = self._parse_actor_nodes(star_box, *avatar_boxes)

        # --- 评分 ---
        rating_el = soup.select_one(".rating")
        if rating_el:
            score_text = rating_el.get_text(strip=True)
            try:
                result.rating = float(score_text)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Optional
    # ------------------------------------------------------------------

    async def search(self, query: str):
        return []
