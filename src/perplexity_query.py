"""Perplexity Sonar 查詢模組 — 即時 web 搜尋 + 引用

複用 Vincent 已購買的 Perplexity API。分工:
  - Perplexity 負責「搜尋 / 發現 / 查精確日期」(內建即時 web search + 來源引用)
  - Claude 負責「整理 / 複核」(沿用 src/claude_validator.validate_exhibition)

介面刻意與 src/claude_query 對齊(query_exhibition / discover_new_exhibitions),
因此可在 scripts/update_all.py 用 --engine 直接切換,不動其他流程。
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .logger import get_logger
from .settings import PERPLEXITY_API_KEY, PERPLEXITY_MODEL

logger = get_logger(__name__)

API_URL = "https://api.perplexity.ai/chat/completions"
TIMEOUT = 120

_SYSTEM = (
    "你是嚴謹的展會與企業活動研究助理。只根據可查證的即時網路資料回答,"
    "不要臆測或混入其他年份。務必只回傳指定格式的 JSON,不要任何多餘文字。"
)

_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "start_date": {"type": "string"},
        "end_date": {"type": "string"},
        "organizer": {"type": "string"},
        "official_url": {"type": "string"},
        "location_summary": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["found"],
}

_DISCOVER_SCHEMA = {
    "type": "object",
    "properties": {
        "new_exhibitions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["new_exhibitions"],
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=4, min=8, max=60),
    reraise=True,
)
def _call(prompt: str, schema: dict[str, Any] | None = None) -> str:
    if not PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY 未設定")
    body: dict[str, Any] = {
        "model": PERPLEXITY_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    if schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"schema": schema},
        }
    resp = requests.post(
        API_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Perplexity API {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict[str, Any]:
    """從回應抽 JSON(response_format 已盡量保證,但仍防御性解析)"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise RuntimeError(f"無法解析 Perplexity JSON: {text[:300]}")


def query_exhibition(name: str, year: int, taiwan_only: bool = False) -> dict[str, Any]:
    """查單一展覽/活動當年精確資訊。回傳 dict,介面同 claude_query.query_exhibition"""
    logger.info(
        f"查詢 (Perplexity): {name} ({year}){' [TW only]' if taiwan_only else ''}"
    )
    taiwan_constraint = (
        "\n【地區限制】此類別只追蹤臺灣舉辦的場次。"
        "若該活動在臺灣以外舉辦,將 found 設為 false 並在 notes 註明「非臺灣場」。\n"
        if taiwan_only
        else ""
    )
    prompt = (
        f"查 {year} 年「{name}」的精確資訊。\n"
        f"{taiwan_constraint}\n"
        f"【投資相關性 + 規模篩選】(任一不符 → found=false 並於 notes 說明):\n"
        f"A. 能直接或間接影響台股相關產業,或影響美股龍頭"
        f"(NVIDIA/AMD/Apple/TSLA/Meta/MSFT 等)連帶台股供應鏈。\n"
        f"B. 規模門檻(至少一項):展商≥100 / 有官方記者會或業界名人 keynote / "
        f"有國際大廠或上市櫃公司主辦或冠名。\n\n"
        f"【硬性要求】(篩選過但下列任一不符也設 found=false):\n"
        f"1. 必須是 {year} 年的場次,絕不混入其他年份。\n"
        f"2. 開始/結束日期精確到日 (YYYY-MM-DD);若只有月份或大概時段 → found=false。\n"
        f"3. organizer 填官方主辦組織名稱。\n"
        f"4. official_url 填當年場次官方頁面(或官方主網域)。\n"
        f"5. location_summary 為「臺灣」或「世界」二選一(在臺灣辦=臺灣,其餘=世界)。\n\n"
        f"只回傳一個 JSON 物件,格式:\n"
        f'{{"found": true, "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", '
        f'"organizer": "...", "official_url": "...", "location_summary": "臺灣", "notes": ""}}'
    )
    out = _call(prompt, schema=_QUERY_SCHEMA)
    info = _extract_json(out)
    logger.info(f"查詢結果: found={info.get('found')} start={info.get('start_date')}")
    return info


def discover_new_exhibitions(
    industry_name: str,
    keywords: list[str],
    known_exhibitions: list[str],
    target_year: int,
    taiwan_only: bool = False,
) -> list[str]:
    """用關鍵字找出不在 known_exhibitions 的新興中大型展/活動。介面同 claude_query"""
    logger.info(
        f"發現新展 (Perplexity): {industry_name}"
        f"{' [TW only]' if taiwan_only else ''}"
    )
    keyword_str = ", ".join(keywords)
    known_str = "\n".join(f"- {n}" for n in known_exhibitions) or "(無)"
    region_constraint = (
        "D. 【地區限制】此類別只追蹤【臺灣舉辦】的展(台北/台中/高雄/南港等)。"
        "國外辦的同類展不要列。\n"
        if taiwan_only
        else ""
    )
    prompt = (
        f"找出 {target_year} 年「{industry_name}」相關的「中大型」產業展覽或重要活動。\n\n"
        f"產業關鍵字: {keyword_str}\n\n"
        f"已知、不需重複列出的:\n{known_str}\n\n"
        f"【篩選準則】(必須全部符合):\n"
        f"A. 能影響台股或美股龍頭(NVIDIA/AMD/Apple/TSLA/Meta/MSFT)股價走勢。\n"
        f"B. 規模門檻:展商≥100 / 官方記者會 / 名人 keynote / 上市櫃公司主辦或贊助 — 至少一項。\n"
        f"C. 不要列入:小型 / 純學術會議 / 純消費展 / 區域性小展。\n"
        f"{region_constraint}\n"
        f"硬性要求:1) 只回「不在已知清單」的新展;2) 必須是 {target_year} 年確實舉辦的場次;"
        f"3) 只回官方展名,不要描述。\n\n"
        f'只回傳 JSON:{{"new_exhibitions": ["展名 1", "展名 2"]}}'
    )
    out = _call(prompt, schema=_DISCOVER_SCHEMA)
    result = _extract_json(out)
    new_names = [
        n for n in result.get("new_exhibitions", []) if n not in known_exhibitions
    ]
    logger.info(f"發現 {len(new_names)} 個新展")
    return new_names
