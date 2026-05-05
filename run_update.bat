@echo off
chcp 65001 > nul
title Exhibition Tracker
cd /d F:\exhibition-tracker

echo ========================================
echo  Exhibition Tracker - Auto Update
echo ========================================
echo.
echo  Layer 1 (web scrape):  about 1 min
echo  Layer 2 (Claude CLI):  30-60 min
echo  ICS + push gh-pages:   5 sec
echo.
echo  You can do other things during the run.
echo ========================================
echo.

python scripts\update_all.py

echo.
echo ========================================
echo  Done. Press any key to close.
echo ========================================
pause >nul
