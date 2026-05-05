"""把 Notion 上既有「龍頭發表會」標籤批量改成「企業」

一次性 migration script。跑一次後可以刪掉。

Usage:
    python scripts/migrate_industry_label.py --dry-run
    python scripts/migrate_industry_label.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logger import get_logger  # noqa: E402
from src.notion_writer import (  # noqa: E402
    NOTION_DATABASE_ID,
    _extract_multiselect,
    _extract_text,
    _patch,
    _post,
)

logger = get_logger(__name__)

OLD_LABEL = "龍頭發表會"
NEW_LABEL = "企業"


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    pages = list_all_pages()
    logger.info(f"DB 共 {len(pages)} 筆")

    targets = []
    for p in pages:
        industries = _extract_multiselect(p.get("properties", {}).get("產業類別", {}))
        if OLD_LABEL in industries:
            targets.append(p)

    logger.info(f"待 migrate: {len(targets)} 筆({OLD_LABEL} → {NEW_LABEL})")

    for p in targets:
        props = p.get("properties", {})
        name = _extract_text(props.get("展覽名稱", {}), "title")
        old_industries = _extract_multiselect(props.get("產業類別", {}))
        new_industries = sorted(set(
            NEW_LABEL if x == OLD_LABEL else x for x in old_industries
        ))

        if args.dry_run:
            logger.info(f"[DRY-RUN] '{name}': {old_industries} → {new_industries}")
            continue

        try:
            _patch(
                f"/pages/{p['id']}",
                {
                    "properties": {
                        "產業類別": {
                            "multi_select": [{"name": n} for n in new_industries]
                        }
                    }
                },
            )
            logger.info(f"migrate: '{name}' → {new_industries}")
        except Exception as e:
            logger.exception(f"migrate 失敗 {name}: {e}")

    logger.info("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
