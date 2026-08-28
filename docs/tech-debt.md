# 技術債登記（動到這些地方之前先讀）

最後盤點：2026-08-29（外殼切片後重盤）。新增條目時附上盤點日期與當下數字。

**下列債全部已上機器閘門**（`app/tests/test_architecture_boundaries.py`）：現況凍成清單，
新增的當場擋下。本文件是給人讀的說明，**判準本身活在那支測試裡**——文件與清單不一致時以測試為準。

| 閘門 | 凍住什麼 | 常數 |
|---|---|---|
| `FileLineCapTest` | 超標檔只准變小，不准有新的超標檔 | `KNOWN_OVERSIZED_FILES` |
| `LayerDirectionTest` | 只准依賴排在自己前面的層 | `LAYER_ORDER`／`KNOWN_LAYER_VIOLATIONS` |
| `ImportCycleScanTest` | 不得新增 import 環 | `KNOWN_IMPORT_CYCLES` |
| `TestRatioTest` | 測試行數／程式行數只准往下 | `TEST_RATIO_CEILING`（0.858） |
| `ModuleSizeRatchetTest` | 每個套件的行數凍在現況，調高要改明表 | `KNOWN_MODULE_SIZES` |

後兩道是票 shell-06 補的。**誠實的天花板**：它們抓不到真正的病因——為一個還沒有人跑過的
系統寫 21,595 行猜出來的門檻。「先用手做，痛過兩次再寫成程式」才是對的規則，而它不可機器
檢查。這兩道買到的是早 10 倍的警報（廣告模組會在約 2,000 行撞上 `ModuleSizeRatchetTest`，
不是 21,595 行），不是解藥。

## 〇、外殼切片（2026-08-29）留下的三筆：沒有閘門，靠這份清單記得

切掉 `app/ads/` 之後，下面三處失去了呼叫端但沒有一起刪——刪它們超出票 2 的範圍，
留給使用者決定。**沒有機器閘門守這三筆**，所以寫在這裡。

| 是什麼 | 現況 | 為什麼沒順手刪 |
|---|---|---|
| `app/core/rule_cards.py` 的 8 張規則卡有 6 張失效（`budget_structure`／`sample_size`／`ad_creative_fatigue`／`pacing`／`health_lights`／`autonomy`） | 設定頁照樣顯示、照樣可以調，但調了不影響任何東西 | 清掉要連動 3 個測試檔＋前端兩個區塊。**這是使用者看得到的謊**，優先處理 |
| `cycle_shopee_code` 資料表與 `app/orders/channel.py` 的 `set_shopee_code`／`get_shopee_code` | 零呼叫端；欄位 `campaign_cycle_id` 指向已刪除的概念 | 它是 orders 模組的表，票 3 的 migration 伸手去刪別的模組的表會違反模組邊界（`CLAUDE.md` #7） |
| `app/dashboard/campaign_calendar.py` 的 `current_campaign_stage()` | 零呼叫端（原本只有駕駛艙在用） | 節日日曆本身活著，這支純函數之後的儀表板可能會用；有自己的單元測試 |

另有一道空轉的閘門：`ImportBoundaryScanTest` 的 `BRANCH_PACKAGES` 現在是空的（唯一的分支
專屬層就是廣告）。掃描器留著等下一個分支層，或直接刪掉——兩種都行，但別假裝它在守東西。

## 一、超過 800 行的檔案：加新功能前先拆

`CLAUDE.md` 規則：單檔超過 800 行即為待拆，**不得再往裡面加新功能；要加就先拆**。
下列檔案已超標。動到哪一個就先拆哪一個，不為了數字單獨排一輪重構。

| 檔案 | 行數 | 倍數 | 先拆什麼 |
|---|---|---|---|
| `app/brand_intelligence/repository.py` | 1667 | 2.08× | 依表分檔（brand／product／rule／claim） |

2026-08-29（外殼切片）：`app/ads/repository.py`（856 行）隨整個 `app/ads/` 刪除，
退出超標清單。全庫現在只剩上面這一個超標檔。

2026-08-21：T4 刪除品牌／產品管理舊頁 handler，`app/brand_web/routes.py` 從 1854 行降到
704 行，退出超標清單（`KNOWN_OVERSIZED_FILES` 同步移除）。

