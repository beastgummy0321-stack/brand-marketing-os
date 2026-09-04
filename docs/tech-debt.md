# 技術債登記（動到這些地方之前先讀）

最後盤點：2026-08-29（外殼切片後重盤）。新增條目時附上盤點日期與當下數字。

**下列債全部已上機器閘門**（`app/tests/test_architecture_boundaries.py`）：現況凍成清單，
新增的當場擋下。本文件是給人讀的說明，**判準本身活在那支測試裡**——文件與清單不一致時以測試為準。

| 閘門 | 凍住什麼 | 常數 |
|---|---|---|
| `FileLineCapTest` | 超標檔只准變小，不准有新的超標檔 | `KNOWN_OVERSIZED_FILES` |
| `LayerDirectionTest` | 只准依賴排在自己前面的層 | `LAYER_ORDER`／`KNOWN_LAYER_VIOLATIONS` |
| `ImportCycleScanTest` | 不得新增**套件之間**的 import 環 | `KNOWN_IMPORT_CYCLES` |
| `FileImportCycleScanTest` | 不得有**檔案之間**的 import 環（含同一套件內部） | 無欠帳清單——2026-09-04 量到違規數 0，沒有債要凍 |
| `CoordinateDimensionSyncTest` | 三份七維鍵名都要等於憲法規則 5，且同名宣告只准一份 | `CONSTITUTION_COORDINATE_KEYS`（抄自 `CONSTITUTION.md` 規則 5） |
| 前端 `feature-internals-are-private` 等三條 | 功能資料夾之間只准走 `index.ts`；`layout` 是共用櫃；只有 `App.tsx` 認得全部功能、且只有 `main.tsx` 准 import 它 | `frontend/.dependency-cruiser.cjs`（ADR 0060）；`npm run depcruise`，CI 每次 push 跑 |
| `TestRatioTest` | 測試**絕對行數**只准往下（ADR 0041） | `TEST_LINES_CEILING`。2026-08-30 從比值改成絕對行數：比值版在同一天被刪碼逼著調高兩次（0.858→0.862→0.865），因為刪 production 會讓分母變小、比值被動漲——等於懲罰刪死碼，而唯一能變綠的動作是調鬆閘門自己。改成絕對行數後，刪碼不會紅、加測試才會紅。**數字不寫在這裡**——它每張真的需要測試的票都會動一次，抄一份到文件就是保證過期（2026-09-03 查證：本欄原本寫 14,305，實際已經是 17,867）。當下值一律看那一行。**比值只是印出來的讀數，不是目標**：ADR 0041 明文「沒有任何文件再訂那個數字」，`docs/workflow-diet.md` 已刪除 |
| `ModuleSizeRatchetTest` | 每個套件的行數凍在現況，調高要改明表 | `KNOWN_MODULE_SIZES` |

後兩道是票 shell-06 補的。**誠實的天花板**：它們抓不到真正的病因——為一個還沒有人跑過的
系統寫 21,595 行猜出來的門檻。「先用手做，痛過兩次再寫成程式」才是對的規則，而它不可機器
檢查。這兩道買到的是早 10 倍的警報（廣告模組會在約 2,000 行撞上 `ModuleSizeRatchetTest`，
不是 21,595 行），不是解藥。

## 〇、外殼切片（2026-08-29）留下的兩筆：沒有閘門，靠這份清單記得

切掉 `app/ads/` 之後，下面兩處失去了呼叫端但沒有一起刪——刪它們超出票 2 的範圍，
留給使用者決定。**沒有機器閘門守這兩筆**，所以寫在這裡。

原本的第三筆（規則卡）2026-08-29 已清掉：`budget_structure`／`sample_size`／
`ad_creative_fatigue`／`pacing`／`health_lights`／`autonomy` 六張卡連同前端投放自動度
區塊一起刪除，設定頁不再顯示調了不影響任何東西的門檻。

**2026-09-03 查證：這兩筆都已經不存在了，這一節結案。** 本節從 2026-08-29 起就沒有人回來看過，
而它正是「沒有機器閘門、靠這份清單記得」的那種欠帳——所以它腐爛得最快，這一節自己就是證據。

