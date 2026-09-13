# Drill 4 — synthesis draft (planner, 2026-09-13, rev 2 after challenge)

來源：`docs/drills/drill-4-final-internal-test.md`、`.harness/scratch/drill4/*/{findings,run}.md`、`.work/features/F04.md`
Open notes、`ARCHITECTURE.md` §0/§4/§5/§6。每條根因都在程式碼查證過。三人各 2 圈走完，六次結案。

## A. Root causes

### RC-A1 商品經濟數字沒有寫入者
- 症狀：F-2／F-10（阿明 Goal・Decision：三情境「累積中」「薑黃錠目前沒有價格資料」）、V 站 1（Vivian 自己繞去產品頁補才有金額）。
- 因果鏈：精靈把售價／成本寫成 `product_fact` 文字 → `save_product_economics`（`app/brand_intelligence/repository.py:715`）
  全專案只有一個呼叫端 `app/brand_web/routes_products.py:479` → `product_economics` 空 → `breakeven_cpa`
  （`app/ads/budget.py:32`）回 None → `_cold_start_scenarios`（`:81-90`）三格金額全 null。上游：「事實文字」與
  「經濟數字」分兩張表，只有商品詳情頁負責後者。層級：**資料模型／流程**。
- 修法：精靈「等你確認」那一步把售價／單位變動成本／運費做成結構化欄位，送出走既有 `save_product_economics`
  （不開新表、不開新 API 形狀）；順手補掉「適用範圍」選單只有「整個品牌／建立新產品…」這個重打一次的洞。
- 不要做：在策略頁再加一條 if「沒有價格就印累積中」（F04-I25 已做完下游那半，再加就是第二層補丁）。大小：中。

### RC-A2 精靈可以「完成」卻一條事實都沒存下來，策略因此讀不到品牌
- 症狀：V-16（Vivian 走完精靈五題，`brand_fact`／`product_fact` 皆 0 列，策略依據印「沒有用到品牌事實」，兩圈皆同）、
  J-7（小杰跳過精靈，`product`／`brand_fact` 0 列，系統照樣讓他走完兩圈、零提醒）、Vivian Q11（文案連不回任何品牌事實）。
- 因果鏈：`strategy._brand_facts_section`（`app/ads/strategy.py:47-53`）只讀 `brand_fact(status='confirmed')`、
  `_products_section` 只讀 economics → 精靈結果若沒落成 confirmed 事實，策略與文案都看不到 → 生成出「換個品牌一字不用改」的內容。
  上游：沒有一處定義「一個品牌要能投放，最少要有哪些知識、誰寫誰讀」；沒有前提就沒有東西能檢查。層級：**資料模型／擁有權**。
- 修法：(1) 先量精靈走完之後 `brand_fact`／`product_fact` 各幾列、卡在哪一步（唯一要被推翻的數字）；(2) 定義「最低
  可投放集合」（≥1 商品＋economics＋≥N 條 confirmed 事實＋已指定的廣告帳戶），由 `app/ads` 出一支前提讀取，建立
  Campaign 與發布入口共用（餵 RC-G）；(3) 明寫哪些事實進策略 prompt、哪些進文案 prompt。
- 不要做：把 `_brand_facts_section` 改成連 pending 事實一起讀（讓沒人確認過的猜測進 prompt）。大小：中（兩張票）。

### RC-B 預算引擎不讀使用者已經宣告的東西
- 症狀：V-1（目標 CPA 889＝毛利 1,270×0.7，成功條件 ROAS 2.5 換算應為 752，同頁並存不解釋）、
  V-13（第二圈推薦 137,795，她宣告的預算是 60,000；且仍走「冷啟動估算」）。
