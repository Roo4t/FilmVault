"""
Genre 映射模块
将日文/英文分类标签翻译为中文
"""
import csv
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认映射表（内置常用分类）
DEFAULT_MAPPING = {
    # 日文 -> 中文
    "高清": "高清",
    "插值": "插值",
    "字幕": "字幕",
    "無碼": "无码",
    "無碼破解": "无码破解",
    "流出": "流出",
    "素人": "素人",
    "单体作品": "单体作品",
    "中出し": "中出",
    "アナル": "肛交",
    "イキり": "高潮",
    "オナニー": "自慰",
    "クンニ": "口交",
    "サンプル動画": "预览视频",
    "シコり": "手淫",
    "スカトロ": "粪便",
    "タイツ": "丝袜",
    "チンポ": "阴茎",
    "ディルド": "假阳具",
    "デブ": "胖子",
    "ドスケベ": "淫荡",
    "ドラッグ": "变装",
    "ドロワイプ": "偷拍",
    "ノーパン": "无内裤",
    "バイブ": "震动棒",
    "バニーガール": "兔女郎",
    "パンスト": "裤袜",
    "ビキニ": "比基尼",
    "フェラチオ": "口交",
    "フェティシズム": "恋物癖",
    "ブルマ": "运动短裤",
    "ペニバイク": "阴蒂刺激",
    "ヘア": "毛发",
    "ボンテージ": "束缚",
    "マウンティング": "骑乘位",
    "マゾ": "受虐",
    "ミッション": "传教士",
    "メガネ": "眼镜",
    "ヤリマン": "淫乱女",
    "ランジェリー": "内衣",
    "リモコン": "遥控",
    "レイプ": "强奸",
    "レズ": "蕾丝",
    "ローター": "震动器",
    "乱交": "乱交",
    "交渉": "交涉",
    "体位": "体位",
    "盗撮": "偷拍",
    "完全": "完全",
    "巨大": "巨大",
    "強制": "强制",
    "恋愛": "恋爱",
    "淫乱": "淫乱",
    "残酷": "残酷",
    "監禁": "监禁",
    "緊縛": "紧缚",
    "妄想": "妄想",
    "痴漢": "痴汉",
    "精液": "精液",
    "美少女": "美少女",
    "AV女優": "AV女优",
    # 英文 -> 中文
    "HD": "高清",
    "SD": "标清",
    "Subtitle": "字幕",
    "Uncensored": "无码",
    "Uncensored Leak": "无码破解",
    "Creampie": "中出",
    "Anal": "肛交",
    "Masturbation": "自慰",
    "Blowjob": "口交",
    "Threesome": "3P",
    "Foursome": "4P",
    "Orgy": "乱交",
    "Bondage": "束缚",
    "Domination": "支配",
    "Submission": "臣服",
    "Lesbian": "蕾丝",
    "Bisexual": "双性",
    "Virgin": "处女",
    "Big Tits": "巨乳",
    "Small Tits": "小乳",
    "Shaved": "剃毛",
    "Unshaved": "未剃",
    "Mature": "熟女",
    "Old Man": "熟男",
    "Student": "学生",
    "Teacher": "教师",
    "Nurse": "护士",
    "Office Lady": "OL",
    "Housewife": "人妻",
}


class GenreMapper:
    """Genre 映射器"""

    def __init__(self, mapping_file: Optional[Path] = None):
        """
        初始化 Genre 映射器

        Args:
            mapping_file: CSV 映射文件路径（格式：id,translate）
        """
        self._mapping = dict(DEFAULT_MAPPING)

        if mapping_file and mapping_file.exists():
            try:
                with open(mapping_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if "id" in row and "translate" in row:
                            jp_text = row["id"].strip()
                            cn_text = row["translate"].strip()
                            if jp_text and cn_text:
                                self._mapping[jp_text] = cn_text
                logger.info(f"从 {mapping_file} 加载了 {len(self._mapping)} 个 Genre 映射")
            except Exception as e:
                logger.error(f"加载 Genre 映射文件失败: {e}")

    def map(self, genre: str) -> str:
        """
        映射单个 Genre

        Args:
            genre: 原始 Genre 标签

        Returns:
            映射后的 Genre 标签（如果找不到映射，返回原始标签）
        """
        return self._mapping.get(genre, genre)

    def map_all(self, genres: list[str]) -> list[str]:
        """
        映射多个 Genre

        Args:
            genres: 原始 Genre 标签列表

        Returns:
            映射后的 Genre 标签列表
        """
        if not genres:
            return []
        return [self.map(g) for g in genres]

    def add_mapping(self, source: str, target: str) -> None:
        """
        添加自定义映射

        Args:
            source: 原始 Genre 标签
            target: 映射后的 Genre 标签
        """
        self._mapping[source] = target

    def remove_mapping(self, source: str) -> None:
        """
        移除映射

        Args:
            source: 要移除的原始 Genre 标签
        """
        self._mapping.pop(source, None)

    def get_all_mappings(self) -> dict[str, str]:
        """获取所有映射"""
        return dict(self._mapping)

    def save_to_file(self, file_path: Path) -> None:
        """
        保存映射到 CSV 文件

        Args:
            file_path: 保存路径
        """
        try:
            with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["id", "translate"])
                writer.writeheader()
                for source, target in self._mapping.items():
                    writer.writerow({"id": source, "translate": target})
            logger.info(f"Genre 映射已保存到 {file_path}")
        except Exception as e:
            logger.error(f"保存 Genre 映射文件失败: {e}")


# 全局映射器实例
_default_mapper: Optional[GenreMapper] = None


def get_default_mapper() -> GenreMapper:
    """获取默认的 Genre 映射器（单例）"""
    global _default_mapper
    if _default_mapper is None:
        from app.config import PROJECT_ROOT
        data_dir = PROJECT_ROOT / "data"
        _default_mapper = GenreMapper()

        # 尝试加载 CSV 映射文件
        for csv_file in ["genre_javbus.csv", "genre_javdb.csv", "genre_javlib.csv"]:
            csv_path = data_dir / csv_file
            if csv_path.exists():
                # 重新创建映射器，加载 CSV 文件
                _default_mapper = GenreMapper(csv_path)
                break

    return _default_mapper


def map_genre(genre: str) -> str:
    """快捷函数：映射单个 Genre"""
    return get_default_mapper().map(genre)


def map_genres(genres: list[str]) -> list[str]:
    """快捷函数：映射多个 Genre"""
    return get_default_mapper().map_all(genres)
