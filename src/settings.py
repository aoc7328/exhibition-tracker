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


# GEMINI_API_KEY 只在跑層次 2 (Gemini 查詢/複核) 時需要
# generate_ics 等其他用途不需要,設成 optional 避免 import 時就爆
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
NOTION_TOKEN = _require("NOTION_TOKEN")
NOTION_DATABASE_ID = _require("NOTION_DATABASE_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

GEMINI_MODEL_QUERY = "gemini-2.5-flash"
GEMINI_MODEL_VALIDATE = "gemini-2.5-pro"

INDUSTRIES_YAML = PROJECT_ROOT / "config" / "industries.yaml"
INDUSTRIES_YAML_LEAN = PROJECT_ROOT / "config" / "industries_lean.yaml"
ICS_OUTPUT = PROJECT_ROOT / "output" / "exhibitions.ics"
