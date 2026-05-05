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


GEMINI_API_KEY = _require("GEMINI_API_KEY")
NOTION_TOKEN = _require("NOTION_TOKEN")
NOTION_DATABASE_ID = _require("NOTION_DATABASE_ID")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")

GEMINI_MODEL_QUERY = "gemini-2.5-flash"
GEMINI_MODEL_VALIDATE = "gemini-2.5-pro"

INDUSTRIES_YAML = PROJECT_ROOT / "config" / "industries.yaml"
ICS_OUTPUT = PROJECT_ROOT / "output" / "exhibitions.ics"
