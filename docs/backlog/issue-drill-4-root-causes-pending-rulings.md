# Drill 4（上線前最終內測，2026-09-13）：八條根因與八題待裁決 — F05 /dig 的第一份輸入

Status: 2026-09-13 內測跑完（三人各兩圈、六次結案），使用者尚未裁決。完整證據與因果鏈在
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
8. RC-G 前提與結果沒有單一出處（發布入口只印「自動發布未接上」、理解如下沒有成功條件格、成效頁沒有對目標的一句話）；RC-H 模型建議被當成使用者決定（精靈預設勾風險最高選項、Meta 帳號未指定品牌也放行）。

## 需要使用者裁決的 8 題（建議在括號）

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
