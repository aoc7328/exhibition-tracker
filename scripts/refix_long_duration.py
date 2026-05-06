"""掃 Notion 上展期 > 14 天的 entries(Claude 抓錯把多活動串在一起的徵兆),
把它們的狀態改成「待確認」+ 清空日期。下次跑 .bat 會重新查;
你也可以在 Notion 上手動填入正確日期 + 改回「已確認」。

Usage:
    python scripts/refix_long_duration.py --dry-run
    python scripts/refix_long_duration.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logger import get_logger  # noqa: E402
from src.models import Status  # noqa: E402
from src.notion_writer import (  # noqa: E402
    NOTION_DATABASE_ID,
    _extract_text,
    _patch,
    _post,
)

logger = get_logger(__name__)

MAX_DURATION_DAYS = 14


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


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    pages = list_all_pages()
    logger.info(f"DB 共 {len(pages)} 筆")

    targets: list[tuple[dict[str, Any], str, date, date, int]] = []
    for p in pages:
        props = p.get("properties", {})
        start_prop = props.get("開始日期", {}).get("date") or {}
        end_prop = props.get("結束日期", {}).get("date") or {}

        start = _parse_date(start_prop.get("start"))
        end = _parse_date(start_prop.get("end")) or _parse_date(end_prop.get("start")) or start

        if not start or not end:
            continue

        duration = (end - start).days
        if duration <= MAX_DURATION_DAYS:
            continue

        name = _extract_text(props.get("展覽名稱", {}), "title")
        targets.append((p, name, start, end, duration))

    logger.info(f"展期 > {MAX_DURATION_DAYS} 天: {len(targets)} 筆")

    for p, name, s, e, d in targets:
        if args.dry_run:
            logger.info(f"[DRY-RUN] '{name}': {s} ~ {e} ({d} 天) → 待確認 + 清日期")
            continue
        try:
            _patch(
                f"/pages/{p['id']}",
                {
                    "properties": {
                        "狀態": {"select": {"name": Status.PENDING.value}},
                        "開始日期": {"date": None},
                        "結束日期": {"date": None},
                    }
                },
            )
            logger.info(f"refix: '{name}' ({d} 天) → 待確認 + 清日期")
        except Exception as e:
            logger.exception(f"failed {name}: {e}")

    logger.info("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
