"""加新台股公司進追蹤清單,並立刻寫進 Notion + 重產 .ics

Usage:
    python scripts/add_taiwan_company.py 2454 聯發科 AI 半導體 5G/6G
    python scripts/add_taiwan_company.py 1101 台泥 工業材料

加進 config/taiwan_companies.yaml 後:
1. 跑月營收 generator filter 該公司,寫 12 個月月營收進 Notion
2. 跑 Claude CLI 查該公司季度法說會,寫進 Notion
3. 重產 .ics + push gh-pages

即跑即生效。下次跑 run_all_in_one.bat 也會自動繼續更新該公司。

Flags:
    --skip-claude   略過 Claude 查法說會(只跑月營收)
    --skip-push     略過 ICS push(只更新 Notion)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.claude_query import query_exhibition  # noqa: E402
from src.claude_validator import validate_exhibition  # noqa: E402
from src.ics_generator import generate_ics  # noqa: E402
from src.logger import get_logger  # noqa: E402
from src.models import (  # noqa: E402
    Confidence,
    Exhibition,
    Location,
    SourceLayer,
    Status,
)
from src.notion_writer import upsert_exhibition  # noqa: E402
from src.scrapers.taiwan_monthly import generate_monthly_revenue_events  # noqa: E402

logger = get_logger(__name__)

CONFIG_PATH = PROJECT_ROOT / "config" / "taiwan_companies.yaml"
CORPORATE_LABEL = "企業"


def _to_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _update_yaml(ticker: str, name: str, industries: list[str]) -> bool:
    """append 公司到 yaml,如果已存在回 False"""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    companies = config.get("companies", []) or []

    if any(c.get("ticker") == ticker for c in companies):
        return False

    companies.append(
        {"ticker": ticker, "name": name, "extra_industries": industries}
    )
    config["companies"] = companies
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    return True


def _write_monthly_revenue(ticker: str, name: str, industries: list[str]) -> int:
    """跑月營收 generator filter 該公司,寫進 Notion,回寫入筆數"""
    all_events = generate_monthly_revenue_events()
    target = [e for e in all_events if ticker in e["name"]]
    ind_set = sorted(set([CORPORATE_LABEL] + industries))

    written = 0
    for ev in target:
        ex = Exhibition(
            name=ev["name"],
            start_date=ev["start_date"],
            end_date=ev["end_date"],
            location=Location.TAIWAN,
            organizer=ev.get("organizer", name),
            url=ev.get("url", ""),
            confidence=Confidence.HIGH,
            source=SourceLayer.WHITELIST,
            industries=ind_set,
            status=Status.CONFIRMED,
        )
        try:
            upsert_exhibition(ex, dry_run=False)
            written += 1
        except Exception as e:
            logger.exception(f"upsert 月營收失敗 {ex.unique_key}: {e}")
    return written


def _query_quarterly_meeting(ticker: str, name: str, industries: list[str]) -> bool:
    """跑 Claude CLI 查季度法說會,寫進 Notion"""
    meeting_name = f"{name} {ticker} 法說會"
    year = datetime.now().year
    ind_set = sorted(set([CORPORATE_LABEL] + industries))

    try:
        info = query_exhibition(meeting_name, year)
    except Exception as e:
        logger.exception(f"Claude 查 {meeting_name} 失敗: {e}")
        return False

    if not info.get("found"):
        logger.info(f"Claude 沒找到 {meeting_name} 精確日期: {info.get('notes')}")
        return False

    start = _to_date(info.get("start_date"))
    end = _to_date(info.get("end_date")) or start
    if not start:
        return False

    confidence = Confidence.MEDIUM
    status = Status.PENDING
    try:
        val = validate_exhibition(meeting_name, start.year, start, end)
        if val.get("confidence_high"):
            confidence = Confidence.HIGH
            status = Status.CONFIRMED
    except Exception as e:
        logger.exception(f"驗證 {meeting_name} 失敗: {e}")

    ex = Exhibition(
        name=meeting_name,
        start_date=start,
        end_date=end,
        location=Location.TAIWAN,
        organizer=info.get("organizer", name),
        url=info.get("official_url", ""),
        confidence=confidence,
        source=SourceLayer.WHITELIST,
        industries=ind_set,
        status=status,
    )
    try:
        upsert_exhibition(ex, dry_run=False)
        logger.info(f"寫入法說會: {meeting_name} ({start} ~ {end})")
        return True
    except Exception as e:
        logger.exception(f"upsert 法說會失敗 {meeting_name}: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="加新台股公司進追蹤清單")
    parser.add_argument("ticker", help="台股代號(例: 2330)")
    parser.add_argument("name", help="公司中文名(例: 台積電)")
    parser.add_argument("industries", nargs="*", help="相關產業 cross-tag")
    parser.add_argument("--skip-claude", action="store_true", help="略過 Claude 查法說會")
    parser.add_argument("--skip-push", action="store_true", help="略過 ICS push")
    args = parser.parse_args()

    industries = args.industries or []

    # 1. yaml
    added = _update_yaml(args.ticker, args.name, industries)
    if added:
        logger.info(f"加進 yaml: {args.ticker} {args.name} {industries}")
    else:
        logger.info(f"{args.ticker} {args.name} 已在 yaml,只跑 refresh")

    # 2. 月營收
    logger.info("=== 跑月營收 generator ===")
    monthly = _write_monthly_revenue(args.ticker, args.name, industries)
    logger.info(f"寫入月營收: {monthly} 筆")

    # 3. 季度法說會
    if not args.skip_claude:
        logger.info("=== 跑 Claude 查季度法說會 ===")
        _query_quarterly_meeting(args.ticker, args.name, industries)

    # 4. ICS push
    if not args.skip_push:
        logger.info("=== 重產 .ics + push gh-pages ===")
        try:
            from scripts.update_all import push_ics_to_gh_pages

            ics_path = generate_ics()
            push_ics_to_gh_pages(ics_path)
            logger.info(f"Apple 行事曆會在下次同步看到 {args.name} 的資料")
        except Exception as e:
            logger.exception(f"ICS / push 失敗: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
