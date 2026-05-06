"""台股月營收公布日 generator

法律規定:上市櫃公司應於每月 10 日前公布上月營收(實際多在 5-10 日)。
公司清單從 config/taiwan_companies.yaml 讀,動態增刪。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "taiwan_companies.yaml"


def load_companies() -> list[dict[str, Any]]:
    """讀 config/taiwan_companies.yaml 的公司清單"""
    if not CONFIG_PATH.exists():
        return []
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("companies", []) or []


def generate_monthly_revenue_events(months_ahead: int = 12) -> list[dict[str, Any]]:
    """生成未來 N 個月每月 10 日的「公司 YYYY-MM 月營收公布」事件"""
    today = date.today()
    events: list[dict[str, Any]] = []
    companies = load_companies()

    for offset in range(months_ahead + 1):
        year = today.year + ((today.month - 1 + offset) // 12)
        month = ((today.month - 1 + offset) % 12) + 1
        try:
            announce_date = date(year, month, 10)
        except ValueError:
            continue
        if announce_date < today:
            continue

        # 月營收公布的是「上月」資料
        if month > 1:
            revenue_year, revenue_month = year, month - 1
        else:
            revenue_year, revenue_month = year - 1, 12

        for c in companies:
            ticker = c["ticker"]
            name = c["name"]
            events.append(
                {
                    "name": f"{name}({ticker}) {revenue_year}-{revenue_month:02d} 月營收公布",
                    "start_date": announce_date,
                    "end_date": announce_date,
                    "organizer": name,
                    "url": f"https://mops.twse.com.tw/mops/web/t146sb05?co_id={ticker}",
                }
            )

    logger.info(
        f"台股月營收 generator: {len(events)} 筆({len(companies)} 家 × {months_ahead} 月)"
    )
    return events
