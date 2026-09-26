@echo off
chcp 65001 >nul
title AntiGravity Telegram Cockpit - 艦隊守護中樞
echo ========================================================
echo   🚀 正在啟動 AntiGravity Telegram 控制塔守護服務...
echo ========================================================
cd /d %~dp0
python -u src/cockpit.py daemon
pause
