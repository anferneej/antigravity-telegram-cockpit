"""
AntiGravity Telegram Cockpit - 排程引擎
負責每日定時時間點 (如 08:00, 12:00, 18:00) 自動觸發全站掃描與分流推播
"""

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable
import schedule

from .config_manager import ConfigManager
from .content_fetcher import fetch_site_content
from .bot_fleet import BotFleet
from .inbox_manager import InboxManager


def run_scan_and_broadcast(target_channel: Optional[str] = None) -> int:
    """執行全網情報掃描並推播至對應頻道"""
    sites = ConfigManager.get_sites_config()
    if target_channel and target_channel != "all":
        sites = [s for s in sites if s.get("target_bot", "default") == target_channel]

    print(f"\n[Cockpit] 🚀 開始掃描情報源 (總計 {len(sites)} 個站點)...")
    total_pushed = 0

    for site in sites:
        name = site.get("name", "站點")
        target_bot = site.get("target_bot", "default")
        try:
            articles = fetch_site_content(site)
            for item in articles:
                if BotFleet.broadcast_article(item):
                    total_pushed += 1
                    print(f"  ✅ 【{target_bot}】已推播: {item.get('title')[:30]}...")
                    time.sleep(1.2)  # 防 Telegram 頻率限制
        except Exception as e:
            print(f"  ❌ 抓取站點失敗 [{name}]: {e}")

    print(f"[Cockpit] ✨ 掃描推播完成！本次累計推送 {total_pushed} 則新鮮情報。\n")
    return total_pushed


def setup_schedules(scan_callback: Callable = run_scan_and_broadcast):
    """依照 settings.json 設定排程任務"""
    schedule.clear()
    settings = ConfigManager.get_settings()
    times = settings.get("schedule_times", ["08:00", "12:00", "18:00"])

    for t in times:
        try:
            schedule.every().day.at(t).do(scan_callback)
            print(f"  [Scheduler] 已註冊定時任務: 每日 {t}")
        except Exception as e:
            print(f"  [Scheduler] 註冊排程失敗 {t}: {e}")


def run_scheduler_loop(stop_event: threading.Event):
    """排程器背景輪詢線程"""
    setup_schedules()
    while not stop_event.is_set():
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"[Error] 排程執行異常: {e}")
        time.sleep(10)
