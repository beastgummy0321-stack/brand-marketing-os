# Drill 4（上線前最終內測，2026-09-13）：八條根因與八題待裁決 — F05 /dig 的第一份輸入

Status: **2026-09-14 八題全部裁決**（見文末「已裁決」一節）。F05 只吸收了第 6 題（建檔地基）
與第 2 題的歷史來源那一半；**其餘是閉環 feature 的輸入，這一檔不要刪**。完整證據與因果鏈在
`docs/drills/drill-4/synthesis.md`（根因 RC-A1…RC-H、七站×三人證據表、通過標準、F05 形狀）與
`docs/drills/drill-4/findings-{aming,jay,vivian}.md`（每站資料庫證據）。這一檔只是入口，被 /carve 消化即刪。

## 摘要

- Golden Path 七站三人全通、每站有 DB 證據；學習真的被下一個 Campaign 的策略讀到並改變配置（Vivian 第二圈的反證最有力）。
- 但六次結案全判「看不出」：樣本等級綁購買數，Meta 路徑的購買數被 `app/ads/outcome.py:168` 那行 `source != "meta"` 擋掉——
  購買數早在 `meta_entity_spend.actions`，解析器 `_CONVERSIONS_LATERAL` 也在，只差 `daily_entity_spend` 沒回那欄。「會傳話，還不會進化」。
- 錢六次全對；零跨品牌；未觀察到 5xx。一次停止條件（阿明白畫面）中途修掉（F04-I24～I26）。
- 三人總評：阿明會用不敢全押；小杰十分鐘摸不到底但沒丟東西；Vivian 現在不建議導入、骨架對、五條採用門檻＝F05 驗收語。

## 八條根因（修根因不修症狀；每條在 synthesis.md 有 症狀→為什麼→上游決策→架構為何擋不住→最小根因修正）

1. RC-A1 商品經濟數字沒有寫入者（精靈只存 `product_fact` 文字；`save_product_economics` 只有產品頁呼叫）。
2. RC-A2 精靈可以「完成」卻零事實；策略只讀 `brand_fact(confirmed)`。
3. RC-B 預算引擎 `budget.scenarios()` 不讀成功條件、預算上限、真實歷史（歷史又等購買數）。
4. RC-C offer 座標種子把 free_shipping／discount／trial_sample／bundle／guarantee 對每個品牌預設啟用；delivery_plan 照挑、文案照寫 → 假優惠流進發布清單（四圈中三圈）。最小修法：種子把六個促銷 key 種成 `disabled_at`（機制已存在）。
5. RC-D 購買數被規則擋住 → 結案永遠看不出（見摘要）。
6. RC-E 座標成效讀舊 `schedule` 的綁定（`channel_entity_map`／`creative_candidate`），新迴圈廣告全「未標座標」；`performance.py` 仍餵 diagnosis／jobs，這一輪套件不退場。
7. RC-F 「後端做完畫面不說」三機制：非同步生成無通知（`GET /api/jobs/active` 已存在、ads 未接）／配對回應成功時不渲染（`PublishPage.tsx`）／行動紀錄硬截 6 筆無「查看全部」（`routes.py:80`）。
8. RC-G 前提與結果沒有單一出處（理解如下沒有成功條件格、成效頁沒有對目標的一句話）；RC-H 模型建議被當成使用者決定（精靈預設勾風險最高選項、Meta 帳號未指定品牌也放行）。

## 歷史提問（已於 2026-09-14 全部裁決；不得再次當成待答）

1. 廢掉「Meta 購買一律當未追蹤」§0 Blocked-if（廢）。
2. 目標 CPA 改由成功條件推導＋推薦金額受宣告預算約束——與 2026-09-12 裁決 4 衝突（都改）。
3. 廣告層顯示觀察到的 ROAS／CTR——與 ARCHITECTURE §6 第 3 條衝突；預算仍只分到投放組（顯示）。
4. 座標成效端點掛 ads router、前端換 URL、schedule 不加新程式、本輪不退場、§4 改寫（照這樣）。
5. offer 預設全關，品牌要用去座標畫面開啟（接受）。
6. 精靈收售價／成本／運費；定義「最低可投放集合」＝至少一商品＋經濟數字＋已指定廣告帳戶（收）。
7. 理解如下六格→七格、欄位清單改後端給——動 §6.1 第 11 條（不裁決就只做一行版：目標格帶「CPA ≤ 300」）。
8. F04 note 13／14：`ended` 狀態刪掉或補寫入者；`closed` 後成效凍結與否（刪掉／凍結）。

## F05 依賴順序（synthesis.md §D）

RC-D → RC-A1‖RC-C → RC-A2 → RC-B → RC-F（三修法）→ RC-G → RC-H → RC-E（最後；V-10 廣告層 ROAS 是一行）。
一行級：目標格帶成功條件、`_QUEUE_JOB_KINDS` 補 `ads_*`＋修 workbench action_url、行動紀錄出口、strategy 提示詞「若用到學習，說明它改變了什麼」、F04 note 10／1。

## 演練道具（不進 F05）

`scripts/drill/fake_meta.py`：mirror 已改讀 ads 表；沒綁帳號改成拒絕（本次已改）；未來期間在未來的 Campaign 要用 SQL 搬日期。


## 已裁決 2026-09-14（使用者逐題答覆，括號是當初的建議）

