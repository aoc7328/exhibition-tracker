"""台北世貿信義一館爬蟲
來源: https://www.twtc.com.tw/exhibition.aspx?p=menu1
結構: ASP.NET 頁面,標準 HTML table,UTF-8 編碼
每筆資料: 展出日期 / 展覽名稱(含 a 連結) / 主辦單位 / 電話 / 展覽館別
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

from ..logger import get_logger

logger = get_logger(__name__)

URL = "https://www.twtc.com.tw/exhibition.aspx?p=menu1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _parse_date_range(s: str, default_year: int) -> tuple[date | None, date | None]:
    """解析 '04/03 ~ 04/06' 為 (start, end)"""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})\s*~\s*(\d{1,2})/(\d{1,2})", s)
    if not m:
        return None, None
    sm, sd, em, ed = (int(g) for g in m.groups())
    try:
        start = date(default_year, sm, sd)
        # 跨年(12 月開始 1 月結束):結束日的年份 +1
        end_year = default_year + 1 if em < sm else default_year
        end = date(end_year, em, ed)
        return start, end
    except ValueError:
        return None, None


def fetch_exhibitions(year: int) -> list[dict[str, Any]]:
    """從 TWTC 抓取展覽列表
    注意: TWTC 用 ASP.NET PostBack 切年份,GET 預設拿到當前頁面顯示的展。
    若 year != 當年,本函式仍以 GET 抓 default,但 _parse_date_range 用該 year 補日期。
    """
    logger.info(f"抓取 TWTC 展覽列表 (year={year})")
    response = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table", class_="date_table")
    if not tables:
        logger.warning("找不到 date_table,可能 HTML 結構變動")
        return []

    # Table 0 通常是「全部」(5 欄,含展覽館別); Table 1+ 是分館(4 欄)
    main = tables[0]
    rows = main.find_all("tr")[1:]  # 跳過 header

    exhibitions: list[dict[str, Any]] = []
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        date_str = cells[0].get_text(strip=True)
        name_cell = cells[1]
        name = name_cell.get_text(strip=True)
        # 移除 "more" 後綴(連結文字)
        if name.endswith("more"):
            name = name[:-4].strip()
        link = name_cell.find("a")
        url = (link.get("href") or "").strip() if link else ""

        organizer = cells[2].get_text(strip=True)
        venue = cells[4].get_text(strip=True) if len(cells) >= 5 else ""

        start, end = _parse_date_range(date_str, year)
        if not name or not start:
            continue

        exhibitions.append(
            {
                "name": name,
                "start_date": start,
                "end_date": end or start,
                "organizer": organizer,
                "url": url,
                "venue": venue,
            }
        )

    logger.info(f"TWTC 抓到 {len(exhibitions)} 筆展覽")
    return exhibitions
