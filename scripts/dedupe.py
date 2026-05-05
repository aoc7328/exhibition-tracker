"""清理 Notion 既有重複展覽

邏輯:撈整個 DB → 按開始年份分組 → 組內兩兩 fuzzy + Claude 確認 →
是同展 → 合併產業類別到主筆 + archive 副筆。

主筆選擇:保留資料較完整(有起訖日期、有官方網址、信心度高)的那筆。

Usage:
    python scripts/dedupe.py --dry-run    # 只列印不動 Notion
    python scripts/dedupe.py              # 實際合併 + archive
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.deduper import (  # noqa: E402
    HIGH_THRESHOLD,
    SIMILARITY_THRESHOLD,
    claude_is_same_exhibition,
    fuzzy_similarity,
)
from src.logger import get_logger  # noqa: E402
from src.notion_writer import (  # noqa: E402
    NOTION_DATABASE_ID,
    _extract_multiselect,
    _extract_select_name,
    _extract_text,
    _patch,
    _post,
)

logger = get_logger(__name__)


def list_all_pages() -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        body: dict[str, Any] = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        response = _post(f"/databases/{NOTION_DATABASE_ID}/query", body)
        pages.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return pages


def get_page_year(page: dict[str, Any]) -> int | None:
    start = (page.get("properties", {}).get("開始日期", {}).get("date") or {}).get("start")
    if not start:
        return None
    try:
        return date.fromisoformat(start[:10]).year
    except ValueError:
        return None


_CONFIDENCE_RANK = {"🟢 高": 3, "🟡 中": 2, "🔴 低": 1}


def _completeness_score(page: dict[str, Any]) -> tuple[int, int, int]:
    """資料完整度評分:(信心度, 是否有起訖, 是否有 URL)"""
    props = page.get("properties", {})
    conf = _extract_select_name(props.get("信心度", {})) or ""
    conf_score = _CONFIDENCE_RANK.get(conf, 0)

    start = (props.get("開始日期", {}).get("date") or {}).get("start")
    end_via_range = (props.get("開始日期", {}).get("date") or {}).get("end")
    end_separate = (props.get("結束日期", {}).get("date") or {}).get("start")
    has_dates = 1 if (start and (end_via_range or end_separate)) else 0

    has_url = 1 if (props.get("官方網址", {}).get("url") or "") else 0

    return (conf_score, has_dates, has_url)


def merge_pages(primary: dict[str, Any], secondary: dict[str, Any], dry_run: bool) -> None:
    """把 secondary 的產業類別合進 primary,然後 archive secondary"""
    primary_id = primary["id"]
    secondary_id = secondary["id"]

    primary_props = primary.get("properties", {})
    secondary_props = secondary.get("properties", {})

    primary_name = _extract_text(primary_props.get("展覽名稱", {}), "title")
    secondary_name = _extract_text(secondary_props.get("展覽名稱", {}), "title")

    primary_industries = _extract_multiselect(primary_props.get("產業類別", {}))
    secondary_industries = _extract_multiselect(secondary_props.get("產業類別", {}))
    merged = sorted(set(primary_industries) | set(secondary_industries))

    if dry_run:
        logger.info(
            f"[DRY-RUN] 會合併: '{secondary_name}' → '{primary_name}',"
            f"產業 {primary_industries} + {secondary_industries} = {merged},"
            f"並 archive secondary"
        )
        return

    if merged != primary_industries:
        _patch(
            f"/pages/{primary_id}",
            {"properties": {"產業類別": {"multi_select": [{"name": n} for n in merged]}}},
        )

    _patch(f"/pages/{secondary_id}", {"archived": True})
    logger.info(f"合併 + archive: '{secondary_name}' → '{primary_name}',industries={merged}")


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 Notion 既有重複展覽")
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    logger.info(f"開始清理 (dry_run={args.dry_run})")

    pages = list_all_pages()
    logger.info(f"DB 共 {len(pages)} 筆")

    # 按年份分組
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for p in pages:
        year = get_page_year(p)
        if year:
            by_year[year].append(p)
        # 沒年份的 (start_date 缺) 不參與比對

    merged_count = 0
    for year, year_pages in sorted(by_year.items()):
        logger.info(f"--- 年份 {year} ({len(year_pages)} 筆) ---")
        # 兩兩比對,逐次把同展合併
        i = 0
        while i < len(year_pages):
            j = i + 1
            while j < len(year_pages):
                page_a = year_pages[i]
                page_b = year_pages[j]
                name_a = _extract_text(page_a.get("properties", {}).get("展覽名稱", {}), "title")
                name_b = _extract_text(page_b.get("properties", {}).get("展覽名稱", {}), "title")

                if not name_a or not name_b:
                    j += 1
                    continue

                sim = fuzzy_similarity(name_a, name_b)
                is_same = False
                if sim >= HIGH_THRESHOLD:
                    is_same = True
                    logger.info(f"  高度相似 ({sim:.2f}): '{name_a}' = '{name_b}'")
                elif sim >= SIMILARITY_THRESHOLD:
                    logger.info(f"  中等相似 ({sim:.2f}),問 Claude: '{name_a}' vs '{name_b}'")
                    is_same = claude_is_same_exhibition(name_a, name_b)
                    if is_same:
                        logger.info("  Claude 確認同展")

                if is_same:
                    # 選資料較完整者為 primary
                    score_a = _completeness_score(page_a)
                    score_b = _completeness_score(page_b)
                    if score_b > score_a:
                        primary, secondary = page_b, page_a
                        merge_pages(primary, secondary, dry_run=args.dry_run)
                        # secondary = page_a 將被移除
                        year_pages.pop(i)
                        # i 不變(後面的會 shift 上來),但 break 內層 loop
                        break
                    else:
                        primary, secondary = page_a, page_b
                        merge_pages(primary, secondary, dry_run=args.dry_run)
                        year_pages.pop(j)
                        merged_count += 1
                        # 不 i++,因為 i 還要對 j+1 繼續比
                        continue
                j += 1
            else:
                i += 1
                continue
            # break 出內層代表 page_a 被合併消失,i 那筆換成原 i+1 的內容
            merged_count += 1
            # i 不變,繼續對新 i 那筆比對
            continue

    logger.info(f"完成,合併 {merged_count} 筆")
    return 0


if __name__ == "__main__":
    sys.exit(main())
