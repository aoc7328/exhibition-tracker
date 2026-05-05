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


def _page_to_meta(page: dict[str, Any]) -> "Any":
    """從 Notion page 提取 deduper.ExhibitionMeta"""
    from .deduper import ExhibitionMeta

    props = page.get("properties", {})
    start_str = _extract_date_start(props.get("開始日期", {}))
    end_via_range = _extract_date_end(props.get("開始日期", {}))
    end_separate = _extract_date_start(props.get("結束日期", {}))
    end_str = end_via_range or end_separate or start_str

    try:
        start = date.fromisoformat(start_str[:10]) if start_str else None
        end = date.fromisoformat(end_str[:10]) if end_str else start
    except (ValueError, TypeError):
        start = end = None

    return ExhibitionMeta(
        name=_extract_text(props.get("展覽名稱", {}), "title"),
        start_date=start,
        end_date=end,
        location=_extract_select_name(props.get("地點", {})) or "",
        organizer=_extract_text(props.get("主辦單位", {}), "rich_text"),
        url=props.get("官方網址", {}).get("url") or "",
    )


def _exhibition_to_meta(ex: Exhibition) -> "Any":
    """從 Exhibition dataclass 提取 deduper.ExhibitionMeta"""
    from .deduper import ExhibitionMeta

    return ExhibitionMeta(
        name=ex.name,
        start_date=ex.start_date,
        end_date=ex.end_date,
        location=ex.location.value,
        organizer=ex.organizer,
        url=ex.url,
    )


def list_pages_by_year(year: int) -> list[dict[str, Any]]:
    """撈某年所有展(用開始日期 filter)"""
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        body: dict[str, Any] = {
            "filter": {
                "and": [
                    {"property": "開始日期", "date": {"on_or_after": f"{year}-01-01"}},
                    {"property": "開始日期", "date": {"on_or_before": f"{year}-12-31"}},
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
    return pages


def _update_existing(page_id: str, ex: Exhibition, existing_props: dict[str, Any]) -> str:
    """共用 update 邏輯:merge industries + 比對 + 條件升級 status"""
    existing_industries = _extract_multiselect(existing_props.get("產業類別", {}))
    merged_industries = sorted(set(existing_industries) | set(ex.industries))
    if merged_industries != sorted(ex.industries):
        ex.industries = merged_industries

    if _existing_matches(ex, existing_props):
        logger.info(f"跳過(無變動): {ex.unique_key}")
        return page_id

    existing_status = (existing_props.get("狀態", {}).get("select") or {}).get("name")
    is_upgrade = (
        existing_status == Status.PENDING.value
        and ex.status == Status.CONFIRMED
    )
    update_props = _build_properties(ex, include_status=is_upgrade)
    _patch(f"/pages/{page_id}", {"properties": update_props})
    msg = f"更新: {ex.unique_key}"
    if is_upgrade:
        msg += " (升級 待確認 → 已確認)"
    logger.info(msg)
    return page_id


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def upsert_exhibition(ex: Exhibition, dry_run: bool = True) -> str:
    """upsert 一筆展覽。

    流程:
    1. 精確 unique key (展名+年份) 找到 → 走 update flow
    2. 找不到 → fuzzy 匹配當年展,Claude 確認,找到 → 走 update flow
    3. 都沒 → 真的新增
    """
    if dry_run:
        logger.info(f"[DRY-RUN] {ex.unique_key} | {ex.status.value} | {ex.confidence.value}")
        return "dry-run"

    # 1. 精確 unique key
    existing = find_existing(ex.unique_key)
    if existing:
        page_id, existing_props = existing
        return _update_existing(page_id, ex, existing_props)

    # 2. 精確找不到 → fuzzy match (僅當有 start_date 時)
    if ex.start_date:
        try:
            year_pages = list_pages_by_year(ex.start_date.year)
        except Exception as e:
            logger.warning(f"撈當年展失敗,跳過 fuzzy match: {e}")
            year_pages = []

        if year_pages:
            from .deduper import find_likely_match

            new_meta = _exhibition_to_meta(ex)
            candidates = [(_page_to_meta(p), p) for p in year_pages]
            match = find_likely_match(new_meta, candidates)
            if match is not None:
                page = match
                return _update_existing(
                    page["id"], ex, page.get("properties", {})
                )

    # 3. 真的新增
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
