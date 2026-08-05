# CLAUDE.md

品牌行銷作業系統：Python + FastAPI + SQLite，單機單人使用。前端過渡期並存：舊頁 Jinja 直出，新殼 React＋Vite（`frontend/`，`npm run build` 產出掛載於 `/app`，ADR 0003）。

- 啟動：雙擊 `啟動行銷系統.bat`，介面在 http://localhost:8710/
- 資料庫：`data/app.db`（不進版控），每日備份在 `backups/`
- AI 金鑰：`.env` 裡的 `ANTHROPIC_API_KEY`（不進版控）
- 測試：`python -m pytest app/tests`
- `app/methodology/` 是**程式零件不是文件**——內容會被組進 AI 的 prompt，刪掉會讓生成品質下降
- 共同語彙、文件修剪詞彙：`CONTEXT.md`
- 過往決策：`docs/adr/`（需要時再查，不必每次讀）
