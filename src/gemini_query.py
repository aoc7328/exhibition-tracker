"""Gemini API 查詢模組 — 階段 A
用 Gemini 2.5 Flash + Google Search Grounding 查單一展覽當年的精確日期/官網/主辦單位
也提供「動態發現」功能,讓 Gemini 用關鍵字找出新興展覽
"""
from __future__ import annotations

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from .logger import get_logger
from .settings import GEMINI_API_KEY, GEMINI_MODEL_QUERY

logger = get_logger(__name__)


class ExhibitionInfo(BaseModel):
    """Gemini 回傳的結構化展覽資訊"""

    found: bool = Field(description="是否成功找到當年舉辦的具體資訊")
    start_date: str | None = Field(
        default=None,
        description="ISO 8601 開始日期 (YYYY-MM-DD),只有精確到日才填,否則 null",
    )
    end_date: str | None = Field(
        default=None,
        description="ISO 8601 結束日期 (YYYY-MM-DD),只有精確到日才填,否則 null",
    )
    organizer: str = Field(default="", description="主辦單位名稱")
    official_url: str = Field(default="", description="官方網站完整網址")
    location_summary: str = Field(default="", description="舉辦地點分類:臺灣 或 世界")
    notes: str = Field(default="", description="備註,例如為何無法確認日期")


class DiscoveryResult(BaseModel):
    """動態發現的新展覽清單"""

    new_exhibitions: list[str] = Field(
        default_factory=list,
        description="不在已知清單中的新興展覽官方名稱",
    )


def _build_query_prompt(exhibition_name: str, target_year: int) -> str:
    return (
        f"請使用 Google 搜尋,查找 {target_year} 年「{exhibition_name}」展覽的精確資訊。\n\n"
        f"硬性要求:\n"
        f"1. 必須是 {target_year} 年的場次,絕對不要混入其他年份。\n"
        f"2. 開始/結束日期必須精確到「日」(YYYY-MM-DD)。如果只有月份或大概時段,將 found 設為 false 並在 notes 說明。\n"
        f"3. 主辦單位填寫官方主辦組織。\n"
        f"4. 官方網址填當年場次的官方頁面;若僅有展覽主網域,亦可。\n"
        f"5. 地點分類為「臺灣」或「世界」二選一。\n\n"
        f"若搜尋結果不足以確定 {target_year} 年精確日期,將 found 設為 false。"
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def query_exhibition(exhibition_name: str, target_year: int) -> ExhibitionInfo:
    """查單一展覽當年精確資訊"""
    logger.info(f"查詢展覽: {exhibition_name} ({target_year})")

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = _build_query_prompt(exhibition_name, target_year)

    grounded = client.models.generate_content(
        model=GEMINI_MODEL_QUERY,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
        ),
    )
    raw_text = grounded.text or ""
    logger.debug(f"搜尋原文 (前 500 字): {raw_text[:500]}")

    extract_prompt = (
        f"以下是「{exhibition_name}」{target_year} 年的搜尋結果原文。\n"
        f"請依照 JSON schema 提取結構化資訊。注意 found 欄位的判斷規則。\n\n"
        f"---\n{raw_text}\n---"
    )
    structured = client.models.generate_content(
        model=GEMINI_MODEL_QUERY,
        contents=extract_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExhibitionInfo,
            temperature=0.0,
        ),
    )

    info = structured.parsed
    if not isinstance(info, ExhibitionInfo):
        raise RuntimeError(f"Gemini 回傳格式錯誤: {structured.text}")

    logger.info(
        f"查詢結果: found={info.found}, start={info.start_date}, end={info.end_date}"
    )
    return info


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def discover_new_exhibitions(
    industry_name: str,
    keywords: list[str],
    known_exhibitions: list[str],
    target_year: int,
) -> list[str]:
    """層次 2 動態發現:用關鍵字找不在 known_exhibitions 裡的新興展"""
    logger.info(f"發現新展: 產業={industry_name}, 年份={target_year}")

    client = genai.Client(api_key=GEMINI_API_KEY)
    keyword_str = ", ".join(keywords)
    known_str = "\n".join(f"- {n}" for n in known_exhibitions) or "(無)"

    prompt = (
        f"請使用 Google 搜尋,找出 {target_year} 年「{industry_name}」相關的重要產業展覽。\n\n"
        f"產業關鍵字: {keyword_str}\n\n"
        f"以下展覽已在追蹤清單,不需要重複列出:\n{known_str}\n\n"
        f"硬性要求:\n"
        f"1. 只回傳「不在已知清單」的新興或近年舉辦的重要展覽。\n"
        f"2. 必須是 {target_year} 年確實有舉辦的場次。\n"
        f"3. 只回傳官方展名,不要描述。\n"
        f"4. 若沒有新發現,new_exhibitions 回傳空陣列。"
    )

    grounded = client.models.generate_content(
        model=GEMINI_MODEL_QUERY,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    raw_text = grounded.text or ""

    extract_prompt = (
        f"以下是搜尋結果原文。請提取出「不在已知清單」的展覽官方名稱。\n\n"
        f"已知清單:\n{known_str}\n\n"
        f"原文:\n---\n{raw_text}\n---"
    )
    structured = client.models.generate_content(
        model=GEMINI_MODEL_QUERY,
        contents=extract_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DiscoveryResult,
            temperature=0.0,
        ),
    )

    result = structured.parsed
    if not isinstance(result, DiscoveryResult):
        raise RuntimeError(f"動態發現回傳格式錯誤: {structured.text}")

    new_names = [n for n in result.new_exhibitions if n not in known_exhibitions]
    logger.info(f"發現 {len(new_names)} 個新展: {new_names}")
    return new_names
