@echo off
chcp 65001 > nul
title Exhibition Tracker - All in One (Lean)
cd /d F:\exhibition-tracker

echo ========================================
echo  Exhibition Tracker - All in One (Lean)
echo ========================================
echo.
echo  Includes:
echo    - Taiwan: TWTC + Nangang scrapers
echo    - World: Top exhibitions per category
echo    - MAG7 keynotes (Apple, Google, NVIDIA, AMD,
echo      OpenAI, Anthropic, AWS, Tesla, SpaceX...)
echo.
echo  Steps:
echo    1. Mark expired entries
echo    2. Layer 1: TWTC + Nangang -^> Notion
echo    3. Layer 2: Lean whitelist + MAG7 -^> Notion
echo    4. Generate exhibitions.ics
echo    5. Push to GitHub gh-pages
echo.
echo  Estimated time:
echo    Max $200:  1-2 hours
echo    Pro $20:   8-15 hours (rate-limit cycles)
echo.
echo ========================================
echo.

python scripts\update_all.py --lean

echo.
echo ========================================
echo  Done. Press any key to close.
echo ========================================
pause >nul
