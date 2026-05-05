"""展覽去重 — 名字 fuzzy + 日期/地點/主辦驗證 + Claude 確認

判斷流程(由便宜到貴):
1. 名字相似度 < 0.6        → 必定不同(免 Claude)
2. 日期完全不重疊         → 必定不同(免 Claude,即便名字像)
3. 日期+主辦完全相同      → 必定同(免 Claude,例如同展不同來源各寫一筆)
4. 名字相似度 ≥ 0.9        → 必定同(免 Claude,例如 "COMPUTEX" vs "COMPUTEX TAIPEI")
5. 中等相似(0.6~0.9)+ 日期重疊或未知 → Claude 拿完整 metadata 判斷
"""
from __future__ import annotations

import difflib
import json
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import date

from .logger import get_logger

logger = get_logger(__name__)

CLI_TIMEOUT = 120
IS_WINDOWS = platform.system() == "Windows"

SIMILARITY_THRESHOLD = 0.6
HIGH_THRESHOLD = 0.9


@dataclass
class ExhibitionMeta:
    """比對用的 metadata,從 Notion page 或 Exhibition dataclass 提取"""

    name: str
    start_date: date | None = None
    end_date: date | None = None
    location: str = ""  # 臺灣 / 世界
    organizer: str = ""
    url: str = ""


def _normalize(s: str) -> str:
    """正規化展名:去年份、空白、標點,小寫化"""
    s = re.sub(r"\b20\d{2}\b", "", s)
    s = re.sub(r"[\s\-_/、,。()()\[\]【】]+", "", s)
    return s.lower()


def fuzzy_similarity(a: str, b: str) -> float:
    """0~1 名字相似度,先正規化(去年份/標點)再比"""
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _dates_overlap(a: ExhibitionMeta, b: ExhibitionMeta) -> bool | None:
    """True 重疊 / False 完全不重疊 / None 任一缺日期無法判斷"""
    if not (a.start_date and a.end_date and b.start_date and b.end_date):
        return None
    return not (a.end_date < b.start_date or b.end_date < a.start_date)


def _claude_confirm(a: ExhibitionMeta, b: ExhibitionMeta) -> bool:
    """Claude 用完整 metadata 確認兩展是否同一個"""
    def fmt(m: ExhibitionMeta) -> str:
        lines = [f"  名稱: {m.name}"]
        if m.start_date and m.end_date:
            lines.append(f"  日期: {m.start_date} ~ {m.end_date}")
        else:
            lines.append("  日期: (未知)")
        if m.location:
            lines.append(f"  地點分類: {m.location}")
        if m.organizer:
            lines.append(f"  主辦單位: {m.organizer}")
        if m.url:
            lines.append(f"  官方網址: {m.url}")
        return "\n".join(lines)

    prompt = (
        f"請判斷下列兩個展覽是否同一個展(可能為不同來源/語言/簡稱描述同一展):\n\n"
        f"展覽 A:\n{fmt(a)}\n\n"
        f"展覽 B:\n{fmt(b)}\n\n"
        f"判斷原則:\n"
        f"- 日期完全不重疊通常代表不同展(年度版本 / 不同活動 / 不同階段)\n"
        f"- 名稱差異大但日期+主辦+地點都一致 → 通常是同展(中英文/簡稱/全稱差異)\n"
        f"- 名稱類似但日期+主辦差異大 → 通常是不同展(同主題不同單位舉辦)\n\n"
        f"請僅回應 JSON,格式:\n"
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
        logger.warning(f"Claude 確認 timeout: {a.name} vs {b.name}")
        return False
    if result.returncode != 0:
        logger.warning(f"Claude 確認失敗: {result.stderr[:200]}")
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


def is_same_exhibition(a: ExhibitionMeta, b: ExhibitionMeta) -> bool:
    """綜合判斷兩展是否同一個。"""
    sim = fuzzy_similarity(a.name, b.name)

    # 1. 名字差太多 → 不同
    if sim < SIMILARITY_THRESHOLD:
        return False

    # 2. 日期完全不重疊 → 不同(即便名字像)
    overlap = _dates_overlap(a, b)
    if overlap is False:
        logger.info(
            f"日期不重疊,視為不同: '{a.name}' ({a.start_date}~{a.end_date}) "
            f"vs '{b.name}' ({b.start_date}~{b.end_date})"
        )
        return False

    # 3. 日期+主辦完全相同 → 同(免 Claude)
    if (
        a.start_date
        and b.start_date
        and a.start_date == b.start_date
        and a.end_date == b.end_date
        and a.organizer
        and a.organizer == b.organizer
    ):
        logger.info(f"日期+主辦完全相同 → 同展: '{a.name}' = '{b.name}'")
        return True

    # 4. 名字高度相似 → 同(免 Claude)
    if sim >= HIGH_THRESHOLD:
        logger.info(f"名稱高度相似 ({sim:.2f}) → 同展: '{a.name}' = '{b.name}'")
        return True

    # 5. 中等相似 → Claude 帶完整 metadata 判斷
    logger.info(f"中等相似 ({sim:.2f}),問 Claude(含 metadata): '{a.name}' vs '{b.name}'")
    same = _claude_confirm(a, b)
    if same:
        logger.info(f"Claude 確認同展: '{a.name}' = '{b.name}'")
    return same


def find_likely_match(
    new_meta: ExhibitionMeta,
    candidates: list[tuple[ExhibitionMeta, object]],
) -> object | None:
    """從候選找最可能的同展。candidates: [(meta, payload)]。回 payload 或 None"""
    # 先用 fuzzy 篩,避免每對都進 is_same_exhibition (含 Claude)
    scored: list[tuple[float, ExhibitionMeta, object]] = []
    for cand_meta, payload in candidates:
        if not cand_meta.name:
            continue
        sim = fuzzy_similarity(new_meta.name, cand_meta.name)
        if sim >= SIMILARITY_THRESHOLD:
            scored.append((sim, cand_meta, payload))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)

    # 對 top-3 用完整 is_same_exhibition (含日期/Claude)
    for _sim, cand_meta, payload in scored[:3]:
        if is_same_exhibition(new_meta, cand_meta):
            return payload

    return None
