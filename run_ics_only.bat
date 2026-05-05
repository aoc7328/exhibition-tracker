@echo off
chcp 65001 > nul
title Exhibition Tracker - ICS only
cd /d F:\exhibition-tracker

echo ========================================
echo  Exhibition Tracker - ICS only
echo ========================================
echo.
echo  Quickly regenerate exhibitions.ics from current Notion DB
echo  and push to GitHub gh-pages. No Layer 1/2 fetching.
echo.
echo  Use cases:
echo    - You manually changed status in Notion (e.g. 待確認 -^> 已確認)
echo      and want Apple Calendar to reflect it immediately
echo    - The main .bat is still running and you want a snapshot
echo      of current progress in your calendar
echo.
echo  Estimated time: about 30 seconds
echo.
echo ========================================
echo.

python scripts\update_all.py --skip-layer1 --skip-layer2

echo.
echo ========================================
echo  Done. Apple Calendar will pick up the new .ics
echo  on its next sync (typically within a few hours).
echo  Press any key to close.
echo ========================================
pause >nul
