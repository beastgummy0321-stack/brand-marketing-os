# CLAUDE.md

## 憲法摘要（給人讀的 10 行；細節 ADR 0027）

1. 目標＝**多租戶雲端 SaaS**。單機是現在的部署形態，不是設計前提；不得以「單機單人」為由簡化。
2. 資料模型三層：**組織 → 使用者 → 品牌**。每張表必有 `org_id`。
3. 平台：Supabase（Postgres／Auth／Storage／Vault）；前端只跟 FastAPI 講話。
4. 原生 SQL、不用 ORM；migration 由 Supabase CLI 管，集中 `supabase/migrations/`。
5. 背景工作走 procrastinate，handler 可重跑、只碰自己組織。
6. 手動路徑永遠一級公民；自動化是加法。
7. 新模組＝新資料夾＋自己的 migrations＋前端 feature 資料夾，不碰別人的表。
8. 先找現成、驗證過的套件，回報 ≤3 個候選再問；不自建連線池、佇列、migration runner。
9. 動 schema、金流、權限、模組邊界：先提計畫等批准。
10. 順序：憲法 → 資料層一次翻 → 身分 → 設定憑證 → 背景工作 → 素材 → 閘門收尾。看板舊票排其後。

## 資料狀態（正式發布時刪除本節）

系統**未發布**。`data/`、`backups/`、資料庫內容、`.scratch/` 演練紀錄**全為測試資料**，可直接刪除重建，
不需備份、不需確認、不需保留相容。「動真實資料需批准」的規則在發布前不適用。

## 專案

品牌行銷作業系統：Python + FastAPI + Postgres（Supabase）。
前端 React＋Vite（`frontend/`，`npm run build` 後掛載於 `/app`）；後端只出 `/api` JSON。
（過渡期：`saas` 分支完成前，`master` 仍是 SQLite 單機版 `v0.1-desktop`。）

- 繁體中文；使用者非工程背景，回報用白話，術語第一次出現附一句說明
- 不確定就問，不要猜
- 對外發布、花錢：先說後果，等確認

## 開場

讀 `BOARD.md`；有 `[>]` 的票，主動報「哪張、進度、卡在哪」。看板只放未完成，完成即刪行。

## 快速事實

- 啟動：`啟動行銷系統.bat` → http://localhost:8710/（過渡期）；本機開發 `supabase start`
- 裝依賴：`uv sync --frozen`（不用 pip／requirements.txt，套件與版本鎖在 `pyproject.toml`／`uv.lock`）
- 金鑰 `.env`（不進版控）
- 語彙 `CONTEXT.md`；決策 `docs/adr/`；技術債與機器閘門 `docs/tech-debt.md`（動超標檔前先讀）；工作流減重 `docs/workflow-diet.md`
- `app/methodology/` 是 prompt 零件不是文件，刪改先問
- 議題：`.scratch/<effort>/issues/`，規則見 `docs/agents/`

## Tests

- 每張票：閘門＝`uv run ruff check app` ＋ `uv run pyright` ＋受影響的測試檔＋typecheck＋build。
- 合併進主線：`uv run pytest app/tests -q -n auto --dist loadfile`
  （`--dist loadfile` 必要——`conftest.py` 給每個測試模組自己的 DB／schema）。
- 800 行上限不適用於 `app/tests/`。
- 分流：不動 schema／模組進入點／花錢／權限路徑的行為修改＝route B（機器閘門綠即完成）；
  route C 只留 schema、模組邊界、金流、權限。
- CI：`.github/workflows/ci.yml`（GitHub Actions），push/PR 到 `saas`／`master` 都跑；
  backend job 開 `supabase start` 給 Postgres／anon role，frontend job 跑 lint／typecheck／test／build。

## Migrations

- `supabase/migrations/<timestamp>_<module>_<desc>.sql`；migration 只能 CREATE 自己模組前綴的表。
- 已套用的檔不改；修正開新檔。
- 重指向一張表前 `grep -rn "REFERENCES <table>" supabase/migrations/`。
