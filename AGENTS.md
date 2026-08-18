# AGENTS.md

品牌行銷作業系統：Python + FastAPI + SQLite，單機單人使用。Codex 專用，規則與同目錄 CLAUDE.md 等價。

- 語言：繁體中文
- 動工前一律完整讀取本目錄的 `CLAUDE.md`（啟動方式、資料庫位置、測試指令、共同語彙、技術債登記、過往決策）
- `app/methodology/` 是程式零件不是文件：內容會被組進 AI 的 prompt，刪除或改寫一律先問使用者
- 刪除、覆蓋、對外發布、花錢：先說明後果並等使用者確認，不得逕行執行

## Agent skills

### Issue tracker

議題以 markdown 檔存放於 `.scratch/<effort>/issues/`。見 `docs/agents/issue-tracker.md`。

### Triage labels

沿用五個標準分類標籤（`needs-triage`／`needs-info`／`ready-for-agent`／`ready-for-human`／`wontfix`）。見 `docs/agents/triage-labels.md`。

### Domain docs

單一 context：根目錄 `CONTEXT.md` ＋ `docs/adr/`。見 `docs/agents/domain.md`。