| 是什麼 | 當時的現況 | 後來怎麼了 |
|---|---|---|
| `cycle_shopee_code` 資料表與 `app/orders/channel.py` 的 `set_shopee_code`／`get_shopee_code` | 零呼叫端；欄位 `campaign_cycle_id` 指向已刪除的概念 | **已刪**：表在 `supabase/migrations/20260829000005_orders_channel_revenue.sql:69` 被 `DROP TABLE`（票 12／ADR 0035，連同 `shopee_report_row`／`pharmacy_batch`），程式那兩支也沒了。全庫現在只剩 `app/orders/repository.py:467` 一行說明它為什麼消失，以及 `app/tests/test_orders_core_brand_cleanup.py:137` 一支確認它真的不在的測試 |
| `app/dashboard/campaign_calendar.py` 的 `current_campaign_stage()` | 零呼叫端（原本只有駕駛艙在用） | **整支檔案已刪**：`grep -rn "current_campaign_stage" app/` 零命中 |

另有一道空轉的閘門：`ImportBoundaryScanTest` 的 `BRANCH_PACKAGES` 現在是空的（唯一的分支
專屬層就是廣告）。掃描器留著等下一個分支層，或直接刪掉——兩種都行，但別假裝它在守東西。

## 〇之二、`card_test.py` 不受每月 AI 花費上限管（2026-08-30 使用者裁決：不補）

每月上限的算法現在只有一份——`app/llm/gateway.py` 的 `check_spend_cap()`，
`run_task()` 與設定頁「測試連線」都問它。**唯一還繞過去的是
`python -m app.intake.card_test`**：它直接呼叫 provider，沒有登入者、要自己挑組織，
HTTP 打不到。使用者 2026-08-30 裁決不補——那是開發者自己在命令列上跑的診斷工具，
跑的人本來就知道自己在花錢。**新增第三個會花錢的路徑時請先問 `check_spend_cap()`**，
不要再自己抄一份算法。

## 一、超過 800 行的檔案：加新功能前先拆

`CLAUDE.md` 規則：單檔超過 800 行即為待拆，**不得再往裡面加新功能；要加就先拆**。
下列檔案已超標。動到哪一個就先拆哪一個，不為了數字單獨排一輪重構。

| 檔案 | 行數 | 倍數 | 先拆什麼 |
|---|---|---|---|
| `app/brand_intelligence/repository.py` | **1387**（凍結值仍是 1667） | 1.73× | 依表分檔（brand／product／rule／claim） |

2026-09-03 查證：這個檔已經從 1667 縮到 **1387**，本表原本寫的 1667 是凍結值不是現況。
`KNOWN_OVERSIZED_FILES` 只鎖「不得超過凍結值」，縮小之後沒有人回頭調低數字，這是刻意的
（見 `FileLineCapTest` 上方的 `ponytail:` 註解：每次縮都要改常數是白工）。所以**這一欄的
數字永遠只能當歷史讀，現況一律用 `wc -l` 量**。全庫現在仍只有這一個超標檔。

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

> 2026-09-04 加了 `FileImportCycleScanTest`：同一件事降到檔案層。套件層的圖是收合出來的，
> 所以 `app/x/a.py ⇄ app/x/b.py` 這種同套件內部的環在套件層必然消失——實測過（`app/core`
> 內兩個檔互 import：套件層兩支全綠，檔案層紅）。同一輪順手修掉一個盲點：`from app import
> storage` 這種寫法原本被判成「不是層」而整條邊消失，三條 `app.intake → app.storage` 的依賴
> 在依賴方向與環兩道掃描裡都是隱形的；現在看得到了（以 `from app import schedule` 寫在
> `app/core/` 裡實測：舊碼全綠，新碼紅）。

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
屬跨模組重構，開工前先提計畫等批准（route C 四類之一：模組邊界。規則由 skeleton-slice-pencil
plugin 的 SessionStart hook 每次注入；`~/.claude/workflow.md` 這個路徑 2026-09-03 查證已不存在）。

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

