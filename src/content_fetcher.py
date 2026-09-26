"""
AntiGravity Telegram Cockpit - 情報採集與結構化條列摘要模組
- 支援標準 RSS、Atom、博客來 OKAPI 與網頁爬蟲
- 繁體中文結構化 2~3 條要點提煉
- 自動與歷史紀錄進行比對去重
"""

import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import feedparser
import requests
from bs4 import BeautifulSoup

from .config_manager import ConfigManager
from .inbox_manager import InboxManager
from .youtube_analyst import fetch_channel_videos, analyze_youtube_video

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
}


def clean_html(raw_html: str) -> str:
    """清理 HTML 標籤並還原純文字"""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    # 移除 script, style
    for tag in soup(["script", "style", "nav", "footer", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_bullet_points(title: str, text: str, max_points: int = 3) -> str:
    """從長文中提取 2~3 個精簡條列繁中重點"""
    cleaned = clean_html(text)
    if not cleaned or len(cleaned) < 30:
        return f"• **概要**：{title}\n• **核心訊息**：點擊下方連結直達原文閱讀詳情。"

    sentences = re.split(r"[。！？\n]+", cleaned)
    valid = []
    for s in sentences:
        s = s.strip()
        # 排除版權聲明、社群追蹤垃圾句
        if len(s) >= 15 and not any(k in s for k in ["版權所有", "按讚追蹤", "點擊訂閱", "未經授權", "轉載請註明"]):
            valid.append(s)

    if not valid:
        return f"• **概要**：{title}\n• **重點**：詳細報導請參閱原文。"

    selected = valid[:max_points]
    points = [f"• {p}。" if not p.endswith(("。", "！", "？")) else f"• {p}" for p in selected]
    return "\n".join(points)


def fetch_okapi_articles(limit: int = 3) -> List[Dict[str, Any]]:
    """博客來 OKAPI 最新文章專屬解析器"""
    url = "https://okapi.books.com.tw/search/latest?loc=newlist"
    articles = []
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select(".list_box li, .newlist_box li, article")
        if not items:
            items = soup.find_all("li")

        for it in items:
            a_tag = it.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            href = a_tag["href"]
            if not href.startswith("http"):
                href = f"https://okapi.books.com.tw{href}"
            
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            desc_elem = it.find("p") or it.find("div", class_="desc")
            desc = desc_elem.get_text(strip=True) if desc_elem else title

            articles.append({
                "title": title,
                "url": href,
                "summary": extract_bullet_points(title, desc, max_points=2),
                "source_name": "博客來 OKAPI 閱讀生活誌",
                "published_at": datetime.now().strftime("%Y-%m-%d")
            })
            if len(articles) >= limit:
                break
    except Exception as e:
        print(f"[Warn] 抓取 OKAPI 失敗: {e}")
    return articles


def fetch_site_content(site_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """採集單一情報源的新鮮內容"""
    name = site_config.get("name", "未命名站點")
    target_bot = site_config.get("target_bot", "default")
    site_type = site_config.get("type", "rss")
    url = site_config.get("url", "")
    feed_url = site_config.get("feed_url", url)

    results = []

    # 1. 博客來 OKAPI 專屬
    if "okapi.books.com.tw" in url:
        arts = fetch_okapi_articles(limit=2)
        for a in arts:
            a["target_bot"] = target_bot
            results.append(a)
        return results

    # 2. YouTube 影音情資 (深度解讀講者口述)
    if site_type == "youtube" or "youtube.com" in url:
        vids = fetch_channel_videos(feed_url, limit=2)
        for v in vids:
            v_url = v["url"]
            if InboxManager.is_pushed(v_url):
                continue
            # 進行真實口述解讀
            analysis = analyze_youtube_video(v_url)
            results.append({
                "title": analysis.get("title", v["title"]),
                "url": v_url,
                "summary": analysis.get("summary", ""),
                "source_name": name,
                "target_bot": target_bot,
                "published_at": v.get("published_at", "")
            })
        return results

    # 3. 標準 RSS / Atom 情資
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:2]:
            link = entry.get("link", "")
            if not link or InboxManager.is_pushed(link):
                continue
            title = entry.get("title", "最新發布")
            content = entry.get("summary") or entry.get("description") or ""
            
            bullet_summary = extract_bullet_points(title, content, max_points=3)
            results.append({
                "title": title.strip(),
                "url": link.strip(),
                "summary": bullet_summary,
                "source_name": name,
                "target_bot": target_bot,
                "published_at": entry.get("published", "")
            })
    except Exception as e:
        print(f"[Warn] 抓取 RSS 失敗 {name} ({feed_url}): {e}")

    return results
