# 阿明｜操作者查證紀錄（第一圈，2026-09-13）

brand `brd_01M2D3397KT78QXRV7WBPFBZ88` ／ org `org_01M2D32M0N84QEZZJYFNNZQRFT` ／ campaign 1 `adc_01M2D3RSAAT9AA4FBMQV0Y8NY8`

## 站別證據（資料庫）

| 站 | 證據 | 結果 |
|---|---|---|
| Goal | `ads_campaign`：goal_text 原句、success_metric=cpa、success_target=300、product_ids=[薑黃錠]、budget 28000（user 改過） | ✅（但畫面沒把「300 元以內」顯示在六格裡，見 F-3） |
| Decision | `llm_task`：brief_parse 1、strategy 1、delivery_plan 1（無 error）；3 投放組 6 廣告；-NT$10 捨入差畫面有標 | ✅ |
| Production | `workbench_pack` 已核准；copy 5 輪、image_prompt 4 輪 | ✅（內容說謊見 F-4） |
| Execution | `ads_action`：publish 1、bind 10（1c+3g+6a）confirmed_manual；三層 external_id 全綁 | ✅ |
| Outcome | `meta_entity_spend` 12 天三層；`ads_outcome_daily` group 36 列／ad 72 列，spend 12,348 兩層各自相等；purchases 0（未追蹤） | ✅ |
| Learning | `ads_campaign` closed、verdict 看不出（CPA 未追蹤、樣本低）；`learning_ledger` 1 列 observed／低／source_cycle_id 對 | ✅ |

## 缺陷（症狀 → 因果鏈 → 層級）

- **F-1 白畫面／假錯誤（已修 I24–I26）**：症狀＝自訂預算套用後整頁白、主按鈕回「找不到這個預算情境」。
  因果鏈：六條寫入路由各自手拼回應、少了 `asset_readiness` → 前端讀 undefined 崩 → 全站沒有 ErrorBoundary。
  上游決策：路由層手工組回應、沒有單一序列化點。本次修法是 helper＋ErrorBoundary；**根因層級**＝回應形狀沒有單一擁有者，
  F05 應考慮「Campaign 回應只從一個函式出」（已部分做到：`_with_readiness`）。
- **F-2 建檔精靈不寫商品經濟數字**（backlog `issue-intake-never-writes-product-economics.md`）：症狀＝策略頁三情境「累積中」、
  「薑黃錠目前沒有價格資料」。因果鏈：售價／成本被存成 `product_fact` 文字 → `product_economics` 空 → 冷啟動算不出目標 CPA。
  上游決策：資料模型把「事實文字」與「經濟數字」分成兩處，精靈只餵前者。**層級＝資料模型／流程**，屬重構題（精靈的確認步驟直接寫 economics）。
- **F-3 「一筆訂單廣告成本 300 內」沒有出現在理解如下**：資料庫其實有抓到（success_metric=cpa、target=300），
  但六格只有「目標＝購買」，成功條件沒有一格。症狀＝使用者以為被吃掉。**層級＝畫面契約**（理解如下少一格「成功條件」或目標格要帶「CPA ≤ 300」）。
- **F-4 文案編出「免運」**：第 5 組廣告 5 版文案有 3 版寫「現在下單享免運」，商品運費 80、使用者沒說過。
  因果鏈：copy 提示詞的「可用字句」只管數字與宣稱來源（§5.9），優惠（offer）不在限制內；offer 座標若是「免運」類的 key，模型就照座標寫。
  要查：該廣告的 `offer_key` 是什麼（座標詞彙裡有沒有「免運」）。**層級＝座標詞彙／提示詞契約**：offer 座標必須只從品牌真的有的優惠挑，或 prompt 明列「本次可用優惠＝無」。
- **F-5 「後端做完、前端沒說」家族**：素材工作檯「上一輪還在跑」要重整才更新。與 F-1 同族（前端不知道後端狀態變了）。
  **層級＝狀態流**：輪詢／重新整理策略沒有統一（各頁自己決定）。F05 /dig 題。
- **F-6 ROAS 有值但購買未追蹤，使用者看不懂「有沒有賺」**：設計如此（Meta 路徑 purchases 未讀，F05）；但畫面沒解釋「ROAS 是平台回報的營收÷花費」。
  **層級＝文案**（成效分頁每個數字要有一句來源）。
