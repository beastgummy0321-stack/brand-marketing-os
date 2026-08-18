# CLAUDE.md

品牌行銷作業系統：Python + FastAPI + SQLite，單機單人使用。前端過渡期並存：
舊頁 Jinja 直出，新殼 React＋Vite（`frontend/`，`npm run build` 產出掛載於 `/app`，ADR 0003）。

- 語言：繁體中文；使用者非工程背景，回報用白話文，術語第一次出現附一句白話說明
- 不確定就問，不要猜；覆蓋前必須先確認
- 刪除、覆蓋、對外發布、花錢：先說明後果並等使用者確認，不得逕行執行

## 開場廣播

- 開新對話先讀根目錄 `BOARD.md`；有 `[>]` 進行中的票，主動報「哪張票、進度、卡在哪」
- 看板只放未開始與進行中的票；完成即刪行，歷史查 git log

## 快速事實

- 啟動：雙擊 `啟動行銷系統.bat`，介面在 http://localhost:8710/
- 資料庫：`data/app.db`（不進版控），每日備份在 `backups/`
- AI 金鑰：`.env` 裡的 `ANTHROPIC_API_KEY`（不進版控）
- 測試：`python -m pytest app/tests`
- 共同語彙：`CONTEXT.md`
- 過往決策：`docs/adr/`（需要時再查，不必每次讀）
- 技術債與機器閘門：`docs/tech-debt.md`——動超標檔案或跨 `llm`／`brand_intelligence` 依賴前先讀
- `app/methodology/` 是程式零件不是文件：內容會被組進 AI 的 prompt，刪改一律先問使用者
- 舊工程紀錄封存於 `archive/old-workdocs/`（2026-08-14 封存，唯讀，不得引用為現行規範）

## 模組地標（2026-08-14 盤點）

紅＝在 import 環內、或有超 800 行檔、或跨包雙向依賴；黃＝依賴面大或含危險區；綠＝邊界乾淨。

- `app/ads` 紅｜64 檔 17k 行；與 orders／creative／dashboard／brand_intelligence 雙向；Meta API（meta_api.py）＋共用狀態 PROVIDER（creative.py:29）＋DB 寫入散布 10+ 檔
- `app/brand_intelligence` 紅｜五組 import 環的根源；routes.py 1805、repository.py 1641 超標；解法見 tech-debt.md 第二節
- `app/templates`＋`app/static` 紅｜96 份 Jinja 模板由各業務包直接渲染，前後端糾纏主因
- `app/intake` 黃｜環的連帶端；routes.py 848 行貼線；建檔精靈九頁仍在 Jinja
- `app/core` 黃｜全部包依賴的地基；DB 寫入點多；金鑰在 settings.py
- `app/llm` 黃｜Anthropic 呼叫會花錢（providers.py:257-328）；與 brand_intelligence 成環
- `app/shared` 黃｜303 行小包被 6 包依賴；反向 import brand_intelligence（環）
- `app/orders` 黃｜與 ads 雙向；main.py 以 9 個注入點單向化
- `app/creative` 黃｜與 ads 雙向
- `app/dashboard` 黃｜import 6 包的葉節點，無人依賴它
- `app/tools` 綠｜唯讀探針工具，無人依賴
- `app/methodology` 綠｜prompt 內容庫，非程式碼
- `frontend/` 綠｜React 新殼 157 檔；只經 `/api` JSON 溝通；14 條路由、10 個頁面

## 畫面遷移現況（2026-08-14）

- 已在 React：收件匣、駕駛艙、品牌智庫、產品清單／詳情、檔期清單、作戰室、素材工作檯、矩陣頁、設定
- 仍在 Jinja：建檔精靈九步、廣告 20+ 頁、品牌管理三頁、產品編輯面板、報表三頁
- 遷移順序照 `BOARD.md` 排定執行

## Agent skills

- 議題追蹤：markdown 檔存於 `.scratch/<effort>/issues/`——見 `docs/agents/issue-tracker.md`
- 分類標籤：五個標準標籤（`needs-triage`／`needs-info`／`ready-for-agent`／`ready-for-human`／`wontfix`）——見 `docs/agents/triage-labels.md`
- 領域文件：單一 context，根目錄 `CONTEXT.md` ＋ `docs/adr/`——見 `docs/agents/domain.md`
