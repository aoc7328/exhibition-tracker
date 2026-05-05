"""本機完整 pipeline — 一鍵跑完所有事情

1. Layer 1 爬蟲 (TWTC + 南港) → 寫 Notion
2. Layer 2 用 Claude CLI 查 + 雙階段複核 → 寫 Notion
3. 從 Notion 撈已確認 → 產 .ics
4. 用 GitHub Contents API 推 .ics 到 gh-pages 分支(Apple 行事曆訂閱會自動更新)

Usage:
    python scripts/update_all.py            # 實寫
    python scripts/update_all.py --dry-run  # 只印不寫
    python scripts/update_all.py --skip-layer2  # 略過 Layer 2(快速跑 Layer 1+ICS)
"""
from __future__ import annotations

import argparse
import base64
import sys
from datetime import date, datetime
from pathlib import Path

import requests
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.category_filter import load_industries, match_industries  # noqa: E402
from src.claude_query import discover_new_exhibitions, query_exhibition  # noqa: E402
from src.claude_validator import validate_exhibition  # noqa: E402
from src.ics_generator import generate_ics  # noqa: E402
from src.logger import get_logger  # noqa: E402
from src.models import Confidence, Exhibition, Location, SourceLayer, Status  # noqa: E402
from src.notion_writer import find_existing, upsert_exhibition  # noqa: E402
from src.scrapers.nangang import fetch_exhibitions as fetch_nangang  # noqa: E402
from src.scrapers.twtc import fetch_exhibitions as fetch_twtc  # noqa: E402
from src.settings import GITHUB_REPO, GITHUB_TOKEN, INDUSTRIES_YAML  # noqa: E402

logger = get_logger(__name__)


def _to_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def run_layer1(year: int, dry_run: bool) -> None:
    logger.info("=== Layer 1: 台北世貿 + 南港 ===")
    industries = load_industries()

    sources = [
        ("TWTC", lambda: fetch_twtc(year), SourceLayer.TWTC),
        ("南港", fetch_nangang, SourceLayer.NANGANG),
    ]
    for source_name, fetch_fn, src_enum in sources:
        try:
            events = fetch_fn()
        except Exception as e:
            logger.exception(f"{source_name} 抓取失敗: {e}")
            continue

        written = 0
        for ev in events:
            cats = match_industries(ev["name"], industries)
            if not cats:
                continue
            ex = Exhibition(
                name=ev["name"],
                start_date=ev["start_date"],
                end_date=ev["end_date"],
                location=Location.TAIWAN,
                organizer=ev.get("organizer", ""),
                url=ev.get("url", ""),
                confidence=Confidence.HIGH,
                source=src_enum,
                industries=cats,
                status=Status.CONFIRMED,
            )
            try:
                upsert_exhibition(ex, dry_run=dry_run)
                written += 1
            except Exception as e:
                logger.exception(f"upsert 失敗 {ex.unique_key}: {e}")
        logger.info(f"{source_name}: 抓到 {len(events)} 筆,寫入 {written} 筆")


def _should_skip_claude(ex_name: str, year: int) -> bool:
    """Notion 已有當年該展、狀態=已確認、結束日尚未過 → 跳過 Claude 查詢"""
    existing = find_existing(f"{ex_name} {year}")
    if not existing:
        return False
    _, props = existing

    status_sel = props.get("狀態", {}).get("select") or {}
    if status_sel.get("name") != Status.CONFIRMED.value:
        return False

    # 結束日從「結束日期」或「開始日期 range end」拿
    end_str = (props.get("結束日期", {}).get("date") or {}).get("start")
    if not end_str:
        start_prop = props.get("開始日期", {}).get("date") or {}
        end_str = start_prop.get("end") or start_prop.get("start")
    if not end_str:
        return False

    try:
        end_d = date.fromisoformat(end_str[:10])
    except ValueError:
        return False
    return end_d >= date.today()


def _query_and_upsert(
    ex_name: str,
    industry: str,
    source: SourceLayer,
    year: int,
    dry_run: bool,
    force_low: bool = False,
) -> None:
    if not dry_run and _should_skip_claude(ex_name, year):
        logger.info(f"跳過 Claude 查詢: {ex_name} {year}(已確認且未過期)")
        return

    info = query_exhibition(ex_name, year)
    if not info.get("found"):
        logger.info(f"排除 {ex_name} {year}: {info.get('notes', '不符合篩選準則')}")
        return

    start = _to_date(info.get("start_date"))
    end = _to_date(info.get("end_date"))

    confidence = Confidence.MEDIUM
    status = Status.PENDING

    if info.get("found") and start and end:
        validation = validate_exhibition(ex_name, start.year, start, end)
        if validation.get("confidence_high"):
            confidence = Confidence.HIGH
            status = Status.CONFIRMED
        else:
            logger.info(f"複核未通過 {ex_name}: {validation.get('reason')}")
    else:
        start = end = None

    if force_low:
        confidence = Confidence.LOW
        status = Status.PENDING

    loc_str = info.get("location_summary", "")
    location = Location.TAIWAN if "臺灣" in loc_str or "台灣" in loc_str else Location.WORLD

    ex = Exhibition(
        name=ex_name,
        start_date=start,
        end_date=end,
        location=location,
        organizer=info.get("organizer", ""),
        url=info.get("official_url", ""),
        confidence=confidence,
        source=source,
        industries=[industry],
        status=status,
    )
    upsert_exhibition(ex, dry_run=dry_run)


