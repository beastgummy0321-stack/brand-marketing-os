# 目標：上線／上雲前必還的帳

Status: **A 組清空**——2026-09-05 一次問完一次派工，七條 issue 全部處理完：一條當場做掉（route B）、
一條裁決不做（憲法第 3 條位階高於票）、五條升成六張票全部 ship 並合併。整套測試 765 passed，
實機驗收五步全過（真的開瀏覽器點過）。只剩第 11 條「刪掉種子除錯帳號」，那張刻意留到部署前一天。
B 組三張仍等你選平台。
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
5. ~~`_row_hash()` 對 int／float 不穩定~~ — 已還（commit `slice-04 done`）。`_row_hash()` 內部
   統一成 float；審查用 `Decimal`、布林、`2**53+1`、帶空白的字串攻擊過，唯一的浮點精度極限被
   `numeric(14,2)` 欄位型別擋在更前面。
6. ~~`assets` bucket 補 `file_size_limit`~~ — 已還（commit `slice-05 done`）。**教訓**：原本的驗收
   條件是假的——本機 `supabase db reset` 最後一步會拿 `config.toml` 覆蓋一次，所以把 migration 的
   數字改錯、甚至整個檔刪掉，reset 之後查資料庫都照樣是對的。審查判 blocked-upstream 判得對。
   改成直接把 migration 檔餵給資料庫跑（＝`supabase db push` 上雲時做的同一件事）才驗得到。
7. ~~刪四個沒人用的欄位~~ — 2026-09-05 裁決**整條不做**。查證後只有 `order_record.attribution_override`
   真的零引用；`interrupt.visible_from` 是排序與過期邏輯的骨幹（`interrupts.py:103-115,127,148`）
   還有專屬測試，`interrupt.kind` 的名字寫死在 `interrupts.py:116` 的 SQL 字串裡，`campaign_cycle_id`
   兩天前就已改名成 `campaign_period_id`（`20260903000002_core_interrupt_period.sql:8`）。憲法第 3 條
   位階高於票：不做的功能，欄位現在就要留好。裁決記在 `docs/contracts/core.md`。
8. ~~`campaign_period` 的八條 FK 升複合鍵~~ — 已還（commit `slice-07 done`）。實際是 **8 條**
   （自參照只有 1 條），不是票原本寫的「8＋6」。三個 migration 檔照擁有模組拆開——schedule 契約
   禁止一個模組的 migration 動別人的表，而機器閘門只檢查 `CREATE TABLE`、看不到這件事。
   審查親手對六條 FK 試插跨組織的列，全部被資料庫擋下。
9. ~~Meta 兩支查名字的函式不驗組織~~ — 已還（commit `slice-06 done`）。裁決走**改呼叫鏈**。
   殘留缺口（沒有任何人綁過的 id 仍會打到 Meta）刻意留著並記在
   `issue-meta-unknown-parent-id-fail-open.md`＋`docs/contracts/meta.md`，門檻是「真的多了第二個呼叫端」。
10. ~~七種記憶體背景工作搬上佇列~~ — 已還（commit `slice-08 done`／`slice-09 done`）。實際是
   **7 種**不是 5 種，**不用開新表**。**這輪最貴的教訓**：票 08 第一輪被審查退回，因為佇列的鎖
   只蓋「排隊中」，工作被 worker 撿走之後到真的打 AI 之前有一段空窗期，第二次按下去會**真的多付
   一次錢**（實測 3 列、3 次呼叫）。裁決改問佇列本人，`app.background` 因此多一支 `is_active(lock)`。
   收尾時 `app/intake` 也補了契約頁（那個模組的檔頭自稱「整體是 Mock、不呼叫任何 LLM」，三句全假）。
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
