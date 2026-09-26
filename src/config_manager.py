"""
AntiGravity Telegram Cockpit - 設定與環境管理器
統一管理 bots.json, sites.json, settings.json, .env
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

ENV_FILE = CONFIG_DIR / ".env"
BOTS_FILE = CONFIG_DIR / "bots.json"
SITES_FILE = CONFIG_DIR / "sites.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# 自動載入環境變數
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)


class ConfigManager:
    @staticmethod
    def get_bots_config() -> Dict[str, Any]:
        if not BOTS_FILE.exists():
            return {}
        try:
            with open(BOTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Error] 讀取 bots.json 失敗: {e}")
            return {}

    @staticmethod
    def get_sites_config() -> List[Dict[str, Any]]:
        if not SITES_FILE.exists():
            return []
        try:
            with open(SITES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return data.get("sites", [])
        except Exception as e:
            print(f"[Error] 讀取 sites.json 失敗: {e}")
            return []

    @staticmethod
    def get_settings() -> Dict[str, Any]:
        if not SETTINGS_FILE.exists():
            return {
                "timezone": "Asia/Taipei",
                "schedule_times": ["08:00", "12:00", "18:00"],
                "max_articles_per_site": 2
            }
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"timezone": "Asia/Taipei", "schedule_times": ["08:00", "12:00", "18:00"]}

    @staticmethod
    def get_bot_token(bot_key: str) -> Optional[str]:
        """從環境變數取得特定 Bot 的 Token"""
        bots_cfg = ConfigManager.get_bots_config()
        bot_info = bots_cfg.get(bot_key, {})
        env_var = bot_info.get("token_env")
        if env_var:
            token = os.getenv(env_var)
            if token and token.strip():
                return token.strip()
        # 退回預設
        return os.getenv("TELEGRAM_BOT_TOKEN")

    @staticmethod
    def get_chat_ids(bot_key: str = "default") -> List[str]:
        """取得目標 Chat ID 列表"""
        bots_cfg = ConfigManager.get_bots_config()
        bot_info = bots_cfg.get(bot_key, {})
        
        # 1. 優先檢查 bots.json 內的 chat_ids 陣列
        chat_ids = bot_info.get("chat_ids", [])
        if chat_ids:
            return chat_ids

        # 2. 檢查專屬 chat_id_env
        env_var = bot_info.get("chat_id_env")
        if env_var:
            raw_id = os.getenv(env_var)
            if raw_id:
                return [cid.strip() for cid in raw_id.split(",") if cid.strip()]

        # 3. 退回預設 TELEGRAM_CHAT_ID
        raw_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if raw_chat_id:
            return [cid.strip() for cid in raw_chat_id.split(",") if cid.strip()]
        return []

    @staticmethod
    def get_gemini_api_key() -> Optional[str]:
        return os.getenv("GEMINI_API_KEY")
