"""Claude CLI 複核模組 — 階段 B
獨立 session 驗證查詢結果合理性 + 程式 sanity check
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
from datetime import date, datetime
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from .logger import get_logger

logger = get_logger(__name__)

CLI_TIMEOUT = 600
IS_WINDOWS = platform.system() == "Windows"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=10, min=30, max=300),
    reraise=True,
)
def _call_claude(prompt: str) -> str:
    flags = ["-p", "--dangerously-skip-permissions"]
    cmd = ["cmd.exe", "/c", "claude", *flags] if IS_WINDOWS else ["claude", *flags]
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI 失敗: {result.stderr[:500]}")
    return result.stdout


def _extract_json(text: str) -> dict[str, Any]:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise RuntimeError(f"無法解析 Claude 輸出 JSON: {text[:300]}")


def _program_sanity_check(
    start: date | None,
    end: date | None,
    target_year: int,
) -> tuple[bool, str]:
    today = datetime.now().date()
    if start is None or end is None:
        return False, "日期不完整"
    if start.year != target_year:
        return False, f"開始年份 {start.year} ≠ 目標 {target_year}"
    if end.year not in (target_year, target_year + 1):
        return False, f"結束年份 {end.year} 與目標不符"
    if end < start:
        return False, "結束日早於開始日"
    if end < today:
        return False, "活動已結束"
    # 展期合理性:大部分展覽 ≤ 7 天,大型國際車展(Auto Shanghai/北京車展/Detroit
    # Auto Show)實際 9~11 天屬正常範圍,> 14 天必為 Claude 把多個活動串在一起
    duration_days = (end - start).days
    if duration_days > 14:
        return False, f"展期過長 ({duration_days} 天),可能誤把多個獨立活動的日期串在一起"
    return True, ""


def validate_exhibition(
    name: str,
    target_year: int,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    """獨立 session 複核查詢結果"""
    logger.info(f"複核展覽 (Claude): {name} ({target_year})")

    sanity_ok, sanity_reason = _program_sanity_check(start_date, end_date, target_year)
    if not sanity_ok:
        logger.warning(f"sanity check 失敗: {sanity_reason}")
        return {
            "is_valid_year": False,
            "is_future": False,
            "is_precise": False,
            "confidence_high": False,
            "reason": f"程式 sanity: {sanity_reason}",
        }

    assert start_date is not None and end_date is not None
    today = datetime.now().date()
    prompt = (
        f"獨立判斷:某查詢結果聲稱「{name}」在 {target_year} 年舉辦日期是 "
        f"{start_date.isoformat()} 至 {end_date.isoformat()}。\n"
        f"今天是 {today.isoformat()}。\n\n"
        f"請依四項條件判斷,可使用 WebSearch 驗證:\n"
        f"1. is_valid_year: 該日期確實在 {target_year} 年(不是 {target_year - 1} 年舊資料)?\n"
        f"2. is_future: 該日期區間在今天之後(尚未發生)?\n"
        f"3. is_precise: 該日期為精確起訖日(年-月-日),不是粗略月份?\n"
        f"4. confidence_high: 三項皆通過,且常識上該展確實在該年舉辦,可標高信心度?\n\n"
        f"請僅回應 JSON,格式:\n"
        f"```json\n"
        f"{{\n"
        f'  "is_valid_year": true,\n'
        f'  "is_future": true,\n'
        f'  "is_precise": true,\n'
        f'  "confidence_high": true,\n'
        f'  "reason": ""\n'
        f"}}\n"
        f"```"
    )
    out = _call_claude(prompt)
    result = _extract_json(out)
    logger.info(f"複核: confidence_high={result.get('confidence_high')} reason={result.get('reason')}")
    return result
