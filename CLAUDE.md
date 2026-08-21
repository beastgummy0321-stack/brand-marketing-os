# CLAUDE.md

品牌行銷作業系統：Python + FastAPI + SQLite，單機單人使用。
前端 React＋Vite（`frontend/`，`npm run build` 後掛載於 `/app`）；後端只出 `/api` JSON。

- 繁體中文；使用者非工程背景，回報用白話，術語第一次出現附一句說明
- 不確定就問，不要猜
- 刪除、覆蓋、對外發布、花錢：先說後果，等確認

## 開場

讀 `BOARD.md`；有 `[>]` 的票，主動報「哪張、進度、卡在哪」。看板只放未完成，完成即刪行。

## 快速事實

- 啟動：`啟動行銷系統.bat` → http://localhost:8710/
- 資料庫 `data/app.db`、備份 `backups/`、金鑰 `.env`（皆不進版控）
- 測試：`python -m pytest app/tests`
- 語彙 `CONTEXT.md`；決策 `docs/adr/`；技術債與機器閘門 `docs/tech-debt.md`（動超標檔前先讀）
- `app/methodology/` 是 prompt 零件不是文件，刪改先問
- 議題：`.scratch/<effort>/issues/`，規則見 `docs/agents/`
