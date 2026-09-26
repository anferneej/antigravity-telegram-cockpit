"""
AntiGravity Telegram Cockpit - 核心指揮官控制台
==================================================
供 AntiGravity 及使用者全面操控與監控 5 大 Telegram Bot 艦隊。
支援指令：
  python src/cockpit.py status              # 檢視目前 5 大 Bot 實時健康狀態看板
  python src/cockpit.py daemon              # 啟動常駐守護服務 (5 Bot 雙向監聽 + 定時排程)
  python src/cockpit.py test-all            # 測試驗證 5 大 Bot 的 Telegram API 連線
  python src/cockpit.py scan [--channel X]  # 手動觸發情報採集與分流推播
  python src/cockpit.py dispatch --bot X --text "..."   # AntiGravity 直接下令推播自訂訊息
  python src/cockpit.py analyze-yt <URL> [--push]       # 解讀 YouTube 講者全片口述重點 (可選推播)
  python src/cockpit.py inbox               # 調閱來自 Telegram 用戶的最新提問佇列
  python src/cockpit.py reply --id X --text "..."       # 由 AntiGravity 回覆特定提問
==================================================
"""

import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path

# 確保輸出支援 UTF-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.config_manager import ConfigManager
from src.inbox_manager import InboxManager
from src.bot_fleet import BotFleet, run_single_bot_listener
from src.youtube_analyst import analyze_youtube_video
from src.scheduler import run_scan_and_broadcast, run_scheduler_loop
from src.dashboard import render_terminal_dashboard, render_markdown_dashboard, get_cockpit_full_state


def cmd_status(args):
    """查看駕駛艙即時看板"""
    print(render_terminal_dashboard())


def cmd_test_all(args):
    """測試所有已配置 Bot 連線"""
    bots = BotFleet.get_active_bots()
    print(f"\n[Cockpit] 🔍 開始測試 5 大 Bot 艦隊連線 (共 {len(bots)} 個配置)...")
    for key, info in bots.items():
        res = BotFleet.test_connection(key)
        if res.get("ok"):
            print(f"  ✅ 【{info['name']}】連線成功！機器人：@{res.get('username')}")
        else:
            print(f"  ❌ 【{info['name']}】連線失敗: {res.get('error')}")
    print()


def cmd_dispatch(args):
    """AntiGravity 直接推播訊息到特定 Bot"""
    bot_key = args.bot
    text = args.text
    chat_ids = ConfigManager.get_chat_ids(bot_key)
    if not chat_ids:
        print(f"[Error] 找不到 {bot_key} 頻道的目標 Chat ID")
        return

    print(f"[Cockpit] 🚀 正在透過【{bot_key}】推播至 {len(chat_ids)} 個目標...")
    success_count = 0
    for cid in chat_ids:
        if BotFleet.send_message(bot_key, cid, text):
            success_count += 1

    print(f"[Cockpit] ✅ 成功發送至 {success_count}/{len(chat_ids)} 個對話框。")


def cmd_scan(args):
    """手動掃描情報並分流推播"""
    channel = getattr(args, "channel", None)
    run_scan_and_broadcast(channel)


def cmd_analyze_yt(args):
    """解讀 YouTube 影片真實講者口述內容 (支援影片網址或頻道網址)"""
    url = args.url
    push = getattr(args, "push", False)

    print(f"\n[Cockpit] 🎬 正在解析 YouTube 影片/頻道: {url}")
    
    # 支援傳入頻道網址自動抓最新影片
    from src.youtube_analyst import extract_video_id, resolve_youtube_channel, fetch_channel_videos
    vid = extract_video_id(url)
    if not vid:
        print("  檢測到頻道網址，正在自動探測最新影片...")
        channel_info = resolve_youtube_channel(url)
        if channel_info and channel_info.get("feed_url"):
            vids = fetch_channel_videos(channel_info["feed_url"], limit=1)
            if vids:
                url = vids[0]["url"]
                print(f"  👉 鎖定最新發布影片: {vids[0]['title']} ({url})")
            else:
                print(f"[Error] 無法從該頻道取得影片清單。")
                return
        else:
            print(f"[Error] 無法解析該 YouTube 網址或頻道。")
            return

    result = analyze_youtube_video(url)
    if result.get("error"):
        print(f"[Error] {result['error']}")
        return

    print(f"\n標題：{result['title']}")
    print(f"逐字稿獲取狀態：{'✅ 成功擷取 (' + str(result['transcript_length']) + ' 字)' if result['has_transcript'] else '❌ 未取得逐字稿 (使用備援分析)'}")
    print("-" * 50)
    print(result["summary"])
    print("-" * 50)

    if push:
        item = {
            "title": result["title"],
            "url": result["url"],
            "summary": result["summary"],
            "source_name": "AntiGravity 影音特刊",
            "target_bot": "youtube"
        }
        BotFleet.broadcast_article(item)
        print("✅ 已同步推播至【影音精選情報 Bot】！")


