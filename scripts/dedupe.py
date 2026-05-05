"""清理 Notion 既有重複展覽

邏輯:撈整個 DB → 按開始年份分組 → 組內兩兩比對(名字+日期+主辦+Claude)→
是同展 → 合併產業類別到主筆 + archive 副筆。

主筆選擇:資料較完整者(信心度高 / 有起訖日 / 有官網)。

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

from src.deduper import is_same_exhibition  # noqa: E402
from src.logger import get_logger  # noqa: E402
from src.notion_writer import (  # noqa: E402
    NOTION_DATABASE_ID,
    _extract_multiselect,
    _extract_select_name,
    _extract_text,
    _page_to_meta,
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
            f"[DRY-RUN] 合併: '{secondary_name}' → '{primary_name}',"
            f"產業 {primary_industries} + {secondary_industries} = {merged}"
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

    merged_count = 0
    for year, year_pages in sorted(by_year.items()):
        logger.info(f"--- 年份 {year} ({len(year_pages)} 筆) ---")
        i = 0
        while i < len(year_pages):
            j = i + 1
            i_removed = False
            while j < len(year_pages):
                page_a = year_pages[i]
                page_b = year_pages[j]
                meta_a = _page_to_meta(page_a)
                meta_b = _page_to_meta(page_b)

                if not meta_a.name or not meta_b.name:
                    j += 1
                    continue

                if is_same_exhibition(meta_a, meta_b):
                    score_a = _completeness_score(page_a)
                    score_b = _completeness_score(page_b)
                    if score_b > score_a:
                        merge_pages(primary=page_b, secondary=page_a, dry_run=args.dry_run)
                        year_pages.pop(i)
                        i_removed = True
                        merged_count += 1
                        break
                    else:
                        merge_pages(primary=page_a, secondary=page_b, dry_run=args.dry_run)
                        year_pages.pop(j)
                        merged_count += 1
                        continue
                j += 1
            if not i_removed:
                i += 1

    logger.info(f"完成,合併 {merged_count} 筆")
    return 0


if __name__ == "__main__":
    sys.exit(main())
