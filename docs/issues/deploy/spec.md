# 目標：上線／上雲前必還的帳

Status: 卡點——**還沒選部署平台**。2026-09-04 使用者裁決「不用上雲沒關係」，這一輪不做。
全文出處：`BOARD.md` @ commit `6574191`。

這些不擋本機閉環，但**第一次真的部署當天每一條都會咬人**，所以留著不刪。選定平台那天，
把這個資料夾的 issue 逐一升票（改名 `NN-*.md` 填四欄）。

## 順序（2026-09-04 重排：不用等平台的先做，等平台的墊後）

**A. 現在就能做，跟平台無關（一張一個 /slice session）**

1. `01-invite-email-match.md`（已升票 2026-09-04）— route C（權限）：accept_invite 比對 email。前端確認步驟
   當天由使用者砍掉：email 綁定之後，誤點只有本人做得到，確認頁是之後的 UI 票不是安全票。
2. `issue-07-2-settings-sentry-staging-cd.md` 的前半 — route B：pydantic-settings 收 19 處環境變數，缺了開機就炸；
   同一張順手收 `issue-is-local-env-flag.md`（那顆「是不是正式環境」的變數就在這裡出生）。
3. `issue-daily-pull-worker-own-process.md` — route C（模組邊界，要寫 ADR 取代 0039）：worker 拆成自己的進入點，
   本機仍可用同一行指令起兩個行程。
4. `issue-delete-seed-debug-account.md` — 最後一張，部署前一天做：刪了之後本機就沒有活得過 reset 的帳號。

**B. 要先選平台**

5. `issue-07-2-settings-sentry-staging-cd.md` 的後半 — Sentry／staging／CD（`supabase db push` 單一 job）＋映像檔帶 IANA 時區。
6. `issue-07-4-github-security-switches.md` — 要付 GitHub Pro 或把 repo 公開，是錢的決定。
7. `issue-ai-cost-reconciliation.md` — 要 Anthropic Admin API key；開始收費前對一次帳即可。

`issue-key-source-switch.md` 不是上雲債，是里程碑之後的產品功能；留在這裡只因為它跟「自帶金鑰」同一組。
