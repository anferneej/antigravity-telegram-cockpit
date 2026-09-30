"""
AntiGravity Telegram Cockpit - 情報採集與結構化完整摘要模組
- 支援標準 RSS、Atom、博客來 OKAPI 與網頁爬蟲
- 繁體中文 100% 完整語意摘要（嚴格防斷句演算法、去截斷符號、自動網頁補全）
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
    """清理 HTML 標籤、廣告、腳本並還原純文字"""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_web_article_text(url: str) -> str:
    """
    當 RSS 僅提供截斷摘要或無內文時，深入原文網址抓取真實內文段落
    """
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=8)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", ".ad", ".ad-container", ".fb-like", ".recommend", ".social-share"]):
            tag.decompose()

        # 鎖定正文主體容器
        container = (
            soup.find("article") or
            soup.find(class_=re.compile(r"(entry-content|article-content|post-content|story-body|news-content|article-body|content-main)", re.I)) or
            soup.find("main") or
            soup.body
        )
        if not container:
            return ""

        paragraphs = []
        for p in container.find_all("p"):
            txt = clean_html(str(p))
            # 排除社群訂閱、登入提示等雜訊段落
            if len(txt) >= 20 and not any(k in txt for k in ["版權所有", "未經授權", "轉載請註明", "會員登入", "點此訂閱", "追蹤粉專", "請參閱著作權"]):
                paragraphs.append(txt)

        return "\n".join(paragraphs)
    except Exception:
        return ""


def extract_complete_sentences(text: str) -> List[str]:
    """
    自文本中提取語意完整且標點閉合的獨立句子（徹底根絕斷句問題）
    """
    if not text:
        return []
    cleaned = clean_html(text)
    # 清理截斷符號與外連指示詞
    cleaned = re.sub(r"\[&#8230;\]|\[\.\.\.\]|\.\.\.|…|\[更多.*?\]|\[繼續閱讀.*?\]", "", cleaned)
    cleaned = re.sub(r"若想立刻加入.*?|客服專線.*?|洽詢專線.*?|如需更多資訊.*?|會員專屬.*?", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", cleaned))
    is_cjk = cjk_count > 15

    if is_cjk:
        pattern = r'([^。！？\n]+[。！？][\"』」”\'’）\)]?)'
        invalid_endings = (
            '，', '、', '：', '；', '為', '由', '在', '與', '及', '的',
            '和', '並', '於', '等', '更', '但', '讓', '將', '以', '或',
            '較', '至', '向', '從', '包括', '像', '如', '（', '(', '【'
        )
    else:
        pattern = r'([^.!?\n]+[.!?][\"\'\)]?)'
        invalid_endings = (',', ':', ';', 'and', 'or', 'the', 'in', 'on', 'at', 'to', 'for', 'with', 'by', 'as', 'of', '(')

    matches = re.findall(pattern, cleaned)
    valid = []
    for m in matches:
        s = m.strip()
        # 清除開頭的序號、點符號、圖片出處標籤
        s = re.sub(r'^[•\-\*\d+\.\s]+', '', s)
        s = re.sub(r'^[（\(]圖[／/].*?[）\)]\s*', '', s)
        # 排除版權聲明、社群追蹤、客服垃圾句
        if any(marker in s for marker in [
            '版權所有', '未經授權', '轉載請註明', '會員登入', '訂閱電子報',
            '追蹤我們', '按讚追蹤', '點擊訂閱', '請登入', '人才招募', '常見問題',
            '客服專線', '洽詢', '加入會員', '付費"Research"'
        ]):
            continue

        min_len = 16 if is_cjk else 30
        max_len = 240 if is_cjk else 320
        if len(s) < min_len or len(s) > max_len:
            continue

        # 嚴格校驗：結尾必須是完整的標點符號
        core = re.sub(r'[\"』」”\'’）\)]+$', '', s).strip()
        end_punct = ('。', '！', '？') if is_cjk else ('.', '!', '?')
        if not core.endswith(end_punct):
            continue

        # 嚴格防斷句：標點前不得為未完結之助詞、介詞、連詞或逗號
        before_punct = core[:-1].strip()
        if any(before_punct.endswith(ie) for ie in invalid_endings):
            continue

        valid.append(s)
    return valid


def select_best_summary_sentences(title: str, sentences: List[str], count: int = 3) -> List[str]:
    """
    從完整句子池中評分並挑選最契合主旨的 2~3 句，依原文邏輯順序輸出
    """
    if not sentences:
        return []
    if len(sentences) <= count:
        return sentences

    clean_title = re.sub(r'[【】「」《》：:、，,\s]+', ' ', title)
    title_words = set(w for w in re.findall(r'[\u4e00-\u9fff]{2,5}|[a-zA-Z0-9]{2,}', clean_title) if len(w) >= 2)

    informative_markers = [
        "指出", "表示", "認為", "強調", "發現", "顯示", "預估", "預計", "宣布", "核心",
        "關鍵", "原因", "主要", "影響", "透過", "帶動", "因此", "總結", "建議", "重點",
        "策略", "分析", "首度", "新高", "成長", "市場", "增加", "投資", "發展", "未來"
    ]
    boilerplate_markers = [
        "歡迎", "點擊", "專欄", "粉絲團", "作者介紹", "按讚", "留言", "追蹤", "分享",
        "訂閱", "電子報", "加入會員", "小編", "編輯部"
    ]

    scored = []
    for idx, s in enumerate(sentences):
        score = 0
        # 標題關鍵詞匹配度 (權重最高)
        for tw in title_words:
            if tw in s:
                score += 4
        # 核心論述關鍵詞
        for kw in informative_markers:
            if kw in s:
                score += 2
        # 扣減樣板廢話
        for bp in boilerplate_markers:
            if bp in s:
                score -= 10

        # 段落位置加權（前段通常是核心結論）
        if idx < 3:
            score += 3
        elif idx < 6:
            score += 1

        # 適中長度加權 (40~140 字閱讀感最佳)
        if 35 <= len(s) <= 150:
            score += 3

        scored.append((score, idx, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_items = scored[:count]
    # 按照原文先後順序排列，保持語意流暢
    top_items.sort(key=lambda x: x[1])
    return [item[2] for item in top_items]


def extract_bullet_points(title: str, text: str, url: str = "", max_points: int = 3) -> str:
    """
    從長文或網頁中提取完整、無斷句之 2~3 條繁中重點
    若傳入文字不足或遭來源端截斷，自動深入原文網址補全
    """
    sentences = extract_complete_sentences(text)

    # 若現有文字無法提煉出足夠的完整句子，且有原文 URL，則主動抓取網頁正文
    if len(sentences) < 2 and url and url.startswith("http"):
        web_text = fetch_web_article_text(url)
        if web_text:
            web_sentences = extract_complete_sentences(web_text)
            if len(web_sentences) >= len(sentences):
                sentences = web_sentences

    if not sentences:
        # 保底退回完整語意宣告句（絕不斷句）
        return f"• **核心焦點**：本文深度聚焦「{title}」，詳細內容與完整分析請參閱原文報導。"

    selected = select_best_summary_sentences(title, sentences, count=max_points)
    points = [f"• {p}" for p in selected]
    return "\n".join(points)


def fetch_okapi_articles(limit: int = 3) -> List[Dict[str, Any]]:
    """博客來 OKAPI 最新文章專屬解析器 (排除導覽列，精準鎖定書籍深度導讀文章)"""
    url = "https://okapi.books.com.tw/search/latest?loc=newlist"
    articles = []
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")

        # 鎖定含有 /article/ 的真實書籍與專欄連結
        seen_urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/article/" not in href:
                continue
            if not href.startswith("http"):
                href = f"https://okapi.books.com.tw{href}"

            clean_url = href.split("?")[0]
            if clean_url in seen_urls or InboxManager.is_pushed(clean_url):
                continue

            title = a_tag.get_text(strip=True)
            # 排除選單項目與短字
            if not title or len(title) < 6 or any(k in title for k in ["HOME", "大人物", "所有分類", "閱讀生活誌", "閱讀推薦"]):
                continue

            seen_urls.add(clean_url)

            # 抓取該篇文章頁面以取得完整內文
            art_text = fetch_web_article_text(href)
            summary = extract_bullet_points(title, art_text, url=href, max_points=2)

            articles.append({
                "title": title,
                "url": clean_url,
                "summary": summary,
                "source_name": "博客來 OKAPI 閱讀生活誌",
                "published_at": datetime.now().strftime("%Y-%m-%d")
            })
            if len(articles) >= limit:
                break
    except Exception as e:
        print(f"[Warn] 抓取 OKAPI 失敗: {e}")
    return articles


def fetch_site_content(site_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """採集單一情報源的新鮮內容 (自動深度提取與防斷句)"""
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
            
            # 優先採用完整的 content，次之採用 summary/description
            content = ""
            if "content" in entry and entry.content:
                content = entry.content[0].get("value", "")
            if not content or len(content.strip()) < 50:
                content = entry.get("summary") or entry.get("description") or ""

            bullet_summary = extract_bullet_points(title, content, url=link, max_points=3)
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
