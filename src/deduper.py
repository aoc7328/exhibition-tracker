"""展覽去重 — 名字模糊匹配 + Claude 確認

用途:
- 即時去重(notion_writer.upsert 內部呼叫):新展跟既有展名很像 → Claude 確認是否同展 → 合併
- 既有清理(scripts/dedupe.py 呼叫):掃整個 Notion DB 把重複的合併

策略:
- 先 fuzzy similarity 篩出候選,完全不像直接跳過(省 Claude query)
- 候選太相似(>= HIGH_THRESHOLD)→ 直接視為同展(免 Claude 確認)
- 中間範圍 → Claude 確認
"""
from __future__ import annotations

import difflib
import json
import platform
import re
import subprocess

from .logger import get_logger

logger = get_logger(__name__)

CLI_TIMEOUT = 120
IS_WINDOWS = platform.system() == "Windows"

# 兩個展名 normalize 後的相似度門檻
SIMILARITY_THRESHOLD = 0.6   # >= 此值才觸發 Claude 確認
HIGH_THRESHOLD = 0.9          # >= 此值直接視為同展(免 Claude)


def _normalize(s: str) -> str:
    """正規化展名:去年份、空白、標點,小寫化"""
    s = re.sub(r"\b20\d{2}\b", "", s)
    s = re.sub(r"[\s\-_/、,。()()\[\]【】]+", "", s)
    return s.lower()


def fuzzy_similarity(a: str, b: str) -> float:
    """0~1 相似度,先正規化(去年份/標點)再比對"""
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def claude_is_same_exhibition(name_a: str, name_b: str) -> bool:
    """用 Claude CLI 判斷兩展名是否同一個展(同主辦/同時間/同地點)"""
    prompt = (
        f"請判斷下列兩個展覽名稱是否指同一個展覽:\n"
        f"A: {name_a}\n"
        f"B: {name_b}\n\n"
        f"判斷依據:展覽的官方主辦組織、舉辦時間、地點是否一致。\n"
        f"忽略年份前後綴、中英文對照、簡稱與全稱的差異。\n\n"
        f"請僅回應一個 JSON,格式:\n"
        f"```json\n"
        f'{{"same": true, "reason": "..."}}\n'
        f"```"
    )
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
    except subprocess.TimeoutExpired:
        logger.warning(f"Claude 確認同展 timeout: {name_a} vs {name_b}")
        return False
    if result.returncode != 0:
        logger.warning(f"Claude 確認同展失敗: {result.stderr[:200]}")
        return False

    out = result.stdout
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", out, re.DOTALL)
    if not m:
        m = re.search(r"(\{[^{}]*\})", out, re.DOTALL)
    if not m:
        return False
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return False
    return bool(data.get("same"))


def find_likely_match(new_name: str, candidates: list[tuple[str, object]]) -> object | None:
    """從候選清單找最可能的同展對應。candidates: [(name, payload)]
    回傳 payload 或 None。
    """
    scored: list[tuple[float, str, object]] = []
    for cand_name, payload in candidates:
        if not cand_name:
            continue
        sim = fuzzy_similarity(new_name, cand_name)
        if sim >= SIMILARITY_THRESHOLD:
            scored.append((sim, cand_name, payload))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)

    # 高度相似免 Claude
    for sim, cand_name, payload in scored:
        if sim >= HIGH_THRESHOLD:
            logger.info(f"高度相似 ({sim:.2f}) 直接視為同展: '{new_name}' = '{cand_name}'")
            return payload

    # 中等相似 → Claude 確認(只試 top-3 避免過多 API call)
    for sim, cand_name, payload in scored[:3]:
        logger.info(f"中等相似 ({sim:.2f}),問 Claude: '{new_name}' vs '{cand_name}'")
        if claude_is_same_exhibition(new_name, cand_name):
            logger.info(f"Claude 確認同展: '{new_name}' = '{cand_name}'")
            return payload

    return None
