# CLAUDE.md — Brand Marketing OS

憲法 `CONSTITUTION.md`（唯一入口）→ 看板 `BOARD.md` ＋ 語彙 `CONTEXT.md`（repo 根）＋ `docs/`（決策 `adr/`、
模組契約 `contracts/`、議題 `issues/<目標>/`、技術債 `tech-debt.md`、前端規則 `design-system.md`）。
流程規則由 skeleton-slice-pencil plugin 帶（開場注入＋/slice 讀 workflow.md）；這裡只放這個專案才有的地標、指令、鐵律。

## 資料狀態（正式發布時刪除本節）

系統**未發布**。`data/`、`backups/`、資料庫內容、`.scratch/` 全為測試資料，可直接刪除重建，
不需備份、不需確認。「動真實資料需批准」的規則在發布前不適用。

## 開場（每次 session）

1. 讀 `BOARD.md`。有 `[>]` 的目標行 → 讀它的資料夾（`spec.md`／`NN-*.md` 票／`issue-*.md`），主動報「哪張票、進度、卡在哪」。
2. 任何功能／修改需求 → /slice 入口分流，不得跳過。
3. `HANDOFF-*.md` 讀完即轉成 issue 檔或票，同一 session 內刪除。

## 地標

- 技術棧：Python＋FastAPI＋Postgres（Supabase：Postgres／Auth／Storage／Vault）；原生 SQL 不用 ORM；
  背景工作走 procrastinate，worker 是獨立行程（ADR 0063）；前端 React＋Vite（`frontend/`，build 後掛 `/app`），
  後端只出 `/api` JSON。`master` 仍是 SQLite 單機版 `v0.1-desktop`，開發在 `saas`。
- 後端模組：`app/<模組>/`＋自己的 migrations，不碰別人的表；契約頁 `docs/contracts/<模組>.md`，
  缺頁清單是 `app/tests/test_architecture_boundaries.py` 的 `MODULES_WITHOUT_CONTRACT`（只准變短）——
  動到某模組的 route C 票先補那個模組的頁。
- 前端功能：`frontend/src/components/<功能>/`，只准從 `index.ts` 進出（`frontend/.dependency-cruiser.cjs`，ADR 0060）；
  外觀與用字唯一規則 `docs/design-system.md`（ADR 0065）。
- `app/methodology/` 是 prompt 零件不是文件，刪改先問。
- 工作流 plugin 原始碼 `D:\0UserProfile\Desktop\Default\skeleton-slice-pen`；改完要 commit＋push＋`claude plugin update`。

## 指令

- 啟動：`啟動行銷系統.bat` → http://localhost:8710/ ；本機開發先 `supabase start`。開機自動啟動見 `docs/boot-autostart.md`。
- 裝依賴：`uv sync --frozen`（不用 pip）。金鑰在 `.env`；`BRAND_OS_LLM_PROVIDER=codex_cli`＝LLM 走本機 codex，不產生帳單；
  跑 pytest 前 unset 它（它會蓋掉測試的假供應商）。
- bash 跑 docker／supabase 前：`export PATH="/c/Users/User/AppData/Local/Programs/DockerDesktop/resources/bin:/c/Users/User/scoop/shims:$PATH"`
- 測試帳號 `123@example.com`／`123456`（`supabase/seed.sql`，組織 `org_bughunt`、品牌 `brd_bughunt`）——
  **唯一活得過 `supabase db reset` 的帳號**；reset 洗掉 seed 以外的一切。
  直接打 API 可自簽 HS256 JWT（`IDENTITY_ALLOW_HS256=1`，密鑰＝`SUPABASE_JWT_SECRET`）。
- 每張票的機器閘門：`uv run ruff check app`＋`uv run pyright`＋受影響的測試檔＋前端 typecheck／build
  ＋`cd frontend && npm run e2e`（自己起 8720 後端跑完收掉，前提 `supabase start`；後端票也要跑）。
- 動 schema／migration 的票再加：
  `uv run pytest app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py -q`
- 合併進主線：`uv run pytest app/tests -q -n 8 --dist loadfile`（`-n 8` 不是 `auto`、`loadfile` 必要，理由在 `CONTEXT.md`）。
- CI：`.github/workflows/ci.yml`，push／PR 到 `saas`／`master` 都跑。

## 鐵律（只列這個專案特有的；通用的在 plugin）

- 實機驗收要在**重啟過的後端**上做——閘門看不到「跑的是舊程式」。
- 單檔上限 800 行（`FileLineCapTest`），不適用 `app/tests/`；超標檔要加功能就先拆。
- Migration：`supabase/migrations/<timestamp>_<模組>_<desc>.sql`，只能 CREATE 自己模組前綴的表；已套用的檔不改，修正開新檔；
  重指向一張表前 `grep -rn "REFERENCES <table>" supabase/migrations/`。
- 對外發布、花錢：先說後果等確認。

## 對使用者說話

繁體中文、白話；使用者非工程背景，術語第一次出現附一句比喻；一次一題、給選項標推薦；時間講具體。