- **F-7 結案文字說「會在品牌智庫留一條學習」，品牌智庫沒有學習分頁**：F03 已知（F04 決定：F05 加分頁）。承諾句要改成不承諾看得到，或 F05 補分頁。
- **F-8 發布 Campaign 先看到「自動發布未接上」空畫面**：手動發布藏在「更多發布方式」。裁決 1 設計如此，但新手卡了一下（5 分）。
  **層級＝資訊架構**：未接上時主按鈕應直接帶到手動清單並說明。

## 分數

站 1：3 ／ 2：8 ／ 3：6 ／ 4：6 ／ 5（重來）：5 ／ 6：5 ／ 7：9 ／ 8：5 ／ 9：6。

## 第二圈補充（2026-09-13）

| 站 | 證據 | 結果 |
|---|---|---|
| Next Decision | campaign 2 `budget_basis_json.basis.learnings` 含 `lrn_01M2D7903J1H3NB0H081M9B3CT`（第一圈的學習）；配置 55/25/20 → 50/30/20 | ✅ Golden Path 的 Learning → Next Decision 接通 |
| Execution 2 | mirror --append；bind 10 列；9 節點全綁 | ✅ |
| Outcome 2 | 操作者以 SQL 把期間搬到 9/2～10/1（演練無法等到 10 月）；12 天、13,188，兩層各自相等 | ✅（道具調整，非產品行為） |
| Learning 2 | closed／看不出（CPA 未追蹤） | ✅（F05 讀購買數前，CPA 目標永遠看不出） |

- **F-4（續）亂編優惠是重複發生**：第二圈 6 組有 2 組（「可先索取試用體驗」×3 版、「折扣／優惠」×5 版，沒有乾淨版本可選）。兩圈都流進手動發布清單。**層級：提示詞契約／座標詞彙**——優惠只能來自品牌真的有的（promotion_note／offer 座標），模型不得自行生成 offer 字眼；要查該廣告的 `offer_key`。
- **F-9 配置從 55/25/20 變 50/30/20 沒說為什麼**：「主要原因」沒有一句引用學習。層級：strategy 提示詞要求「若用到學習，說明它改變了什麼」。
- **F-10 商品價格兩輪都「沒被用到」**：同 F-2 根因（economics 空）。
- **F-11 「購買未追蹤」兩輪皆同**：F05 Meta 購買數讀取；文案應解釋 ROAS 的來源（平台回報）。

## 分數（全程）
1:3 ／ 2:8 ／ 3:6 ／ 4:6 ／ 5(重來):5 ／ 6:5 ／ 7:9 ／ 8:5 ／ 9:6 ／ 10:7 ／ 11:4 ／ 12:9+6。
總評：會用但不敢全押；最卡＝建檔精靈、第 5 站當機（已修）、亂編優惠。

## F-4 成因（操作者查證，2026-09-13）

不是文案模型「幻覺」，是**上游的投放結構把優惠指派給了廣告**：`ads_ad.offer_key` 直接來自 `delivery_plan.md`
從品牌座標詞彙的 `offer` 維度挑的值——`free_shipping`（免運）、`trial_sample`（試用體驗）、`discount`（折扣特價）、
`bundle`（組合加贈）都是每個品牌預設就有的通用詞彙，跟這個品牌到底有沒有這些優惠無關；文案提示詞照座標
「一字不差」寫出來，所以「免運」「試用」「折扣」全是照指令做的。12 則廣告只有 3 則是 `none`。
因果鏈：座標詞彙把 offer 當成「創意角度」的通用選項 → delivery_plan 沒有「品牌實際可用優惠」的輸入 → 模型憑感覺分配 →
文案忠實執行 → 假優惠流到發布清單。**層級＝資料模型／提示詞契約（上游）**：
根因修法＝offer 維度必須由品牌宣告（哪些優惠真的存在，來源可為 promotion_note／品牌事實／產品頁），
delivery_plan 只能在宣告過的集合裡挑，預設只有 `none`；不是在 copy 提示詞加一句禁令（那是修症狀）。
