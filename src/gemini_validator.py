"""Gemini API 複核模組 — 階段 B
用 Gemini 2.5 Pro 獨立 session 驗證查詢結果合理性
+ 程式自身 sanity check(年份比對、未來性、起訖日合理性)
"""
from __future__ import annotations

from datetime import date, datetime

from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

from .logger import get_logger
from .settings import GEMINI_API_KEY, GEMINI_MODEL_VALIDATE

logger = get_logger(__name__)


class ValidationResult(BaseModel):
    is_valid_year: bool = Field(description="日期是否確實落在指定年份")
    is_future: bool = Field(description="日期是否在今天之後")
    is_precise: bool = Field(description="是否為精確起訖日(年-月-日),不是粗略月份")
    confidence_high: bool = Field(description="三項皆通過,且 AI 常識判斷該展覽確實在該年舉辦")
    reason: str = Field(default="", description="若任一項失敗,說明理由")


def _program_sanity_check(
    start: date | None,
    end: date | None,
    target_year: int,
) -> tuple[bool, str]:
    """免成本的程式自身合理性檢查,擋掉低級錯誤"""
    today = datetime.now().date()
    if start is None or end is None:
        return False, "日期不完整(缺起或訖)"
    if start.year != target_year:
        return False, f"開始年份 {start.year} ≠ 目標 {target_year}"
    if end.year not in (target_year, target_year + 1):
        return False, f"結束年份 {end.year} 與目標 {target_year} 不符"
    if end < start:
        return False, "結束日早於開始日"
    if end < today:
        return False, "活動已結束"
    return True, ""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def validate_exhibition(
    exhibition_name: str,
    target_year: int,
    start_date: date | None,
    end_date: date | None,
) -> ValidationResult:
    """獨立 session 複核查詢結果"""
    logger.info(f"複核展覽: {exhibition_name} ({target_year})")

    sanity_ok, sanity_reason = _program_sanity_check(start_date, end_date, target_year)
    if not sanity_ok:
        logger.warning(f"程式 sanity check 失敗: {sanity_reason}")
        return ValidationResult(
            is_valid_year=False,
            is_future=False,
            is_precise=False,
            confidence_high=False,
            reason=f"程式 sanity check: {sanity_reason}",
        )

    assert start_date is not None and end_date is not None  # sanity_ok 已保證
    today = datetime.now().date()

    prompt = (
        f"獨立判斷:某個查詢結果聲稱「{exhibition_name}」在 {target_year} 年的舉辦日期為 "
        f"{start_date.isoformat()} 至 {end_date.isoformat()}。\n"
        f"今天是 {today.isoformat()}。\n\n"
        f"請依下列四項條件判斷:\n"
        f"1. is_valid_year: 該日期確實在 {target_year} 年(不是 {target_year - 1} 年的舊資料)?\n"
        f"2. is_future: 該日期區間在今天之後(尚未發生)?\n"
        f"3. is_precise: 該日期為精確起訖日(年-月-日),不是粗略月份?\n"
        f"4. confidence_high: 上述三項皆通過,且根據你的常識,該展覽確實在該年舉辦,可標為高信心度?\n\n"
        f"請依 schema 回傳判斷結果,任一項失敗時請在 reason 欄位說明原因。"
    )

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL_VALIDATE,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ValidationResult,
            temperature=0.0,
        ),
    )

    result = response.parsed
    if not isinstance(result, ValidationResult):
        raise RuntimeError(f"複核回傳格式錯誤: {response.text}")

    logger.info(
        f"複核結果: confidence_high={result.confidence_high}, reason={result.reason}"
    )
    return result
