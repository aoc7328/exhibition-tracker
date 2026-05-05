"""南港展覽館爬蟲
來源: https://www.tainex.com.tw/2021/api/event (Vue SPA 後端 JSON API)
回傳 list,每筆含: id, title, btime/etime (Unix 秒), organizer, webpage, hall (1/2), category, location
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from ..logger import get_logger

logger = get_logger(__name__)

URL = "https://www.tainex.com.tw/2021/api/event"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_exhibitions() -> list[dict[str, Any]]:
    """從南港展覽館 JSON API 抓取展覽"""
    logger.info("抓取南港展覽館展覽列表")
    response = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    data = response.json()

    items = data.get("list", [])
    exhibitions: list[dict[str, Any]] = []
    for item in items:
        btime = item.get("btime")
        etime = item.get("etime")
        if not btime or not etime:
            continue

        try:
            start = datetime.fromtimestamp(btime).date()
            end = datetime.fromtimestamp(etime).date()
        except (ValueError, OSError, OverflowError):
            continue

        name = (item.get("title") or "").strip()
        if not name:
            continue

        hall = item.get("hall", 1)
        venue = f"南港{hall}館"

        exhibitions.append(
            {
                "name": name,
                "start_date": start,
                "end_date": end,
                "organizer": (item.get("organizer") or "").strip(),
                "url": (item.get("webpage") or "").strip(),
                "venue": venue,
                "category": item.get("category"),
            }
        )

    logger.info(f"南港抓到 {len(exhibitions)} 筆展覽")
    return exhibitions