- 因果鏈：裁決 4 把目標 CPA 定成「打平 × 0.7」（`app/ads/budget.py:19`）→ `scenarios()`（`app/ads/budget.py:69`）
  的參數只有 product_ids／days／history，**成功條件與 `constraints_json.budget` 都不在裡面** →
  兩個「目標」並存、推薦金額可以是宣告預算的兩倍。第三條線：`budget_history` 需要 CPA（購買數），
  購買數未追蹤（RC-D）→ history None → 第二圈仍是冷啟動。架構擋不住：成功條件與預算上限住在 `ads_campaign`，
  預算引擎只拿 product_ids。層級：**核心定義**（與 2026-09-12 裁決 4 衝突，要使用者重裁）。
- 修法：`scenarios()` 多收 success_criterion 與 budget cap：有 ROAS／CPA 目標時目標 CPA 由它推導
  （ROAS → 客單價 ÷ 目標 ROAS），沒有宣告才回到「打平 × 0.7」；超過宣告預算的情境不推薦或在 basis 說明為什麼超。
- 不要做：在畫面上加一句「這兩個數字不一樣是正常的」。大小：小（一支函式的輸入＋basis 文案）。

### RC-C offer 座標預設全開，模型挑得到品牌沒有的優惠
- 症狀：F-4 重複發生（阿明第一圈 12 則廣告只有 3 則 `none`：免運 ×3 版、試用 ×3 版、折扣 ×5 版，商品運費 80、
  使用者沒說過任何優惠；阿明第二圈 6 組有 2 組；Vivian 第二圈 discount／bundle／free_shipping／guarantee，文案印出
  「現在入手還有折扣」「回購組合與加贈內容」）；三人之二、六圈之三，全部流進手動發布清單。Vivian 自己在畫面上找到
  機制：品牌智庫 → 創意座標 → 優惠，七個優惠全部「啟用」，藏在三層深，從沒問過她。
- 因果鏈：`ensure_coordinates_seeded`（`app/schedule/repository.py:158-167`）每個品牌都種下 offer 七個值（含
  `free_shipping`／`discount`／`trial_sample`／`bundle`／`guarantee`／`limited_time`），且 `disabled_at` 為 NULL＝啟用 →
  `coordinate_vocabulary`（`app/ads/repository.py:472-483`，已經有 `disabled_at IS NULL` 過濾）原樣餵進詞彙表
  （`app/ads/plan.py:58-62,145-157`）→ 模型在 offer 維度照挑 → 文案提示詞要求「一字不差照座標寫」→ 假優惠上清單。
  層級：**資料模型／提示詞契約（上游）**。
- 修法（較小路徑）：種子把那六個促銷 offer key 種成 `disabled_at = now()`，只留 `none` 啟用；品牌真的有優惠時用既有
  座標畫面開啟（`set_coordinate_disabled`，`app/schedule/repository.py:267`）。不新增宣告制資料結構、不新增設定入口。
- 不要做：在 copy 提示詞加一句「不准寫免運」（`offer_key` 照樣會被指派，條件沒消失）。大小：小（種子一處）。

### RC-D 購買數其實已經在資料庫裡，只是被一條規則擋著不准用
- 症狀：J-4／J-9（ROAS 2.24 ≥ 目標 2.0 判「看不出」；2.01 貼線同一句）、F-6／F-11（阿明兩圈 CPA 永遠看不出）、
  V-11（購買未追蹤卻有 ROAS）、V-12（學習句「樣本太小」講兩次、沒說少了什麼）、Vivian Q25（「低」是多少？無答案）。
- 因果鏈：`sample_bucket(purchases, days)`（`app/ads/outcome.py:39-45`）用購買數定義樣本 →
  `ingest_meta` 寫死 `purchases=0`（`app/ads/outcome.py:140`）→ 更關鍵的是 `_bucket` 的
  `tracked_purchase_rows = [r for r in rows if r["source"] != "meta"]`（`app/ads/outcome.py:168`）
  **把 Meta 來源的購買整批丟掉**，註解（`:162-163`）說這是 §0「Blocked if」的規定 →
  `closeout._judge` 在 `sample_bucket == "低"` 直接回「看不出」（`app/ads/closeout.py:60-62`）→ 真實路徑上永遠不下定論。
  既有能力：`meta_entity_spend.actions`／`action_values` 早就存了 Meta 原始轉換陣列
  （`supabase/migrations/20260830000004_meta_entity_spend.sql:34-35`），`app/meta/repository.py:510-521` 的
  `_CONVERSIONS_LATERAL` 早就會解析它——只是 `daily_entity_spend`（`:665`）沒回這一欄。層級：**核心定義＋既有能力沒接上**。
