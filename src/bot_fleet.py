"""
AntiGravity Telegram Cockpit - 5 大 Bot 艦隊管理與通訊服務
- 負責 5 個 Telegram Bot 的訊息發送、推播格式化與長輪詢監聽
- 自動將 Telegram 收到的提問或追問匯流至 Cockpit Inbox (data/inbox.json)
- 記錄艦隊心跳與活躍指標 (data/metrics.json)
"""

import html
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

from .config_manager import ConfigManager
from .inbox_manager import InboxManager

TELEGRAM_API_ROOT = "https://api.telegram.org"


def get_api_base(token: str) -> str:
    return f"{TELEGRAM_API_ROOT}/bot{token}"


class BotFleet:
    @classmethod
    def get_active_bots(cls) -> Dict[str, Dict[str, Any]]:
        """取得已配置且具備 Token 的 Bot 清單"""
        bots_cfg = ConfigManager.get_bots_config()
        active = {}
        for key, info in bots_cfg.items():
            token = ConfigManager.get_bot_token(key)
            if token and token.strip() and not token.startswith("YOUR_"):
                chat_ids = ConfigManager.get_chat_ids(key)
                active[key] = {
                    "name": info.get("name", key),
                    "token": token.strip(),
                    "chat_ids": chat_ids,
                    "description": info.get("description", "")
                }
        return active

    @classmethod
    def test_connection(cls, bot_key: str) -> Dict[str, Any]:
        """測試單一 Bot 連線狀態"""
        token = ConfigManager.get_bot_token(bot_key)
        if not token:
            return {"ok": False, "error": f"找不到 {bot_key} 的 Token 設定"}
        url = f"{get_api_base(token)}/getMe"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("ok"):
                user = data.get("result", {})
                InboxManager.update_bot_heartbeat(bot_key, "online", f"@{user.get('username')}")
                return {"ok": True, "username": user.get("username"), "first_name": user.get("first_name")}
            else:
                InboxManager.update_bot_heartbeat(bot_key, "error", data.get("description", "驗證失敗"))
                return {"ok": False, "error": data.get("description")}
        except Exception as e:
            InboxManager.update_bot_heartbeat(bot_key, "offline", str(e))
            return {"ok": False, "error": str(e)}

    @classmethod
    def send_message(
        cls,
        bot_key: str,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """發送單則訊息"""
        token = ConfigManager.get_bot_token(bot_key)
        if not token:
            print(f"[Warn] 未設定 {bot_key} 的 Token")
            return False

        url = f"{get_api_base(token)}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            resp = requests.post(url, json=payload, timeout=15)
            return resp.status_code == 200 and resp.json().get("ok", False)
        except Exception as e:
            print(f"[Error] 發送訊息失敗 ({bot_key} -> {chat_id}): {e}")
            return False

    @classmethod
    def broadcast_article(cls, item: Dict[str, Any]) -> bool:
        """推播格式化的單則情報至對應 Bot"""
        bot_key = item.get("target_bot", "default")
        title = item.get("title", "")
        summary = item.get("summary", "")
        url = item.get("url", "")
        source_name = item.get("source_name", "精選情報")

        bots_cfg = ConfigManager.get_bots_config()
        channel_name = bots_cfg.get(bot_key, {}).get("name", "情報頻道")

        msg = (
            f"<b>【{channel_name}】{html.escape(title)}</b>\n\n"
            f"{summary}\n\n"
            f"📌 來源：<code>{html.escape(source_name)}</code>\n"
            f"<a href=\"{url}\">點此閱讀完整內容 ↗</a>"
        )

        chat_ids = ConfigManager.get_chat_ids(bot_key)
        success = False
        for cid in chat_ids:
            if cls.send_message(bot_key, cid, msg):
                success = True

        if success:
            InboxManager.record_push(bot_key, title, url)
        return success

    @classmethod
    def send_chat_action(cls, bot_key: str, chat_id: str, action: str = "typing"):
        """發送輸入中狀態"""
        token = ConfigManager.get_bot_token(bot_key)
        if not token:
            return
        url = f"{get_api_base(token)}/sendChatAction"
        try:
            requests.post(url, json={"chat_id": chat_id, "action": action}, timeout=5)
        except Exception:
            pass


# 5 大頻道專屬 Persona
PERSONA_MAP = {
    "finance": "資深財經投資顧問，專注在市場趨勢、資產配置、風險管理與總體經濟分析。",
    "reading": "深度閱讀教練與知識導讀專家，擅長從書籍中提煉核心思想、心智模型與實踐法則。",
    "tech": "科技產業分析師與架構師，專精 AI 前沿技術、軟體工程趨勢與產業脈動。",
    "youtube": "影音深度內容分析專家，擅長解構講者口述全片脈絡、提煉論點邏輯與精華重點。",
    "default": "全方位智慧助手，負責統籌各領域情報、為讀者提供清晰條理的解答。"
}


def query_gemini_or_synthesizer(bot_key: str, question: str, context: str = "") -> str:
    """呼叫 Gemini 或智能本地合成回答"""
    api_key = ConfigManager.get_gemini_api_key()
    persona = PERSONA_MAP.get(bot_key, PERSONA_MAP["default"])

    if api_key and api_key.strip():
        # 直連 Google 官方最新 Gemini Flash
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        prompt = (
            f"你現在是 AntiGravity Telegram 指揮中心旗下的【{persona}】。\n"
            f"請使用繁體中文（台灣標準），針對使用者的提問給出專業、邏輯清晰、結構條理的解答。\n"
        )
        if context:
            prompt += f"\n【背景參考情報內容】：\n{context}\n"
        prompt += f"\n【使用者提問】：\n{question}\n\n請直接輸出排版優美、重點鮮明之回答。"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1000}
        }
        try:
            resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=18)
            if resp.status_code == 200:
                data = resp.json()
                cands = data.get("candidates", [])
                if cands:
                    parts = cands[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
        except Exception as e:
            print(f"[Warn] Gemini API 呼叫異常: {e}")

    # 本地結構化智慧降級回答
    role_title = {
        "finance": "📈 財經顧問精析",
        "reading": "📖 導讀教練解析",
        "tech": "💻 科技分析師觀點",
        "youtube": "🎬 影音解讀專家精萃",
        "default": "🤖 駕駛艙中樞回答"
    }.get(bot_key, "🤖 智慧回答")

    if context:
        return (
            f"<b>【{role_title}・深入剖析】</b>\n\n"
            f"針對您對本則情報的提問：<i>「{html.escape(question)}」</i>\n\n"
            f"• <b>核心要點</b>：本篇深入聚焦關鍵觀點，建議關注其論述中之底層因果關係。\n"
            f"• <b>實務延伸</b>：在實際應用時，可從自身需求與限制出發進行驗證。\n"
            f"• <b>後續追蹤</b>：AntiGravity 控制中樞持續為您追蹤相關動態。\n\n"
            f"💡 <i>（已同步登錄至 AntiGravity Cockpit 互動收件匣）</i>"
        )
    else:
        return (
            f"<b>【{role_title}】</b>\n\n"
            f"收到您的諮詢：<i>「{html.escape(question)}」</i>\n\n"
            f"• <b>專業評估</b>：此問題涉及核心實務判斷，建議先確立目標再擬定執行步驟。\n"
            f"• <b>操作建議</b>：保持敏捷迭代，以數據與事實為依據進行複盤。\n\n"
            f"💡 <i>（已同步登錄至 AntiGravity Cockpit 互動收件匣）</i>"
        )


def make_keyboard(bot_key: str) -> Dict[str, Any]:
    """生成底部快捷按鈕 (第一個按鈕設定為「最新情報」)"""
    return {
        "keyboard": [
            [{"text": "最新情報"}, {"text": "🔍 監控清單"}],
            [{"text": "⏰ 推播時間"}, {"text": "📊 駕駛艙狀態"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }


def get_latest_news_for_bot(bot_key: str, name: str) -> str:
    """取得該頻道最新情報 (今日推播摘要或即時掃描)"""
    from .content_fetcher import fetch_site_content

    metrics = InboxManager.get_metrics_summary()
    today_pushes = [p for p in metrics.get("recent_pushes", []) if p.get("bot_key") == bot_key]

    if today_pushes:
        msg_lines = [
            f"📰 <b>【{name}・今日最新情報摘要】</b>\n",
            "以下為今日已推播之精選焦點：\n"
        ]
        for idx, p in enumerate(today_pushes[:3], 1):
            t = html.escape(p.get("title", ""))
            u = p.get("url", "")
            msg_lines.append(f"{idx}. <b>{t}</b>\n   🔗 <a href='{u}'>點此閱讀全文 ↗</a>\n")
        msg_lines.append("💡 <i>如需深入了解特定篇章，長按情報選擇「回覆」即可向 AI 發問！</i>")
        return "\n".join(msg_lines)

    # 若今日尚未推播該頻道，現場即時抓取新鮮情報回傳
    sites = ConfigManager.get_sites_config()
    matched_sites = [s for s in sites if s.get("target_bot", "default") == bot_key]
    if not matched_sites and bot_key == "default":
        matched_sites = sites

    for s in matched_sites:
        try:
            arts = fetch_site_content(s)
            if arts:
                art = arts[0]
                return (
                    f"📰 <b>【{name}・即時最新情資速報】</b>\n\n"
                    f"<b>{html.escape(art.get('title', ''))}</b>\n\n"
                    f"{art.get('summary', '')}\n\n"
                    f"📌 來源：<code>{html.escape(art.get('source_name', ''))}</code>\n"
                    f"<a href=\"{art.get('url', '')}\">點此閱讀完整內容 ↗</a>"
                )
        except Exception:
            continue

    return f"📰 <b>【{name}】</b>\n\n目前暫無未讀的新情報，每日排程將於 08:00, 12:00, 18:00 自動為您檢測更新！"


def run_single_bot_listener(bot_key: str, bot_data: Dict[str, Any], stop_event: threading.Event):
    """單一 Bot 的長輪詢監聽工作線程"""
    token = bot_data["token"]
    name = bot_data["name"]
    api_base = get_api_base(token)
    offset = None

    print(f"  [Fleet] 啟動監聽線程: 【{name}】 (Channel: {bot_key})")
    InboxManager.update_bot_heartbeat(bot_key, "online", "監聽輪詢中")

    # 若為總管理 Bot，確保清除左側自訂選單命令列表
    if bot_key == "default":
        try:
            requests.post(f"{api_base}/deleteMyCommands", timeout=5)
            requests.post(f"{api_base}/deleteMyCommands", json={"scope": {"type": "all_private_chats"}}, timeout=5)
            requests.post(f"{api_base}/setChatMenuButton", json={"menu_button": {"type": "default"}}, timeout=5)
        except Exception:
            pass

    while not stop_event.is_set():
        try:
            params = {"timeout": 20, "allowed_updates": ["message", "callback_query"]}
            if offset:
                params["offset"] = offset

            resp = requests.get(f"{api_base}/getUpdates", params=params, timeout=25)
            if resp.status_code == 200:
                updates = resp.json().get("result", [])
                InboxManager.update_bot_heartbeat(bot_key, "online", f"心跳正常 ({len(updates)} 筆事件)")

                for update in updates:
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if not msg:
                        continue

                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    msg_id = msg.get("message_id")
                    raw_text = (msg.get("text") or "").strip()
                    user_name = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name", "User")

                    if not raw_text:
                        continue

                    # 1. 快捷選單指令處理 (精確比對 4 大功能按鈕與斜線命令)
                    if raw_text in ["/start", "開始"]:
                        welcome_msg = (
                            f"👋 <b>歡迎使用【{name}】！</b>\n\n"
                            f"本頻道隸屬於 <b>AntiGravity 控制塔駕駛艙</b>。\n"
                            f"您可以點擊下方按鈕查詢情報，或長按情報點擊「回覆」向 AI 追問！"
                        )
                        BotFleet.send_message(bot_key, chat_id, welcome_msg, reply_markup=make_keyboard(bot_key))
                        continue

                    # 功能按鈕 1：最新情報
                    if raw_text in ["/today", "最新情報", "📰 最新情報", "今日情報", "📰 獲取今日最新情報"]:
                        BotFleet.send_chat_action(bot_key, chat_id, "typing")
                        news_reply = get_latest_news_for_bot(bot_key, name)
                        BotFleet.send_message(bot_key, chat_id, news_reply, reply_markup=make_keyboard(bot_key))
                        continue

                    # 功能按鈕 2：推播時間
                    if raw_text in ["/time", "⏰ 推播時間", "推播時間"]:
                        settings = ConfigManager.get_settings()
                        times_str = ", ".join(settings.get("schedule_times", ["08:00", "12:00", "18:00"]))
                        BotFleet.send_message(
                            bot_key,
                            chat_id,
                            f"⏰ <b>每日固定推播時間點</b>：\n<code>{times_str}</code> (台北時間)",
                            reply_markup=make_keyboard(bot_key)
                        )
                        continue

                    # 功能按鈕 3：監控清單
                    if raw_text in ["/sites", "🔍 監控清單", "監控清單"]:
                        sites = ConfigManager.get_sites_config()
                        matched = [s for s in sites if s.get("target_bot", "default") == bot_key]
                        if not matched and bot_key == "default":
                            matched = sites
                        site_list = "\n".join([f"• <b>{s.get('name')}</b> ({s.get('type')})" for s in matched]) or "（無綁定站點）"
                        BotFleet.send_message(
                            bot_key,
                            chat_id,
                            f"🔍 <b>【{name}】監控站點清單</b>：\n\n{site_list}",
                            reply_markup=make_keyboard(bot_key)
                        )
                        continue

                    # 功能按鈕 4：駕駛艙狀態
                    if raw_text in ["/cockpit", "/status", "📊 駕駛艙狀態", "駕駛艙狀態"]:
                        metrics = InboxManager.get_metrics_summary()
                        status_msg = (
                            f"📊 <b>【AntiGravity 駕駛艙中樞實況】</b>\n\n"
                            f"• 今日已推播篇數：<b>{metrics.get('today_pushes_count', 0)}</b> 篇\n"
                            f"• 待處理收件匣提問：<b>{metrics.get('pending_inbox_count', 0)}</b> 則\n"
                            f"• 頻道名稱：<b>{name}</b> ({bot_key})\n"
                            f"• 運行模式：AntiGravity 控制塔常駐守護中 🚀"
                        )
                        BotFleet.send_message(
                            bot_key,
                            chat_id,
                            status_msg,
                            reply_markup=make_keyboard(bot_key)
                        )
                        continue

                    # 2. 提問與追問處理 (Reply 引用追問 vs 直接諮詢)
                    BotFleet.send_chat_action(bot_key, chat_id, "typing")
                    context_text = ""
                    reply_msg = msg.get("reply_to_message")
                    if reply_msg and reply_msg.get("text"):
                        context_text = reply_msg.get("text", "")

                    # 登記至 Cockpit 收件匣
                    answer = query_gemini_or_synthesizer(bot_key, raw_text, context_text)
                    InboxManager.add_interaction(
                        bot_key=bot_key,
                        chat_id=chat_id,
                        user_name=user_name,
                        question=raw_text,
                        context=context_text,
                        auto_answer=answer
                    )

                    # 回傳答案
                    BotFleet.send_message(
                        bot_key=bot_key,
                        chat_id=chat_id,
                        text=answer,
                        reply_to_message_id=msg_id
                    )

            elif resp.status_code == 409:
                print(f"[Warn] {bot_key} 遭遇衝突 (409 Conflict)，稍後重試...")
                time.sleep(5)
            else:
                time.sleep(3)

        except Exception as e:
            if not stop_event.is_set():
                print(f"[Error] {bot_key} 監聽輪詢錯誤: {e}")
                time.sleep(4)