def cmd_inbox(args):
    """檢視 Telegram 提問收件匣"""
    status_filter = getattr(args, "status", None)
    items = InboxManager.get_inbox(status=status_filter, limit=15)
    print(f"\n[Cockpit] 📥 Telegram 互動收件匣 (篩選: {status_filter or '全部'}, 共 {len(items)} 筆):")
    print("-" * 64)
    if not items:
        print("  目前尚無互動紀錄。")
    for it in items:
        status_tag = "[已回覆]" if it.get("status") == "answered" else "[⏳ 待處理]"
        print(f"  • ID: {it.get('id')} {status_tag} 來自 @{it.get('user_name')} ({it.get('bot_key')} 頻道)")
        print(f"    時間: {it.get('timestamp')}")
        print(f"    問題: {it.get('question')}")
        if it.get("context"):
            c_first = it.get("context").replace("\n", " ")[:60]
            print(f"    情境: {c_first}...")
        if it.get("answer"):
            ans_short = it.get("answer").replace("\n", " ")[:60]
            print(f"    回答: {ans_short}...")
        print("-" * 64)


def cmd_pending(args):
    """專供 AntiGravity 查看並批次處理所有待回答的 Telegram 提問"""
    items = InboxManager.get_inbox(status="pending", limit=20)
    if not items:
        print("\n[Cockpit] ✨ 目前沒有待處理的 Telegram 提問。")
        return
    print(f"\n[Cockpit] ⚠️ 發現 {len(items)} 筆來自手機的待處理提問（等待 AntiGravity 親覆）：")
    for it in items:
        print("=" * 64)
        print(f"🔹 佇列 ID: {it.get('id')} | 頻道: 【{it.get('bot_key')}】 | 用戶: @{it.get('user_name')}")
        print(f"🕒 時間: {it.get('timestamp')}")
        if it.get("context"):
            print(f"📌 背景情報內容:\n{it.get('context')}")
        print(f"❓ 使用者提問:\n{it.get('question')}")
    print("=" * 64)
    print("💡 提示：在 AntiGravity 對話框直接說「回覆該題 [ID]」即可調用 Gemini 大腦生成解答並推播！\n")


def cmd_reply(args):
    """由 AntiGravity 回覆 Telegram 用戶提問"""
    item_id = args.id
    reply_text = args.text
    items = InboxManager.get_inbox(limit=100)
    target = next((i for i in items if i.get("id") == item_id), None)
    if not target:
        print(f"[Error] 找不到收件匣 ID: {item_id}")
        return

    bot_key = target.get("bot_key", "default")
    chat_id = target.get("chat_id")
    q = target.get("question")

    formatted_msg = (
        f"<b>【AntiGravity 智慧中樞親覆】</b>\n\n"
        f"針對您的問題：<i>「{q}」</i>\n\n"
        f"{reply_text}"
    )

    if BotFleet.send_message(bot_key, chat_id, formatted_msg):
        InboxManager.mark_answered(item_id, reply_text)
        print(f"[Cockpit] ✅ 成功回傳至 @{target.get('user_name')} (ID: {chat_id})！")
    else:
        print(f"[Cockpit] ❌ 回傳失敗，請檢查 Token 與 Chat ID。")


