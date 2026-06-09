"""總體經濟數據行事曆 — 從「財經 M 平方 全球財經日曆」ICS 抓重要美國數據

設計原則:
- 只取 Vincent 指定的「核心四項」會影響美股的美國總經數據:
  FOMC 利率決議、非農就業 NFP、CPI、PCE(其餘指標刻意不收,維持月曆乾淨)。
- 排除高頻雜訊:每週初領失業金、原油庫存、農業部供需報告。
- 排除個股財報(營收)— 那屬「企業」類別,另由 Finnhub earnings scraper 處理。
- US-only:SUMMARY 必須以「美國」開頭,避免抓到英國/歐元區/中國同名數據。
- 同一天同一指標只留一筆(M 平方 CPI 有「年增率」「NSA 年增率」兩條,去重)。

日期採 ICS DTSTART 的「日」(UTC);美國數據多為美東上午發布,UTC 當日 = 美國發布日。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import requests

from ..logger import get_logger
from ..settings import MACRO_ICS_URL

logger = get_logger(__name__)

# (SUMMARY 內含關鍵字, 顯示名稱) — 由上而下比對,取第一個命中。
# 只追蹤 Vincent 指定的「核心四項」會影響美股的美國總經數據:
#   FOMC 利率決議、非農就業 NFP、CPI、PCE。
# 其餘(PPI/ISM/零售/GDP/ADP/會議紀要…)刻意不收,維持月曆乾淨。
MACRO_KEYWORDS: list[tuple[str, str]] = [
    ("聯準會利率決策", "美國 FOMC 利率決議"),
    ("非農就業人數", "美國 非農就業 NFP"),
    ("消費者物價指數", "美國 CPI 消費者物價"),
    ("個人消費支出物價指數", "美國 PCE 物價指數"),
]

_MM_URL_RE = re.compile(r"https?://www\.macromicro\.me/\S+")
_DTSTART_RE = re.compile(r"\nDTSTART[^:\n]*:(\d{8})")
_SUMMARY_RE = re.compile(r"\nSUMMARY:(.*)")
_DESC_RE = re.compile(r"\nDESCRIPTION:(.*)")
DEFAULT_URL = "https://www.macromicro.me/calendars/me"


def _unfold(text: str) -> str:
    """ICS 行折疊還原:接續行(以空白或 tab 開頭)併回上一行"""
    return re.sub(r"\r?\n[ \t]", "", text)


def _classify(summary: str) -> str | None:
    """SUMMARY → 顯示名稱;非「美國重要總經」回 None"""
    if not summary.startswith("美國"):
        return None
    for kw, display in MACRO_KEYWORDS:
        if kw in summary:
            return display
    return None


def _horizon(today: date, months_ahead: int) -> date:
    """回傳 today 之後第 N 個月的 1 號(只抓到這之前的事件,避免抓進太遙遠的零星排程)"""
    total = today.month - 1 + months_ahead
    return date(today.year + total // 12, total % 12 + 1, 1)


def fetch_macro_events(months_ahead: int = 14) -> list[dict[str, Any]]:
    """抓 M 平方 ICS → 過濾重要美國總經 → 回傳未來事件(已去重、依日期排序)"""
    today = date.today()
    horizon = _horizon(today, months_ahead)

    try:
        resp = requests.get(MACRO_ICS_URL, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.exception(f"抓 M 平方 ICS 失敗: {e}")
        return []

    text = _unfold(resp.text)
    blocks = text.split("BEGIN:VEVENT")[1:]

    seen: set[tuple[str, str]] = set()
    events: list[dict[str, Any]] = []
    for b in blocks:
        sm = _SUMMARY_RE.search(b)
        dm = _DTSTART_RE.search(b)
        if not sm or not dm:
            continue
        display = _classify(sm.group(1).strip())
        if not display:
            continue
        try:
            ev_date = datetime.strptime(dm.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if ev_date < today or ev_date >= horizon:
            continue
        key = (ev_date.isoformat(), display)
        if key in seen:
            continue
        seen.add(key)

        dsc = _DESC_RE.search(b)
        url_m = _MM_URL_RE.search(dsc.group(1)) if dsc else None
        events.append(
            {
                "name": f"{display}（{ev_date.month}/{ev_date.day}）",
                "start_date": ev_date,
                "end_date": ev_date,
                "organizer": "財經 M 平方",
                "url": url_m.group(0) if url_m else DEFAULT_URL,
            }
        )

    events.sort(key=lambda e: e["start_date"])
    logger.info(
        f"總經行事曆: 命中 {len(events)} 筆未來美國重要數據(去重後,horizon {horizon})"
    )
    return events