## 四、全套平行測試會隨機紅：測試 schema 的 queue 隔壁房沒被砍（2026-08-29 已修）

**已修**（`app/tests/conftest.py`，本節保留成因，因為坑本身還在：`__queue` 這個後綴寫死在
三個地方，改一個要改三個）。

### 症狀（修之前）

`uv run pytest app/tests -q -n auto --dist loadfile` **每跑一次紅在不同的模組**，錯誤永遠是
同一句：

```
psycopg.errors.DuplicateObject: type "procrastinate_job_status" already exists
```

被打到的模組隨機（實測四次分別是 `test_methodology.py`／`test_capacity_check.py`（2026-09-04 已隨
死碼 `app/tools/capacity_check.py` 一起刪除，此處保留只為忠實記錄當時實測）／
`test_main_dotenv.py`／`test_inbox_api.py`＋`test_brand_delete_routes.py`），**單獨跑一定綠**，
再跑一次整套也可能整套綠。已驗證不是哪一張票帶進來的：在停在 `4777392` 的乾淨 worktree
上跑同一條指令，一樣紅。

### 成因（2026-08-29 實測證實，不是推測）

`conftest.py` 每個測試模組建自己的 schema `t_<module>_<pid>`，但 ADR 0038 讓 procrastinate
的四張表住在**隔壁的** `t_<module>_<pid>__queue`（migration
`20260829000001_background_baseline.sql` 的 prelude 由 `current_schema() || '__queue'` 導出）。
建房和退房都只砍了模組 schema，**隔壁房從來沒有人砍**。

`_schema_name()` 用 `os.getpid()` 當後綴，而 pid 作業系統會回收再發。下一輪某個 worker 拿到
同一個 pid、`--dist loadfile` 又剛好把同一個測試檔分給它 → 房名一模一樣 → prelude 那句
`CREATE SCHEMA IF NOT EXISTS` 看到房還在就跳過 → 接著的 `CREATE TYPE procrastinate_job_status`
撞上上一輪留下的同名 type。

當時資料庫實測：**499 個殘留的 `__queue` schema，各裝一份 `procrastinate_job_status`；
只有 150 個不重複 pid，最兇的一個 pid 被 15 個不同模組用過**。主房殘留 0 個——只有隔壁房漏。

決定性重現：把 `conftest.py` 的建房 SQL 對同一個房名連跑兩次，第二次必噴上面那句，字句一致。

### 修法

建房與退房的 SQL 各多一句 `DROP SCHEMA IF EXISTS "<schema>__queue" CASCADE`。
修完同一支重現腳本兩次都過、不留東西；清掉 499 個殘留後全套閘門**連跑四次結果一模一樣**
（721 passed，0 個 DuplicateObject），隨機紅消失。

### 留下的小尾巴（不追）

`-n auto` 下每輪仍會留 1 間 `__queue`，只發生在該輪失敗的那個模組（單跑不留），推測是
xdist 在 session 結束時提前收掉 worker、module-scope teardown 沒跑完。**數量不會長**
（連三輪都是 1），因為建房時會先砍同名的隔壁房——這反而是修法在生效的證據。

沒有為這條補新測試：它保護的是測試腳手架，不是金流／租戶隔離／API 契約／資料正確性，
照 `CLAUDE.md` 的規則不寫。守門員就是閘門本身現在會穩定重現。

## 五、路由處理器不得是「`async def` 但從不 `await`」（2026-08-29 全站修正，無機器閘門）

**已修**：全站 75 個路由處理器拿掉 `async`。留下的規則是給未來的人看的：

> 路由處理器如果體內從不 `await`，就宣告成 `def`，不要宣告成 `async def`。

