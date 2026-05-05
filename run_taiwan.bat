@echo off
chcp 65001 > nul
title Exhibition Tracker - Taiwan
cd /d F:\exhibition-tracker

echo ========================================
echo  Exhibition Tracker - Taiwan only
echo  (TWTC + Nangang scrapers, no Claude CLI)
echo ========================================
echo.
echo  Estimated time: 1 to 2 minutes
echo.
echo  Steps:
echo    1. Mark expired entries
echo    2. Scrape TWTC + Nangang -^> Notion
echo    3. Generate exhibitions.ics
echo    4. Push to GitHub gh-pages
echo.
echo ========================================
echo.

python scripts\update_all.py --skip-layer2

echo.
echo ========================================
echo  Done. Press any key to close.
echo ========================================
pause >nul
