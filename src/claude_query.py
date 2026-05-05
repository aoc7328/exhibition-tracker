"""Claude CLI 查詢模組 — 階段 A
透過 Claude Code CLI subprocess 呼叫 + 內建 WebSearch 工具
複用 Vincent 的 Claude Pro 訂閱,不需要額外 API 費用
"""
from __future__ import annotations

import json
import platform
import re
import subprocess
from typing import Any

from .logger import get_logger

logger = get_logger(__name__)

CLI_TIMEOUT = 600
IS_WINDOWS = platform.system() == "Windows"


def _call_claude(prompt: str) -> str:
    """呼叫 claude -p 一次性查詢,prompt 從 stdin"""
    cmd = ["cmd.exe", "/c", "claude", "-p"] if IS_WINDOWS else ["claude", "-p"]
    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Claude CLI timeout {CLI_TIMEOUT}s") from e
    except FileNotFoundError as e:
        raise RuntimeError("找不到 claude 命令,請確認 Claude Code CLI 已安裝") from e

    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI 失敗 (rc={result.returncode}): {result.stderr[:500]}"
        )
    return result.stdout


def _extract_json(text: str) -> dict[str, Any]:
    """從 Claude 輸出抽取 JSON 物件"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise RuntimeError(f"無法解析 Claude 輸出 JSON: {text[:300]}")


def query_exhibition(name: str, year: int) -> dict[str, Any]:
    """查單一展覽當年精確資訊"""
    logger.info(f"查詢展覽 (Claude): {name} ({year})")
    prompt = (
        f"請用 WebSearch 工具查找 {year} 年「{name}」展覽的精確資訊。\n\n"
        f"硬性要求:\n"
        f"1. 必須是 {year} 年的場次,絕對不要混入其他年份。\n"
        f"2. 開始/結束日期必須精確到「日」(YYYY-MM-DD)。"
        f"如果只有月份或大概時段,將 found 設為 false 並在 notes 說明。\n"
        f"3. 主辦單位填官方主辦組織名稱。\n"
        f"4. 官方網址填當年場次的官方頁面;若僅有展覽主網域亦可。\n"
        f"5. 地點分類為「臺灣」或「世界」二選一(在臺灣辦 = 臺灣,其他都算世界)。\n\n"
        f"請僅回應一個 JSON 物件(不要任何其他文字、說明或標題),格式:\n"
        f"```json\n"
        f"{{\n"
        f'  "found": true,\n'
        f'  "start_date": "YYYY-MM-DD",\n'
        f'  "end_date": "YYYY-MM-DD",\n'
        f'  "organizer": "...",\n'
        f'  "official_url": "...",\n'
        f'  "location_summary": "臺灣",\n'
        f'  "notes": ""\n'
        f"}}\n"
        f"```"
    )
    out = _call_claude(prompt)
    info = _extract_json(out)
    logger.info(f"查詢結果: found={info.get('found')} start={info.get('start_date')}")
    return info


def discover_new_exhibitions(
    industry_name: str,
    keywords: list[str],
    known_exhibitions: list[str],
    target_year: int,
) -> list[str]:
    """動態發現:用關鍵字找出不在 known_exhibitions 的新興展"""
    logger.info(f"發現新展 (Claude): {industry_name}")
    keyword_str = ", ".join(keywords)
    known_str = "\n".join(f"- {n}" for n in known_exhibitions) or "(無)"

    prompt = (
        f"請用 WebSearch 工具,找出 {target_year} 年「{industry_name}」相關的重要產業展覽。\n\n"
        f"產業關鍵字: {keyword_str}\n\n"
        f"已知不需重複列出的展覽:\n{known_str}\n\n"
        f"硬性要求:\n"
        f"1. 只回傳「不在已知清單」的新興或近年舉辦的重要展覽。\n"
        f"2. 必須是 {target_year} 年確實有舉辦的場次。\n"
        f"3. 只回傳官方展名,不要描述。\n\n"
        f"請僅回應一個 JSON 物件,格式:\n"
        f"```json\n"
        f'{{"new_exhibitions": ["展名 1", "展名 2"]}}\n'
        f"```"
    )
    out = _call_claude(prompt)
    result = _extract_json(out)
    new_names = [n for n in result.get("new_exhibitions", []) if n not in known_exhibitions]
    logger.info(f"發現 {len(new_names)} 個新展")
    return new_names
