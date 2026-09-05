# 目標：在本機跑完一輪廣告閉環，不上雲

Status: 進行中——①～⑦ 已走完（2026-09-04），只剩 ⑧⑨；卡在資料不是程式。
全文出處：`BOARD.md` @ commit `6574191`（看板改成一行一目標前的最後一版）。

一輪 = 憲法第 4 條的那個環，走一遍：

```
①建品牌＋綁 Meta → ②排程頁填表出方案 → ③展開三層活動樹 → ④核准
→ ⑤產素材（帶七維座標）→ ⑥人照樹上的名稱在 Meta 手動建廣告
→ ⑦名稱精準比對綁定 → ⑧花費／ROAS 回流接上座標 → ⑨判斷 → 回到②
```

管線整條都在（`/plans`→`/tree`→`/tree/approve`→`/tree/bind`→`/creative`→`/creative-performance`）。

## 現況（2026-09-04）

- ①：使用者貼上權杖，`brd_bughunt`（Beast Prime 野獸至尊）綁上 BP AD（`act_368741390835357`），
  `conversion_goal='purchase'`（照拉回來的真資料判的：購買 474、開始結帳 684、加購物車 912）。
- ②～⑦：出方案、展開三層樹、產素材（七維全填、T8b 驗收通過）、在 Meta 手動建了
  「Beast Gummy｜廣泛開發｜銷售」整條（活動＋組合＋廣告01，發布後關閉）、名稱比對三層全綁上
  （commit `5dfe8d8`）。
- ⑧⑨：綁上的那條是關閉狀態、沒花過錢，所以沒有數字回流；⑨ 的前半（座標賺賠圖
  `CoordinateQuadrantChart.tsx`）已上線，後半（三個 agent 的診斷）見 `issue-t6c-three-agent-diagnosis.md`。
- **有座標的花費今天是 0 元**：唯一綁上的深度 3 節點 `1.1.1 → 120251641305860671` 在
  `meta_entity_spend` 是 0 列；本月廣告層 32 列、6,458 元、8 則廣告全部落在「未標座標」桶子。
  任何需要「有座標的花費」的東西今天都畫不出來，不是程式壞了。
  （2026-09-04 傍晚重驗一次，數字一模一樣：直接叫
  `performance.brand_creative_performance(conn, "org_bughunt", "brd_bughunt")`，
  七個維度的 `values` 全是空陣列，`untagged` 每維都是 6,458／8 則。）
- **同名最深層節點配錯**已根治（2026-09-04，route B）：代理現在也回 `node_key`，答得出來就
  照編號配、漏答或答錯退回原本的名稱排隊。決定改在 `docs/contracts/schedule.md` 的 T3d 那條。

## 排序（離閉環多遠，2026-09-04 使用者裁決）

錢的那三顆 bug（M1／T7／M2）2026-09-04 全部修完並合併，所以才輪得到用「離閉環多遠」排。
**之後又冒出會靜靜算錯錢的東西，一律插回最前面。**

1. `issue-t6c-three-agent-diagnosis.md` — 閉環現在就是斷的；開票條件是資料不是程式。
2. `issue-variance-probe.md` — 探針要使用者自己跑一次，跑出數字才回頭重判。

（`issue-same-name-leaf-node-key.md` 2026-09-04 做掉、刪檔；`issue-image-on-ad-node.md` 同日
重判完畢，判不做，檔案留著記結論，不要再問第三次。）

每日拉取 worker 是獨立行程（ADR 0063，`啟動行銷系統.bat` 會順便開起來）；worker 沒開或
機器關著的日子照樣沒人拉，手動補 `uv run python -m app.meta.daily_pull`。

## 你要做的（agent 做不了）

- **把剩下的節點也貼進 Meta 並打開**（廣告02、廣告03、第二個行銷活動那整條）。名稱去排程頁
  「展開結果」複製，**分隔號是全形 `｜`，一定要複製不要用打的**。這是第 1 條的開票條件：
  至少兩個不同的座標值真的花到錢。
