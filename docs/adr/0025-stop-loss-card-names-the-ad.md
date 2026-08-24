# 0025 「停掉」下沉到廣告層，「加碼」留在產品層（2026-08-24）

承 ADR 0008（素材分三層：切角 → 主題／一則廣告 → 單張素材；歸因不往主題層以下走）。
起因：驗收 A 第 4 節第 2 題——五支廣告，一支 ROAS 0.86、四支 5.74，整檔 3.79。
週提案卡只出「加碼 Beast Gummy」，「停掉那支」只出現在 AI 白話。

規則層看得到數字卻一句話都沒說，有兩個原因，都不是「沒有資料」：

- `weekly_proposals.select_cards()`（`app/ads/weekly_proposals.py:126-176`）的停掉／加碼
  只讀 `product_readings`，逐支廣告的成效 `asset_breakdown` 就在同一包 `loaded` 裡沒被讀。
- `reading.py:381` 那句規則式的「點名拖累最兇那支」被 `if allocations and not per_product`
  擋住——只有成效分不到各產品時才講。驗收 A 是單一產品、分得出來，所以不會出現。

經 grill 三輪（15 題）裁決如下。

## 決定

1. **「停掉」下沉到廣告（主題）層，不是切角層。**
   依據是卡片自己的指令：`_instruction()` 寫「前往 Meta 廣告後台，找到「{target}」並暫停
   投放」——Meta 後台裡「切角」不是可以按暫停的物件，廣告才是。點名切角＝叫使用者去停
   一個後台不存在的東西。

2. **「加碼」留在產品層，不下沉。** 兩張卡的對稱是假的：
   (a) Meta 的預算在廣告組（adset）層，「把這支廣告加碼」在後台沒有對應動作；
   (b) 加碼卡的 `suggested_amount` 是 `budget.proposed_budget`＝**下期整檔預算**，掛到單支
   廣告上是一個數量級的錯誤金額，而 `approve_card()` 會逼使用者確認這個金額。
   停掉是止血、單支可執行、金額不用算；加碼是花錢、要有預算層級對應。

3. **資料窗＝本期，不是歷史。**
   `nextcycle.historical_cell_performance(exclude_cycle_id=cycle_id)` 排除本期，且它的成效
   SQL 沒有 cycle 條件（跨檔期累加）——驗收 A 那支廣告就在本期，永遠觸發不了。
   改讀 `reading.py:380-384` 已經算好的 `asset_breakdown` 與 `cycle_breakeven`，掛在
   `loaded` 裡 product_id 為 None 那筆判讀上，不新開查詢。
   歷史那條路留給「換素材」不動：換素材本來就該問「這個切角過去打得怎樣」。
   實作時檔期打平線改存進檔期層判讀的 `rule_result_json`；算它的那段從 `reading.py`
   抽成 `reading_verdict.cycle_breakeven_roas()`——`reading.py` 已到單檔 800 行閘門，
   抽出去反而讓它從 800 降到 799，不動容忍清單。

4. **產品層停掉卡存在時，廣告層停掉卡不出。**
   上位動作已涵蓋下位；兩張並存會叫使用者把同一件事做兩次。反過來才是這次要補的洞：
   產品是 `scale_candidate`／`maintain`（驗收 A 就是），但底下有一支在漏血。

5. **門檻用 `reading.judge()`，不用 `nextcycle.cell_trust_flags()`。**
   `plan_budget` 取「檔期預算 ÷ 本期廣告支數」均分（先例：`nextcycle.py:151-153` 對切角
   已經這樣做並標明是刻意簡化）。`status == "pause_candidate"` 才出卡。
   理由是護欄：`cell_trust_flags()` 沒有 `MIN_CONVERSIONS_FOR_DIRECTIONAL_CALL = 10`
   （`reading.py:81`，修憲落地 G4），換素材可以繞過它（便宜、可逆），叫人關掉一支廣告不行。

6. **一次只點名最差的一支**（ROAS 最低），比照 `worst_asset_reason()`。
   卡片總數上限 3 張，一次三張「停掉」會把加碼與換素材整個擠掉；做完一支後重新判讀，
   第二差的自然浮上來。

7. **卡片優先序改成「止血 → 花錢 → 備料」**：
   廣告層停掉 → 產品層停掉 → 加碼 → 疲勞換素材 → 歷史切角換素材。
   `cards[:3]` 照 append 順序砍尾巴，順序即優先序。

