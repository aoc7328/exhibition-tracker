"""類別關鍵字篩選
讀 config/industries.yaml,根據展名比對 keywords,
判斷該展覽屬於哪個產業類別(可多)
"""
from __future__ import annotations

from typing import Any

import yaml

from .logger import get_logger
from .settings import INDUSTRIES_YAML

logger = get_logger(__name__)


def load_industries() -> list[dict[str, Any]]:
    """讀 industries.yaml,回傳產業範疇 list"""
    with open(INDUSTRIES_YAML, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("industries", [])


def match_industries(name: str, industries: list[dict[str, Any]] | None = None) -> list[str]:
    """根據展名比對 keywords,回傳匹配的產業名稱清單(可空)"""
    if industries is None:
        industries = load_industries()
    matches: list[str] = []
    name_lower = name.lower()
    for ind in industries:
        ind_name = ind.get("name", "")
        if not ind_name:
            continue
        for kw in ind.get("keywords", []) or []:
            if not kw:
                continue
            if str(kw).lower() in name_lower:
                matches.append(ind_name)
                break
    return matches