- 修法：(1) 使用者先廢掉「Meta 購買一律當未追蹤」那條 Blocked-if；(2) `daily_entity_spend` 沿用既有 lateral 多回
  `conversions`，`ingest_meta` 寫真的 purchases，刪掉 `outcome.py:168` 的 `source != "meta"` 過濾；(3)「看不出」必須帶
  數字（`missing` 寫「僅 N 筆購買，低於門檻 10」），學習句由同一份 verdict_json 組一次。樣本等級的定義**不動**。
- 不要做：在 closeout 加「ROAS 略過樣本檢查」的例外；也不要只做 (2) 不做 (1)（畫面不會變）。大小：中。
- 反證：Vivian 第二圈自己把探索從 30% 加到 50%，探索 ROAS 2.50 → 1.70、新客 1.60 → 2.20——系統站 10 拒絕依低樣本
  加碼是對的；要修的不是「敢下定論」，是「說出樣本是幾」。

### RC-E 座標成效讀的是退場中的 schedule 綁定，看不見新迴圈的廣告
- 症狀：V-9（經營概況／素材成效比較顯示「未標座標 8 則」，她的三角度測試在產品裡比不出來）、V-12（學習句沒有角度）、
  V-10（廣告層沒有 ROAS）、Vivian Q22／Q26（三個角度誰贏：無答案）。
- 因果鏈：F03 決定 schedule 套件留著給經營概況讀四個判讀面（`ARCHITECTURE.md:428-432`：creative-performance、
  diagnosis、coordinates、舊廣告 history）→ `app/schedule/performance.py` 的座標成效靠 `channel_entity_map`＋
  `creative_candidate` → `app/ads`（全套件 grep）從不寫這兩張表 → 新迴圈的每一塊花費在舊面板上都是「未標座標」。
  層級：**模組邊界／資料來源**。
- 修法與**真正的退場範圍**：`performance.py` 不只餵那支端點，還餵 `diagnosis.py:510` 與
  `jobs.py:59,130`（`ad_performance`）。這一輪只能做：(1) `app/ads` 出一個座標成效讀取入口（讀 `ads_ad.coordinates`
  ＋`ads_outcome_daily`）；(2) 經營概況的素材成效比較改打這支；(3) 移除 schedule 的 `creative-performance` 端點與其
  前端讀者。**留著不動**：diagnosis 與 jobs 仍吃 `performance.py`，coordinates／舊廣告 history 也還在——套件**不退場**，
  `ARCHITECTURE.md:431` 的條件仍未達成，§4 要改寫成「四個讀者搬走了第一個」。順帶解掉 V-10：每則廣告的 ROAS
  `_bucket` 早就算好（`app/ads/outcome.py:253-266`），只是畫面只印花費占比——顯示它不等於在廣告層分配預算。
- 隱藏依賴（要先裁決）：`app/tests/test_architecture_boundaries.py:500-509` 的 LAYER_ORDER 只允許 schedule → ads，
  所以「ads 出入口、`app/schedule/routes.py:469` 去讀」機器檢查合法，卻是往退場套件加新工作（違反 `ARCHITECTURE.md:431`）。
  建議：端點直接掛 ads 的 router、前端換 URL，schedule 不加新程式。
- 不要做：把 ads 的綁定回寫一份進 `channel_entity_map` 讓舊面板看得到（同一份真相存兩處）。
  大小：大（讀取面＋端點搬家＋前端換來源＋刪舊端點），可拆三票；套件退場不在這一輪。

