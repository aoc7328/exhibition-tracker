@echo off
chcp 65001 > nul
title Exhibition Tracker - World (Lean)
cd /d F:\exhibition-tracker

echo ========================================
echo  Exhibition Tracker - World (Lean version)
echo  for Claude Pro $20 subscription
echo ========================================
echo.
echo  Includes:
echo    - Top exhibition per category (CES, MWC, GTC, etc.)
echo    - MAG7 keynotes (Apple, Google, NVIDIA, AMD,
echo      OpenAI, Anthropic, AWS, Tesla, SpaceX...)
echo    - Taiwan-only categories (stationery, building, travel)
echo.
echo  Estimated time:
echo    Max $200:  1-2 hours
echo    Pro $20:   8-15 hours (distributed across rate-limit cycles)
echo.
echo ========================================
echo.

python scripts\update_all.py --skip-layer1 --lean

echo.
echo ========================================
echo  Done. Press any key to close.
echo ========================================
pause >nul
