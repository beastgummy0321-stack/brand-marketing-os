# 技術債登記（動到這些地方之前先讀）

判準活在 `app/tests/test_architecture_boundaries.py`；本檔只說每道閘門凍住什麼，數字一律看那支測試的當下值
（抄一份到文件就是保證過期）。已清掉的債不留在這裡，歷史查 git log。

| 閘門 | 凍住什麼 | 常數 |
|---|---|---|
| `FileLineCapTest` | 超標檔只准變小，不准有新的超標檔（目前僅 `app/brand_intelligence/repository.py`） | `KNOWN_OVERSIZED_FILES` |
| `LayerDirectionTest` | 只准依賴排在自己前面的層 | `LAYER_ORDER`／`KNOWN_LAYER_VIOLATIONS`（空） |
| `ImportCycleScanTest`／`FileImportCycleScanTest` | 不得新增套件之間或檔案之間的 import 環 | `KNOWN_IMPORT_CYCLES`（空） |
| `CoordinateDimensionSyncTest` | 三份七維鍵名都要等於憲法規則 5 | `CONSTITUTION_COORDINATE_KEYS` |
| `TestRatioTest` | 測試**絕對行數**只准往下（ADR 0041） | `TEST_LINES_CEILING` |
| `ModuleSizeRatchetTest` | 每個套件的行數凍在現況，調高要改明表 | `KNOWN_MODULE_SIZES` |
| `ContractPageRatchetTest` | 沒有契約頁的模組清單只准變短 | `MODULES_WITHOUT_CONTRACT` |
| 前端 depcruise 三條 | 功能資料夾之間只走 `index.ts`；只有 `App.tsx` 認得全部功能 | `frontend/.dependency-cruiser.cjs`（ADR 0060） |

## 沒有閘門、靠這裡記得的兩條規則

- **路由處理器體內從不 `await` 就宣告成 `def`，不是 `async def`**（2026-08-29 全站修過 75 支）。不 await 的
  `async def` 會把自己的阻塞時間變成全站停頓——多租戶下 A 組織的一次排程會凍住 B 組織的每一個請求。
  抓回歸：`git grep -n "^async def " -- app/`，逐一確認真的有 await。
- **新增第三個會花錢的路徑時先問 `app/llm/gateway.py` 的 `check_spend_cap()`**，不要再抄一份算法。
  目前唯一繞過它的是 `python -m app.intake.card_test`（開發者自己在命令列跑的診斷工具，2026-08-30 裁決不補）。

## 棘輪撞上「不得放寬容忍清單」時怎麼判（2026-09-02 使用者裁決）

`KNOWN_MODULE_SIZES` 這類 frozen baseline 的目的是「讓成長被看見」，不是「禁止成長」。一句話判斷：
**新增的行數是那張票的交付物本身**（票要求的功能就是需要這些行）→ 調高到量到的數字、不留餘裕、理由寫在調高的那一行旁邊；
**為了繞過閘門而塞進來的** → 不准。開票時先量餘裕（`_line_totals()`／`_module_sizes()` 印當下值），要加測試的票在票裡寫明授權調高。

## 模組欠帳（沒有目標認領的 issue 住這裡；被認領時搬進 `docs/issues/<目標>/`）

每條都已查證**今天咬不到人**，所以是欠帳不是漏洞；動到那個模組的 route C 票先讀這一節。

- **404 沒有機器可讀的代碼**：`NotFoundKind`（`app/shared/web.py:188-192`）只帶中文名詞，靠字串分辨。
  今天沒有畫面需要分辨；真的有畫面需要分岔時再開票（2026-09-04 判不做）。
- **`meta-format-specs.md:52-53` 的 `script`／`hook_pool` 沒有字數預算**（實跑佔 18.1%／7.3%）。實跑從沒真的被截斷過；
  真的被截斷一次再回頭收（2026-09-01 裁決）。
- **程式註解裡的「決策 NNNN」不是 ADR**，來源文件已不可考；規則本身都寫在同一句裡，出處死了而已。
  詳 `CONTEXT.md` 那一節，不要拿去查 `docs/adr/`。
- **方法論檔只有 `TW` 有內容**（`brand.market_region` 收 ISO 3166-1 alpha-2）；待建置範圍在 `app/methodology/README.md`。
