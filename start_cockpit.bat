@echo off
chcp 65001 >nul
title AntiGravity Telegram Cockpit - Daemon
cd /d %~dp0
python -u src/cockpit.py daemon
pause