def run_layer2(year: int, dry_run: bool, industry_filter: str | None = None) -> None:
    logger.info("=== Layer 2: Claude CLI 查詢 + 雙階段複核 ===")

    with open(INDUSTRIES_YAML, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    industries = config.get("industries", [])
    if industry_filter:
        industries = [i for i in industries if i.get("name") == industry_filter]
        if not industries:
            logger.warning(f"找不到產業: {industry_filter}")
            return
        logger.info(f"只跑指定產業: {industry_filter}")

    for ind in industries:
        name = ind["name"]
        keywords = ind.get("keywords") or []
        known = ind.get("known_exhibitions") or []
        logger.info(f"--- 產業: {name} ({len(known)} 已知) ---")

        for ex_name in known:
            try:
                _query_and_upsert(ex_name, name, SourceLayer.WHITELIST, year, dry_run)
            except Exception as e:
                logger.exception(f"查詢失敗 {ex_name}: {e}")

        try:
            new_names = discover_new_exhibitions(name, keywords, known, year)
            for ex_name in new_names:
                try:
                    _query_and_upsert(
                        ex_name, name, SourceLayer.AI_DISCOVERY, year, dry_run, force_low=True
                    )
                except Exception as e:
                    logger.exception(f"動態發現後查詢失敗 {ex_name}: {e}")
        except Exception as e:
            logger.exception(f"動態發現失敗 {name}: {e}")


def push_ics_to_gh_pages(ics_path: Path) -> None:
    """用 GitHub Contents API 把 exhibitions.ics 推到 gh-pages 分支"""
    logger.info(f"Push {ics_path.name} 到 {GITHUB_REPO}/gh-pages")

    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.warning("缺 GITHUB_TOKEN 或 GITHUB_REPO,跳過 push")
        return

    content = ics_path.read_text(encoding="utf-8")
    encoded = base64.b64encode(content.encode("utf-8")).decode()
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1. 確保 gh-pages 分支存在
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/branches/gh-pages",
        headers=headers,
        timeout=30,
    )
    if r.status_code == 404:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/git/refs/heads/main",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        main_sha = r.json()["object"]["sha"]
        r = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/git/refs",
            headers=headers,
            json={"ref": "refs/heads/gh-pages", "sha": main_sha},
            timeout=30,
        )
        r.raise_for_status()
        logger.info("建立 gh-pages 分支")

    # 2. 取得既有 .ics 的 sha(若有)
    r = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/exhibitions.ics",
        params={"ref": "gh-pages"},
        headers=headers,
        timeout=30,
    )
    sha = r.json().get("sha") if r.status_code == 200 else None

    # 3. PUT 內容(create or update)
    body: dict[str, str] = {
        "message": f"Update exhibitions.ics ({datetime.now():%Y-%m-%d %H:%M})",
        "content": encoded,
        "branch": "gh-pages",
    }
    if sha:
        body["sha"] = sha

    r = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/exhibitions.ics",
        headers=headers,
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    logger.info(f"exhibitions.ics 已 push,Apple 行事曆會在下次同步時更新")


def main() -> int:
    parser = argparse.ArgumentParser(description="本機完整 pipeline")
    parser.add_argument("--dry-run", action="store_true", help="只印不寫")
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=None,
        help="目標年份,可多個(預設今年+明年,半年後跑會自動往未來推)",
    )
    parser.add_argument("--skip-layer1", action="store_true")
    parser.add_argument("--skip-layer2", action="store_true")
    parser.add_argument("--skip-ics", action="store_true")
    parser.add_argument(
        "--industry",
        type=str,
        default=None,
        help="只跑指定產業(用 industries.yaml 的名稱,例如「半導體」)",
    )
    args = parser.parse_args()

    dry_run = args.dry_run
    current_year = datetime.now().year
    years = args.years or [current_year, current_year + 1]
    logger.info(f"模式: {'DRY-RUN' if dry_run else '實寫'} | 年份: {years}")

    if not args.skip_layer1:
        # Layer 1 (TWTC + 南港) 用當年抓 default 頁面
        run_layer1(current_year, dry_run)

    if not args.skip_layer2:
        # Layer 2 對每個年份分別跑(跨年版本以 unique key 區隔)
        for year in years:
            logger.info(f"--- Layer 2 年份: {year} ---")
            run_layer2(year, dry_run, args.industry)

    if not args.skip_ics:
        try:
            ics_path = generate_ics()
            if not dry_run:
                push_ics_to_gh_pages(ics_path)
        except Exception as e:
            logger.exception(f"ICS / push 失敗: {e}")

    logger.info("✓ 全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
