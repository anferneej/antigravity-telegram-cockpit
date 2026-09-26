"""
AntiGravity Telegram Cockpit - 互動收件匣與運行監控管理模組
- 管理來自 Telegram 用戶的追問與諮詢佇列 (data/inbox.json)
- 記錄 5 大 Bot 艦隊心跳與健康指標 (data/metrics.json)
- 線程安全 (Thread-Safe)，防止多線程並行寫入競爭
"""

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
INBOX_FILE = DATA_DIR / "inbox.json"
METRICS_FILE = DATA_DIR / "metrics.json"
HISTORY_FILE = DATA_DIR / "history.json"

_IO_LOCK = threading.Lock()


class InboxManager:
    @staticmethod
    def _load_json_unlocked(file_path: Path, default_val: Any) -> Any:
        if not file_path.exists():
            return default_val
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default_val

    @staticmethod
    def _save_json_unlocked(file_path: Path, data: Any):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Error] 寫入 {file_path.name} 失敗: {e}")

    @classmethod
    def update_bot_heartbeat(cls, bot_key: str, status: str = "online", details: str = ""):
        """更新單一 Bot 的健康狀態與心跳時間 (線程安全)"""
        with _IO_LOCK:
            metrics = cls._load_json_unlocked(METRICS_FILE, {"bots": {}, "pushes": []})
            if "bots" not in metrics:
                metrics["bots"] = {}
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            metrics["bots"][bot_key] = {
                "status": status,
                "last_heartbeat": now_str,
                "details": details
            }
            cls._save_json_unlocked(METRICS_FILE, metrics)

    @classmethod
    def add_interaction(
        cls,
        bot_key: str,
        chat_id: str,
        user_name: str,
        question: str,
        context: Optional[str] = None,
        auto_answer: Optional[str] = None
    ) -> Dict[str, Any]:
        """記錄一筆來自 Telegram 的提問/回覆 (線程安全)"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item_id = str(uuid.uuid4())[:8]

        record = {
            "id": item_id,
            "timestamp": now_str,
            "bot_key": bot_key,
            "chat_id": str(chat_id),
            "user_name": user_name or "Unknown",
            "question": question,
            "context": context or "",
            "status": "answered" if auto_answer else "pending",
            "answer": auto_answer or ""
        }
        with _IO_LOCK:
            items = cls._load_json_unlocked(INBOX_FILE, [])
            items.insert(0, record)
            if len(items) > 300:
                items = items[:300]
            cls._save_json_unlocked(INBOX_FILE, items)
        return record

    @classmethod
    def get_inbox(cls, status: Optional[str] = None, limit: int = 15) -> List[Dict[str, Any]]:
        """讀取收件匣 (線程安全)"""
        with _IO_LOCK:
            items = cls._load_json_unlocked(INBOX_FILE, [])
            if status:
                items = [it for it in items if it.get("status") == status]
            return items[:limit]

    @classmethod
    def mark_answered(cls, item_id: str, answer: str) -> bool:
        """標記已回覆並更新答案 (線程安全)"""
        with _IO_LOCK:
            items = cls._load_json_unlocked(INBOX_FILE, [])
            found = False
            for it in items:
                if it.get("id") == item_id:
                    it["status"] = "answered"
                    it["answer"] = answer
                    it["answered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    found = True
                    break
            if found:
                cls._save_json_unlocked(INBOX_FILE, items)
            return found

    @classmethod
    def record_push(cls, bot_key: str, title: str, url: str):
        """記錄推播歷史與計數 (線程安全)"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_str = datetime.now().strftime("%Y-%m-%d")

        with _IO_LOCK:
            # 1. 寫入 history.json
            history = cls._load_json_unlocked(HISTORY_FILE, [])
            if url not in history:
                history.append(url)
                if len(history) > 1000:
                    history = history[-1000:]
                cls._save_json_unlocked(HISTORY_FILE, history)

            # 2. 寫入 metrics.json
            metrics = cls._load_json_unlocked(METRICS_FILE, {"bots": {}, "pushes": []})
            if "pushes" not in metrics:
                metrics["pushes"] = []
            metrics["pushes"].insert(0, {
                "date": today_str,
                "time": now_str,
                "bot_key": bot_key,
                "title": title,
                "url": url
            })
            if len(metrics["pushes"]) > 200:
                metrics["pushes"] = metrics["pushes"][:200]
            cls._save_json_unlocked(METRICS_FILE, metrics)

    @classmethod
    def is_pushed(cls, url: str) -> bool:
        """檢查該連結是否已推播過 (線程安全)"""
        with _IO_LOCK:
            history = cls._load_json_unlocked(HISTORY_FILE, [])
            return url in history

    @classmethod
    def get_metrics_summary(cls) -> Dict[str, Any]:
        """彙整全體艦隊健康指標摘要 (線程安全)"""
        with _IO_LOCK:
            metrics = cls._load_json_unlocked(METRICS_FILE, {"bots": {}, "pushes": []})
            inbox = cls._load_json_unlocked(INBOX_FILE, [])

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_pushes = [p for p in metrics.get("pushes", []) if p.get("date") == today_str]
        pending_count = len([i for i in inbox if i.get("status") == "pending"])

        return {
            "bots": metrics.get("bots", {}),
            "today_pushes_count": len(today_pushes),
            "pending_inbox_count": pending_count,
            "recent_pushes": today_pushes[:5]
        }
