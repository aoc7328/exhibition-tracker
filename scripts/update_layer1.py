"""層次 1 主程式 — 台北世貿信義一館 + 南港展覽館爬蟲

- 來源權威,日期精確 → 直接寫入「已確認 / 🟢 高信心度」
- 用 industries.yaml 的 keywords 篩選,只有匹配到至少一個產業類別才寫入
- 預設 dry-run,加 --apply 才實際寫 Notion
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.category_filter import load_industries, match_industries  # noqa: E402
from src.logger import get_logger  # noqa: E402
from src.models import Confidence, Exhibition, Location, SourceLayer, Status  # noqa: E402
from src.notion_writer import upsert_exhibition  # noqa: E402
from src.scrapers.nangang import fetch_exhibitions as fetch_nangang  # noqa: E402
from src.scrapers.twtc import fetch_exhibitions as fetch_twtc  # noqa: E402

logger = get_logger(__name__)


def _process(events: list[dict[str, Any]], source: SourceLayer, industries: list, dry_run: bool) -> tuple[int, int]:
    """處理一個來源的展覽,回傳 (matched, written)"""
    matched_count = 0
    for ev in events:
        cats = match_industries(ev["name"], industries)
        if not cats:
            continue
        matched_count += 1
        ex = Exhibition(
            name=ev["name"],
            start_date=ev.get("start_date"),
            end_date=ev.get("end_date"),
            location=Location.TAIWAN,
            organizer=ev.get("organizer", ""),
            url=ev.get("url", ""),
            confidence=Confidence.HIGH,
            source=source,
            industries=cats,
            status=Status.CONFIRMED,
        )
        try:
            upsert_exhibition(ex, dry_run=dry_run)
        except Exception as e:
            logger.exception(f"upsert 失敗 {ex.unique_key}: {e}")
    return matched_count, matched_count


def main() -> int:
    parser = argparse.ArgumentParser(description="層次 1 - 台北世貿+南港")
    parser.add_argument("--apply", action="store_true", help="實寫 Notion(預設 dry-run)")
    parser.add_argument("--year", type=int, default=datetime.now().year, help="目標年份")
    args = parser.parse_args()

    dry_run = not args.apply
    logger.info(f"模式: {'實寫' if not dry_run else 'DRY-RUN'} | 年份: {args.year}")

    industries = load_industries()
    logger.info(f"載入 {len(industries)} 個產業類別")

    # TWTC
    logger.info("=== TWTC 信義一館 ===")
    try:
        twtc_events = fetch_twtc(args.year)
        m, _ = _process(twtc_events, SourceLayer.TWTC, industries, dry_run)
        logger.info(f"TWTC: 抓到 {len(twtc_events)} 筆,匹配產業 {m} 筆")
    except Exception as e:
        logger.exception(f"TWTC 抓取失敗: {e}")

    # 南港
    logger.info("=== 南港展覽館 ===")
    try:
        nangang_events = fetch_nangang()
        m, _ = _process(nangang_events, SourceLayer.NANGANG, industries, dry_run)
        logger.info(f"南港: 抓到 {len(nangang_events)} 筆,匹配產業 {m} 筆")
    except Exception as e:
        logger.exception(f"南港抓取失敗: {e}")

    logger.info("層次 1 跑完")
    return 0


if __name__ == "__main__":
    sys.exit(main())