### RC-F 「後端做完了，畫面不說」——同一個名字底下三個機制
共同上游：沒有人擁有「一個動作的結果怎麼回到畫面上」，所以三條路各自漏；三個修法互不替代。
- **F-1 非同步生成沒有通知**（F-5／V-5：素材生成完不自更新，Vivian 等 4 分鐘，畫面同時印「還沒有生成過」與
  「上一輪還在跑」；V-15 同一批任務三種行為）。全站 8 份各自寫的輪詢（`layout/ActiveJobsBell.tsx:33`、
  `intake/useIntakeJob.ts:43`、`products/ProductDetailPage.tsx:98`、`library/PersonaSection.tsx:47`、
  `library/tabs/CustomerVoiceTab.tsx:49`、`report/BrandReportPage.tsx:57`、`intake/HistoryPage.tsx:83`、
  `cockpit/DiagnosisPanel.tsx:80`），而 `components/{ads,workbench}/` **一份都沒有**——最新的兩個功能根本沒接。
  後端已有單一出口 `GET /api/jobs/active`（`app/dashboard/routes_jobs_api.py:82`），`workbench_copy`／
  `workbench_image_prompt` 已在對照表（`:43-47`），但 `action_url` 指向已退場的 `/app/brands/{id}/schedule`（`:74`），
  `ads_*` 三種 task_type 不在表裡。修法：一支共用 hook 訂閱既有出口（品牌＋kind），工作從清單消失就重抓該頁資料；
  補 `ads_*`、修 action_url。既有 8 份輪詢屬於別的頁面，這張票不刪（有票動到時再收）。
- **F-2 同步回應沒有被渲染**（J-2(b)／V-7／J-6：配對按鈕按了像沒反應）。`manual.bind` 缺前提時回 200＋一句訊息
  （`app/ads/adapters/manual.py:132-135`），`PublishPage.tsx:172-222` 只在「沒有全綁」的分支印 `bindMessage`，
  **成功時一句都不印**。修法：bind 回應一律帶「做了幾項／剩幾項／缺什麼前提」，成功與失敗印同一塊（同 RC-G 的字串來源）。
- **F-3 行動紀錄硬截 6 筆且沒有出口**（V-7／Vivian 第二圈：9 月的紀錄被擠掉）。`app/ads/routes.py:80`
  `recent_actions(..., limit=6)`。修法：加「查看全部」，或照 F04 既有規矩印「另有 N 筆沒有列出」。
- 層級：**狀態流**（F-1）＋**畫面契約**（F-2、F-3）。大小：中／小／一行。

### RC-G 「這一步需要什麼、結果是什麼」沒有單一出處
- 症狀：F-8／J-1／V-6（發布只看到「自動發布未接上」，手動清單藏在「更多發布方式」，小杰判成「按鈕壞了」）、
  F-3／V-3（理解如下六格沒有成功條件）、V-4（手動清單缺日期與圖片提示詞、名稱截斷卻寫「一字不差」、複製零回饋）、
  J-5／J-8（成效頁沒有一句對目標的判斷、每組沒跟目標比）、V-8（「第 13／30 天」不解釋）。
- 因果鏈：每個畫面自己決定顯示什麼——`ConfirmBriefPage.tsx:196-211` 的目標格只印 `campaign.objective`，
  而 `success_target` 早就在 payload 裡（`app/ads/brief.py:187-189`）；`PublishPage.tsx:61,145` 一般路徑只印
  `describe.message`，前置條件與下一步不在同一個回應裡。上游：F04 決定 10「判斷句歸程式」只做到首頁／清單／總覽。
  層級：**畫面契約（lifecycle）**。
