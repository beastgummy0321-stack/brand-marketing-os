# 02 第⑨步後半：判讀上畫面 ＋「採用」把它變成下一輪的規則

依據：`spec.md` 的「T6c 規格（2026-09-06 站①裁決）」；票 01 已交件（後端 GET/POST 存在）才開工。
這張票是閉環真正合攏的那一刀：按下「採用」→ 規則卡 → 下次出方案的 prompt 自己吃到。

## What

### 畫面位置：長在「素材座標成效」區塊裡，不另開第三個長區塊

`frontend/src/components/cockpit/CockpitPage.tsx` 的 `CreativePerformanceSection`：
標題列右側加一顆「跑一次判讀」，結果顯示在標題下方、七維分頁與圖表**上方**。
不新增獨立區塊、不把頁面拉更長（前端紅線：資訊多的頁面用分頁／標籤／展開收納，
不得做成一路下滑的長頁；駕駛艙的長頁問題已經掛在 U3）。

新元件放新檔 `frontend/src/components/cockpit/DiagnosisPanel.tsx`
（`CockpitPage.tsx` 已 502 行，不再往裡面塞）。

### 四個狀態，一個都不能少

1. **沒跑過**：一句「還沒判讀過這個月的成效」＋按鈕。
2. **跑的時候**：按鈕轉成停用＋「判讀中」，沿用既有 `llm_task` 輪詢慣例（同 `_display_task_row`
   那套「正在跑就繼續顯示上一次成功的結果」）。
3. **有結果**：最多 5 張卡，每張：一句話結論、依據那行數字、`agreed_by` 有兩個以上時標
   「兩個判讀器都這麼說」、一顆「採用」。卡片上方一行灰字固定寫
   **「這是方向性判讀，不是統計顯著的結論」**（`ab-testing.md:75`）與窗口日期。
   打平線算得出來就寫「賺賠線 1.43x（毛利率 70%）」，算不出來就寫「還沒有毛利率，這個月不判賺賠」。
4. **建議是空的**（`suggestions: []`）：兩種原因要說不同的話，用票 01 回應裡的
   `no_tagged_spend` 這個布林分辨（票 01 交件後接上的，見 `diagnosis.brand_diagnosis_response`）：
   - `no_tagged_spend: true` → 「這個月的花費全部沒有座標可對，要先讓系統產的素材真的花到錢」
   - `no_tagged_spend: false` → 「有座標，但這一輪判讀沒有給出建議」
   兩種都不是空白、不是錯誤紅框（票 01 的矛盾檢查段已裁決）。

### 「採用」做什麼

新路由 `POST /api/schedule/brands/{brand_id}/diagnosis/adopt`，body 是那條建議的索引：

```json
{"suggestion_index": 0}
```

後端（`app/schedule/routes.py`）：讀最新一輪那 5 條、取第 N 條、呼叫既有
`bi_repo.create_rule(conn, brand_id, actor=…, rule_type=<那條的 rule_type>, content=<下方格式>,
severity="soft", source_reference_id=None)`。

- `rule_type` 只用既有三個值（`SOFT_REJECT_RULE_TYPES` 的 `angle`／`audience`／`budget_split`）。
- `severity` 一律 `soft`。
- **`source_reference_id` 必須是 `None`**：那一欄的 FK 指向 `source_reference`，塞
  `llm_task.id` 會違反約束（plan review 2026-09-06 實跑 SQL 證明）。來源改寫進 `content`：

```
下一輪把預算往「陌生・知道問題」加碼，這群人保守 ROAS 2.58x／樂觀 3.17x、覆蓋率 75%。
（本條來自 2026-09-06 的成效判讀，方向性判讀，不是統計顯著的結論）
```

- 回應回那列 rule 的 id 與 content，畫面把那張卡標成「已採用」（同一條不重複建立：
  同一輪同一條已經採用過就回既有那列，比照既有 accept 的冪等寫法「先查再寫」）。
- **不重跑方案**：既有 `POST .../reject` 會順手重新排程，這支不會——採用一條判讀不等於
  現在就要重出方案。

### 前端 API 層

`frontend/src/lib/scheduleApi.ts` 加三支（`fetchDiagnosis` / `runDiagnosis` / `adoptSuggestion`），
沿用該檔既有 `getJson` / `apiFetch` 形狀，不新增第二套請求慣例。

## How we know it's done

