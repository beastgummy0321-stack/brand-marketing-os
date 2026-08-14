# 技術債登記（動到這些地方之前先讀）

最後盤點：2026-08-07。新增條目時附上盤點日期與當下數字。

**這三筆債全部已上機器閘門**（`app/tests/test_architecture_boundaries.py`）：現況凍成清單，
新增的當場擋下。本文件是給人讀的說明，**判準本身活在那支測試裡**——文件與清單不一致時以測試為準。

| 閘門 | 凍住什麼 | 常數 |
|---|---|---|
| `FileLineCapTest` | 超標檔只准變小，不准有新的超標檔 | `KNOWN_OVERSIZED_FILES` |
| `LayerDirectionTest` | 只准依賴排在自己前面的層 | `LAYER_ORDER`／`KNOWN_LAYER_VIOLATIONS` |
| `ImportCycleScanTest` | 不得新增 import 環 | `KNOWN_IMPORT_CYCLES` |

## 一、超過 800 行的檔案：加新功能前先拆

`CLAUDE.md` 規則：單檔超過 800 行即為待拆，**不得再往裡面加新功能；要加就先拆**。
下列檔案已超標。動到哪一個就先拆哪一個，不為了數字單獨排一輪重構。

| 檔案 | 行數 | 倍數 | 先拆什麼 |
|---|---|---|---|
| `app/brand_web/routes.py` | 1854 | 2.3× | brand fact 與 product 兩組 CRUD 路由各自獨立成檔 |
| `app/brand_intelligence/repository.py` | 1667 | 2.08× | 依表分檔（brand／product／rule／claim） |
| `app/tests/test_ads_reading.py` | 1157 | 1.4× | 測試檔，優先度最低 |
| `app/ads/reading.py` | 1039 | 1.3× | 判讀規則與資料取數分離 |
| `app/intake/routes.py` | 951 | 1.2× | 依精靈五步分檔 |
| `app/tests/test_ads_creative.py` | 870 | 1.1× | 測試檔，優先度最低 |
| `app/ads/repository.py` | 856 | 1.07× | 剛超標，先觀察 |

**已知違例**：2026-08-07 票 C 在 `brand_intelligence/routes.py` 加了約 70 行沒先拆（主控放行）；
2026-08-09～10 的三張票在 `app/ads/repository.py` 共加了約 42 行（cascade 表登記、排期策略落地），
每次都把計算本體另開新檔，只留「唯一登記點」那幾行在超標檔裡。
放行理由逐票寫在該 commit 的訊息裡，本檔不複述；當前凍結值一律以
`KNOWN_OVERSIZED_FILES` 為準。

## 二、四個套件糾成一個 import 環（五組相鄰對）

2026-08-07 補了機器掃描（`test_architecture_boundaries.py` 的 `ImportCycleScanTest`），
現況凍在 `KNOWN_IMPORT_CYCLES`：**新增的環當場擋下，既有這五組是欠帳**。
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
