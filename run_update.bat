@echo off
chcp 65001 > nul
title Exhibition Tracker
cd /d F:\exhibition-tracker

echo ========================================
echo   展覽追蹤系統 - 全自動更新
echo ========================================
echo.
echo 預估時間: Layer 1 約 1 分鐘
echo           Layer 2 約 30 分鐘 ~ 1 小時 (Claude CLI)
echo           ICS 產生 + push 約 5 秒
echo.
echo 過程中可以做別的事,不需要顧著看
echo ========================================
echo.

python scripts\update_all.py

echo.
echo ========================================
echo   完成! 按任意鍵關閉
echo ========================================
pause >nul
