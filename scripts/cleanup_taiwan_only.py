"""清理「臺灣專屬」產業裡誤抓到的非臺灣展

對 industries.yaml 標 taiwan_only=true 的產業(目前是文具禮品/建材/旅展),
掃 Notion 找出產業類別含這些 + 地點=「世界」的展,把狀態改成「已過期」。

不刪除,只改狀態;之後想看仍可在 Notion 找到。.ics 不再輸出。

Usage:
    python scripts/cleanup_taiwan_only.py --dry-run   # 只列出不動
    python scripts/cleanup_taiwan_only.py             # 實際標已過期
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.logger import get_logger  # noqa: E402
from src.models import Status  # noqa: E402
from src.notion_writer import (  # noqa: E402
    NOTION_DATABASE_ID,
    _extract_multiselect,
    _extract_select_name,
    _extract_text,
    _patch,
    _post,
)
from src.settings import INDUSTRIES_YAML  # noqa: E402

logger = get_logger(__name__)


def load_taiwan_only_industries() -> set[str]:
    with open(INDUSTRIES_YAML, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return {
        ind["name"]
        for ind in config.get("industries", [])
        if ind.get("taiwan_only")
    }


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
    parser = argparse.ArgumentParser(description="清理 taiwan_only 產業誤抓的非臺灣展")
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    tw_only = load_taiwan_only_industries()
    logger.info(f"標 taiwan_only 的產業: {sorted(tw_only)}")
    if not tw_only:
        logger.info("沒有 taiwan_only 產業,結束")
        return 0

    pages = list_all_pages()
    logger.info(f"DB 共 {len(pages)} 筆")

    targets: list[dict[str, Any]] = []
    for p in pages:
        props = p.get("properties", {})
        industries = set(_extract_multiselect(props.get("產業類別", {})))
        location = _extract_select_name(props.get("地點", {})) or ""
        # 命中:產業有交集 + 地點=世界
        if industries & tw_only and location == "世界":
            targets.append(p)

    logger.info(f"待標已過期: {len(targets)} 筆")

    for p in targets:
        props = p.get("properties", {})
        name = _extract_text(props.get("展覽名稱", {}), "title")
        cats = _extract_multiselect(props.get("產業類別", {}))
        if args.dry_run:
            logger.info(f"[DRY-RUN] 將標已過期: '{name}' (產業={cats})")
            continue
        try:
            _patch(
                f"/pages/{p['id']}",
                {"properties": {"狀態": {"select": {"name": Status.EXPIRED.value}}}},
            )
            logger.info(f"標已過期: '{name}'")
        except Exception as e:
            logger.exception(f"標已過期失敗 {name}: {e}")

    logger.info("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