FastAPI 的規則：`def` 會被丟進執行緒池，`async def` 跑在 uvicorn 自己的 event loop 上。一個
從不 await 的 `async def` 拿不到任何非同步的好處，卻把自己的阻塞時間變成**全站停頓**——
2026-08-29 實測，排程端點那 170～300 秒的 LLM 呼叫期間，整個網站對**所有組織**都沒有反應，
不是只有按下按鈕的那個人在等。多租戶下這代表 A 組織的一次排程會凍住 B 組織的每一個請求。

搬進執行緒池不影響連線綁定：`app/core/db.py:160` 的 `_current` 是 ContextVar，Starlette 的
執行緒池會複製 context。真正被 await 的東西（lifespan 的 `start_worker`／`stop_worker`、
`@app.exception_handler` 註冊的處理器）沒有路由裝飾器，本來就不在這條規則範圍內。

**為什麼這條沒有機器閘門**——寫了，然後刪掉了，兩個獨立的理由：

1. `TestRatioTest` 直接擋下來。天花板 0.858，動工前已經是 0.857，只剩約 40 行測試碼的空間；
   最精簡的版本仍然超標。那個閘門的職責就是拒絕「產品碼加一行、測試碼加五十行」，它做對了，
   而它明文只准往下調，不准為了讓自己過而放寬。
2. 憲章：「測試必須說出它保護什麼：金流、租戶隔離、API 契約、資料正確性。其餘一律不寫。」
   全站反應速度可以硬拗成租戶隔離（A 組織凍住 B 組織），但那是硬拗。

所以這條活在這裡而不是活在測試裡。要抓回歸，一行 grep 就夠：

    git grep -n "^async def " -- app/ | # 再確認每個都真的有 await

## 六、行數棘輪撞上「不得放寬容忍清單」（2026-09-02 使用者裁決）

兩條規則直接相撞，記在這裡，下一個撞到的人不必重跑一次那段對話。

- 全域 `CLAUDE.md`：「Never widen a tolerance list（known-drift、known-oversized、
  allowed-failures、skip markers、a frozen baseline）to turn a gate red→green.」
- `test_architecture_boundaries.py` 的 `KNOWN_MODULE_SIZES` 自己的說明：
  「**允許調高，但必須改這張表**——重點不是禁止成長，是讓成長出現在 diff 裡有人看得到。」

`KNOWN_MODULE_SIZES` 是一份 frozen baseline，所以第一條讀起來禁止調高；第二條說調高就是
它的設計用法。2026-09-02 R3b 這張票撞上了：`app/core` 當時**正好卡在凍結值 1554**，
意思是那個模組任何一行新增都是紅的，而該票需要 +5 行（三處 Vault 直接存取改走組織門）。

**裁決（使用者，2026-09-02）：調高，寫理由，調到量到的數字、不留餘裕。**

理由三句：這道閘門的目的是「讓成長被看見」，不是「禁止成長」——它擋的是 `app/ads` 那種
長到 21,595 行沒人發現的過程；把數字調到剛好等於實測值，下一行新增仍然會紅，棘輪還在；
留餘裕才是真的廢掉它。全域那條規則要擋的是「為了把紅燈弄綠而偷偷放寬」，這一次的差別在於
**理由寫在調高的那一行旁邊、也寫在這裡**，而且金額是量出來的不是喬出來的。

判斷下一次是不是同一種情況，一句話：**新增的行數是那張票的交付物本身**（票要求的功能就是
需要這些行），還是**為了繞過閘門而塞進來的**？前者調高並寫理由；後者不准。

## 七、模組欠帳（2026-09-04 從看板搬來；沒有目標認領的 issue 住這裡，被目標認領時搬進 `docs/issues/<目標>/`）

全文出處 `BOARD.md` @ `6574191`。每條都已查證**今天咬不到人**，所以是欠帳不是漏洞；動到那個模組的
route C 票先讀這一節。