1. `cd frontend && npx tsc -b` 全綠。
2. `cd frontend && npm run lint` 與 `npm run depcruise` 全綠。
3. `cd frontend && npm run build` 全綠。
4. `uv run ruff check app` ＋ `uv run pyright` 全綠。
5. `uv run pytest app/tests/test_schedule_diagnosis.py -q` 全綠——票 01 那個檔加一支，
   只測「採用寫出來的那列 rule 形狀對」（API 契約／資料正確性）：
   `rule_type` 落在 `SOFT_REJECT_RULE_TYPES`、`severity == "soft"`、
   **`source_reference_id IS NULL`**、`content` 含來源日期那句、同一條採用兩次只有一列。
6. `cd frontend && npm run e2e` 全綠。
7. **真人驗收（重啟過的後端上做）**：
   a. `uv run python -m app.tools.simulate_meta_spend --org org_bughunt --brand brd_bughunt`
   b. 重新啟動後端（閘門看不到「跑的是舊程式」）
   c. 開 http://localhost:8710/app/brands/brd_bughunt ，「素材座標成效」右上按「跑一次判讀」
   d. 出現最多 5 張卡，每張有一句話＋依據數字；上方有「方向性判讀」那句與賺賠線 1.43x
   e. 任一張按「採用」→ 卡片變「已採用」
   f. 去 `/app/brands/brd_bughunt/library` 看到那條新規則（soft）
   g. 回排程頁按「出方案」，`docker exec supabase_db_marketing psql -U postgres -c "select
      rendered_output from llm_task where task_type='schedule_plan' order by started_at desc limit 1"`
      ——**prompt 裡真的出現那條規則的文字**。這一步是整張票存在的理由，前六步全綠但這一步紅，
      就是沒交件。

## Shared files touched

2026-09-06 全 repo 搜尋原始命中。

`CockpitPage`（新增一個子區塊的呼叫者）：
```
app/meta/repository.py:609（註解提到）
app/meta/routes.py:150（註解提到）
frontend/src/App.tsx:8, :130
frontend/src/components/cockpit/CockpitPage.tsx:45
frontend/src/components/inbox/InboxPage.tsx:18（註解引為慣例）
frontend/src/components/layout/Breadcrumb.tsx:12（註解引為慣例）
frontend/src/components/settings/SettingsPage.tsx:20（註解引為慣例）
frontend/src/lib/api.ts:44（註解引為慣例）
```

`create_rule`（新增一個呼叫者，且這次刻意傳 `source_reference_id=None`）：
```
app/brand_intelligence/repository.py:882
app/brand_web/routes_library_write.py:175
app/intake/repository.py:449
app/schedule/routes.py:11, :281, :315
app/tests/test_brand_delete.py:31
app/tests/test_brand_menu_categories.py:59
app/tests/test_isolation.py:30
app/tests/test_library_api.py:100
app/tests/test_llm_gateway.py:382, :395, :435, :447, :451
```

`SOFT_REJECT_RULE_TYPES`：
```
app/schedule/routes.py:270, :293
docs/issues/ad-loop/spec.md:103
```

`_run_reject` / `POST .../reject`（採用**不走**這條路，列出來是為了讓實作者知道差別在哪）：
```
app/schedule/routes.py:302, :447, :451
app/tests/test_architecture_boundaries.py:1891
app/tests/test_schedule.py:725, :854, :867
frontend/src/lib/scheduleApi.ts:406
```

檔案大小現況：`CockpitPage.tsx` 502 行、`scheduleApi.ts` 472 行、`app/schedule/routes.py` 520 行
（單檔上限 800）。新元件進新檔。

## Contradiction check

**done-check 5（`source_reference_id IS NULL`）與 done-check 7f（規則要在品牌智庫看得到、
且看得出來源）會互相矛盾。** 顯示矛盾的輸入：使用者採用一條建議之後，去品牌智庫想知道
「這條規則哪來的」——欄位是空的，資料庫層面追不回那一輪判讀。

處置：來源只存在 `content` 的文字裡（決定 8），這是這一版接受的上限。追溯性靠人看得懂的那句話，
不靠外鍵。真的需要機器可查的來源時，那是「給 `rule` 開一個新的來源型別」的另一張票
（會動 schema，走路線 C），不在這一版。

第二組：done-check 6（e2e 煙霧測試）與「不重跑方案」。煙霧測試不碰診斷，不會互相踩到；
但實作者若把採用接到既有 `_run_reject` 上（那支會重新排程），煙霧測試仍然綠、7g 也仍然綠，
**錯誤不會被任何一條 done-check 抓到**。所以：採用路由自己一支，不得重用 `_run_reject`，
審查時對著 `git diff` 確認這一點。
