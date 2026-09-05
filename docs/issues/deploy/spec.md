# 目標：上線／上雲前必還的帳

Status: 進行中——2026-09-05 使用者裁決：上雲前全清、不再留負債。A 組七張不用等平台；B 組三張等選平台。
全文出處：`BOARD.md` @ commit `6574191`。

這些不擋本機閉環，但**第一次真的部署當天每一條都會咬人**，所以留著不刪。選定平台那天，
把這個資料夾的 issue 逐一升票（改名 `NN-*.md` 填四欄）。

## 順序（2026-09-04 重排：不用等平台的先做，等平台的墊後）

**A. 現在就能做，跟平台無關（一張一個 /slice session）**

1. ~~邀請連結持有即可用~~ — 2026-09-04 已還（ADR 0061，commit `slice-01 done`）。前端確認步驟
   當天由使用者砍掉：email 綁定之後，誤點只有本人做得到，確認頁是之後的 UI 票不是安全票。
2. ~~環境變數收進一個地方＋「是不是正式環境」的旗標~~ — 2026-09-05 已還（ADR 0062，
   commit `slice-02 done`）。原本判成 route B 是錯的：`_is_local()` 的三個呼叫端全是權限判斷
   （兩道開發後門＋邀請連結要不要放進 API 回應），所以走了 route C。原本寫的「8 個鍵」也是錯的，
   實測 10 個。`issue-is-local-env-flag.md` 被它收走並刪除；`DATABASE_URL` 是唯一不快取的一顆
   （ADR 0062 §5a，背景工作靠它偵測 schema 換了沒）。
3. ~~worker 拆成自己的行程~~ — 2026-09-05 已還（ADR 0063 取代 0039，commit `slice-03 done`）。
   `python -m app.worker` 是唯一跑背景工作的東西，本機也一樣；兩支 .bat 與開機自動啟動各自幫使用者
   開起來與收掉。過程中修掉兩個票面原本沒看到的洞：`fail_interrupted_tasks()` 留在網站啟動時跑，
   worker 分家後網站重開會把 worker 正在跑的活工作誤標成失敗（搬到 worker 進入點）；以及拆行程
   等於拿掉了「一次只有一個行程」的唯一保證（8710 那個 port），第二個 worker 會誤殺活著的付費工作、
   讓畫面放行使用者再按一次＝真的再花一次錢（改用 Postgres session advisory lock，按 schema 分鑰匙）。
   **教訓**：把一個行程拆成兩個，要先問「原本是誰在保證只有一個」。
4. `issue-codex-cli-provider-in-production.md` — route B，一行：`codex_cli` 只准在 `local`。
5. `issue-row-hash-numeric-normalisation.md` — route C（金流），兩行＋一個測試。
6. `issue-assets-bucket-size-limit.md` — route C（schema），一個 migration 檔。
7. `issue-drop-unused-columns.md` — route C（schema，需批准）；上雲前刪最便宜，之後是對真資料跑 migration。
8. `issue-campaign-period-composite-fk.md` — route C（schema＋租戶隔離），八條 FK 重建。
9. `issue-meta-name-lookup-tenant-asymmetry.md` — route C（租戶隔離）；站① 先裁決：多打一次 Meta API，還是改呼叫鏈往下傳。
10. `issue-in-memory-background-jobs.md` — route C（模組邊界）；雲端重啟／多實例會把 dict 裡的狀態弄丟，照 ADR 0042 搬上佇列。
11. `issue-delete-seed-debug-account.md` — 最後一張，部署前一天做：刪了之後本機就沒有活得過 reset 的帳號。

（5～10 是 2026-09-05 從 `docs/tech-debt.md` §七認領進來的：使用者裁決上雲前全清、不再留負債。）

**B. 要先選平台**

12. `issue-07-2-settings-sentry-staging-cd.md`（現在整張都是後半）— Sentry／staging／CD
   （`supabase db push` 單一 job）＋映像檔帶 IANA 時區。
13. `issue-07-4-github-security-switches.md` — 要付 GitHub Pro 或把 repo 公開，是錢的決定。
14. `issue-ai-cost-reconciliation.md` — 要 Anthropic Admin API key；開始收費前對一次帳即可。

`issue-key-source-switch.md` 不是上雲債，是里程碑之後的產品功能；留在這裡只因為它跟「自帶金鑰」同一組。