8. **去重改用 `pkg_id`，不用 target 字串。**
   疲勞卡的 target 是 `COALESCE(cell.creative_angle, pkg.ad_name)`
   （`reading_assets.py:88`），新的停掉卡是 `pkg.ad_name`——同一支廣告會變成兩個名字，
   現行字串比對（`select_cards()` 的 `any(...)`、`generate()` 的 `handled`）認不出。
   `asset_totals()` 已回 `pkg_id`；`max_frequency_by_asset()` 加選一欄即可。
   同一支廣告同時「該停」與「疲勞」時**只留停掉**：先做新素材再去停一支正在虧的廣告，
   順序是反的。歷史切角那張仍走切角命名空間，不跟這兩張比。

9. **歸屬閘門綁資料，不綁匯入路徑。**
   該筆成效列所走的 `external_ad_mapping` 有 `meta_ad_id`（或 CSV 廣告名對得回交接包）
   才出卡，否則不出（鐵則 16）。
   `reading_assets.py:22-25` 那段「Meta API 同步用 `meta_campaign_id` 而非 `meta_ad_id`」
   的註解**已經過期**：`sync.py:249,270,340,351` 現在優先用 `meta_ad_id`；本票順手改正該註解。
   真正還有洞的只剩「認領既有活動」那條路——`tracking.py:160-164` 建 mapping 時沒寫
   `meta_ad_id`，同一活動多支廣告會擠進同一個 package。**記為本決策的已知上限**，
   根治要補 `tracking.py` 那支 INSERT，是另一張票。

10. **對不準時安靜，不留焦慮句。** 不出卡就是不出卡，不加「可能有一支在虧但我不知道是
    哪支」——不可行動的話只製造焦慮，且與 `worst_asset_reason()` 算不出就回 None 的既有
    態度一致。

11. **`product_id` 填 None；`performance_reading_id` 指向本期 product_id 為 None 的檔期層判讀。**
    廣告層沒有 product_id（`publishing_package` 掛在 `experiment_cell`，切角的 product_id
    常是 NULL，`nextcycle.py` 註解自己標了「真實資料常見」）。指向檔期層判讀是為了可追溯：
    這張卡的數字來源 `asset_breakdown` 就存在那筆的 `rule_result_json`（`reading.py:463`），
    日後回答「當時憑什麼叫我停」查得到當時的逐支數字。填 None 等於斷線，硬湊一個 product_id
    等於編造歸屬。

12. **理由句另寫，不改 `judge()` 的字串。**
    `judge()` 的 `pause_candidate` 理由是「**這些產品**要投報 1.16 倍才回本，這期是 0.86 倍」，
    主詞是產品，套到單支廣告是錯的；改它會波及檔期層與產品層兩個既有呼叫端。
    新句形狀比照 `_tired_reason()` 路徑②：「有成交但每花 1 元只回 0.86 元，低於停損線 0.81」
    ——使用者要能自己驗算為什麼這支該停、那四支不用。

13. **廣告層不走 `_budget_impact()`**，固定一句「先止住這支的花費，另外幾支照跑」。
    停一支廣告跟下期總預算增減沒有因果；照套第一分支會說出「停掉這支 → 下期總預算增加」
    （驗收 A 整檔賺，下期預算是加的）這種自相矛盾的句子。

## 一、ADR 0008 不修訂

0008 的分層是「切角 → 主題（＝一則廣告）→ 單張素材」，它禁止的是**逐張素材**歸因——
主題層是**地板不是天花板**。點名一支廣告正好踩在地板上，沒有越線；點名切角在地板上方。
本決策停在地板上不往下。要動 0008 的唯一情境是有人要求「哪一張圖比較好」，那時另開 ADR
推翻，不是現在偷偷放寬。

## 二、驗收 A 的期望欄不改

`.scratch/orchestrator/ACCEPTANCE-A.md` 第 4 節 (a) 本來就寫著「週卡有一張『停掉』點名 a」。
這次是**程式沒做到規格**，不是規格要放寬。不得改期望欄把閘門從紅轉綠。

## 三、怎麼證明檢查紅過一次

`app/tests/test_ads_weekly_proposal.py`（418 行，未逼近拆檔線）新增三個測試，
第 1 個**在動程式之前先跑、看它紅**：

1. 整檔 ROAS 3.79、五支裡一支 0.86 → 出一張「停掉」，target 是那支廣告名
2. 產品層已是 `pause_candidate` → 廣告層那張不出（決定 4）
3. 那支只有 8 筆成交 → 不出卡（決定 5 的護欄沒被繞過）

既有 `test_all_maintain_returns_empty_array_without_filler_cards` 為回歸網，一併跑。