- 修法（先小後大）：(1) 目標格印「購買・CPA ≤ 300」（欄位已在手上，不改契約）；(2) 發布入口在前提不足時把主按鈕
  換成該前提的下一步（吃 RC-A2）；(3) 成效頁每組對目標一句判斷、手動清單補日期與圖片提示詞、複製給回饋；
  (4) **要裁決才做**：欄位清單改由後端給（六格變七格）——動 ARCHITECTURE §6.1 第 11 條。
- 不要做：一頁一頁加提示字（三個人撞到的是同一個缺口的 9 個切面）。大小：一行／中／中；(4) 視裁決。

### RC-H 系統把「模型的建議」與「使用者的決定」存成同一件事
- 症狀：V-2（第 5 題預設勾「已有測試數據，可支持明確宣稱」——法規風險最高的一格）、V 站 1（第 1、2 題各出現兩個
  一字不差的選項，其中一個掛「AI 建議」）、J-2（小杰只貼權杖沒勾品牌，系統放行、他給 10 分，到第 7 站才爆）。
- 因果鏈：`intake/steps/QuestionStep.tsx:107` 的 `useState("suggested")` 對每一題都預選模型建議，且 `question.branches`
  與 `question.suggested` 沒有去重（同檔 `:145-155`）→ 一路按下一步＝全盤接受模型的猜測；Meta 連線同一個模式：
  `POST /api/meta/token` 與 `POST /api/meta/brands/{id}/accounts/{id}` 是兩支獨立端點（`app/meta/routes.py:58,83`），
  沒有一處要求第二步 → `manual.bind` 只好在最後一站回「還沒綁廣告帳戶」（`app/ads/adapters/manual.py:15`）。
  上游：把「連上了」與「可以用了」當成同一個狀態。層級：**預設值／狀態定義**。
- 修法：問答題預設不選（未選時送出鍵停用），AI 建議只掛標籤；選項與建議重複時不重複渲染；
  Meta 連線把「指定給品牌」做成同一步的必填，或連線頁在未指定時顯示未完成而不是綠勾。
- 不要做：把 bind 的 200＋訊息改成 400 就當修好（只換了症狀的顏色）。大小：小。

### 不屬於產品（給操作者，不進 F05）
- J-3：沒綁帳號時 `scripts/drill/fake_meta mirror` 把活動塞進 `accounts[0]`（別人的帳號）→ 改成「找不到綁定就拒絕」。

## B. Golden Path 七站 × 三人

| 站 | 阿明（2 圈完） | 小杰（2 圈完） | Vivian（2 圈完） |
|---|---|---|---|
| Goal | 部分：`success_metric=cpa／target=300／budget 28000` 有存，但 `product_economics` 0 列（F-2）、六格無成功條件（F-3） | 不通過：`product` 0 列、`brand_fact` 0 列、`product_ids=[]`，無任何 intake 呼叫，畫面零提醒（J-7） | 部分：走完精靈但 `brand_fact`／`product_fact` 皆 0 列（V-16）；economics 靠她自己繞去產品頁補；六格無 ROAS 2.5（V-3） |
| Decision | 通過：`llm_task` brief_parse 1／strategy 1／delivery_plan 1（無 error），3 組 6 廣告，−NT$10 捨入差有標 | 部分：三情境全「累積中」，靠自訂預算過關；−NT$5 有誠實標示 | 部分：目標 CPA 889 與成功條件換算 752 並存（V-1）；第二圈推薦 137,795 對宣告 60,000（V-13） |
| Production | 部分：`workbench_pack` 已核准（copy 5 輪／image_prompt 4 輪），但第一次觸發停止條件（白畫面，已修）＋假優惠（F-4） | 部分：素材 7／7，14 下確認；文案在零品牌知識下生成 | 部分：8 組 vs 她要的 3 角度；生成完不自更新（V-5／V-15）；文案零品牌事實（Q11）；第二圈再現 F-4 |
| Execution | 通過：`ads_action` publish 1／bind 10 confirmed_manual，三層 external_id 全綁 | 不通過→通過：首次 bind 無任何列（帳號未指定品牌，畫面無感）；補綁後 bind 11 列、live／bound | 部分：第一圈 11 節點、第二圈 10 節點全綁，但同畫面零回饋（V-7）、清單缺日期與圖片提示詞（V-4） |
| Outcome | 通過：group 36／ad 72 列，spend 12,348 兩層各自相等；第二圈 13,188 | 通過：12 天 9,306 兩層各自相等 | 部分：第一圈 25,584、第二圈 24,606（9,222＋7,248＋8,136＝廣告層總和＝總計）兩層各自相等，但素材成效比較「未標座標 8 則」（V-9） |
| Learning | 部分：closed／看不出（CPA 未追蹤、樣本低），`learning_ledger` 1 列 observed／低／source_cycle_id 對 | 部分：closed／看不出，ROAS 2.24 ≥ 2.0（J-4）；第二圈 2.01 同一句（J-9） | 部分：兩圈都 closed／看不出（ROAS 2.01 對 2.50），第二圈學習句與第一圈**只差活動名**（V-12）；品牌智庫仍無學習分頁 |
| Next Decision | 通過：campaign 2 `budget_basis_json.basis.learnings` 含 `lrn_01M2D7903J1H3NB0H081M9B3CT`，55/25/20 → 50/30/20，但「主要原因」沒說學習改了什麼（F-9） | 通過：策略「主要原因」直接引用第一圈學習；45/25/30 → 45/20/35 | 通過（三人中最好）：campaign 2 basis 含 `lrn_01M2DCVKEJ44878CJNP2XX73DG`，「主要原因」明說「學習指出樣本低，所以不照你的要求砍組加碼」 |

