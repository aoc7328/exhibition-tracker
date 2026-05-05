"""Notion API 寫入模組(用 raw HTTP requests,不依賴 notion-client SDK)
特性:
- unique key (展名 + 起始年份) 做 upsert
- 比對核心欄位,完全相同則跳過 PATCH(不洗"最後更新"時間)
- update 時不動「狀態」欄位(尊重 Vincent 手動審核)
- create 時才寫入完整含 status 的初始值
"""
from __future__ import annotations

from datetime import date
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .logger import get_logger
from .models import Exhibition, Status
from .settings import NOTION_DATABASE_ID, NOTION_TOKEN

logger = get_logger(__name__)

API = "https://api.notion.com/v1"
_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    r = requests.post(f"{API}{path}", json=body, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _patch(path: str, body: dict[str, Any]) -> dict[str, Any]:
    r = requests.patch(f"{API}{path}", json=body, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _build_properties(ex: Exhibition, include_status: bool = True) -> dict[str, Any]:
    """組 Notion properties payload。update 時 include_status=False 保留手動審核"""
    props: dict[str, Any] = {
        "展覽名稱": {"title": [{"text": {"content": ex.name}}]},
        "地點": {"select": {"name": ex.location.value}},
        "信心度": {"select": {"name": ex.confidence.value}},
        "來源層次": {"select": {"name": ex.source.value}},
    }
    if include_status:
        props["狀態"] = {"select": {"name": ex.status.value}}
    if ex.start_date:
        date_obj: dict[str, Any] = {"start": ex.start_date.isoformat()}
        if ex.end_date and ex.end_date != ex.start_date:
            date_obj["end"] = ex.end_date.isoformat()
        props["開始日期"] = {"date": date_obj}
    if ex.end_date and ex.end_date != ex.start_date:
        props["結束日期"] = {"date": {"start": ex.end_date.isoformat()}}
    if ex.organizer:
        props["主辦單位"] = {"rich_text": [{"text": {"content": ex.organizer}}]}
    if ex.url:
        props["官方網址"] = {"url": ex.url}
    if ex.industries:
        props["產業類別"] = {"multi_select": [{"name": ind} for ind in ex.industries]}
    if ex.related_stocks:
        props["相關個股"] = {"rich_text": [{"text": {"content": ex.related_stocks}}]}
    return props


def _extract_text(prop: dict[str, Any], key: str) -> str:
    return "".join(t.get("plain_text", "") for t in (prop.get(key) or []))


def _extract_select_name(prop: dict[str, Any]) -> str | None:
    sel = prop.get("select")
    return sel.get("name") if sel else None


def _extract_multiselect(prop: dict[str, Any]) -> list[str]:
    return sorted([s.get("name", "") for s in (prop.get("multi_select") or [])])


def _extract_date_start(prop: dict[str, Any]) -> str | None:
    d = prop.get("date") or {}
    return d.get("start")


def _extract_date_end(prop: dict[str, Any]) -> str | None:
    d = prop.get("date") or {}
    return d.get("end")


def _existing_matches(ex: Exhibition, existing_props: dict[str, Any]) -> bool:
    """比對 ex 與 Notion 既有頁面核心欄位。狀態與相關個股不比對(Vincent 手動)"""

    if _extract_text(existing_props.get("展覽名稱", {}), "title") != ex.name:
        return False
    if _extract_select_name(existing_props.get("地點", {})) != ex.location.value:
        return False
    if _extract_select_name(existing_props.get("信心度", {})) != ex.confidence.value:
        return False
    if _extract_select_name(existing_props.get("來源層次", {})) != ex.source.value:
        return False
    if _extract_multiselect(existing_props.get("產業類別", {})) != sorted(ex.industries):
        return False
    if _extract_text(existing_props.get("主辦單位", {}), "rich_text") != ex.organizer:
        return False
    if (existing_props.get("官方網址", {}).get("url") or "") != ex.url:
        return False

    # 開始日期 (含 range end if present)
    start_prop = existing_props.get("開始日期", {})
    expected_start = ex.start_date.isoformat() if ex.start_date else None
    if _extract_date_start(start_prop) != expected_start:
        return False

    # 開始日期欄位的 range end
    expected_range_end = (
        ex.end_date.isoformat()
        if ex.end_date and ex.start_date and ex.end_date != ex.start_date
        else None
    )
    if _extract_date_end(start_prop) != expected_range_end:
        return False

    # 結束日期欄位 (獨立的)
    end_prop = existing_props.get("結束日期", {})
    expected_end = (
        ex.end_date.isoformat()
        if ex.end_date and ex.start_date and ex.end_date != ex.start_date
        else None
    )
    if _extract_date_start(end_prop) != expected_end:
        return False

    return True


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_existing(unique_key: str) -> tuple[str, dict[str, Any]] | None:
    """以 unique key (展名+年份) 找既有頁面,回傳 (page_id, properties) 或 None"""
    name, _, year_str = unique_key.rpartition(" ")
    if not name or not year_str.isdigit():
        return None
    year = int(year_str)
    response = _post(
        f"/databases/{NOTION_DATABASE_ID}/query",
        {
            "filter": {
                "and": [
                    {"property": "展覽名稱", "title": {"equals": name}},
                    {"property": "開始日期", "date": {"on_or_after": f"{year}-01-01"}},
                    {"property": "開始日期", "date": {"on_or_before": f"{year}-12-31"}},
                ]
            }
        },
    )
    results = response.get("results", [])
    if not results:
        return None
    return results[0]["id"], results[0].get("properties", {})


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def upsert_exhibition(ex: Exhibition, dry_run: bool = True) -> str:
    """upsert 一筆展覽。比對既有資料,完全相同則跳過。
    update 時不寫狀態欄位(保留 Vincent 手動審核)。"""
    if dry_run:
        logger.info(f"[DRY-RUN] {ex.unique_key} | {ex.status.value} | {ex.confidence.value}")
        return "dry-run"

    existing = find_existing(ex.unique_key)
    if existing:
        page_id, existing_props = existing
        if _existing_matches(ex, existing_props):
            logger.info(f"跳過(無變動): {ex.unique_key}")
            return page_id

        # status 處理規則:只允許「待確認 → 已確認」升級,其他不動 status
        existing_status = (existing_props.get("狀態", {}).get("select") or {}).get("name")
        is_upgrade = (
            existing_status == Status.PENDING.value
            and ex.status == Status.CONFIRMED
        )
        update_props = _build_properties(ex, include_status=is_upgrade)
        _patch(f"/pages/{page_id}", {"properties": update_props})
        msg = f"更新: {ex.unique_key}"
        if is_upgrade:
            msg += f" (升級 待確認 → 已確認)"
        logger.info(msg)
        return page_id

    # 新增時送完整 properties (含 status)
    create_props = _build_properties(ex, include_status=True)
    response = _post(
        "/pages",
        {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": create_props},
    )
    new_id = response["id"]
    logger.info(f"新增: {ex.unique_key} -> {new_id}")
    return new_id


def mark_expired_confirmed() -> int:
    """掃 Notion,把『已確認但結束日已過』的展自動標為『已過期』,回傳改動筆數"""
    today = date.today().isoformat()
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        body: dict[str, Any] = {
            "filter": {
                "and": [
                    {"property": "狀態", "select": {"equals": Status.CONFIRMED.value}},
                    {"property": "結束日期", "date": {"before": today}},
                ]
            }
        }
        if cursor:
            body["start_cursor"] = cursor
        response = _post(f"/databases/{NOTION_DATABASE_ID}/query", body)
        pages.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    count = 0
    for page in pages:
        page_id = page["id"]
        try:
            _patch(
                f"/pages/{page_id}",
                {"properties": {"狀態": {"select": {"name": Status.EXPIRED.value}}}},
            )
            count += 1
        except Exception as e:
            logger.exception(f"標已過期失敗 page={page_id}: {e}")
    return count


def list_confirmed_future() -> list[dict[str, Any]]:
    """讀回所有狀態=已確認且結束日期 ≥ 今天的展(供 .ics 產生器用)"""
    today = date.today().isoformat()
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        body: dict[str, Any] = {
            "filter": {
                "and": [
                    {"property": "狀態", "select": {"equals": Status.CONFIRMED.value}},
                    {"property": "結束日期", "date": {"on_or_after": today}},
                ]
            }
        }
        if cursor:
            body["start_cursor"] = cursor
        response = _post(f"/databases/{NOTION_DATABASE_ID}/query", body)
        results.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return results
