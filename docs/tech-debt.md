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

## 二、`app/llm` 與 `app/brand_intelligence` 互相依賴

兩個方向的 import 同時存在，形成套件層級的環：

- `app/llm/context_compiler.py`、`app/llm/methodology.py` → `app.brand_intelligence.repository`
- `app/brand_intelligence/report.py`、`customer_voice.py`、`product_ai.py` → `app.llm`

`app/tests/test_architecture_boundaries.py` **不檢查 import 環**（它只檢查分支專屬層、
ads→orders、跨層原生 SQL、dashboard 寫入四件事）。這個環不會被任何測試擋下來。

新增這兩個模組之間的依賴前，先確認是否能改走既有邊，不新增第三條。
要解這個環，方向是把 `brand_intelligence` 那三個檔對 `app.llm` 的呼叫上移到路由層。

## 三、只有台灣市場有內容

`brand.market_region` 收 ISO 3166-1 alpha-2，但方法論檔目前只有 `TW` 有對應內容。
待建置範圍與細節記在 `app/methodology/README.md` 的「待建置」一節，不在此處重複。
