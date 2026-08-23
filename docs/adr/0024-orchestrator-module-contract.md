# 0024 調度台：無事件表、模組自報狀態、決策單一收口（2026-08-23）

承 ADR 0018（背景執行緒＋輪詢、使用者關卡 ≤4、不做統一任務表）與 ADR 0019。
規劃草稿 `.scratch/orchestrator/PLAN.md`「不可逆決定」5 條，經 grill 八問裁決如下。
調度台＝`decide(facts) -> [Action]` 純函數（規則登記制）＋派工員，掛在既有 4 小時／每週執行緒。

## 裁決

1. **沒有事件表，也沒有訊息匯流排（否決「真事件」）。**
   模組間唯一溝通面＝一包 facts 快照。調度台每次醒來呼叫每個模組的
   `status(conn, brand_id) -> dict` 組裝 facts，**絕不 SELECT 其他模組的表**。
   PLAN.md 模組表「發出事件」欄位一律改讀為「facts 條件命名」，不是訊息。
   既有 `app/dashboard/routes_jobs_api.py`（聚合 5 個模組的公開 `active_jobs()`）
   就是本條的既存範例，本 ADR 只是把同一慣例再加兩個函式。

2. **每個容器的對外公開面固定三個函式**，調度台不 import 模組內部任何東西：
   - `active_jobs()`（已存在於部分模組）
   - `status(conn, brand_id) -> dict`——唯讀，key 一律英文小寫加模組前綴（`ads.pacing_over`）
   - `handle(conn, action) -> result`——唯一寫入口

3. **決策留痕開新表 `decision`（append-only，比照 `learning_ledger`）。**
   不塞 `recommendation`：該表 `campaign_cycle_id NOT NULL REFERENCES campaign_cycle(id)`
   （`app/ads/migrations/0001_tables.sql:487`）綁死廣告檔期，非廣告模組塞不進去。
   欄位：`id / module / brand_id / rule_id / action_json / risk_level / autonomy_mode /
   outcome(auto_done|carded|failed) / attempt_count / error_text / created_at`。
   一表三用：稽核軌跡、失敗計數器、Action 去重依據。

4. **同步/非同步照 ADR 0018 不變**，不開新執行緒、不加新節奏。觸發點三個：
   4 小時同步後、每週判讀後、使用者按鍵時。
   **但 `handle()` 一律非阻塞**——長工作（影音剪輯／上字幕等未來模組）走既有
   背景工作＋`active_jobs()` 慣例，完成狀態由該模組 `status()` 反映。
   阻塞式 `handle()` 會讓一個慢模組卡住整圈派工，等同破壞第 5 條。

5. **錯誤邊界比照 `app/ads/auto_sync.py:93`**：每個 Action 各自 try/except，一個炸掉不擋其他。
   可見度按風險級分流：`spend` 級失敗出卡進收件匣；`save`／`asset` 級只寫 `decision` 表、
   下一輪自動重試；**同一 `dedupe_key` 連續失敗 3 輪，不分風險級一律升級出卡**。

6. **Action 的 `op` 是自由字串，調度台不認得也不驗證。**
   ```
   Action = {module, op, brand_id, params, risk(save|spend|asset), rule_id, dedupe_key}
   ```
   打錯字的防線在模組自己：`handle()` 收到不認得的 `op` 丟 `ValueError`，由第 5 條接住。
   `dedupe_key` 沿用 `interrupts.enqueue()` 既有同名概念。

7. **規則登記在模組，不在調度台**（否則每加一個模組就要改調度台，與設計目的相反）。
   歸屬看「這條規則叫誰做事」——被叫的那個模組擁有它，模組被拔掉時規則跟著消失。
   規則讀 facts 一律 `facts.get(...)`，讀不到回 `None` 不觸發，好讓上游模組缺席時安靜降級。

8. **自動度閘門單一收口在調度台**，模組永遠不知道有沒有人核可過。
   調度台讀 `rule_cards.py` 的 autonomy（1.0 保守／2.0 放手，目前設定存在、零消費端）
   × `action.risk`，決定「直接呼叫 `handle()`」或「寫 `decision` 列＋出卡等同意」。
   核可回路：出卡時整包 Action 存進 `decision.action_json`，使用者按同意後原封不動執行，
   `outcome` 由 `carded` 改 `auto_done`——使用者點頭的是當時那個 Action，不是近似動作。

9. **調度台沒有前端頁面。** 產出只從兩個既有出口露出：駕駛艙指南卡
   （`guide_cards.build(facts)`）與收件匣（`app/core/interrupts.py`）。
   `decision` 表暫不做畫面。

## 當時排除了什麼

- **事件表／訊息匯流排**：庫內零事件基礎設施，模組要記得發訊息（漏發＝流程無聲斷掉），
  另需處理重複投遞。單機單人不值這個價。本設計不封死它：未來某模組真需要訊息語意，
  改成它的 `status()` 去讀自己的事件表即可，調度台不動。
- **調度台自己 SELECT 各模組的表**：最省事，但每加一個模組就要改調度台，且違反唯一進入點；
  拔掉任一模組會直接讓調度台的 facts 組裝碼壞掉。
- **調度台持有合法 op 清單**：能提早攔錯字，代價是調度台必須知道各模組內部詞彙。
- **自動度判斷散在各模組**：花錢的閘門散開＝未來新模組某天忘了判就在保守檔自動花錢。
- **開「調度台」專頁**：多一個使用者得記得去看的地方，與 ADR 0018 關卡 ≤4 的用意相反。

## 後果

- 新增 migration 一支（`decision` 表）＋ `migration_manifest.json` 一筆；動 live DB 前先備份 `data/app.db`。
- 現有 9 個功能模組要各補 `status()`／`handle()` 兩個函式；廣告模組寫完即定，不再擴充。
- `rule_cards.py` 的 autonomy 從「零消費端」變成有消費端，保守檔行為改變（同意即執行）。
- 第一批票見 `.scratch/orchestrator/PLAN.md`；第 1 票（接通學習迴路）不依賴本 ADR，可先做。
