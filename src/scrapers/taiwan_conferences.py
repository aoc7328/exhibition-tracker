"""台股法說會(投資人說明會)真實排程 — 公開資訊觀測站 MOPS『法人說明會一覽表』

取代舊的「每月 10 日推算月營收」(10 號不一定是工作日,推算會落在假日 → 不可靠)。
法說會是公司「事先申報、會公告」的真排程,從 MOPS 直接抓得到。

- 追蹤公司清單從 config/taiwan_companies.yaml 動態讀 → 可隨時增刪,不寫死。
- 端點:POST https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1
  參數 TYPEK=sii(上市)/otc(上櫃)、year=民國年、month 空字串=整年。
  (舊網域 mops.twse.com.tw 已 302 失效,2024 改版後改用 mopsov.twse.com.tw)
- 回傳 HTML 表格:公司代號 / 簡稱 / 預定日期(民國) / 時間 / 形式或地點。
- 只回未來場次;同公司同日去重(同一天跑多家券商的 roadshow 併成一筆)。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

from ..logger import get_logger
from .taiwan_monthly import load_companies  # 共用同一份 yaml 公司清單

logger = get_logger(__name__)

AJAX_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
PAGE_URL = "https://mopsov.twse.com.tw/mops/web/t100sb02_1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_ROC_RE = re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})")
_TICKER_RE = re.compile(r"\d{4,6}")


def _roc_to_date(s: str) -> date | None:
    """民國日期字串 '115/03/23' → date(2026, 3, 23)"""
    m = _ROC_RE.match(s.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _fetch(typek: str, roc_year: int) -> str:
    resp = requests.post(
        AJAX_URL,
        data={
            "encodeURIComponent": 1,
            "step": 1,
            "firstin": 1,
            "off": 1,
            "TYPEK": typek,
            "year": roc_year,
            "month": "",  # 整年
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def _parse(html: str, tracked: dict[str, dict[str, Any]]) -> list[tuple[str, date]]:
    """從一覽表 HTML 抽出 (ticker, 日期),只留 tracked 清單內的公司"""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, date]] = []
    for tr in soup.find_all("tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) < 3:
            continue
        ticker = tds[0]
        if not _TICKER_RE.fullmatch(ticker) or ticker not in tracked:
            continue
        d = _roc_to_date(tds[2])
        if d:
            out.append((ticker, d))
    return out


def fetch_conferences() -> list[dict[str, Any]]:
    """抓 tracked 公司的未來法說會(MOPS 真排程,同公司同日去重)"""
    companies = load_companies()
    tracked = {c["ticker"]: c for c in companies if c.get("ticker")}
    if not tracked:
        logger.info("taiwan_companies.yaml 無公司,跳過法說會抓取")
        return []

    today = date.today()
    roc = today.year - 1911

    rows: list[tuple[str, date]] = []
    for typek in ("sii", "otc"):  # 上市 + 上櫃(隨清單彈性)
        for yr in (roc, roc + 1):  # 當年 + 隔年(隔年通常未排,抓到就賺到)
            try:
                rows += _parse(_fetch(typek, yr), tracked)
            except Exception as e:
                logger.warning(f"MOPS 法說會抓取失敗 TYPEK={typek} year={yr}: {e}")

    seen: set[tuple[str, str]] = set()
    events: list[dict[str, Any]] = []
    for ticker, d in sorted(rows, key=lambda x: x[1]):
        if d < today:
            continue
        key = (ticker, d.isoformat())
        if key in seen:
            continue
        seen.add(key)
        c = tracked[ticker]
        events.append(
            {
                "name": f"{c['name']}({ticker}) 法說會（{d.month}/{d.day}）",
                "start_date": d,
                "end_date": d,
                "organizer": c["name"],
                "url": PAGE_URL,
                "extra_industries": c.get("extra_industries") or [],
            }
        )

    logger.info(
        f"台股法說會: {len(tracked)} 家追蹤,未來 {len(events)} 場(MOPS 真排程,已去重)"
    )
    return events
