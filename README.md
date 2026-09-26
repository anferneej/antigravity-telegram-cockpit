# 🛰️ AntiGravity Telegram Cockpit (中央控制塔駕駛艙)

本專案是 **以 AntiGravity 為智慧中樞與指揮塔** 的 Telegram 多頻道情報與雙向互動體系。
透過本控制中樞，您可以在 AntiGravity 視窗中直接操控、監控 5 大 Telegram Bot 艦隊，並結合大模型智慧進行深度內容解讀。

---

## 艦隊架構與頻道分工

| 頻道名稱 | 識別 Key | 綁定 Telegram 帳號 | 監控情資焦點 | 專屬 AI Persona |
| :--- | :---: | :---: | :--- | :--- |
| **💰 財經投資情報** | `finance` | `@Anf_finance_bot` | 華爾街日報、DIGITIMES 產經與供應鏈、聚財網 | 資深財經投資顧問 |
| **📚 閱讀書摘導讀** | `reading` | `@Anf_reading_bot` | 博客來 OKAPI、閱讀前哨站、蔡依橙、綠角等 | 深度閱讀導讀教練 |
| **⚡ 科技產業情報** | `tech` | `@Anf_tech_bot` | 科技新報、DIGITIMES 科技焦點 | 科技產業分析師 |
| **🎬 影音精選情報** | `youtube` | `@Anf_YT_bot` | 7 大精選頻道全片講者口述逐字稿深度提煉 | 影音精選深度分析師 |
| **🤖 綜合預設頻道** | `default` | `@Anf_home_bot` | 系統重要廣播、通用諮詢、備援接收端 | 全方位指揮官助理 |

---

## 🎮 在 AntiGravity 中隨時操控與監控

您無需打開黑色終端機，只要在 AntiGravity 對話框直接對 AI 下令即可：

### 1. 📊 即時監控艦隊
```bash
python src/cockpit.py status
```
* 查看 5 個 Bot 是否在線、最新心跳時間、今日推播數量、待處理的 Telegram 提問。

### 2. 🚀 直接派發推播 (Direct Dispatch)
```bash
python src/cockpit.py dispatch --bot youtube --text "🎬 本週推薦專題..."
python src/cockpit.py dispatch --bot finance --text "📈 市場最新即時焦點..."
```

### 3. 🎙️ 深度解讀 YouTube 影片口述重點
```bash
# 輸入影片網址或頻道 Handle，自動取得講者真實全片逐字稿並結構化提煉（--push 可直接發送）
python src/cockpit.py analyze-yt https://www.youtube.com/@betterleaf --push
```

### 4. 📥 檢視與回覆 Telegram 使用者提問
```bash
# 查看手機用戶在 Telegram 提出的問題
python src/cockpit.py inbox

# 由 AntiGravity 智慧中樞親自回覆指定問題
python src/cockpit.py reply --id <INBOX_ID> --text "..."
```

### 5. ⏰ 手動觸發情報掃描與定時守護
```bash
# 立即手動掃描所有 23 個情資源並推播
python src/cockpit.py scan

# 啟動 5 大 Bot 雙向監聽與背景定時排程 (08:00, 12:00, 18:00)
python src/cockpit.py daemon
```

---

## 🔄 AntiGravity 關閉後重開的啟動方式

當您重開電腦或重新開啟 AntiGravity 時，有 **3 種最輕鬆的開啟方式**：

1. **【最直覺・對話一秒開啟】**：
   * 在 AntiGravity 對話視窗直接說：**「TG 開工」** 或 **「啟動駕駛艙」**。
   * AI 會自動在背景啟動守護進程，並回報各 Bot 連線狀態。
2. **【最快速・滑鼠雙擊啟動】**：
   * 直接雙擊專案目錄底下的 **`啟動駕駛艙.bat`**。
   * 會自動開啟視窗並常駐監聽，隨時按 `Ctrl+C` 即可中止。
3. **【終端機標準啟動】**：
   ```bash
   python -u src/cockpit.py daemon
   ```

---

## 📁 檔案結構

```
E:\antigravity-telegram-cockpit\
├── config/
│   ├── .env               # 儲存 5 組真實 Bot Token 與 Chat ID（受 .gitignore 保護）
│   ├── bots.json          # 5 大 Bot 的名稱、Token 變數與目標定義
│   ├── settings.json      # 時區與每日定時排程時間點
│   └── sites.json         # 23 個精選來源（含 7 個 YouTube 官方 XML Feed）
├── data/
│   ├── history.json       # 已推播連結去重庫
│   ├── inbox.json         # 雙向互動提問佇列（線程安全保護）
│   └── metrics.json       # 實時健康心跳與推播計數器
├── src/
│   ├── cockpit.py         # ★ 核心指揮官控制台 (CLI 與 Agent 介面)
│   ├── bot_fleet.py       # 5 大 Bot 艦隊管理、長輪詢監聽與專屬 Persona
│   ├── youtube_analyst.py # 深入全片口述之字幕/音軌提煉引擎
│   ├── content_fetcher.py # RSS / 博客來 OKAPI / 網頁新聞採集器
│   ├── scheduler.py       # 每日定時任務排程器
│   └── dashboard.py       # 駕駛艙狀態儀表板渲染器
├── requirements.txt
└── README.md
```
