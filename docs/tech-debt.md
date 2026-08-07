# 技術債登記（動到這些地方之前先讀）

最後盤點：2026-08-07。新增條目時附上盤點日期與當下數字。

## 一、超過 800 行的檔案：加新功能前先拆

`CLAUDE.md` 規則：單檔超過 800 行即為待拆，**不得再往裡面加新功能；要加就先拆**。
下列檔案已超標。動到哪一個就先拆哪一個，不為了數字單獨排一輪重構。

| 檔案 | 行數 | 倍數 | 先拆什麼 |
|---|---|---|---|
| `app/brand_intelligence/routes.py` | 1854 | 2.3× | brand fact 與 product 兩組 CRUD 路由各自獨立成檔 |
| `app/brand_intelligence/repository.py` | 1591 | 2.0× | 依表分檔（brand／product／rule／claim） |
| `app/tests/test_ads_reading.py` | 1157 | 1.4× | 測試檔，優先度最低 |
| `app/ads/reading.py` | 1039 | 1.3× | 判讀規則與資料取數分離 |
| `app/intake/routes.py` | 951 | 1.2× | 依精靈五步分檔 |
| `app/tests/test_ads_creative.py` | 870 | 1.1× | 測試檔，優先度最低 |
| `app/ads/repository.py` | 816 | 1.0× | 剛超標，先觀察 |

**已知違例**：2026-08-07 的票 C 在 `brand_intelligence/routes.py` 加了約 70 行沒有先拆。
當時的取捨是「先讓開關有寫入路徑」優先於先拆檔，由主控判斷放行，記在此處不隱藏。

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

**層級定義的權威文件已遺失**：`docs/architecture-rules.md`、`docs/rule-checks.md`、
`docs/design/19-constitution-audit.md` 都不在 repo 裡，程式與測試裡的「A1 三層地界」
引用全部指向不存在的檔案。要正式定依賴方向，先把層級定義重建成一份新文件。

## 三、只有台灣市場有內容

`brand.market_region` 收 ISO 3166-1 alpha-2，但方法論檔目前只有 `TW` 有對應內容。
待建置範圍與細節記在 `app/methodology/README.md` 的「待建置」一節，不在此處重複。
