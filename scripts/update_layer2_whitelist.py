"""層次 2 主程式 — 白名單 + 動態發現

讀 config/industries.yaml,對每個產業:
  ① 對 known_exhibitions 每個展查當年精確日期 (Gemini Flash + Google Search)
  ② 雙階段複核 (Gemini Pro 獨立驗證) → 通過 = 已確認、未通過 = 待確認
  ③ 用 keywords 動態發現新興展 → 標 AI發現、低信心度、待確認

預設 dry-run(只印不寫),加 --apply 才實際寫 Notion
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.gemini_query import (  # noqa: E402
    ExhibitionInfo,
    discover_new_exhibitions,
    query_exhibition,
)
from src.gemini_validator import validate_exhibition  # noqa: E402
from src.logger import get_logger  # noqa: E402
from src.models import Confidence, Exhibition, Location, SourceLayer, Status  # noqa: E402
from src.notion_writer import upsert_exhibition  # noqa: E402
from src.settings import INDUSTRIES_YAML  # noqa: E402

logger = get_logger(__name__)


def _to_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _to_location(summary: str) -> Location:
    if "臺灣" in summary or "台灣" in summary:
        return Location.TAIWAN
    return Location.WORLD


def _info_to_exhibition(
    name: str,
    info: ExhibitionInfo,
    industry: str,
    source: SourceLayer,
) -> Exhibition:
    """Gemini 查詢結果 → Exhibition (含複核步驟)"""
    start = _to_date(info.start_date)
    end = _to_date(info.end_date)
    confidence = Confidence.MEDIUM
    status = Status.PENDING

    if info.found and start and end:
        validation = validate_exhibition(name, start.year, start, end)
        if validation.confidence_high:
            confidence = Confidence.HIGH
            status = Status.CONFIRMED
        else:
            logger.info(f"複核未通過 {name}: {validation.reason}")
    else:
        start = end = None

    return Exhibition(
        name=name,
        start_date=start,
        end_date=end,
        location=_to_location(info.location_summary),
        organizer=info.organizer,
        url=info.official_url,
        confidence=confidence,
        source=source,
        industries=[industry],
        status=status,
    )


def run_industry(industry_data: dict, target_year: int, dry_run: bool) -> None:
    name = industry_data["name"]
    keywords = industry_data.get("keywords") or []
    known = industry_data.get("known_exhibitions") or []

    logger.info(f"=== 產業: {name}({len(known)} 個已知)===")

    for ex_name in known:
        try:
            info = query_exhibition(ex_name, target_year)
            ex = _info_to_exhibition(ex_name, info, name, SourceLayer.WHITELIST)
            upsert_exhibition(ex, dry_run=dry_run)
        except Exception as e:
            logger.exception(f"查詢失敗 {ex_name}: {e}")

    try:
        new_names = discover_new_exhibitions(name, keywords, known, target_year)
    except Exception as e:
        logger.exception(f"動態發現失敗 {name}: {e}")
        return

    for ex_name in new_names:
        try:
            info = query_exhibition(ex_name, target_year)
            ex = _info_to_exhibition(ex_name, info, name, SourceLayer.AI_DISCOVERY)
            ex.confidence = Confidence.LOW
            ex.status = Status.PENDING
            upsert_exhibition(ex, dry_run=dry_run)
        except Exception as e:
            logger.exception(f"動態發現後查詢失敗 {ex_name}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="層次 2:白名單 + 動態發現")
    parser.add_argument("--apply", action="store_true", help="實寫 Notion(預設 dry-run)")
    parser.add_argument("--year", type=int, default=datetime.now().year, help="目標年份")
    parser.add_argument("--industry", type=str, default=None, help="只跑指定產業名稱")
    args = parser.parse_args()

    dry_run = not args.apply
    logger.info(f"模式: {'實寫' if not dry_run else 'DRY-RUN'} | 目標年份: {args.year}")

    if not INDUSTRIES_YAML.exists():
        logger.error(f"找不到產業設定: {INDUSTRIES_YAML}")
        return 1

    with open(INDUSTRIES_YAML, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    industries = config.get("industries", [])
    if args.industry:
        industries = [i for i in industries if i.get("name") == args.industry]
        if not industries:
            logger.error(f"找不到產業: {args.industry}")
            return 1

    for ind in industries:
        run_industry(ind, args.year, dry_run)

    logger.info("層次 2 跑完")
    return 0


if __name__ == "__main__":
    sys.exit(main())
