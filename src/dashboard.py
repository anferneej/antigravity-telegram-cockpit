"""
AntiGravity Telegram Cockpit - 儀表板與狀態渲染模組
產生終端機 ASCII 看板與 Markdown / JSON 報告
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from .config_manager import ConfigManager
from .inbox_manager import InboxManager
from .bot_fleet import BotFleet


def get_cockpit_full_state() -> Dict[str, Any]:
    """彙整駕駛艙完整運行狀態"""
    bots_cfg = ConfigManager.get_bots_config()
    active_bots = BotFleet.get_active_bots()
    sites = ConfigManager.get_sites_config()
    settings = ConfigManager.get_settings()
    metrics = InboxManager.get_metrics_summary()
    recent_inbox = InboxManager.get_inbox(limit=5)

    bot_statuses = []
    for key, info in bots_cfg.items():
        is_active = key in active_bots
        token = ConfigManager.get_bot_token(key)
        has_token = bool(token and not token.startswith("YOUR_"))
        heartbeat = metrics.get("bots", {}).get(key, {})
        
        # 統計關聯站點數
        matched_sites = [s for s in sites if s.get("target_bot", "default") == key]
        
        bot_statuses.append({
            "key": key,
            "name": info.get("name", key),
            "status": heartbeat.get("status", "ready" if is_active else "unconfigured"),
            "token_configured": has_token,
            "chat_ids_count": len(ConfigManager.get_chat_ids(key)),
            "monitored_sources_count": len(matched_sites),
            "last_heartbeat": heartbeat.get("last_heartbeat", "N/A"),
            "details": heartbeat.get("details", "")
        })

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": settings.get("timezone", "Asia/Taipei"),
        "schedule_times": settings.get("schedule_times", []),
        "total_sources_count": len(sites),
        "today_pushes_count": metrics.get("today_pushes_count", 0),
        "pending_inbox_count": metrics.get("pending_inbox_count", 0),
        "bots": bot_statuses,
        "recent_pushes": metrics.get("recent_pushes", []),
        "recent_inbox": recent_inbox
    }


def render_terminal_dashboard() -> str:
    """渲染終端機 ASCII 儀表板"""
    state = get_cockpit_full_state()
    lines = []
    lines.append("=" * 64)
    lines.append("  🚀  ANTIGRAVITY TELEGRAM COCKPIT (中央控制塔駕駛艙)  🚀  ")
    lines.append("=" * 64)
    lines.append(f" 🕒 系統時間: {state['generated_at']} ({state['timezone']})")
    lines.append(f" ⏰ 排程推播: {', '.join(state['schedule_times'])}")
    lines.append(f" 📡 監控來源: {state['total_sources_count']} 個站點 (含 YouTube 深度解讀)")
    lines.append(f" 📨 今日累計推播: {state['today_pushes_count']} 則 | 待處理提問: {state['pending_inbox_count']} 則")
    lines.append("-" * 64)
    lines.append(f" {'BOT 頻道':<18} | {'狀態':<8} | {'來源數':<6} | {'目標':<5} | {'最後心跳'}")
    lines.append("-" * 64)

    for b in state["bots"]:
        status_icon = "🟢" if b["status"] in ["online", "ready"] else "⚪"
        name_str = f"{status_icon} {b['name']}"
        lines.append(
            f" {name_str:<18} | {b['status']:<8} | {b['monitored_sources_count']:<6} | "
            f"{b['chat_ids_count']:<5} | {b['last_heartbeat']}"
        )

    lines.append("-" * 64)
    if state["recent_inbox"]:
        lines.append(" 💬 最新 Telegram 互動/提問紀錄:")
        for it in state["recent_inbox"][:3]:
            q_short = it.get("question", "")[:28]
            lines.append(f"   [{it.get('bot_key')}] @{it.get('user_name')}: {q_short}.. ({it.get('status')})")
    else:
        lines.append(" 💬 互動收件匣：目前無待處理提問")

    lines.append("=" * 64)
    return "\n".join(lines)


def render_markdown_dashboard() -> str:
    """渲染 Markdown 報告，供 AntiGravity 生成 Artifact 呈現"""
    state = get_cockpit_full_state()
    md = []
    md.append(f"# 🛰️ AntiGravity Telegram 控制塔駕駛艙\n")
    md.append(f"> **狀態更新時間**：`{state['generated_at']}` | **排程時間**：`{', '.join(state['schedule_times'])}`\n")
    md.append("### 📊 今日關鍵運行指標")
    md.append(f"- **監控情資站點數**：`{state['total_sources_count']}` 個")
    md.append(f"- **今日成功推播總量**：`{state['today_pushes_count']}` 則")
    md.append(f"- **待回覆 Telegram 諮詢**：`{state['pending_inbox_count']}` 則\n")

    md.append("### 🤖 5 大 Bot 艦隊狀態")
    md.append("| 頻道名稱 | 識別 Key | 連線狀態 | 監控來源數 | 目標 Chat ID | 最後活躍時間 |")
    md.append("| :--- | :--- | :---: | :---: | :---: | :--- |")
    for b in state["bots"]:
        badge = "🟢 連線正常" if b["status"] in ["online", "ready"] else "⚪ 待機中"
        md.append(f"| **{b['name']}** | `{b['key']}` | {badge} | {b['monitored_sources_count']} 個 | {b['chat_ids_count']} 人/群 | `{b['last_heartbeat']}` |")

    md.append("\n### 📥 最近 Telegram 互動收件匣")
    if state["recent_inbox"]:
        md.append("| 時間 | 頻道 | 發問者 | 提問內容 | 狀態 |")
        md.append("| :--- | :--- | :--- | :--- | :---: |")
        for it in state["recent_inbox"]:
            st = "✅ 已回覆" if it.get("status") == "answered" else "⏳ 待處理"
            md.append(f"| {it.get('timestamp')} | `{it.get('bot_key')}` | @{it.get('user_name')} | {it.get('question')} | {st} |")
    else:
        md.append("*目前無未處理之訊息。*")

    return "\n".join(md)
