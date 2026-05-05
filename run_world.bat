@echo off
chcp 65001 > nul
title Exhibition Tracker - World
cd /d F:\exhibition-tracker

echo ========================================
echo  Exhibition Tracker - World only
echo  (Whitelist + AI discovery via Claude CLI)
echo ========================================
echo.
echo  Estimated time: 3 to 5 hours (Claude CLI + WebSearch)
echo.
echo  Steps:
echo    1. Mark expired entries
echo    2. Layer 2: Whitelist + AI discovery -^> Notion
echo    3. Generate exhibitions.ics
echo    4. Push to GitHub gh-pages
echo.
echo  You can use the computer for other tasks during the run.
echo ========================================
echo.

python scripts\update_all.py --skip-layer1

echo.
echo ========================================
echo  Done. Press any key to close.
echo ========================================
pause >nul
