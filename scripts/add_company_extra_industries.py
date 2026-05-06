"""一次性 migration:對 Notion 上 industries 含「企業」的 entries,
根據展名前綴自動補上對應公司的相關產業 tag。

例:
- "Apple WWDC" → 既有 [企業] → 變 [企業, 消費電子]
- "NVIDIA Q3 2026 Earnings" → 變 [企業, AI, 半導體]
- "台積電(2330) 2026-04 月營收公布" → 變 [企業, 半導體]

跑一次即可,跑完可以刪。
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

CORPORATE_LABEL = "企業"

HARDCODED_COMPANY_TAGS: dict[str, list[str]] = {
    "Apple": ["消費電子"],
    "Alphabet": ["AI"],
    "Google": ["AI", "消費電子"],
    "NVIDIA": ["AI", "半導體"],
    "AMD": ["AI", "半導體"],
    "Microsoft": ["AI"],
    "Meta": ["AI", "消費電子"],
    "Amazon": ["AI"],
    "AWS": ["AI"],
    "Oracle": ["AI"],
    "Tesla": ["車用電子", "AI"],
    "SpaceX": ["太空航太", "低軌衛星"],
    "OpenAI": ["AI"],
    "Anthropic": ["AI"],
    "Broadcom": ["AI", "半導體", "5G/6G", "光通訊"],
    "AVGO": ["AI", "半導體", "5G/6G", "光通訊"],
}


def _load_taiwan_company_tags() -> dict[str, list[str]]:
    """從 taiwan_companies.yaml 動態載入"""
    from src.scrapers.taiwan_monthly import load_companies

    tags: dict[str, list[str]] = {}
    for c in load_companies():
        ticker = c.get("ticker", "")
        name = c.get("name", "")
        extras = c.get("extra_industries") or []
        if ticker:
            tags[ticker] = extras
        if name:
            tags[name] = extras
    return tags


def _company_extra_industries(name: str) -> list[str]:
    for prefix, industries in _load_taiwan_company_tags().items():
        if prefix in name:
            return industries
    for prefix, industries in HARDCODED_COMPANY_TAGS.items():
        if prefix in name:
            return industries
    return []


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

    targets: list[tuple[dict[str, Any], str, list[str], list[str]]] = []
    for p in pages:
        props = p.get("properties", {})
        industries = _extract_multiselect(props.get("產業類別", {}))
        if CORPORATE_LABEL not in industries:
            continue
        name = _extract_text(props.get("展覽名稱", {}), "title")
        extras = _company_extra_industries(name)
        if not extras:
            continue
        new_industries = sorted(set(industries) | set(extras))
        if new_industries == sorted(industries):
            continue
        targets.append((p, name, industries, new_industries))

    logger.info(f"待補產業 tag: {len(targets)} 筆")

    for page, name, old, new in targets:
        if args.dry_run:
            logger.info(f"[DRY-RUN] '{name}': {old} → {new}")
            continue
        try:
            _patch(
                f"/pages/{page['id']}",
                {
                    "properties": {
                        "產業類別": {
                            "multi_select": [{"name": n} for n in new]
                        }
                    }
                },
            )
            logger.info(f"updated: '{name}' → {new}")
        except Exception as e:
            logger.exception(f"failed {name}: {e}")

    logger.info("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
