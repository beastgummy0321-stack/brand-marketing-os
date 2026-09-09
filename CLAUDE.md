# CLAUDE.md — Brand Marketing OS

工作流由 harness plugin 帶：`/dig` 決定 → `/carve` 規劃 → `/crank` 執行，三個都只有使用者能打。
真相檔只有三處：`ARCHITECTURE.md`（模組地圖＋現況，規劃師寫）、`.work/`（唯一佇列：PLAN／tickets／
ready／doing／blocked／done）、`.harness/`（本機狀態，不進版控）。定案直接寫進 ARCHITECTURE.md，
舊版在 git；沒有憲法、沒有 ADR、沒有看板、沒有契約頁。
其餘留下的文件：語彙 `CONTEXT.md`、前端規則 `docs/design-system.md`、可用性演練 `docs/drills/`、
開機 `docs/boot-autostart.md`、`docs/backlog/`（實測撞到但還沒排進 `.work/` 的問題，一檔一條，
是 /dig 的輸入不是佇列，被 /carve 消化的條目即刪）。

## 資料狀態（正式發布時刪除本節）

系統**未發布**。`data/`、`backups/`、資料庫內容全為測試資料，可直接刪除重建，
不需備份、不需確認。「動真實資料需批准」的規則在發布前不適用。

## 開場（每次 session）

1. harness 的 SessionStart 會報 mode、進行中的 issue、blocked、violations；照它報的接手。
   沒有 `.harness/` 就請使用者打 /dig（方向已清楚可直接 /carve），主對話不自己動手做。
2. 任何功能／修改需求 → /dig 或 /carve 入口，不得在主對話直接改程式。
3. `docs/backlog/` 裡的東西是候選不是決定；/dig 時主動拿出來對。

## 地標

- 技術棧：Python＋FastAPI＋Postgres（Supabase：Postgres／Auth／Storage／Vault）；原生 SQL 不用 ORM；
  背景工作走 procrastinate，worker 是獨立行程；前端 React＋Vite（`frontend/`，build 後掛 `/app`），
  後端只出 `/api` JSON。`master` 仍是 SQLite 單機版 `v0.1-desktop`，開發在 `saas`。
- ARCHITECTURE.md 的 `stack` 是 `python`（2026-09-10 裁決）：後端 `app/<模組>/` 是受管模組；
  前端邊界沿用 `frontend/.dependency-cruiser.cjs`（功能資料夾只准從 `index.ts` 進出），
  放在 verify 指令裡跑，不另立 harness 模組。
- 後端模組：`app/<模組>/`＋自己的 migrations，不碰別人的表；分層方向與跨層 SQL 的機器檢查在
  `app/tests/test_architecture_boundaries.py`。
- `app/methodology/` 是 prompt 零件不是文件，刪改先問。
- harness plugin 原始碼 `D:\0UserProfile\Desktop\Default\harness`，發布倉庫 `beastgummy0321-stack/Planner`；
  改完要 commit＋push＋`claude plugin update harness@Planner`。

## 指令

- 啟動：`啟動行銷系統.bat` → http://localhost:8710/ ；本機開發先 `supabase start`。開機自動啟動見 `docs/boot-autostart.md`。
- 裝依賴：`uv sync --frozen`（不用 pip）。金鑰在 `.env`；`BRAND_OS_LLM_PROVIDER=codex_cli`＝LLM 走本機 codex，不產生帳單；
  跑 pytest 前 unset 它（它會蓋掉測試的假供應商）。
- bash 跑 docker／supabase 前：`export PATH="/c/Users/User/AppData/Local/Programs/DockerDesktop/resources/bin:/c/Users/User/scoop/shims:$PATH"`
- 測試帳號 `123@example.com`／`123456`（`supabase/seed.sql`，組織 `org_bughunt`、品牌 `brd_bughunt`）——
  **唯一活得過 `supabase db reset` 的帳號**；reset 洗掉 seed 以外的一切。
  直接打 API 可自簽 HS256 JWT（`IDENTITY_ALLOW_HS256=1`，密鑰＝`SUPABASE_JWT_SECRET`）。
- 規劃師寫 issue／ticket 的 verify 時，這個專案的機器閘門是：`uv run ruff check app`＋`uv run pyright`
  ＋受影響的測試檔＋`cd frontend && npx tsc -b --noEmit && npm run depcruise && npm run build`
  ＋`cd frontend && npm run e2e`（自己起 8720 後端跑完收掉，前提 `supabase start`；後端票也要跑）。
- 動 schema／migration 再加：
  `uv run pytest app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py -q`
- 合併進主線：`uv run pytest app/tests -q -n 8 --dist loadfile`（`-n 8` 不是 `auto`、`loadfile` 必要，理由在 `CONTEXT.md`）。
- CI：`.github/workflows/ci.yml`，push／PR 到 `saas`／`master` 都跑。

## 鐵律（只列這個專案特有的；通用的在 plugin）

- **不要求、不提醒使用者實機投放 Meta**（2026-09-07 裁決、2026-09-08 重申加嚴）：提示詞、素材產出、廣告排程完全落地前，
  任何 issue、文件、回報都不寫「要看到真結果得讓活動跑」；帳戶資料的狀態只當事實記錄。驗收用測試資料證明分支，真資料只證明管線會動。
- 實機驗收要在**重啟過的後端**上做——閘門看不到「跑的是舊程式」。
- Migration：`supabase/migrations/<timestamp>_<模組>_<desc>.sql`，只能 CREATE 自己模組前綴的表；已套用的檔不改，修正開新檔；
  重指向一張表前 `grep -rn "REFERENCES <table>" supabase/migrations/`。
- 對外發布、花錢：先說後果等確認。

## 對使用者說話

繁體中文、白話；使用者非工程背景，術語第一次出現附一句比喻；一次一題、給選項標推薦；時間講具體。
