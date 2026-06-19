"""
新刮削器插件开发模板
=================

使用方法:
1. 复制此文件到 ``app/scraper/plugins/`` 目录
2. 重命名为有意义的文件名 (如 ``javbus.py``)
3. 修改下面的类名、name、label、priority
4. 实现 ``can_handle`` 和 ``scrape`` 方法
5. 重启服务，插件自动加载

注意:
- 文件名不能以 ``_`` 开头（下划线开头的文件被忽略）
- 每个文件只能定义一个 BaseScraper 子类
- priority 越小越优先（建议 10-100），generic_html 固定为 999
"""

from app.scraper.base import BaseScraper, ScrapedMetadata, ScrapingFailed
from bs4 import BeautifulSoup


class MyScraper(BaseScraper):
    # ---- 元数据 ----
    name = "myscraper"               # 唯一标识（英文，无空格）
    label = "我的刮削器"              # 显示名称（中文）
    version = "1.0.0"
    priority = 50                    # 越小越优先，建议10-100
    enabled = True
    requires_url = False             # True 表示必须用户提供 URL

    # ---- 可选：基础 URL ----
    BASE_URL = "https://example.com"

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    async def can_handle(self, code: str, filename: str) -> bool:
        """
        判断此插件是否能处理给定的视频。

        例如：
        - 检查 code 是否匹配特定前缀模式
        - 返回 True 表示可以处理
        """
        # 示例：只处理非空 code
        return bool(code) and len(code) >= 5

    async def scrape(
        self, code: str, filename: str, search_url: str | None = None
    ) -> ScrapedMetadata:
        """
        执行刮削逻辑。

        典型流程:
        1. 构造搜索/详情页 URL
        2. 请求页面 (self.fetch_soup)
        3. 解析 HTML 提取字段
        4. 构造并返回 ScrapedMetadata
        """
        # 构造 URL
        target_url = search_url or f"{self.BASE_URL}/search?q={code}"

        # 获取并解析页面
        soup = await self.fetch_soup(target_url)

        # 提取标题（必须）
        title = self.safe_extract(soup, "h1.title")
        if not title:
            raise ScrapingFailed(self.name, "标题未找到", target_url)

        # 构造结果
        return ScrapedMetadata(
            title=title,
            original_title=self.safe_extract(soup, "meta[property='og:title']", "content"),
            plot=self.safe_extract(soup, "meta[name='description']", "content"),
            poster_url=self.safe_extract(soup, "meta[property='og:image']", "content"),
            year=self._extract_year(soup),
            runtime=self._extract_runtime(soup),
            genres=self.safe_extract_all(soup, ".genre-tag"),
            tags=self.safe_extract_all(soup, ".tag-item"),
            actors=self._extract_actors(soup),
            director=self.safe_extract(soup, ".director"),
            studio=self.safe_extract(soup, ".studio"),
            rating=self._extract_rating(soup),
            source_plugin=self.name,
            source_url=target_url,
        )

    # ------------------------------------------------------------------
    # 辅助方法（根据需要实现）
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_year(soup: BeautifulSoup) -> int | None:
        """从页面提取发行年份。"""
        import re

        el = soup.select_one(".year, [itemprop='datePublished']")
        if el and (text := el.get_text(strip=True)):
            m = re.search(r"(\d{4})", text)
            return int(m.group(1)) if m else None
        return None

    @staticmethod
    def _extract_runtime(soup: BeautifulSoup) -> int | None:
        """从页面提取时长（分钟）。"""
        import re

        el = soup.select_one(".runtime, [itemprop='duration']")
        if el and (text := el.get_text(strip=True)):
            m = re.search(r"(\d+)", text)
            return int(m.group(1)) if m else None
        return None

    @staticmethod
    def _extract_rating(soup: BeautifulSoup) -> float | None:
        """从页面提取评分。"""
        el = soup.select_one(".rating, [itemprop='ratingValue']")
        if el and (text := el.get_text(strip=True)):
            try:
                return float(text)
            except ValueError:
                pass
        return None

    @staticmethod
    def _extract_actors(soup: BeautifulSoup) -> list[dict]:
        """从页面提取演员列表。"""
        actors = []
        for el in soup.select(".actor-item, [itemprop='actor']"):
            name_el = el.select_one(".actor-name, [itemprop='name']")
            thumb_el = el.select_one("img")
            actors.append({
                "name": name_el.get_text(strip=True) if name_el else el.get_text(strip=True),
                "thumb": thumb_el.get("src") if thumb_el else None,
            })
        return actors

    # ------------------------------------------------------------------
    # 可选方法
    # ------------------------------------------------------------------

    async def search(self, query: str) -> list:
        """实现搜索功能（可选）。"""
        return []

    async def health_check(self) -> bool:
        """检查数据源连通性（可选）。"""
        try:
            resp = await self.client.head(self.BASE_URL)
            return resp.status_code < 500
        except Exception:
            return False
