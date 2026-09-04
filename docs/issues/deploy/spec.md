# 目標：上線／上雲前必還的帳

Status: 卡點——**還沒選部署平台**。2026-09-04 使用者裁決「不用上雲沒關係」，這一輪不做。
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
3. 升成票 `03-worker-own-process.md`（2026-09-05）— route C，ADR 0063 已寫、取代 0039：worker 變成獨立行程
   `python -m app.worker`，本機也一樣，`啟動行銷系統.bat` 與開機自動啟動各自幫使用者開起來。
   順手抓到的隱形 bug：`fail_interrupted_tasks()` 掛在網站啟動時跑，worker 分家後網站重開會把
   worker 正在跑的活工作誤標成失敗——跟著搬到 worker 進入點。
4. `issue-delete-seed-debug-account.md` — 最後一張，部署前一天做：刪了之後本機就沒有活得過 reset 的帳號。

**B. 要先選平台**

5. `issue-07-2-settings-sentry-staging-cd.md`（現在整張都是後半）— Sentry／staging／CD
   （`supabase db push` 單一 job）＋映像檔帶 IANA 時區。
6. `issue-07-4-github-security-switches.md` — 要付 GitHub Pro 或把 repo 公開，是錢的決定。
7. `issue-ai-cost-reconciliation.md` — 要 Anthropic Admin API key；開始收費前對一次帳即可。

`issue-key-source-switch.md` 不是上雲債，是里程碑之後的產品功能；留在這裡只因為它跟「自帶金鑰」同一組。
`issue-codex-cli-provider-in-production.md`（2026-09-05 開票 02 時發現）跟著票 02 的環境表走，02 落地後補一條規則即可。