2026-08-22：票 10 拆 `app/ads/reading.py`（1039→779）／`app/tests/test_ads_reading.py`
（1157→767），兩檔退出超標清單。拆出 `reading_baselines.py`（品牌基線）、
`reading_hypotheses.py`（假設結案週邊讀寫）、`reading_verdict.py`（判讀結論周邊小函式，
含原本 D3 沒點名、但為了避開 `PROVIDER`／`orders_repo` 猴子補丁循環依賴而額外抽出的
幾個純函式）＋對應三個測試檔；`_explain`／`_explain_diff`／`_explain_hypotheses`
（LLM 文案，D3 原訂的第二個縫）沒有拆——它們要用到的 `PROVIDER` 被十幾個票 10 清單
外的測試檔直接改 `reading.PROVIDER = FakeProvider(...)`，搬去別檔會讓猴子補丁失效
（改的是 reading 模組的名字，不是實際執行 LLM 呼叫那個模組的全域變數），詳細原因見
`reading_verdict.py` 開頭說明。

**已知違例**：2026-08-07 票 C 在 `brand_intelligence/routes.py` 加了約 70 行沒先拆（主控放行）；
2026-08-09～10 的三張票在 `app/ads/repository.py` 共加了約 42 行（cascade 表登記、排期策略落地），
每次都把計算本體另開新檔，只留「唯一登記點」那幾行在超標檔裡。
放行理由逐票寫在該 commit 的訊息裡，本檔不複述；當前凍結值一律以
`KNOWN_OVERSIZED_FILES` 為準。

## 二、四個套件糾成一個 import 環（五組相鄰對）

2026-08-07 補了機器掃描（`test_architecture_boundaries.py` 的 `ImportCycleScanTest`），
現況凍在 `KNOWN_IMPORT_CYCLES`：**新增的環當場擋下，既有這五組是欠帳**。

> 2026-08-29 盤點：`KNOWN_IMPORT_CYCLES` 與 `KNOWN_LAYER_VIOLATIONS` 現在**都是空集合**，
> 掃描全綠——這五組環在某次重構後已經解掉，只是沒人回來改這一節。以下內容當歷史讀，
> 判準以測試為準（見本檔開頭）。這筆不是外殼切片造成的，切片只是順手發現。
掃描只算 import 期會執行的 import；函式內的延遲 import（例：`app/core/settings.py:108`）
是解環的標準手法，不算硬邊。

    app.brand_intelligence ⇄ app.intake
    app.brand_intelligence ⇄ app.llm
    app.brand_intelligence ⇄ app.shared
    app.intake             ⇄ app.llm      （連帶效應，非獨立成因）
    app.intake             ⇄ app.shared   （同上）

**五組出自同一個成因**：`app/brand_intelligence`（品牌永久層）反過來 import 了上層三個套件。

| 要拆的邊 | 位置 | 解法 |
|---|---|---|
| → `app.shared` | `brand_intelligence/routes.py:41-42` | 路由屬 web 層，整份移出 `brand_intelligence/` |
| → `app.intake` | `brand_intelligence/routes.py:40` | 同上，一起解決 |
| → `app.llm` | `report.py:17`、`customer_voice.py:21`、`product_ai.py:19` | AI 呼叫上移到路由層，這三個檔留純資料函式 |

拆掉這三條邊，五組環一起消失（已用圖驗算：`brand_intelligence` 只剩指向 `app.core`）。
代價：動 `routes.py` 1854 行 ＋ 三個檔的 `PROVIDER` 模組層變數與其 monkeypatch 測試。
屬跨模組重構，開工前先提計畫等批准（`~/.claude/workflow.md` 第三節例外清單）。

2026-08-15 修訂：`background_job.py` 對 `app.shared` 的邊是在 8/7 盤點後才長出來；本票以
`notify(conn, ...)` 連線注入解掉，不搬進 `app/brand_web`，避免 intake 與 brand_web 形成新環。

**層級定義的權威文件已遺失**：`docs/architecture-rules.md`、`docs/rule-checks.md`、
`docs/design/19-constitution-audit.md` 都在 `5eca0db`「乾淨重啟」被清除，程式與測試裡的
「A1 三層地界」引用全部指向不存在的檔案。

2026-08-07 重建成 `test_architecture_boundaries.py` 的 `LAYER_ORDER` 常數，**不重寫成文件**——
文件會腐爛且沒人讀，常數每次跑測試都會執行。順序由現況推導：這是唯一一種讓違規收斂到
「只剩上表那三條」的排法，其餘七個套件零違規。改 `LAYER_ORDER` 的排法讓測試變綠一律禁止。

## 三、只有台灣市場有內容

`brand.market_region` 收 ISO 3166-1 alpha-2，但方法論檔目前只有 `TW` 有對應內容。
待建置範圍與細節記在 `app/methodology/README.md` 的「待建置」一節，不在此處重複。