1. **RC-D**：廢掉「Meta 購買一律當未追蹤」這條 §0 Blocked-if。照建議——新開 migration 讓
   `ads_outcome_daily.purchases` 可以是 NULL（NULL＝未追蹤、0＝真的是零），`daily_entity_spend`
   沿用既有的 `_CONVERSIONS_LATERAL` 多回 `conversions`，`ingest_meta` 寫真的數字，刪掉
   `outcome.py:168` 的 `source != "meta"` 過濾。「看不出」必須帶數字。樣本等級的定義不動。→ **閉環 feature**
2. **RC-B**：目標 CPA 改由成功條件推導（ROAS → 客單價 ÷ 目標 ROAS；CPA → 它自己），沒有宣告才
   回到「打平 × 0.7」；推薦金額不得超過 `constraints_json.budget`，會超就在 basis 說明。
   這條**改寫 2026-09-12 裁決 4**。→ **閉環 feature**（歷史來源那一半已在 F05-I08）
3. **RC-E／V-10**：廣告層顯示觀察到的 ROAS／CTR（資料 `_bucket` 早就算好），但預算**仍然只分配
   到投放組**——「不分配預算」與「不給看數字」是兩件事。這條改寫 ARCHITECTURE §6 第 3 條。→ **閉環 feature**
4. **RC-E 範圍：選 B**。角度比較做在投放中心的成效 tab（把 `_bucket` 的每則廣告按
   `ads_ad.coordinates` 分組），刪掉經營概況的「素材成效比較」面板與它那支 schedule 端點；
   不開新端點、`app/schedule` 不加任何新程式。套件這一輪**不退場**，§4 要改寫成「四個讀者搬走了
   第一個」。→ **閉環 feature**
5. **RC-C**：`ensure_coordinates_seeded` 把六個促銷 offer key 種成 `disabled_at = now()`，只留
   `none` 啟用；品牌真的有優惠就去既有的座標畫面開啟。既有測試品牌用一次性 UPDATE 修（測試資料）。
   → **閉環 feature**
6. **RC-A1／A2**：精靈收售價／成本／運費；「最低可投放集合」＝至少一項要賣的東西＋經濟數字＋
   已指定的廣告帳戶（＋成效目標），不設「N 條事實」門檻，改修精靈的事實寫入者。
   → **F05 已吸收**（F05-I01／I02／I04／I05／I06／I07；`ARCHITECTURE.md` §8）
7. **RC-G(4)**：只做一行版——理解如下的目標格印「購買・CPA ≤ 300」（`success_target` 早就在
   payload 裡）。六格不變成七格，欄位清單**不**改由後端給，§6.1 第 11 條不動。→ **閉環 feature**
8. **F04 note 13／14**：`ended` 狀態**刪掉**（live → closed，「已過期待結案」改成 `judgment.py`
   從 `end_date` 組的一句話）；`closed` 之後成效**凍結**（`ingest_meta` 遇到 closed 直接 no-op，
   讓「結案後判斷不再變」這句話變成真的）。→ **閉環 feature**

閉環 feature 的依賴順序沿用 `docs/drills/drill-4/synthesis.md` §D，但 RC-A1／RC-A2 那兩層拿掉（F05 做完了）：
RC-D → RC-C → RC-B → RC-F（三修法）→ RC-G → RC-E。

## RC-D 補充證據（F07 審查，2026-09-15）

合併自 `issue-meta-purchases-not-ingested.md`，仍未排入佇列；沿用上述已裁決 RC-D，不重問。
`app/ads/outcome.py::ingest_meta` 當時將 Meta purchases 寫為 0，`_bucket` 當未追蹤；`sample_bucket` 在購買數低於 10 時回低。F07 `app/ads/visual_learning.py` 因而持續寫「看不出」，只有 simulated rows 可產生 winner。影響為結案視覺學習無法餵回下一輪主力 looks。修復時核對當前程式並保留 NULL（未追蹤）與 0（真零）的區分，不將歷史行號當現況。

### RC-D 實作進度（F16-I01 schema、F16-I05 資料來源，2026-09-20）——RC-D 閉環

`ads_outcome_daily.purchases`／`revenue` 已改成 nullable（F16-I01，見
`docs/architecture/ads.md` §6.10），`_bucket`／`_outcome_totals`／`experiments.judge` 都改成用
「欄位是不是 `NULL`」判斷未追蹤，拿掉 `source == 'meta'`／`revenue != 0` 這兩個 sentinel。

F16-I05 接上資料來源：`app/meta/repository.py::daily_entity_spend` 多回 `purchases`／
`revenue`／`action_type`／`attribution_window`，同義字判定沿用既有的
`external_purchase_values()`（`purchase` 目標唯一定義是 `graph._ROAS_ACTION_PRIORITY`），不是
另外挑一次也不是原建議的 `_CONVERSIONS_LATERAL`（那支是給「SQL 端一次聚合整段月份」的
`spend_summary`／CPA 用；`daily_entity_spend` 逐日逐實體、通常一個 group 一個 physical row，
直接在 Python 呼叫既有的 pure function 更省一次重寫）。`ingest_meta` 現在寫真的
`purchases`（`NULL`／`0`／真數字三選一）跟真的 `revenue`（只認 `action_values`，不再從
`roas` 反推）。真實 Meta 活動只要樣本門檻通過，結案會判「達成」／「未達成」，不再恆是
「看不出」。詳見 `docs/architecture/ads.md` §6.11。RC-D 到此閉環。
