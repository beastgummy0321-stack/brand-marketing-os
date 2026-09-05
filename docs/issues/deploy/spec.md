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
4. ~~`codex_cli` 在正式環境是合法的~~ — 2026-09-05 已還（route B，無 ADR）。`app/core/config.py`
   多一張「只有某個值違規」的表（既有兩張是「有值就違規」，形狀塞不下），`codex_cli` 只准 `local`。
5. `04-row-hash-numeric-normalisation.md` — route C（金流）。`_row_hash()` 內部統一成 float。
6. `05-assets-bucket-size-limit.md` — route C（schema，2026-09-05 已批准）。50 MiB 的出處是
   `supabase/config.toml:118`，不是這張票挑的數字。
7. ~~刪四個沒人用的欄位~~ — 2026-09-05 裁決**整條不做**。查證後只有 `order_record.attribution_override`
   真的零引用；`interrupt.visible_from` 是排序與過期邏輯的骨幹（`interrupts.py:103-115,127,148`）
   還有專屬測試，`interrupt.kind` 的名字寫死在 `interrupts.py:116` 的 SQL 字串裡，`campaign_cycle_id`
   兩天前就已改名成 `campaign_period_id`（`20260903000002_core_interrupt_period.sql:8`）。憲法第 3 條
   位階高於票：不做的功能，欄位現在就要留好。裁決記在 `docs/contracts/core.md`。
8. `07-campaign-period-composite-fk.md` — route C（schema＋租戶隔離，2026-09-05 已批准）。
   實際是 **8 條 FK**（其中自參照只有 1 條），不是票原本寫的「8＋6」；且要先補
   `campaign_period` 的 `(id, org_id)` 唯一鍵，八條才掛得上。
9. `06-meta-name-lookup-tenant-symmetry.md` — route C（租戶隔離）。2026-09-05 裁決：**改呼叫鏈**，
   不多打 Meta API（唯一相近的 insights 端點會漏掉沒花錢的實體，正是當初改掉它的原因）。
10. `08-standalone-jobs-on-the-queue.md` ＋ `09-intake-and-persona-jobs-on-the-queue.md` — route C
   （模組邊界，照 ADR 0042）。實際是 **7 種** job 不是 5 種（ADR 0042 自己當天就數錯）；
   **不用開新表**，七種全都已經在寫 `llm_task`，只是沒人拿它當狀態來源。2026-09-05 裁決：
   初掃的逐張進度放棄，不為它加欄位（`issue-intake-scan-per-photo-progress.md`）。
   拆兩張是因為一份 7 支 job 的 diff 沒人審得動：08 先在三支獨立的證明模板，09 收掉 intake 四支、
   刪掉最後一張 dict、順手修好右上角鈴鐺（今天只聚合 7 種裡的 4 種，人物誌完全看不到）。
11. `issue-delete-seed-debug-account.md` — 最後一張，部署前一天做：刪了之後本機就沒有活得過 reset 的帳號。

（5～10 是 2026-09-05 從 `docs/tech-debt.md` §七認領進來的：使用者裁決上雲前全清、不再留負債。
同日一次問完一次派工：七條 issue 全部處理完畢——一條當場做掉、一條裁決不做、五條升成六張票。
升票前每一條都重新實測過，其中三條的數字是錯的，已在票裡標明原本錯在哪。）

**B. 要先選平台**

12. `issue-07-2-settings-sentry-staging-cd.md`（現在整張都是後半）— Sentry／staging／CD
   （`supabase db push` 單一 job）＋映像檔帶 IANA 時區。
13. `issue-07-4-github-security-switches.md` — 要付 GitHub Pro 或把 repo 公開，是錢的決定。
14. `issue-ai-cost-reconciliation.md` — 要 Anthropic Admin API key；開始收費前對一次帳即可。

`issue-key-source-switch.md` 不是上雲債，是里程碑之後的產品功能；留在這裡只因為它跟「自帶金鑰」同一組。
