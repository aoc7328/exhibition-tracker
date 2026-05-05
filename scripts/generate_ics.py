"""主程式:從 Notion 撈已確認展覽,產生 .ics 檔到 output/exhibitions.ics
GitHub Actions 後續會把這個檔推到 gh-pages 分支,Apple 行事曆訂閱該 URL
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ics_generator import generate_ics  # noqa: E402
from src.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


def main() -> int:
    try:
        path = generate_ics()
        logger.info(f".ics 產生成功: {path}")
        return 0
    except Exception as e:
        logger.exception(f".ics 產生失敗: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