- **`campaign_period` 的 FK 沒用複合鍵（T6a 審查量出）**：`channel_entity_map`／`period_node_membership`／
  `channel_credential` 用 `FOREIGN KEY (channel_id, org_id) REFERENCES ad_channel(id, org_id)` 在資料庫層擋跨組織；
  但指向 `campaign_period` 的八條 FK（`decision`／`interrupt`／`llm_task`／`feedback`／`period_node_membership`／
  `campaign_period_budget_version`／`channel_revenue`＋自己的 `source_period_id`）與六條自參照全是單欄。
  升成 `(id, org_id)` 唯一鍵＋八條複合 FK 是一張獨立 route C 票，不是順手做的事。
- **`_row_hash()` 對 int／float 不穩定（T7 審查活體證出）**：`app/orders/channel.py` 把 `revenue`／`quantity`
  直接餵 `json.dumps`，`hash(5000, 3)` ≠ `hash(5000.0, 3.0)`。今天唯一呼叫端 `app/orders/routes_api.py:161,164`
  先過 `parse_number()`（`app/shared/web.py:291-298`，永遠回 `float | None`）所以壓成同一個雜湊。
  防線是隱性的：第二個呼叫端（補登腳本、後台工具）一出現，去重靜靜失效，營收翻倍那顆 bug 回來。
  根治兩行（`float()` 統一），但是金流路徑，走 route C。
- **租戶防線不對稱（T3c 審查發現）**：`ad_set_ids_by_exact_name`／`ad_ids_by_exact_name`
  （`app/meta/repository.py`）只拿 `org_id` 取權杖，`campaign_id`／`adset_id` 原封不動送 Meta、不驗屬於哪個組織；
  姊妹函式 `campaign_ids_by_exact_name` 有驗。擋住跨組織的是呼叫端的形狀，審查逐條追過沒有任何請求構造得出
  跨組織輸入。補法比「一次查詢」貴：這個資料庫沒有一張表存「campaign_id 屬於哪個組織」，要嘛多打一次
  Meta API（先查官方文件核對回傳形狀），要嘛改呼叫鏈把 `binding.py` 驗過的結果往下傳（改簽章）。
  是要不要付代價的設計題，留給使用者。`docs/contracts/meta.md` 已逐字記下這個不對稱。
- **404 沒有機器可讀的代碼**（07-3 剩下的那半，2026-09-04 判不做）：`NotFoundKind`（`app/shared/web.py:188-192`）
  只帶中文名詞；`/api/health` 回「找不到頁面」、找不到品牌回「找不到這個品牌」，靠字串分辨。加 `code` 成本低、
  價值零——今天沒有畫面分辨這兩件事。真的有畫面需要分岔時再開票。
- **五個記憶體背景工作**（品牌智庫抽原話、產品調研、顧問報告、建檔精靈初掃與出題）還是「一張 dict＋一條執行緒」，
  重開後端就消失。排程那三支已搬上佇列（ADR 0042）；這五支沒量到痛過。真的痛了照 ADR 0042 同一個做法搬。
- **需批准（schema）四個沒人用的欄位**：`order_record.attribution_override`、`interrupt.kind`／`visible_from`／
  `campaign_cycle_id`；欄位還在所以 `enqueue()` 那三個沒有生產呼叫端的參數也還留著。`decision` 表 2026-09-01
  改判不刪（要當「建議落表」，形狀剛好）。
- **`meta-format-specs.md:52-53` 的 `script`／`hook_pool` 沒有字數預算**（實跑佔 18.1%／7.3%）。2026-09-01 裁決不收：
  ADR 0047 已拿掉約六成輸出，實跑從沒真的被截斷過；T1b 閘門只擋圖片欄位。真的被截斷一次再回頭收。
- **`assets` bucket 沒設 `file_size_limit`**（`supabase/migrations/20260830000002_core_storage_assets_bucket.sql`）：
  上傳端已擋兩道 50MB（`app/brand_web/routes_library.py:57`／`:79`／`:273`），這是第二道防線不是沒有防線。
  補一行要開新 migration 檔，照憲法第 9 條先提計畫等批准，不算順手。
- **`決策 NNNN` 那 84 處已緩解**：`CONTEXT.md` 有一節說明。剩 `report.py:1`／`repository.py:1244` 兩處寫
  「決策 0017」，由那節涵蓋，不動。
