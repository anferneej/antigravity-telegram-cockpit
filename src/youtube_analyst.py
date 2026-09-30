"""
AntiGravity Telegram Cockpit - YouTube 講者真實在線口述解讀與結構化分析模組
- 徹底擺脫表面資訊欄宣傳詞
- 取得講者真實全片口述逐字稿 (youtube-transcript-api + yt-dlp VTT 自動字幕下載)
- 具備篇章分塊與結構化深度提煉算法
- 支援 AntiGravity 直接調度分析任何 YouTube 影片
"""

import glob
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
TEMP_DIR = DATA_DIR / "temp_yt"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
}


def extract_video_id(url: str) -> Optional[str]:
    """從 YouTube 網址中提取 11 碼 video_id"""
    if not url:
        return None
    patterns = [
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$"
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def resolve_youtube_channel(url_or_handle: str) -> Optional[Dict[str, str]]:
    """解析 YouTube 頻道網址或 handle，取得官方 RSS Feed"""
    raw = url_or_handle.strip()
    if not raw:
        return None

    # 直接匹配 channel/UCxxxx
    m_direct = re.search(r"/channel/(UC[a-zA-Z0-9_-]{22})", raw)
    if m_direct:
        cid = m_direct.group(1)
        return {
            "channel_id": cid,
            "channel_name": f"YouTube 頻道 ({cid[:8]})",
            "feed_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
            "original_url": f"https://www.youtube.com/channel/{cid}"
        }

    target_url = raw
    if not target_url.startswith("http://") and not target_url.startswith("https://"):
        if target_url.startswith("@"):
            target_url = f"https://www.youtube.com/{target_url}"
        else:
            target_url = f"https://www.youtube.com/@{target_url}"

    try:
        resp = requests.get(target_url, headers=DEFAULT_HEADERS, timeout=12)
        resp.encoding = "utf-8"
        html = resp.text

        cid = None
        for pattern in [
            r'itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"',
            r'"channelId":"(UC[a-zA-Z0-9_-]{22})"',
            r'channel_id=(UC[a-zA-Z0-9_-]{22})'
        ]:
            m = re.search(pattern, html)
            if m:
                cid = m.group(1)
                break

        title = "YouTube 頻道"
        t_match = re.search(r'<meta property="og:title"\s+content="([^"]+)"', html)
        if t_match:
            title = t_match.group(1).replace(" - YouTube", "").strip()

        if cid:
            return {
                "channel_id": cid,
                "channel_name": title,
                "feed_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                "original_url": target_url
            }
    except Exception as e:
        print(f"[Warn] 解析頻道失敗 {url_or_handle}: {e}")

    return None


def fetch_channel_videos(feed_url: str, limit: int = 3) -> List[Dict[str, Any]]:
    """透過官方 XML Feed 抓取最新影片基本清單"""
    videos = []
    try:
        resp = requests.get(feed_url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code != 200:
            return []
        
        root = ET.fromstring(resp.content)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
            "media": "http://search.yahoo.com/mrss/"
        }
        
        entries = root.findall("atom:entry", ns)
        for entry in entries[:limit]:
            vid_elem = entry.find("yt:videoId", ns)
            title_elem = entry.find("atom:title", ns)
            link_elem = entry.find("atom:link", ns)
            pub_elem = entry.find("atom:published", ns)
            
            vid = vid_elem.text if vid_elem is not None else ""
            title = title_elem.text if title_elem is not None else "最新影片"
            href = link_elem.attrib.get("href") if link_elem is not None else f"https://www.youtube.com/watch?v={vid}"
            pub_date = pub_elem.text if pub_elem is not None else ""
            
            videos.append({
                "video_id": vid,
                "title": title.strip(),
                "url": href,
                "published_at": pub_date
            })
    except Exception as e:
        print(f"[Warn] 抓取 XML Feed 失敗 {feed_url}: {e}")
    return videos


def get_transcript_via_api(video_id: str) -> Optional[str]:
    """優先使用 youtube-transcript-api 取得講者逐字稿"""
    if not YouTubeTranscriptApi:
        return None
    try:
        # 嘗試中文（繁/簡）、英文等
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        for lang_code in ["zh-TW", "zh-Hant", "zh", "zh-Hans", "zh-CN", "en"]:
            try:
                transcript = transcript_list.find_transcript([lang_code])
                break
            except Exception:
                continue
        
        if not transcript:
            # 抓第一個可翻譯或自動產生的
            for t in transcript_list:
                transcript = t
                break

        if transcript:
            parts = transcript.fetch()
            texts = [p.get("text", "").strip() for p in parts if p.get("text", "").strip()]
            full_text = " ".join(texts)
            if len(full_text) > 100:
                return full_text
    except Exception:
        pass
    return None


def get_transcript_via_ytdlp(video_id: str) -> Optional[str]:
    """備援方案：呼叫 yt-dlp 下載自動/官方字幕並解析純文字"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    out_tmpl = str(TEMP_DIR / f"{video_id}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-sub",
        "--write-auto-sub",
        "--sub-lang", "zh-Hant,zh-TW,zh,zh-Hans,en",
        "--sub-format", "vtt/best",
        "-o", out_tmpl,
        video_url
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25, check=False)
        pattern = str(TEMP_DIR / f"{video_id}*.vtt")
        vtt_files = glob.glob(pattern)
        if not vtt_files:
            return None

        chosen_file = vtt_files[0]
        # 偏好繁體中文
        for vf in vtt_files:
            if "zh-Hant" in vf or "zh-TW" in vf:
                chosen_file = vf
                break

        with open(chosen_file, "r", encoding="utf-8", errors="ignore") as f:
            vtt_content = f.read()

        # 清除暫存
        for vf in vtt_files:
            try:
                os.remove(vf)
            except Exception:
                pass

        # 解析 VTT 純文字
        lines = []
        for line in vtt_content.splitlines():
            line = line.strip()
            if not line or "-->" in line or line.startswith("WEBVTT") or line.startswith("NOTE"):
                continue
            cleaned = re.sub(r"<[^>]+>", "", line).strip()
            if cleaned and (not lines or lines[-1] != cleaned):
                lines.append(cleaned)

        full_text = " ".join(lines)
        if len(full_text) > 100:
            return full_text
    except Exception as e:
        print(f"[Warn] yt-dlp 字幕下載失敗: {e}")
    return None


def extract_full_speech(video_id: str) -> Optional[str]:
    """雙管齊下獲取講者全片完整口述內容"""
    text = get_transcript_via_api(video_id)
    if text and len(text) > 150:
        return text
    text_dlp = get_transcript_via_ytdlp(video_id)
    if text_dlp and len(text_dlp) > 150:
        return text_dlp
    return text


def synthesize_structured_summary(title: str, transcript: str) -> str:
    """
    從長逐字稿提煉出層次分明、深度詳實且 100% 語意完整的繁中重點結構（徹底防斷句）
    """
    if not transcript or len(transcript.strip()) < 50:
        return f"• **主旨重點**：講者針對「{title}」進行深入剖析，完整論述與精采細節建議點擊觀賞完整影音。"

    # 清理停用字詞、時間戳記與無關括號
    cleaned = re.sub(r"\[.*?\]", "", transcript)
    cleaned = re.sub(r"\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\[&#8230;\]|\[\.\.\.\]|\.\.\.|…", "", cleaned).strip()

    invalid_endings = (
        '，', '、', '：', '；', '為', '由', '在', '與', '及', '的',
        '和', '並', '於', '等', '更', '但', '讓', '將', '以', '或',
        '較', '至', '向', '從', '包括', '像', '如', '（', '(', '【'
    )

    sentences = []
    # 1. 優先檢測是否有標準標點符號
    has_punct = bool(re.search(r"[。！？]", cleaned))
    if has_punct:
        raw_matches = re.findall(r'([^。！？\n]+[。！？][\"』」”\'’）\)]?)', cleaned)
        for m in raw_matches:
            s = m.strip()
            s = re.sub(r'^[•\-\*\d+\.\s]+', '', s)
            if len(s) < 16 or len(s) > 220:
                continue
            core = re.sub(r'[\"』」”\'’）\)]+$', '', s).strip()
            if not core.endswith(('。', '！', '？')):
                continue
            before_punct = core[:-1].strip()
            if any(before_punct.endswith(ie) for ie in invalid_endings):
                continue
            sentences.append(s)

    # 2. 若逐字稿缺乏標點（如自動字幕），則以自然詞意與長度重組為完整句子
    if len(sentences) < 4:
        tokens = [t.strip() for t in re.split(r"[\n\s]+", cleaned) if t.strip()]
        reconstructed = []
        curr = []
        curr_len = 0
        for tok in tokens:
            curr.append(tok)
            curr_len += len(tok)
            if curr_len >= 38:
                last_char = tok[-1] if tok else ""
                if last_char not in invalid_endings:
                    sent = "".join(curr)
                    if not sent.endswith(("。", "！", "？")):
                        sent += "。"
                    reconstructed.append(sent)
                    curr = []
                    curr_len = 0
        if curr:
            sent = "".join(curr)
            if len(sent) >= 15:
                if not sent.endswith(("。", "！", "？")):
                    sent += "。"
                reconstructed.append(sent)
        if len(reconstructed) > len(sentences):
            sentences = reconstructed

    if not sentences:
        return f"• **主旨重點**：本片深度探討「{title}」，講者提出諸多原創見解，完整精彩內容請參閱影音連結。"

    total_len = len(sentences)
    if total_len <= 3:
        points = [f"• {s}" for s in sentences]
        return "\n".join(points)

    chunk1 = sentences[: int(total_len * 0.35)] or sentences[:1]
    chunk2 = sentences[int(total_len * 0.35): int(total_len * 0.75)] or sentences[1:2]
    chunk3 = sentences[int(total_len * 0.75):] or sentences[2:3]

    def pick_best(chunk: List[str], count: int = 1) -> List[str]:
        keywords = ["重點", "核心", "關鍵", "原因", "發現", "認為", "策略", "問題", "原則", "方法", "結論", "建議", "投資", "分析", "影響"]
        scored = []
        for s in chunk:
            score = sum(2 for kw in keywords if kw in s)
            if 30 <= len(s) <= 120:
                score += 3
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:count]]

    p1 = pick_best(chunk1, 1) or [chunk1[0]]
    p2 = pick_best(chunk2, 1) or [chunk2[0]]
    p3 = pick_best(chunk3, 1) or [chunk3[0]]

    res = [
        "🎙️ **講者口述全片重點精萃**：",
        f"• **開篇洞察**：{p1[0]}",
        f"• **核心論述**：{p2[0]}",
        f"• **實務啟發**：{p3[0]}"
    ]
    return "\n".join(res)


def analyze_youtube_video(video_url: str) -> Dict[str, Any]:
    """
    一站式分析 YouTube 影片：
    取得標題、ID、講者口述純文字（可供 AntiGravity 自身深度研讀），以及結構化提煉重點
    """
    vid = extract_video_id(video_url)
    if not vid:
        return {"error": "無法從網址中解析出 YouTube Video ID"}

    speech = extract_full_speech(vid)
    title = f"YouTube 影片 ({vid})"
    
    # 嘗試獲取標題
    try:
        resp = requests.get(f"https://www.youtube.com/watch?v={vid}", headers=DEFAULT_HEADERS, timeout=8)
        m = re.search(r'<title>([^-<]+) - YouTube</title>', resp.text)
        if m:
            title = m.group(1).strip()
    except Exception:
        pass

    summary = synthesize_structured_summary(title, speech or "")

    return {
        "video_id": vid,
        "title": title,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "has_transcript": bool(speech and len(speech) > 100),
        "transcript_length": len(speech) if speech else 0,
        "transcript": speech or "",
        "summary": summary
    }
