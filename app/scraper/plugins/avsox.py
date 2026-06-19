"""
AVSOX 刮削插件
从 https://avsox.website 抓取影片元数据（与 JavBus 同结构，作为备用源）

使用 BeautifulSoup + 页面有效性双重校验。
"""
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup, Tag

from app.scraper.base import BaseScraper, ScrapedMetadata, ScrapingFailed
from app.config import config

logger = logging.getLogger(__name__)

BASE_URL = "https://avsox.website"


class AVSOXScraper(BaseScraper):
    """AVSOX 刮削器 — 与 JavBus 同结构，作为备用"""

    name = "avsox"
    label = "AVSOX 刮削器"
    priority = 20
    version = "2.0.0"
    enabled = True
    requires_url = False

    # ------------------------------------------------------------------

    def _get_base_url(self) -> str:
        return BASE_URL

    # ------------------------------------------------------------------

    async def can_handle(self, code: str, filename: str) -> bool:
        return bool(code) and len(code) >= 3

    async def scrape(
        self, code: str, filename: str, search_url: str | None = None
    ) -> ScrapedMetadata:
        result = ScrapedMetadata(source_plugin=self.name)
        code_upper = code.upper()

        urls_to_try = [
            f"{BASE_URL}/video/{code_upper}",
            f"{BASE_URL}/video/{code_upper.replace('-', '_')}",
        ]

        soup: BeautifulSoup | None = None
        for url in urls_to_try:
            try:
                resp = await self.client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    # 双重校验：必须包含标志性元素才认为是有效视频页
                    if (soup.select_one(".bigImage") or soup.select_one(".col-md-3.info")) and soup.select_one("h3"):
                        result.source_url = url
                        break
                    else:
                        soup = None  # 页面内容无效（可能是404页或空模板）
                        continue
                elif resp.status_code == 404:
                    continue
                else:
                    raise ScrapingFailed(self.name, f"HTTP {resp.status_code}", url)
            except ScrapingFailed:
                raise
            except Exception as e:
                logger.warning("[avsox] 访问 %s 失败: %s", url, e)
                continue

        if soup is None:
            raise ScrapingFailed(self.name, f"番号未找到: {code}", urls_to_try[0])

        try:
            self._parse_detail(soup, code_upper, result)
        except ScrapingFailed:
            raise
        except Exception as e:
            logger.error("[avsox] 解析失败: %s — %s", code, e)
            raise ScrapingFailed(self.name, str(e), result.source_url) from e

        logger.info("[avsox] 刮削成功: %s — %s", code, result.title)
        return result

    # ------------------------------------------------------------------
    # Parsing (same structure as JavBus)
    # ------------------------------------------------------------------

    def _parse_detail(self, soup: BeautifulSoup, code: str, result: ScrapedMetadata) -> None:
        """Parse the AVSOX detail page (mirrors JavBus structure)."""
        # 标题
        h3 = soup.select_one("h3")
        if h3:
            raw = h3.get_text(strip=True)
            result.title = raw
            result.original_title = raw

        # 二次校验：标题不能是站点名本身
        if not result.title or result.title.strip() in ("AVSOX", "Avsox"):
            raise ScrapingFailed(self.name, f"无效页面标题: {result.title}", result.source_url)

        # 封面
        big_img = soup.select_one(".bigImage")
        if big_img:
            poster = big_img.get("href", "")
            result.poster_url = self._resolve_url(poster)
            result.fanart_urls = [result.poster_url] if result.poster_url else []

        # 信息区域
        info_area = soup.select_one(".col-md-3.info")
        if info_area:
            date_val = self._parse_info_item(info_area, "發行日期")
            if date_val:
                result.premiered = date_val
                try:
                    result.year = int(date_val.split("-")[0])
                except ValueError:
                    pass

            dur_val = self._parse_info_item(info_area, "長度")
            if dur_val and "分鐘" in dur_val:
                try:
                    result.runtime = int(dur_val.replace("分鐘", "").strip())
                except ValueError:
                    pass

            dir_val = self._parse_info_item(info_area, "導演")
            if dir_val:
                result.director = dir_val

            stu_val = self._parse_info_item(info_area, "製作商")
            if stu_val:
                result.studio = stu_val

            set_val = self._parse_info_item(info_area, "系列")
            if set_val:
                result.set_name = set_val

        # 分类标签 — same fix as javbus: each genre is its own <span class="genre">
        genre_spans = soup.select("span.genre")
        if genre_spans:
            for span_a in genre_spans:
                for a in span_a.select("a[href]"):
                    if "/genre/" in (a.get("href") or ""):
                        text = a.get_text(strip=True)
                        if text and text not in result.genres:
                            result.genres.append(text)

        # 演员
        star_box = soup.select_one(".star-box")
        avatar_boxes = soup.select(".avatar-box")
        result.actors = self._parse_actor_nodes(star_box, *avatar_boxes)

        # 评分
        rating_el = soup.select_one(".rating")
        if rating_el:
            try:
                result.rating = float(rating_el.get_text(strip=True))
            except ValueError:
                pass

    # ------------------------------------------------------------------

    async def search(self, query: str):
        return []
