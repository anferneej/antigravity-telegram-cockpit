@echo off
chcp 65001 >nul
title AntiGravity Telegram Cockpit - Status
cd /d %~dp0
python src/cockpit.py status
echo.
pause
