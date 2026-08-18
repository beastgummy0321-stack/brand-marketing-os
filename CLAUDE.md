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

## 模組地標（2026-08-19 盤點）

紅＝有超 800 行檔或高風險糾纏；黃＝依賴面大或含危險區；綠＝邊界乾淨。
import 環已清零（8/14 的五組環隨智庫路由搬出 brand_web 拆除）；唯一軟環＝core⇄intake（settings.py:111 函式內延遲 import，刻意設計）。

- `app/ads` 紅｜66 檔 18k 行；reading.py 1039、repository.py 856 超標；Meta API（meta_api.py:20）＋共用狀態 PROVIDER（creative.py:29）＋LLM 呼叫 3 處＋DB 寫入散布 29 檔
- `app/brand_web` 紅｜routes.py 1850 超標＝現存最大檔；LLM 呼叫 3 檔；渲染 34 頁 Jinja
- `app/brand_intelligence` 紅｜repository.py 1641 超標；被 6 包依賴＝全站樞紐；本身不叫 LLM／Meta
- `app/templates`＋`app/static` 紅｜Jinja 66 實頁（ads 23＋brand_web 34＋intake 9）由各業務包直接渲染，T4 整批刪
- `app/intake` 黃｜routes.py 848 行貼線；LLM 呼叫（ai.py:22）；建檔精靈舊頁仍在 Jinja
- `app/core` 黃｜全部包依賴的地基；DB 寫入 8 檔；金鑰在 settings.py
- `app/llm` 黃｜Anthropic 呼叫會花錢（providers.py:315、334）；單向 import brand_intelligence
- `app/shared` 黃｜303 行小包被 6 處依賴；全站共用同一 DB 連線物件（web.py:47）
- `app/orders` 黃｜單向依賴 ads；main.py 注入避免回頭
- `app/dashboard` 黃｜依賴 7 包的葉節點；直接摸他包私有變數（routes_jobs_api.py:24-26），T4 修
- `app/creative` 綠｜821 行，0 跨包 import
- `app/tools` 綠｜唯讀探針工具，無人依賴
- `app/methodology` 綠｜prompt 內容庫，非程式碼
- `frontend/` 綠｜React 新殼 218 檔；只經 `/api` JSON 溝通（2 處註明理由的舊頁例外：api.ts:153、libraryApi.ts:321）；16 條路由、11 個頁面

## 畫面遷移現況（2026-08-19）

- 已在 React：收件匣、駕駛艙、品牌智庫、產品清單／詳情、檔期清單、作戰室、素材工作檯、矩陣頁、設定、建檔精靈、追蹤健檢兩頁
- 仍在 Jinja：66 實頁——廣告檔期 23、品牌／產品管理與報表 34、建檔精靈舊版 9
- 遷移順序照 `BOARD.md` 排定執行

## Agent skills

- 議題追蹤：markdown 檔存於 `.scratch/<effort>/issues/`——見 `docs/agents/issue-tracker.md`
- 分類標籤：五個標準標籤（`needs-triage`／`needs-info`／`ready-for-agent`／`ready-for-human`／`wontfix`）——見 `docs/agents/triage-labels.md`
- 領域文件：單一 context，根目錄 `CONTEXT.md` ＋ `docs/adr/`——見 `docs/agents/domain.md`
