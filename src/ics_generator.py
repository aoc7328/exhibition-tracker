"""ICS (iCalendar) 產生器
從 Notion 讀「狀態 = 已確認」且「結束日 ≥ 今天」的展覽,生成 .ics 檔
事件只含展覽名稱 + 起訖日期(全日活動)— Vincent 規格:不輸出地點、不輸出產業類別
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ics import Calendar, Event

from .logger import get_logger
from .notion_writer import list_confirmed_future
from .settings import ICS_OUTPUT

logger = get_logger(__name__)


def _parse_notion_date(date_property: dict[str, Any] | None, key: str = "start") -> date | None:
    if not date_property or not date_property.get("date"):
        return None
    raw = date_property["date"].get(key)
    if not raw:
        return None
    return date.fromisoformat(raw[:10])


def _build_event_from_notion(page: dict[str, Any]) -> Event | None:
    props = page.get("properties", {})
    title_blocks = props.get("展覽名稱", {}).get("title", [])
    if not title_blocks:
        return None
    name = "".join(b.get("plain_text", "") for b in title_blocks).strip()
    if not name:
        return None

    start_prop = props.get("開始日期")
    start = _parse_notion_date(start_prop, "start")
    end = _parse_notion_date(start_prop, "end")
    if end is None:
        end_prop = props.get("結束日期")
        end = _parse_notion_date(end_prop, "start")
    if start and end is None:
        end = start
    if not start:
        return None

    event = Event()
    event.name = name
    event.begin = start.isoformat()
    if end and end != start:
        event.end = (end + timedelta(days=1)).isoformat()
    event.make_all_day()
    return event


def generate_ics() -> Path:
    """從 Notion 讀資料,寫 .ics 到 ICS_OUTPUT,回傳路徑"""
    pages = list_confirmed_future()
    logger.info(f"從 Notion 讀到 {len(pages)} 筆已確認且未過期展覽")

    cal = Calendar()
    cal.creator = "exhibition-tracker"
    success = 0
    for page in pages:
        try:
            event = _build_event_from_notion(page)
            if event:
                cal.events.add(event)
                success += 1
        except Exception as e:
            logger.warning(f"事件建構失敗: {e}")

    ICS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(ICS_OUTPUT, "w", encoding="utf-8", newline="") as f:
        f.writelines(cal.serialize_iter())

    logger.info(f"已寫入 {success} 個事件到 {ICS_OUTPUT}")
    return ICS_OUTPUT