**「能不能自我進化」：機制通、內容空。** 三人的第二圈 `basis.learnings` 都實際帶上第一圈的 learning id，配置也真的動了；
兩人（小杰、Vivian）的「主要原因」明講學習改了什麼，阿明那圈沒有（F-9）——鏈路是通的。
但**六次結案 verdict 全部是「看不出」**（RC-D），學習句從未指出缺了什麼、第二圈與第一圈只差活動名（V-12），
所以配置變動沒有證據支撐。反過來說，系統拒絕依低樣本加碼是對的：Vivian 自己加碼探索的那一手退步了。
結論：今天是「會傳話」，還不是「會進化」；缺的是學習裡的數字，不是膽子。

## C. 通過標準六條

1. 三人兩圈、無停止條件 — **不成立（一次）**：阿明第 5 站按「套用」後整頁白，符合停止條件 4（畫面死路），
   演練中斷、由 I24–I26 修復後再續（`aming/run.md:130-134`）。小杰、Vivian 全程零停止條件。
2. 七站都有 DB 證據＋Next Decision 連得上學習 — **三人皆成立**（見 B 表的 learning id）。
3. 阿明主路徑無 ≤4 分 — **不成立**：站 1＝3、站 5 第一次＝1、站 11＝4
   （阿明 3/8/6/6/5/5/9/5/6/7/4/9・6；小杰 9/10/8/7/7/4/3→9/6/6/8/7/9・7；Vivian 6/9/5/6/4/5/4/5/6/7/5/3・5）。
   小杰亂點未造成資料錯亂 — **成立**（唯一的跨品牌串線 J-3 是演練替身 `fake_meta` 的 fallback，不是產品）。
   Vivian 的「憑什麼」都找得到答案 — **不成立**：40 題中 9 有答案、5 半套、**26 沒有**。
4. 零 HTTP 5xx — **觀察上成立**（三人與操作者全程未回報 5xx；白畫面是前端讀 undefined 崩，不是 5xx；
   沒有伺服器 log 層級的計數佐證）。錢的不變量 — **成立**：12,348／13,188／9,306／25,584／24,606 五次結算
   兩層各自相等，日預算 × 天數＝畫面總額，捨入差 −NT$10／−NT$5／−15／＋977 都在畫面上標出來。
   Vivian 第二圈的「花費 8,136 > 日預算上限 4,644」是替身按 `--daily-total` 編的花費，**不是產品算錯**。
