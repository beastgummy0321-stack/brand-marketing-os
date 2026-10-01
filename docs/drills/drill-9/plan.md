# Drill 9 — 重跑 B 側（F41–F43 之後），先重排建檔（2026-10-01，使用者點頭：照計畫跑、三樣都刪；結果見 report.md）

目的：建檔改成「品牌建檔 7 步 → 商品建檔 5 步 → 建活動選賣法」（intake.md F42／F43、ads.md §6.46／§6.47），舊劇本走不通。
只重排四件：演員劇本、品牌事實補充、AI 預填讀的官網、新增量測。**演練中不修產品程式**；缺口只記錄（對回檔案行號）。

沿用不動：A 側（`.harness/scratch/drill6/rows_A_1..3`、`fit_A_1..3`）、`../drill-6/contract.md`、`judge-rubric.md`、
`../drill-4/persona-rules.md`、`../drill-7/plan.md` 的每期流程、`tw_sim`、Meta 替身、`.harness/scratch/drill8/judge-prompt.md`、
drill 8 的期別與兩套模擬（實際日期＋對齊 A 窗）。

## 只換了什麼

| 項 | drill 8 | drill 9 |
|---|---|---|
| B 系統 | master `aeb1812c` | master（F41–F43 之後） |
| B 帳號 | beast.drill8@example.com | 新註冊 `beast.drill9@example.com`（新組織） |
| 建檔 | 貼文字 → 真相卡 → 賣什麼與數字 | 品牌 7 步 → 商品 Beast Gummy 5 步 → 賣法 → 組合（典藏組） |
| AI 讀的網站 | 無 | 本機固定副本（下節），persona 輸入真網址 |
| 期別 | P1 10/3–10/9、P2 10/10–10/16、P3 10/17–10/23 | 同 drill 8（規劃日都晚於真實日期 10/01），B8 可直接對照 |

## 1. 官網固定副本（AI 預填讀這份）

- 9/26 當天的網頁原檔不存在（沒存檔、Wayback 無快照），而官網 9/29–9/30 已改過商品頁。做法：10/01 抓下原檔
  （`.harness/scratch/drill9/site_raw_20261001/`，證據），刪掉 9/26 紀錄（`../drill-6/brand-facts.md`、`.harness/scratch/drill6/A/research.md`）
  證實不了的內容，存成 `scripts/drill/site/`。刪除清單：
  1. 「爆能野獸盒（12 顆）NT$400」商品卡與商品頁（9/26 兩份紀錄都沒有）。
  2. 首頁「新東西不敢嘗試？聯繫我們，免費給您試用包！」區塊（A 沒看到；留著＝B 多一個 A 沒有的優惠）。
  3. 商品頁「科學證實口腔微血管吸收更快速[1]」句（A 紀錄寫「無公開檢驗報告」；保留會讓證據量測失準）。
- 收錄頁：首頁、關於我們、退換貨政策、四個賣法商品頁（體驗包／超能特惠組／終極組合包／典藏組）、聯名 T-shirt 頁。
- 接法：`scripts/drill/worker.py` 與 `serve.py` 把 `app.intake.ai.fetch_url`、`app.intake.product_prefill.fetch_url` 換成讀副本
  （`https://beastprime.com.tw/<path>` → `site/<path>.html`；其他網址回讀不到）。persona 看到、存進系統的都是真網址；三次演練讀同一份。

## 2. 品牌事實補充

寫在 `../drill-6/brand-facts.md` 的 「Onboarding supplement」 節（A、B、評審同一份；A 的 rows／fit 不重跑）。

## 3. 阿虎劇本（persona 規則不變：只看畫面、只點畫面、事實表以外不知道）

他手上多了：官網網址、四張照片（`.harness/scratch/drill8/photos/`：lifestyle、trial、3box、5box）。沒有 logo 檔、沒有影片。

**P1（時鐘 10/03）**
1. 註冊 → 品牌建檔 7 步。步 1 填品牌名、網址三個（首頁、關於我們、退換貨政策；他是老闆，知道自己網站有哪幾頁）、
   lifestyle 當品牌形象照、地區台灣、法規照事實表、「沒投過」。步 2 等 AI 讀完。步 3–5 對照事實表：AI 提的對就按下一步、
   錯就改、事實表沒寫的不自己編。步 6 接 Meta 替身權杖、成效目標＝購買。步 7 看檢查表、照畫面去下一站。
2. 商品建檔 Beast Gummy 5 步：商品頁網址＝超能特惠組頁；照片 trial／3box／5box；顧客群照 AI 提案對照事實表；
   證據照事實表（沒有就沒有）；賣法三個：隨身體驗包、超能特惠組、終極組合包（售價、原價、成本照事實表）。
3. 組合：典藏組＝Beast Gummy 12 盒＋聯名 T-shirt（T-shirt 先建成第二個商品；事實表沒給 T-shirt 成本，畫面問就答不知道）。
4. 建活動：選賣法**超能特惠組**（drill 8 三期都賣它，可直接對照）；期間、預算照事實表；其餘照畫面預設，到「到平台完成」清單 → ⏸。

**P2、P3**：回系統讀成效、判讀、結案、排下一期；賣法照系統建議，沒有建議就沿用。每期一個活動、日預算 NT$1,500。

## 4. 量測

新增（每條都從 DB／匯出檔算，不靠 persona 回報）：

| # | 量什麼 | 怎麼算 | 及格 |
|---|---|---|---|
| 1 | 優惠在、而且是真的 | 每期 `export_plan` 的 `offer_key`；真集合＝賣法原價 > 售價（discount／bundle）＋該賣法名稱有免運（free_shipping）＋退貨政策不是優惠 | P1 起每期 ≥1 則帶真優惠；假優惠 0 則 |
| 2 | 只有照片就沒有影片格 | `brand.media_capability`＝photo；三期 `ads_ad` format＝video 的數量 | 0 |
| 3 | 痛點來自顧客群 | 每則 `ads_ad.pain` ∈ 活動 `customer_group_ids` 那些群的 pain | 100% |
| 4 | 沒有繞路 | persona 紀錄：為了完成而打開「進階」／改系統預設的次數 | 0 |
| 5 | 預填不幻想 | 預填提案（`intake_draft.prefill_json`、`intake_product_prefill`）每條對回副本文字；副本沒有的＝幻想 | 0 |

沿用 drill 8 的三條：座標沿用並在 rationale 點名、不同受眾 scene 不同、行事曆進 hook。外加建檔各站 persona 分數與原句。

預期會看到的缺口（先寫下，跑完核對）：免運只寫在三個賣法名稱上，官網沒有全店門檻；`POLICY_TYPES` 沒有「指定商品免運」，
系統可能表達不了 → 量測 1 的 free_shipping 只能靠自訂政策。

## 5. 時間

操作者準備約 30 分（副本清理、讀取替換、補充節）。阿虎：drill 8 三期約 1 小時 53 分，這次 P1 多建檔約 40–60 分，估 2.5–3 小時；
評審每次 2–3.5 分、模擬秒級、根因對回程式約 40 分。