- **建檔精靈**：`brd_bughunt` 的品牌事實仍是空的（已確認事實、顧客原話、規則卡都空）。不擋閉環，
  但方案品質差一階——代理只能靠通用方法論寫。這是設計上允許的（憲法「資料狀態」）。
- **晨光咖啡要重建**：2026-08-30 `supabase db reset` 後 8/29 那次資料全部消失。
- **那則手動建的廣告，圖從哪來**——2026-09-04 問完了：使用者自己照提示詞生圖、手動上傳。
  重判結果與理由寫在 `issue-image-on-ad-node.md`，判不做。這一題不要再問第三次。

## 里程碑

第一段 $0——整套在本機 `supabase start` 跑通，用真品牌走完一條路。2026-08-29 用晨光咖啡＋BP AD
走通第一次；2026-09-04 用 Beast Prime＋BP AD 走通第二次，只差 ⑧⑨。第二段才推免費層雲端。
`app/ads/` 那個舊閉環已整個刪除，要回頭看用 tag `v0.2-ads-last`。

## 依據（2026-09-01 重訂，舊的七張票全部作廢）

`CONSTITUTION.md`＋`docs/adr/0050`（資料模型之記錄，25 張表）＋`docs/contracts/schedule.md`。
架構圖與 ADR 0050 不一致以 0050 為準。2026-08-26～31 那輪的十條凍結決定與 S3／S4／S5／⑨ 全部作廢
（資料模型換了：廣告屬通路、檔期是濾鏡、素材帶七維指紋、不得用現況欄位回答當時）。
舊碼與舊決策在 git：`v0.2-ads-last`、`v0.3-onboarding-read-last`、`.scratch/adloop/`。
T8 站①的裁決（33 個候選值、四題）：草案頁
<https://claude.ai/code/artifact/7d1ab1eb-04ca-4e16-9462-83656f140564>；摘要：`format` 只有 3 個
（Meta 版位）；`audience`／`pain` 給的是軸，品牌自己的名字用 `parent_id` 掛底下；`proof: none`／
`offer: none` 要有 key 不留 `null`；代理挑不到值回 `null`＋`coordinates_status='pending'`，不准硬挑。

## T6c 規格（2026-09-06 站①裁決；票 01／02 依這一節而生）

第⑨步後半。使用者選的交付形狀（Premise check，2026-09-06）：**顯示 ＋ 每條建議一顆「採用」**，
按下去把那條變成品牌規則卡——走「我不喜歡這方案」既有那條路（`_run_reject` → `bi_repo.create_rule`
→ `context_compiler` 注入下次 `schedule_plan` 的 prompt）。零新表、零 migration，而且是使用者
按過才算數。全自動回流被同一題否決：AI 判錯的結論無人攔截地餵進下一輪，錯了看不出是哪裡錯。

流程（一條線，每一段各有出處）：

```
畫面「跑一次診斷」→ 程式壓縮（純算術）→ 三次 LLM（素材／受眾／錢）
→ 程式收斂（去重＋按影響金額排序取前 5）→ 畫面顯示 → 每條「採用」→ rule 一列
→ 下次出方案的 prompt 自己吃到
```

### 凍結的決定（每一條都有來源，沒有一條是這一輪現編的）

