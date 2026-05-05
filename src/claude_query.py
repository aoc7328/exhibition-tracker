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
    """呼叫 claude -p 一次性查詢,prompt 從 stdin。撞 rate limit 自動等 30~300 秒重試"""
    flags = ["-p", "--dangerously-skip-permissions"]
    cmd = ["cmd.exe", "/c", "claude", *flags] if IS_WINDOWS else ["claude", *flags]
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


def query_exhibition(name: str, year: int, taiwan_only: bool = False) -> dict[str, Any]:
    """查單一展覽當年精確資訊。taiwan_only=True 時非台灣場 → found=false"""
    logger.info(f"查詢展覽 (Claude): {name} ({year}){' [TW only]' if taiwan_only else ''}")
    taiwan_constraint = (
        "\n【地區限制】此產業類別只追蹤臺灣舉辦的場次。"
        "若該展是在臺灣以外的國家舉辦,將 found 設為 false 並在 notes 註明「非臺灣場」。\n"
        if taiwan_only
        else ""
    )
    prompt = (
        f"請用 WebSearch 工具查找 {year} 年「{name}」展覽的精確資訊。\n"
        f"{taiwan_constraint}\n"
        f"【投資相關性 + 規模篩選】(任一不符合 → found=false 並在 notes 說明排除原因):\n"
        f"A. 能否直接或間接影響「台股」相關產業股價?(有台廠重要參與 / 有上市櫃公司直接受益 / 屬熱門投資題材)\n"
        f"B. 規模門檻 — 至少符合一項:\n"
        f"   (1) 展商家數 >= 100\n"
        f"   (2) 有正式官方記者會 / 有業界名人 keynote\n"
        f"   (3) 至少一家國際大廠或台灣上市櫃公司主辦或冠名贊助\n"
        f"C. 即使展辦在國外,只要影響美股龍頭(NVIDIA / AMD / Apple / TSLA / Meta / MSFT 等)、"
        f"會帶動台股供應鏈,亦算符合。\n\n"
        f"若以上任一項不符合 → found=false,在 notes 寫具體原因(例:「規模過小,無記者會」或「無投資相關性」)。\n\n"
        f"【硬性要求】(若篩選通過但下列任一不符,也設 found=false):\n"
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
    taiwan_only: bool = False,
) -> list[str]:
    """動態發現:用關鍵字找出不在 known_exhibitions 的新興展。
    taiwan_only=True 時只回臺灣舉辦的展。
    """
    logger.info(f"發現新展 (Claude): {industry_name}{' [TW only]' if taiwan_only else ''}")
    keyword_str = ", ".join(keywords)
    known_str = "\n".join(f"- {n}" for n in known_exhibitions) or "(無)"

    region_constraint = (
        "D. 【地區限制】此產業只追蹤【臺灣舉辦】的展(在台北/台中/高雄/南港等地舉辦)。"
        "國外辦的展即使是同類別也不要列。\n"
        if taiwan_only
        else ""
    )

    prompt = (
        f"請用 WebSearch 工具,找出 {target_year} 年「{industry_name}」相關的「中大型」產業展覽。\n\n"
        f"產業關鍵字: {keyword_str}\n\n"
        f"已知不需重複列出的展覽:\n{known_str}\n\n"
        f"【篩選準則】(必須全部符合才回傳):\n"
        f"A. 能影響台股或美股龍頭(NVIDIA/AMD/Apple/TSLA/Meta/MSFT)股價走勢\n"
        f"B. 規模門檻:展商 >= 100 / 有官方記者會 / 業界名人 keynote / 上市櫃公司主辦或贊助 — 至少一項\n"
        f"C. 不要列入:小型 / 純學術會議 / 純消費展 / 區域性小展\n"
        f"{region_constraint}"
        f"\n"
        f"硬性要求:\n"
        f"1. 只回傳「不在已知清單」的新興或近年舉辦的中大型展覽。\n"
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
