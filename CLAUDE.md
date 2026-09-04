# CLAUDE.md — Brand Marketing OS

憲法 `CONSTITUTION.md`（20 行，唯一入口）→ 看板 `BOARD.md` ＋ `docs/`（語彙 `CONTEXT.md`、決策 `adr/`、
模組契約 `contracts/`、議題 `issues/<目標>/`、技術債 `tech-debt.md`）。規則不在這裡重抄；這裡只放地標、指令、鐵律。

## 資料狀態（正式發布時刪除本節）

系統**未發布**。`data/`、`backups/`、資料庫內容、`.scratch/` 全為測試資料，可直接刪除重建，
不需備份、不需確認。「動真實資料需批准」的規則在發布前不適用。

## 開場（每次 session）

1. 讀 `BOARD.md`：一行一個目標，細節全在 `docs/issues/<目標>/`（`spec.md`／`NN-*.md` 票／`issue-*.md`）。
   有 `[>]` 的目標行 → 讀它的資料夾，主動報「哪張票、進度、卡在哪」。
2. 任何功能／修改需求 → 走 /slice 入口分流，不得跳過。
3. 做票途中發現、這張票不修的事 → `issue-<名>.md`；沒有目標認領的模組欠帳 → `docs/tech-debt.md` §七。
   看板本身不寫細節（plugin `board-shape` 閘門擋）；票做完刪票檔，資料夾空了才刪行。
4. `HANDOFF-*.md` 讀完即轉成 issue 檔或票，同一 session 內刪除。

## 地標

- 技術棧：Python＋FastAPI＋Postgres（Supabase：Postgres／Auth／Storage／Vault）；原生 SQL 不用 ORM；
  背景工作走 procrastinate（handler 可重跑、只碰自己組織）；前端 React＋Vite（`frontend/`，build 後掛 `/app`），
  後端只出 `/api` JSON，前端只跟 FastAPI 講話。過渡期 `master` 仍是 SQLite 單機版 `v0.1-desktop`，開發在 `saas`。
- 模組：`app/<模組>/`＝新資料夾＋自己的 migrations＋`frontend/src/features/<模組>/`，不碰別人的表。
  契約頁 `docs/contracts/<模組>.md`，16 個模組現有 6 份；`ContractPageRatchetTest` 只准缺頁清單變短——
  動到某模組的 route C 票先補那個模組的頁（格式 `container-contract.md` §8）。
- `app/methodology/` 是 prompt 零件不是文件，刪改先問。
- 工作流 plugin 原始碼 `D:\0UserProfile\Desktop\Default\skeleton-slice-pen`（不是 `skeleton-slice`）；
  改完要 commit＋push＋`claude plugin update`。

## 指令

- 啟動：`啟動行銷系統.bat` → http://localhost:8710/ ；本機開發先 `supabase start`。
- 裝依賴：`uv sync --frozen`（不用 pip）。金鑰在 `.env`；`BRAND_OS_LLM_PROVIDER=codex_cli`＝LLM 走本機 codex，不產生帳單。
- bash 跑 docker／supabase 前：`export PATH="/c/Users/User/AppData/Local/Programs/DockerDesktop/resources/bin:/c/Users/User/scoop/shims:$PATH"`
- 測試帳號 `123@example.com`／`123456`（`supabase/seed.sql`，組織 `org_bughunt`、品牌 `brd_bughunt`）——
  **唯一活得過 `supabase db reset` 的帳號**；reset 洗掉 seed 以外的一切，含帳號、品牌、Meta 綁定。
  信箱驗證本機關著，畫面直接註冊也行；直接打 API 可自簽 HS256 JWT（`IDENTITY_ALLOW_HS256=1`，密鑰＝`SUPABASE_JWT_SECRET`）。
- 每張票的閘門：`uv run ruff check app`＋`uv run pyright`＋受影響的測試檔＋前端 typecheck／build
  ＋`cd frontend && npm run e2e`（自己起 8720 後端跑完收掉，前提 `supabase start`；後端票也要跑）。
- 動 schema／migration 的票再加：
  `uv run pytest app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py -q`
- 合併進主線：`uv run pytest app/tests -q -n 8 --dist loadfile`（`-n 8` 不是 `auto`、`loadfile` 必要，理由在 `CONTEXT.md` 量到的教訓）。
- CI：`.github/workflows/ci.yml`，push／PR 到 `saas`／`master` 都跑。

## 鐵律

- 動 schema、金流、權限、模組邊界：先提計畫等批准。對外發布、花錢：先說後果等確認。
- 測試只寫四類（金額／租戶隔離／API 契約／資料正確性）；800 行上限不適用 `app/tests/`。
- 實機驗收要在**重啟過的後端**上做——閘門看不到「跑的是舊程式」。
- Migration：`supabase/migrations/<timestamp>_<模組>_<desc>.sql`，只能 CREATE 自己模組前綴的表；已套用的檔不改，修正開新檔；
  重指向一張表前 `grep -rn "REFERENCES <table>" supabase/migrations/`。
- 不確定就問，不要猜。

## 對使用者說話

繁體中文、白話；使用者非工程背景，術語第一次出現附一句比喻；一次一題、給選項標推薦；時間講具體。