| # | 決定 | 來源 |
|---|---|---|
| 1 | **打平線 = 1 ÷ 毛利率**，不是固定 1.0（1.0 等於假設毛利 100%，會把賠錢的座標畫成贏家）。毛利率三層，有哪層用哪層：①這個月官網訂單算出來的實際毛利率（`sku_cost` 齊了自動接手）→ ②規則卡 `gross_margin`（新卡，default **0.70**＝打平線 1.43x，2026-09-06 使用者暫定，設定頁可自己改）→ ③兩個都沒有就**不畫線**，畫面明說算不出來 | `app/methodology/ads-commerce.md:13`「打平 ROAS = 1 ÷ 毛利率」；`ab-testing.md:72`「財務線一律用毛利反推」；三層順序＝2026-09-06 使用者裁決 |
| 1b | 新規則卡走 `app/core/rule_cards.py` 的 `CARDS` 常數加一筆即可，**不必 migration**（沒有 DB 覆寫列時 `get_value` 回 `default`，該檔檔頭原文）。順便讓使用者日後自己在設定頁改毛利率 | `app/core/rule_cards.py:1-18` |
| 1c | 逐產品的打平線**這一版不做，但不封死**：`sku_cost` 本來就逐 SKU，缺的是「這則廣告賣掉哪個 SKU」的歸因（`period.compute_money` 註解：營收不分節點）。欄位與 fallback 順序現在就留好，日後接上是打開開關 | `app/orders/repository.py:204-241`；`app/schedule/period.py:202-241` |
| 2 | 收斂靠程式不靠 agent：按影響金額排序**取前 5** | ADR 0057 §6 |
| 3 | **三個固定 agent 按判斷維度分工**（素材／受眾／錢），不按廣告筆數扇出 | 2026-08-31 使用者定案（24-agent／130 條建議的失敗教訓） |
| 4 | 「樣本不足」一律查 `app/methodology/ab-testing.md` §3 速查表，**不用自訂常數**；收不到樣本時介面誠實寫「方向性判讀，不是統計顯著的結論」 | `ab-testing.md:73`、`:75` 原文 |
| 5 | 餵給 agent 的 ROAS 要帶**保守／樂觀兩個值＋覆蓋率**，不是單一數字 | `docs/contracts/schedule.md`「One coordinate has two ROAS values」；算法已在 `frontend/src/lib/quadrant.ts` |
| 6 | 方法論走既有對照表「成效判讀／下期草案」＝ `ab-testing.md`＋`ads-core.md`＋`ads-commerce.md`（需要：有商品）。**這張票是接線，不是寫方法論** | `app/methodology/README.md:36`、`docs/contracts/schedule.md` |
| 7 | `task_type` 用既有的 `performance_reading`（已註冊、零呼叫者，舊表已 drop） | `app/llm/providers.py:151`、`:176` |
| 8 | 零 migration：診斷結果存 `llm_task.rendered_output`；採用寫既有 `rule` 表，**`source_reference_id` 留 NULL**，來源寫進 `content` 的文字裡（例：「本條來自 2026-09-06 的成效判讀」） | `llm_task.task_type` 無 CHECK（`20260826000001_core_baseline.sql:49`）。**原本寫「存 `llm_task.id`」是錯的**：plan review 2026-09-06 實跑 `insert ... rollback`，回 `violates foreign key constraint "rule_source_reference_id_fkey"`，該欄 FK 指向 `source_reference` |
| 9 | 採用寫出的規則 `severity` 一律 `soft`；`rule_type` 只用既有的 `angle`／`audience`／`budget_split` | `app/schedule/routes.py:270` `SOFT_REJECT_RULE_TYPES` |
| 10 | 觸發＝使用者按按鈕，不自動跑 | 出方案／展開樹／產素材三個既有 `llm_task` 都是按鈕 |

### 探針量到的（2026-09-06，模擬資料上跑一次三個 agent）

- 壓縮後 **57 行 / 1,879 字**——原始是幾百列。不爆 token 這件事成立。
- 三個判斷器**都沒有硬掰**：素材器自己算出五個維度數字逐字重複、直接拒答並改給整組層級建議；
  預算器擋住「每個贏的座標只靠 1 支廣告撐」；受眾器把覆蓋率 40% 那條的話說軟。
- **受眾器與預算器的建議重疊**（同樣兩條）——收斂必須去重，否則前 5 名會被同一句話佔掉兩格。
- **判斷準不準這次驗不到**：模擬資料的 ROAS 是亂數。管線／格式／不硬掰驗到了，判斷品質只有真廣告能驗。

### Plan review 打回來的（2026-09-06，Opus 無對話上下文，自己跑指令查證）