def cmd_daemon(args):
    """啟動全艦隊常駐守護服務 (監聽 + 定時排程)"""
    print("\n" + "=" * 64)
    print("  🚀  ANTIGRAVITY TELEGRAM COCKPIT 艦隊守護常駐服務啟動中  🚀  ")
    print("=" * 64)

    active_bots = BotFleet.get_active_bots()
    if not active_bots:
        print("[Error] 未發現已配置 Token 的 Bot，請檢查 config/.env")
        return

    stop_event = threading.Event()

    # 1. 為每個 Bot 啟動獨立長輪詢線程
    threads = []
    for key, data in active_bots.items():
        t = threading.Thread(
            target=run_single_bot_listener,
            args=(key, data, stop_event),
            daemon=True,
            name=f"Thread-Bot-{key}"
        )
        t.start()
        threads.append(t)

    # 2. 啟動定時排程引擎
    sched_t = threading.Thread(
        target=run_scheduler_loop,
        args=(stop_event,),
        daemon=True,
        name="Thread-Scheduler"
    )
    sched_t.start()
    threads.append(sched_t)

    print("\n" + render_terminal_dashboard())
    print("\n  👉 常駐守護已進入待機狀態。按 Ctrl+C 可隨時中止。\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Cockpit] 收到中止訊號，正在安全關閉所有監聽器...")
        stop_event.set()
        for t in threads:
            t.join(timeout=2)
        print("[Cockpit] ✅ 服務已安全終止。")


def main():
    parser = argparse.ArgumentParser(description="AntiGravity Telegram Cockpit Master Controller")
    subparsers = parser.add_subparsers(dest="subcommand", help="子指令")

    # status
    p_status = subparsers.add_parser("status", help="檢視目前 5 大 Bot 艦隊狀態看板")
    p_status.set_defaults(func=cmd_status)

    # test-all
    p_test = subparsers.add_parser("test-all", help="測試驗證 5 大 Bot API 連線")
    p_test.set_defaults(func=cmd_test_all)

    # daemon
    p_daemon = subparsers.add_parser("daemon", help="啟動全艦隊常駐守護服務")
    p_daemon.set_defaults(func=cmd_daemon)

    # scan
    p_scan = subparsers.add_parser("scan", help="手動觸發情資掃描並推播")
    p_scan.add_argument("--channel", help="指定頻道代號 (finance, reading, tech, youtube, default)")
    p_scan.set_defaults(func=cmd_scan)

    # dispatch
    p_dispatch = subparsers.add_parser("dispatch", help="由 AntiGravity 直接下令推播自訂訊息")
    p_dispatch.add_argument("--bot", required=True, help="目標 Bot 頻道代號 (finance, reading, tech, youtube, default)")
    p_dispatch.add_argument("--text", required=True, help="推播文字內容")
    p_dispatch.set_defaults(func=cmd_dispatch)

    # analyze-yt
    p_yt = subparsers.add_parser("analyze-yt", help="解讀 YouTube 講者全片口述重點")
    p_yt.add_argument("url", help="YouTube 影片網址")
    p_yt.add_argument("--push", action="store_true", help="是否直接推播至影音頻道")
    p_yt.set_defaults(func=cmd_analyze_yt)

    # inbox
    p_inbox = subparsers.add_parser("inbox", help="查看 Telegram 互動收件匣")
    p_inbox.add_argument("--status", choices=["pending", "answered"], help="依狀態篩選")
    p_inbox.set_defaults(func=cmd_inbox)

    # pending
    p_pending = subparsers.add_parser("pending", help="查看所有待回答的 Telegram 提問佇列")
    p_pending.set_defaults(func=cmd_pending)

    # reply
    p_reply = subparsers.add_parser("reply", help="回覆 Telegram 用戶提問")
    p_reply.add_argument("--id", required=True, help="收件匣項目 ID")
    p_reply.add_argument("--text", required=True, help="回覆內容")
    p_reply.set_defaults(func=cmd_reply)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        cmd_status(args)


if __name__ == "__main__":
    main()
