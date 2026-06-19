"""
番号处理工具 — 变体展开、编辑距离、结果排序。

参考: Emby.Plugins.JavScraper 的 GetAllKeys() + SortIndex()
"""

import re
from typing import Any


# ======================================================================
# 番号变体展开
# ======================================================================

def expand_number_variants(code: str) -> list[str]:
    """
    将番号展开为多种变体，覆盖不同网站的编码习惯。

    示例::
        "ABC-123" → ["ABC-123", "ABC123", "ABC_123", "ABC-0123", "abc-123", ...]
        "FC2-PPV-1234567" → ["FC2-PPV-1234567", "FC2PPV-1234567", "fc2-ppv-1234567"]

    变体规则:
    1. 原始格式 (保留优先级最高)
    2. 分隔符变体: -, _, 无
    3. 补零变体: 数字部分补到至少3-4位
    4. 大小写变体
    5. FC2 特殊格式
    """
    if not code or not isinstance(code, str):
        return []

    code = code.strip()
    variants: list[str] = [code]

    # --- 标准番号: PREFIX-### ---
    m = re.match(r'^([a-zA-Z]{2,})-?(\d+)$', code)
    if m:
        prefix, num = m.group(1), m.group(2)

        # 分隔符变体
        for sep in ('-', '_', ''):
            v = f"{prefix}{sep}{num}"
            if v not in variants:
                variants.append(v)

        # 补零变体 (3-5位)
        for width in (3, 4, 5):
            padded = num.zfill(max(len(num), width))
            if padded != num:
                for sep in ('-', '_', ''):
                    v = f"{prefix}{sep}{padded}"
                    if v not in variants:
                        variants.append(v)

    # --- FC2 特殊格式 ---
    fc2_m = re.match(r'^(fc2-?ppv-?\s*)(\d+)$', code, re.IGNORECASE)
    if fc2_m:
        prefix_part, num = fc2_m.group(1), fc2_m.group(2)
        for fmt in (f"FC2-PPV-{num}", f"FC2PPV-{num}", f"fc2-ppv-{num}"):
            if fmt not in variants:
                variants.append(fmt)

    # --- 独立数字 (可能是纯数字番号) ---
    m_numeric = re.match(r'^(\d{4,})$', code)
    if m_numeric:
        num = m_numeric.group(1)
        for prefix in ('', 'FC2-PPV-', 'FC2PPV-'):
            v = f"{prefix}{num}"
            if v not in variants:
                variants.append(v)

    # --- 大小写变体 (对已有变体生成) ---
    extra_case: list[str] = []
    for v in variants:
        vl = v.lower()
        if vl not in variants and vl not in extra_case:
            extra_case.append(vl)
        vu = v.upper()
        if vu not in variants and vu not in extra_case:
            extra_case.append(vu)
    variants.extend(extra_case)

    return variants


# ======================================================================
# Levenshtein 编辑距离
# ======================================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    """
    计算两个字符串的 Levenshtein 编辑距离。

    用于搜索结果与目标番号的模糊匹配排序。
    """
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    if s1 == s2:
        return 0

    # 确保 len(s1) <= len(s2) 以优化空间
    if len(s1) > len(s2):
        s1, s2 = s2, s1

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


# ======================================================================
# 结果排序
# ======================================================================

def normalize_code(code: str) -> str:
    """标准化番号为统一格式（大写、无分隔符）。"""
    return (
        code.upper()
        .replace("-", "")
        .replace("_", "")
        .replace(" ", "")
    )


def sort_results_by_relevance(
    results: list[dict[str, Any]],
    target_code: str,
    key_field: str = "num",
) -> list[dict[str, Any]]:
    """
    按与目标番号的相关性排序结果。

    排序规则:
    1. 精确匹配 (normalized 后完全一致) → 最高优先
    2. 包含关系 (结果包含目标或目标包含结果) → 次优
    3. 编辑距离 (距离越小越靠前)

    Returns:
        排序后的新列表。
    """
    target_norm = normalize_code(target_code)

    def relevance(item: dict[str, Any]) -> tuple[int, int]:
        item_num = normalize_code(str(item.get(key_field, "")))
        if item_num == target_norm:
            return (0, 0)  # 精确匹配
        if target_norm in item_num or item_num in target_norm:
            return (1, 0)  # 包含关系
        dist = levenshtein_distance(target_norm, item_num)
        return (2, dist)  # 编辑距离

    return sorted(results, key=relevance)