5. 沒有 0 冒充未追蹤、成效無因果句 — **成立**（購買印「未追蹤」不是 0）。但 V-11 指出反向的不誠實：
   購買未追蹤卻印得出 ROAS，且保守／樂觀的定義不在成效頁上。
6. <7 分的步驟都落成 backlog 一檔一條 — **未完成**：目前只有 `docs/backlog/issue-intake-never-writes-product-economics.md`
   落檔，其餘待本次綜整轉票。

## D. F05 形狀（依賴順序）

1. **RC-D**（廢掉 Meta 購買封鎖規則＋接上既有 lateral）——擋住 Learning 站的一切，且 RC-B 的 history 也等它。
2. **RC-A1**（精靈寫 economics）與 **RC-C**（六個促銷 offer 種成 disabled）——互不相干，可平行，兩張都小。
3. **RC-A2**（先量精靈到底存下什麼，再定義最低可投放集合＋前提讀取）——餵 RC-G 的發布入口。
4. **RC-B**（預算引擎讀成功條件與預算上限）——依賴 RC-A1 的數字先存在。
5. **RC-F**（三個修法：共用 job hook／bind 回應印結果／行動紀錄出口）——獨立，可平行。
6. **RC-G**（一行的目標格 → 發布入口 → 成效與清單）——(2) 依賴 RC-A2。
7. **RC-H**（預設不選、連線兩步併一步）——獨立，最小。
8. **RC-E**（座標成效換來源）——最大，放最後；V-10 的「廣告層顯示 ROAS」是一行（資料已算好）。

一行級：RC-G(1) 目標格帶成功條件、`_QUEUE_JOB_KINDS` 補 `ads_*` ＋修 workbench action_url、RC-F-3 行動紀錄出口、
strategy 提示詞加「若用到學習，說明它改變了什麼」（`app/departments/ads/strategy.md:27`）、F04 note 10／note 1。

Vivian 的五條「要我採用就得有」（可當 F05 驗收語）：商業承諾類座標預設全關（RC-C）／角度層看得到 ROAS（RC-E）／
購買未追蹤時不准顯示 ROAS 數字（RC-D）／配對要有回饋（RC-F-2）／學習要帶數字與樣本量（RC-D）。
觀察（非缺陷）：產品沒有任何一處把實際花費與日預算上限擺在一起比（F05 可順手加）。

需要使用者裁決（planner 不自己改）：
- **廢掉「Meta 購買一律當未追蹤」這條 §0 Blocked-if**（RC-D）。不廢，後面兩步做了畫面也不會變。建議：廢。
- **與 2026-09-12 裁決 4 衝突**：目標 CPA 是否改由成功條件推導、推薦金額是否受宣告預算約束（RC-B）。建議：兩個都改。
- **與 ARCHITECTURE §6 第 3 條衝突**：廣告層是否顯示觀察到的 ROAS／CTR（RC-E／V-10）。
  建議：顯示，但仍不在廣告層分配預算——「不分配預算」與「不給看數字」是兩回事。
- **座標成效端點掛在哪**（RC-E）：建議掛 ads 的 router、前端換 URL，schedule 不加新程式；並認這一輪套件不退場，§4 要改寫。
- **offer 預設全關的取捨**（RC-C）：品牌要用優惠得去座標畫面開啟，多一步。建議：接受。
- 建檔精靈是否收經濟數字（RC-A1）＋「最低可投放集合」的門檻怎麼定（RC-A2）。
- **理解如下六格變七格、欄位清單改由後端給**（RC-G(4)）——會動 ARCHITECTURE §6.1 第 11 條。不裁決就只做一行版。
- F04 Open note 13（`ended` 補寫入者還是刪掉）與 note 14（`closed` 之後成效還會被灌進來）——兩題各二選一。
