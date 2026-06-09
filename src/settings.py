"""集中讀取 .env 設定"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"環境變數 {key} 未設定，請檢查 .env 檔")
    return value


NOTION_TOKEN = _require("NOTION_TOKEN")
NOTION_DATABASE_ID = _require("NOTION_DATABASE_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

# Finnhub API（earnings calendar)
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# Perplexity API（即時 web 搜尋 → 由 Claude 整理/複核）
# 設定後 update_all 預設改用 Perplexity 當查詢/發現引擎；未設定則回退 Claude CLI
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
# 預設用最便宜的 sonar(查展覽日期堪用);要更強可設 sonar-pro
PERPLEXITY_MODEL = os.getenv("PERPLEXITY_MODEL", "sonar")

# 總經數據行事曆 — 財經 M 平方全球財經日曆（公開 ICS）
# 只擷取會影響美股的重要美國總經事件，可用 MACRO_ICS_URL 覆蓋成自己的行事曆
MACRO_ICS_URL = os.getenv(
    "MACRO_ICS_URL",
    "https://calendar.google.com/calendar/ical/"
    "c_597b99efc6b2429fff1bf02863b61b7b08a176d17fb6ad0b1d6ba1f3fa3ac9c9"
    "%40group.calendar.google.com/public/basic.ics",
)

INDUSTRIES_YAML = PROJECT_ROOT / "config" / "industries.yaml"
INDUSTRIES_YAML_LEAN = PROJECT_ROOT / "config" / "industries_lean.yaml"
ICS_OUTPUT = PROJECT_ROOT / "output" / "exhibitions.ics"
