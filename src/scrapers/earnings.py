"""Finnhub earnings calendar scraper

從 Finnhub /calendar/earnings 抓 9 家美股龍頭未來 N 個月 earnings 日期。
- 免費 tier:60 calls/min,我們 9 ticker 一次跑完
- 只抓「公司已 announce 的」earnings(通常 1-3 個月前才會公告下一場)
- 半年後重跑會自動補新一輪
"""
from __future__ import annotations

import datetime as _dt
from datetime import date
from typing import Any

import requests

from ..logger import get_logger

logger = get_logger(__name__)

API_URL = "https://finnhub.io/api/v1/calendar/earnings"

# Ticker -> 公司顯示名(name 統一英文,Notion 上跟年度發表會風格一致)
TICKERS: dict[str, str] = {
    "AAPL": "Apple",
    "GOOGL": "Alphabet",
    "NVDA": "NVIDIA",
    "AMD": "AMD",
    "MSFT": "Microsoft",
    "META": "Meta",
    "AMZN": "Amazon",
    "ORCL": "Oracle",
    "TSLA": "Tesla",
}


def fetch_earnings(api_key: str, months_ahead: int = 12) -> list[dict[str, Any]]:
    """抓 9 家公司未來 N 個月 earnings,回 Exhibition-friendly dict list"""
    today = date.today()
    end = today + _dt.timedelta(days=int(30.5 * months_ahead))
    events: list[dict[str, Any]] = []

    for symbol, company in TICKERS.items():
        try:
            r = requests.get(
                API_URL,
                params={
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                    "symbol": symbol,
                    "token": api_key,
                },
                timeout=30,
            )
            r.raise_for_status()
            cal = r.json().get("earningsCalendar", []) or []
        except Exception as e:
            logger.exception(f"Finnhub fetch {symbol} 失敗: {e}")
            continue

        for entry in cal:
            d_str = entry.get("date")
            quarter = entry.get("quarter")
            year = entry.get("year")
            if not d_str or not quarter or not year:
                continue
            try:
                event_date = date.fromisoformat(d_str)
            except ValueError:
                continue
            name = f"{company} Q{quarter} {year} Earnings"
            events.append(
                {
                    "name": name,
                    "start_date": event_date,
                    "end_date": event_date,
                    "organizer": company,
                    "url": f"https://finance.yahoo.com/quote/{symbol}/calendar",
                }
            )
        logger.info(f"{symbol} ({company}): {len(cal)} 筆 earnings")

    logger.info(f"Finnhub 總計:{len(events)} 筆 earnings")
    return events
