"""台股月營收公布日 generator

法律規定:上市櫃公司應於每月 10 日前公布上月營收(實際多在 5-10 日)。
為提醒目的,以「每月 10 日」當作預定公布日,生成未來 N 個月每月一筆事件。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..logger import get_logger

logger = get_logger(__name__)

# (ticker, 顯示名稱)
COMPANIES: list[tuple[str, str]] = [
    ("2330", "台積電"),
    ("2308", "台達電"),
]


def generate_monthly_revenue_events(months_ahead: int = 12) -> list[dict[str, Any]]:
    """生成未來 N 個月每月 10 日的「公司 YYYY-MM 月營收公布」事件"""
    today = date.today()
    events: list[dict[str, Any]] = []

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

        for ticker, company in COMPANIES:
            events.append(
                {
                    "name": f"{company}({ticker}) {revenue_year}-{revenue_month:02d} 月營收公布",
                    "start_date": announce_date,
                    "end_date": announce_date,
                    "organizer": company,
                    "url": f"https://mops.twse.com.tw/mops/web/t146sb05?co_id={ticker}",
                }
            )

    logger.info(f"台股月營收 generator: {len(events)} 筆({len(COMPANIES)} 家 × {months_ahead} 月)")
    return events
