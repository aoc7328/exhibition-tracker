"""Notion API 寫入模組
用 unique key (展名 + 起始年份) 做 upsert,避免重複寫入
支援 dry-run 模式(預設):印出將寫入內容,不實際寫
"""
from __future__ import annotations

from datetime import date
from typing import Any

from notion_client import Client
from tenacity import retry, stop_after_attempt, wait_exponential

from .logger import get_logger
from .models import Exhibition, Status
from .settings import NOTION_DATABASE_ID, NOTION_TOKEN

logger = get_logger(__name__)

_client = Client(auth=NOTION_TOKEN)


def _build_properties(ex: Exhibition) -> dict[str, Any]:
    props: dict[str, Any] = {
        "展覽名稱": {"title": [{"text": {"content": ex.name}}]},
        "地點": {"select": {"name": ex.location.value}},
        "信心度": {"select": {"name": ex.confidence.value}},
        "來源層次": {"select": {"name": ex.source.value}},
        "狀態": {"select": {"name": ex.status.value}},
    }
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
        props["產業類別"] = {
            "multi_select": [{"name": ind} for ind in ex.industries]
        }
    if ex.related_stocks:
        props["相關個股"] = {
            "rich_text": [{"text": {"content": ex.related_stocks}}]
        }
    return props


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def find_existing(unique_key: str) -> str | None:
    """以 unique key (展名+年份) 找既有頁面,回傳 page_id 或 None"""
    name, _, year_str = unique_key.rpartition(" ")
    if not name or not year_str.isdigit():
        return None
    year = int(year_str)
    year_start = date(year, 1, 1).isoformat()
    year_end = date(year, 12, 31).isoformat()

    response = _client.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "and": [
                {"property": "展覽名稱", "title": {"equals": name}},
                {"property": "開始日期", "date": {"on_or_after": year_start}},
                {"property": "開始日期", "date": {"on_or_before": year_end}},
            ]
        },
    )
    results = response.get("results", [])
    if results:
        return results[0]["id"]
    return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def upsert_exhibition(ex: Exhibition, dry_run: bool = True) -> str:
    """upsert 一筆展覽。預設 dry-run:只印不寫"""
    props = _build_properties(ex)

    if dry_run:
        logger.info(f"[DRY-RUN] {ex.unique_key} | {ex.status.value} | {ex.confidence.value}")
        for k, v in props.items():
            logger.debug(f"    {k}: {v}")
        return "dry-run"

    existing_id = find_existing(ex.unique_key)
    if existing_id:
        _client.pages.update(page_id=existing_id, properties=props)
        logger.info(f"更新: {ex.unique_key}")
        return existing_id

    response = _client.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=props,
    )
    new_id = response["id"]
    logger.info(f"新增: {ex.unique_key} → {new_id}")
    return new_id


def list_confirmed_future() -> list[dict[str, Any]]:
    """讀回所有狀態=已確認且結束日期 ≥ 今天的展(供 .ics 產生器用)"""
    today = date.today().isoformat()
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "database_id": NOTION_DATABASE_ID,
            "filter": {
                "and": [
                    {"property": "狀態", "select": {"equals": Status.CONFIRMED.value}},
                    {"property": "結束日期", "date": {"on_or_after": today}},
                ]
            },
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        response = _client.databases.query(**kwargs)
        results.extend(response.get("results", []))
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")
    return results