review 是備註不是否決權（workflow.md）；下面是每一條的處置，處置權在這一節。

| 意見 | 處置 |
|---|---|
| 打平線 ROAS=1 與方法論檔互斥（實查 `ads-commerce.md:13`） | **採納**，見決定 1／1b／1c |
| `source_reference_id` 塞 `llm_task.id` 會違反 FK（實跑 SQL 證明） | **採納**，見決定 8 |
| 保守／樂觀雙 ROAS 的算術只在 `quadrant.ts`（TS），後端要用等於重寫一份 | **部分採納**：後端不重寫，`_bucket()` 已經有 `revenue` 與兩種花費，保守值＝`revenue ÷ 全部花費`，多除一次而已（決定 11） |
| §3 樣本速查表最寬鬆一格也要每變體 200 次轉換，現況恆真為「不足」，是常數不是邏輯 | **照方法論檔既有結論走**：不寫門檻常數、不查表比大小，介面固定顯示「方向性判讀，不是統計顯著的結論」（`ab-testing.md:75`）。查表留給資料量真的長大的那天 |
| 取前 5 碰不到上限（本月 `level='ad'` 只有 4 個實體／24 列） | **保留**：ADR 0057 §6 的決定，票無權推翻（precedence）。票裡記明今天量到 4 個實體，日後真的長大不必再改一次 |
| 三個 agent 可能不比一個強 | **照 2026-08-31 使用者定案做三個**，但票 01 多一條 done-check：實作完在同一份壓縮資料上跑一次「只有一個 agent」，數出三個比一個多出幾條**真正獨立**的建議，數字交給使用者決定要不要砍 |
| 「本月」窗口在月初只有一天資料 | **不另開窗口**：AI 看到的數字必須跟畫面那張圖是同一份，兩份窗口才是更大的錯。畫面寫明日期範圍與天數，天數太少時由「方向性判讀」那句話擋著 |
| 最簡替代「這輪不做」 | 使用者 2026-09-06 已裁決要做（Premise check 選了「先探針再開票」，探針已跑完） |

| 11 | 餵給 agent 與畫面的 ROAS 一律**兩個值＋覆蓋率**：保守＝營收 ÷ 全部花費、樂觀＝營收 ÷ 有追蹤到的花費。單一數字禁止出現 | `docs/contracts/schedule.md`「One coordinate has two ROAS values that are both true; drawing one is picking a lie」 |

### 這一節新產生的兩條規則（探針逼出來的，票要落實）

- **共線性要由程式標出來，不能指望 agent 每次都自己發現**：一個維度底下每個座標值都只掛 1 則廣告、
  且多個維度的分組完全相同時，壓縮層要在那幾個維度旁邊寫明「這幾個維度分不開，因為是同一批廣告」。
  探針那次素材器抓到了，但那是運氣，不是保證。
- **去重鍵 = (維度, 座標值, 方向)**：同鍵只留一條，並記下「有幾個判斷器都這麼說」——重複不是雜訊，
  是兩個角度指向同一件事的信號。

## 2026-09-04 消融砍掉的四件事（不要再提案一次）

用 computer-use 接管真瀏覽器走了一遍閉環，抓到三個缺陷，五個提案砍掉四個：

1. 「幫配對失敗訊息加一條 Playwright 斷言」——砍。測試只收四類，「錯誤訊息措辭」不是。
   （訊息本身有修，commit `2e24ca1`，改的是既有斷言。）
2. 「開一支 `npm run e2e:real` 真跑驗收腳本」——砍。它只驗得出「不是空的」，斷言比問題弱；
   三個新抽象換一個更差的答案。留下來的是 T8b 那行 SQL。
3. 「版面另開一張票」——砍。長頁那半掛回 U3（`docs/issues/ui/`）。
4. 「右邊一大片空白」這個觀察本身——砍。那是 `--width-form: 42rem` 刻意的表單寬度上限。
   **先看 CSS 再喊版面 bug。**
