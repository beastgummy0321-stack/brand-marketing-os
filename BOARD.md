# 切片看板（只放未開始＋進行中；完成即刪行，歷史＝git log）

> 憲法：[`CONSTITUTION.md`](CONSTITUTION.md)（廣告／排程模組，2026-09-01 簽署）

排序＝執行順序。標「需批准」的票動工前先提計畫等批准；動到畫面先過畫面契約（草圖 → 後端 → 前端）。

## 里程碑

第一段 $0——整套在本機 `supabase start` 跑通，用真品牌走完一條路：
**排程頁填表 → 出 N 個方案 → 選一個展開成三層活動樹 → 人照樹上的名稱在 Meta 後台自己建、
自己投放 → 名稱配對把成效綁回方案**。第二段才推免費層雲端。
2026-08-29 用晨光咖啡＋BP AD 真帳號整條走通過（細節見 git log；`app/ads/` 那個舊閉環已整個刪除，
要回頭看用 tag `v0.2-ads-last`）。

**唯一還缺的一段：沒辦法把一張圖掛到某一個廣告節點上。** 今天放圖只能放進品牌智庫的「官方素材」，
那是品牌層圖庫，跟樹上哪一則廣告無關。**等使用者真的手動貼過一次圖進 Meta 之後再重判**
（不做的理由：到今天為止一次都沒痛過）。

## 廣告閉環（2026-09-01 重訂——舊的七張票全部作廢）

依據三份，全部在 repo 裡：`CONSTITUTION.md`（廣告／排程模組憲法）＋`docs/adr/0050`（資料模型之記錄：
25 張表、每張的擁有模組、哪張票落它）＋`docs/contracts/schedule.md`（模組進入點與生效決策）。
架構圖仍是可讀的概覽，**兩邊不一致以 ADR 0050 為準**——0050 已更正圖上四條（cleanup 早就註冊了、
CASCADE 今早已修、上傳有 50MB 上限、產品照那條查無此事）。表的形狀不再寫在看板行上，票死不會帶走決定。
2026-08-26～31 那輪的十條凍結決定與 S3／S4／S5／⑨ **全部作廢**——不是做錯，是這輪重新訪談
加九份壓測之後資料模型換了（廣告屬通路、檔期是濾鏡、素材帶七維指紋、不得用現況欄位回答當時）。
舊碼與舊決策留在 git：`v0.2-ads-last`、`v0.3-onboarding-read-last`、`.scratch/adloop/`。

其中三條的內容被這輪吸收，不必重想：舊③「舊節點不動、可以長新枝，重畫樹會洗掉學習期」＝
這輪的「贏家畢業、不插進既有廣告組合」；舊④「統計門檻不開新規則卡」＝財務線／統計線分離；
舊②「檔期是實體、輪不建表」＝membership（輪次用算的）。

### 新票單（2026-09-01，垂直切，循序做不平行）

表的形狀一律看 ADR 0050 的表清單；migration 檔名前綴一律看 ADR 0049（前綴＝擁有那張表的模組，
不是要它的那張票，所以一張票可以有好幾個不同前綴的 migration 檔）。

- [ ] **T4（route C）** `ad_channel` 補完（T3a 已建最小版：id／org_id／channel_key／label／enabled，
      這裡補五個能力旗標＋`last_data_at`／`data_lag_days`／`spec`，並決定它和
      `platform_objectives.json` 誰是「有哪些平台」的真相——T3 刻意不搬那個檔）
      ＋ `ad_channel_format_spec`（鍵是 (channel, format)）＋ `channel_credential`
      取代 `meta_credential`（現在主鍵是 org_id＝一個組織只能一個 token）＋ `meta_ad_account` 補 `timezone_name`
      （Meta 回的日期是廣告帳戶時區，現在沒有這欄）
- [ ] **T5（route C）** 成效回流接座標——**第 3 層（廣告）的綁定是這張票的**（ADR 0055 §7：
      schema 位置 T3a 已留好，開它是多幾列不是 migration），同時決定
      `creative_candidate.published_ad_external_id` 是留成便利欄位還是刪掉
      ＋ 診斷（程式先壓縮、三個 agent、程式排序取前 5）
      ＋ `meta_entity_spend` 補 `currency` 與 `(adset_id, spend_date)` 索引 ＋ `channel_revenue` 補 spend／檔期／幣別／
      通路／來源雜湊與唯一鍵（現在手填列完全不去重）＋ `learning_ledger` 趁 0 列一次補齊
      ＋ 破除 `_latest_task_row`（`app/schedule/routes.py:133-139`）的「最新一列即真相」。**閉環在這裡合攏**
- [ ] **T6（route C）** 四象限泡泡看板 ＋ 建議落 `decision`（補六欄，不新開表；該表 0 列、程式零引用）
      ＋ `order_record.utm_json`。**現在畫不出來的五個理由，票裡要逐條有解**：`spend_summary` 的
      `bool_and(roas IS NOT NULL)`（`app/meta/repository.py:424,437`）讓整支回 None；`roas = 0` 的列一列都沒有，
      賠錢象限畫不出來；真實毛利接不到廣告（就是 utm_json 那條）；~~`daily_pull` 只拉今天但歸因窗是 7d_click~~
      ——**2026-09-02 查證為誤報**，`app/meta/daily_pull.py:89` 拉的是 `[今天-7, 今天]`，理由就寫在 `:54`；
      `frontend/src/lib/echarts.ts:11` 沒註冊 ScatterChart——**沒註冊的圖種靜默不畫也不報錯，閘門會是綠的**

## 仍然成立的事實（不是票，是量到的東西）

- 里程碑第一段 2026-08-29 用真帳號整條走通過。**這輪踩在它上面，不是取代它。**
- worker `concurrency` 是 procrastinate 3.9.0 預設值 1（`app/background` 沒指定）——N 個工作項
  仍一個一個跑。要真的同時跑得調它，而同時開 N 個代理＝同時花 N 份錢。**先量一次真實單次耗時再決定。**
- `graph.fetch_page` 的 `timeout=10.0` 還沒量過。真不夠時官方寫的下一步是切更小的日期區間，不是加大逾時。
- `app/methodology/README.md` 的「成效判讀／下期草案」與「期中檢查點」兩列**零個呼叫端**，
  `providers.py:154` 的 `performance_reading` 標籤空著。覆盤要的方法論早就寫好了。
- 心智圖的 C 診斷、D 市場競品、E 客群、P 週月報**摘要留存不排票**，閉環跑起來再判。
- `compute_money()` 的花費（T3e，ADR 0055 §11）從 `spend_summary(level="campaign")` 換成
  `daily_entity_spend(level="adset")`——membership 認的是廣告組合，用不同層算會兜不起來。
  **Meta 的活動層跟廣告組合層加總理論上該一致，這件事至今沒有拿真帳號量過**：
  2026-09-03 `meta_entity_spend` 是 0 列。等真帳號重新走一次通路那天再驗，不先加容錯。

## 第 ⑦ 片：收尾

- [ ] 07-1 閘門收尾：前端 depcruise 擋 supabase-js 只在登入模組（**Playwright 那一半已完成**，
      見 `frontend/e2e/smoke.spec.ts`，`cd frontend && npm run e2e` 一行跑完）
- [ ] 07-2 部署前（選平台後）：Hey API TS client、Sentry、staging、CD（單一 job `supabase db push`）
      ＋**pydantic-settings 收環境變數**：現在 19 個地方各自讀環境變數、8 個不同的鍵，缺了或打錯字
      會安靜地用預設值繼續跑。它真正值錢的時刻就是第一次部署——開機當場大聲失敗，好過上線後
      某個功能莫名不動、查半天發現少一個變數
      ＋**部署映像檔要有 IANA 時區資料庫**（`today_for_org()` 靠 `zoneinfo`；Debian 系內建，
      Alpine 沒有——沒有就開機第一次算日期時大聲炸掉，這是刻意的，不要安靜退回 UTC）
- [ ] 07-3 統一 404 信封：`require_brand` 走 `NotFoundKind` 吐 `{"detail": …}`，identity 路由走
      `handle_api_error` 吐 `{"error": {"code","message"}}`；前端三處讀 `.detail`
      （`brandReportApi.ts:36`、`http.ts:116`、`ordersApi.ts:93`）要跟著改。這是 API 契約改動
- [ ] 07-4 GitHub 四個安全開關（secret scanning／push protection／CodeQL／branch protection）：
      需 GitHub Pro 或公開 repo。**本機單人階段先不付費**（2026-08-30 裁決），跟 Sentry／staging／CD
      同一批再決定；在那之前 CI 綠不擋合併，靠人工

## 租戶隔離與 RLS（2026-09-02 完成，R1～R4 全清）

這一節原本的四張票全部做完了，決策與量到的數字收在 **ADR 0052**（角色、claim、為什麼不寫 FORCE、
為什麼佇列不碰、Vault 那扇門與它的 `pg_temp` 洞），不在看板重複一份。
現在的狀態：`public` 47 張表每張都有 `TO authenticated` 的 policy，已登入的請求在 `require_actor()`
之後降成 `authenticated` 角色並帶 `app.org_id`，連線還回池子時清乾淨。
**RLS 仍然是第二道防線**——主要門禁是 `require_brand` 與查詢層的 `org_id` 篩選，這個順位沒有變。

棘輪三條，新表漏了任何一條都會紅：每張表開 RLS（`test_real_db_schema_drift.py`）、
有 `org_id` 的表要有 policy（`test_rls_tenant_policy.py`）、讀租戶表的函式要帶租戶欄位
（`test_architecture_boundaries.py`）。**T2～T6 新增的表照這三條走，不必再想一次。**

## 需批准（金流路徑）：核准的到底是「上限」還是「當時那個數字」——T2 已刻意跳過它

`_tree_signature`（`app/schedule/routes.py:213-224`）把每個節點的 `daily_amount` 算進 `content_hash`，
所以預算一動，已簽過的核准就失效。**今天咬不到人**——repo 裡沒有任何程式會自己改 `daily_amount`
（grep 零命中），所以架構圖說它「現在就壞」是未來式。**2026-09-02 更新**：T2a 已經把
`campaign_period_budget_version` 這張表建起來了（含 `change_type = auto_decrease` 這個值），
但 **T2 全程沒有任何程式寫它**——引信裝好了，還沒有人點火。哪天有一張票讓系統自己調預算，
這條當天生效。

要改的是核准的語意（`approval` 加 `max_daily_amount`，核准的是上限而不是當下的數字），
**那等於修改 ADR 0040 那道錢煞車**，是金流路徑：先提計畫、等批准、寫自己的 ADR。
T2 三張票逐字寫明不碰它，審查也逐字驗過 diff 裡沒有 `max_daily_amount`。

## 需批准（金流路徑）：核准超支的「過了幾天」把 UTC 跟組織時區混著減

`_approval_overspend()`（`app/schedule/routes.py:243`）拿 `approval.approved_at`（存 UTC）換算出來的
日期，去減 `today_for_org()`（組織時區的今天）——**台北時間每天 00:00–08:00 這段，UTC 還停在前一天**，
兩個日期差一天，`days_elapsed` 多算一天。兩次實測釘死：UTC `2026-08-30 17:25`／組織今天 `08-31` 時紅
（`AssertionError: 2 != 1`），跨過 UTC 午夜後連跑三次全綠。

影響方向不好：`expected_to_date = 核准金額 × days_elapsed`，天數多算一天＝「應該花到這裡」被高估，
實際花費相對看起來**更沒有超支**。ADR 0040 那道錢煞車錯的方向應該是更嚴格，不是更寬鬆。

現形方式：`app/tests/test_approval.py::ApprovalApiContractTest` 那條 `days_elapsed == 1` 的斷言
只在台北 00:00–08:00 會紅，白天全綠——**所以它躲過了每一次在正常時間跑的閘門**，包括 CI。
**動的是金流路徑，先提計畫等批准，不順手改。**

## 2026-09-03 規範體檢：對過真實數字的一輪，四條已裁決

看板／憲法／55 份 ADR／5 份契約／機器閘門常數／plugin 5.7.0 三個 hook 全部對過**實測值**，
不是照文件抄。已裁決的四條與當下狀態：

- [x] ~~**`.env.example` 的 HS256 後門**~~ **2026-09-03 完成，route C 審查 `ship`（尚未 commit）**。
      原狀：範本第 15-16 行同時附上 `IDENTITY_ALLOW_HS256=1` 與 Supabase 公開示範密鑰，
      照範本複製上雲＝任何人能自簽任意 `org_id` 的權杖讀全部租戶。修法不是新決定——
      `IDENTITY_DEV_TOKEN` 早就有同一道開機守衛，這張票把**已經存在的裁決**套到漏掉的第二個後門。
      兩個後門現在共用 `app/identity/__init__.py:44-46` 的 `_is_local()`；`.env.example` 全檔
      已無示範密鑰。順手補了 `docs/contracts/identity.md`（identity 模組**一份 ADR 都沒有**，
      寫進頁裡當事實記著）。審查逐條打過：`register()` 是唯一 FastAPI 實例的必經之路、
      背景 worker 完全不碰 identity、`mock.patch.dict` 確實還原、循環沒被重新接上
- [ ] **`_is_local()` 只認 localhost／127.0.0.1，交給 07-2**（2026-09-03 審查發現，**先天限制不是本輪引入**，
      `IDENTITY_DEV_TOKEN` 從票 03-1 起就靠同一個判斷）：自架 Supabase 跟網站同機是合理的正式拓撲，
      那種機器上 `SUPABASE_URL=http://127.0.0.1:...`，守衛會判它「本機」而放行。要根治就要一個
      「這是不是正式環境」的變數——**那顆空白屬於 07-2，不在任何單張票的權限裡**。
      順帶：沒有 scheme 的 `SUPABASE_URL`（`localhost:54321`）`urlparse` 回 `hostname=None`，
      會讓開發者開機失敗；不影響安全，但會浪費一個下午
- [x] ~~**`app/schedule/routes.py` 768／上限 800**~~ **2026-09-03 完成，768 → 502**。
      做法照工作流規範「A boundary escalation is not a menu」：先派一支 READ-ONLY 問「這個檔該裝
      什麼、每個函式去哪、哪些碰錢」，把它的表變成兩張票——`state.py`（route B，畫面組裝）
      與 `tree_approval.py`（route C，錢，獨立審查 `ship`）。**判準寫進 `docs/contracts/schedule.md`**：
      一個符號只有在「離開 HTTP 端點就沒有存在理由」時才配留在 routes.py。
      金流審查的關鍵一步是**機器逐字元比對**六段搬過去的程式碼（六次 diff、六次空輸出），
      不是用眼睛讀——`_tree_signature` 的排除欄位清單增減一個鍵，會默默改變所有已簽核准的
      `content_hash`，任何測試都不一定抓得到。時區 bug 與 `max_daily_amount` 兩條逐字禁止順手動，
      **偷偷修好也算未經批准的金流變更**。T5 現在有約 300 行餘裕可落地
- [ ] **`ImportCycleScanTest` 看不到套件內部的環**（2026-09-03 實作時發現）：它只記錄頂層套件
      之間的邊，所以 `app/schedule/state.py` ⇄ `app/schedule/routes.py` 那個雙向 import 全程綠燈。
      這次靠票面明文與人工檢查關掉，**下一個在同一個套件裡拆檔的人不會自動被擋**。
      已寫進 `docs/contracts/schedule.md` 當唯一的守門文字。要不要把掃描器降到模組層是個決定
- [x] ~~`AGENTS.md`~~ **已刪（使用者裁決）**：它第 1 行寫「SQLite、單機單人使用」，正是
      `CONSTITUTION.md` 第 1 條禁止的前提，而且它不在 adr-sweep 的掃描樹、也不在
      「CONSTITUTION > ADR > 契約 > 票」的優先序裡——沒有任何機制守它。ADR 0031:55 本來就寫
      「workspace 不放 `AGENTS.md`」。同一個 commit 修掉兩個指回來的指標
      （`app/core/__init__.py:2`、ADR 0002 的載入預算定義）
- [ ] **契約頁：16 個模組缺 11 份**（不是 `CLAUDE.md:79` 寫的「只有 schedule.md」——現在有
      brand_intelligence／brand_web／core／meta／schedule 五份，加上剛補的 identity＝六份）。
      **裁決：route C 逐票補，並裝閘門**（`CLAUDE.md` 那句「不加機器閘門」已改掉，
      否則它跟全域規則「散文裡的限制不是限制」永久對撞）。**閘門還沒建**，形狀已定：
      在 `test_architecture_boundaries.py` 加一份 `MODULES_WITHOUT_CONTRACT` 凍結清單，
      **只准變短**——開票當天清單＝現況所以是綠的，新模組沒有頁會紅，補完一份劃掉一行。
      跟 `KNOWN_OVERSIZED_FILES` 同一種棘輪。**要先弄紅一次才算數**（加一個假模組資料夾看它紅）

- [x] ~~**合併閘門會隨機紅，而 `CLAUDE.md` 把成因寫錯了**~~ **2026-09-03 量出來並修好**：
      這台機器 20 核，`-n auto` 就開 20 個 worker，每個帶連線池＋procrastinate 的 worker 與
      listener 連線，加上 Supabase 常駐的約 30 條，直接頂穿 `max_connections=100`。
      同一份程式碼同一條指令，**`-n auto` 是 717 passed／28 errors，`-n 8` 是 745 passed，
      而且沒有變慢**（41 秒 vs 45 秒）。原本寫的成因是「同時開著兩個後端」——這次一個多餘後端
      都沒有（實測 `Get-NetTCPConnection` 8710／8720 皆空、`Get-Process python` 零筆）照樣紅。
      28 個 error 之外還會冒出一個看起來像真斷言失敗的 `test_meta_daily_spend.py:548`，
      其實是背景工作連不上資料庫的下游效應——**這正是它危險的地方**：紅得像程式壞了。
      `CLAUDE.md` 的合併指令已改成 `-n 8` 並寫上理由

### 查到但還沒裁決（都已查證是真的，不是文件上的說法）

- [ ] **CI 從來不跑 e2e smoke**。`.github/workflows/ci.yml` 只有 ruff／pyright／pytest／前端
      lint-typecheck-test-build。而 `CLAUDE.md` 與工作流規範都把 e2e 當「整合 bug 唯一現形處」
      ——**這個系統最吃重的閘門只活在開發機上**，CI 綠不代表 server 起得來
- [ ] **`決策 NNNN` 是一套死掉的平行編號，全庫 84 處引用它**（2026-09-03 查證；本行原本寫成
      「引用已退休的 ADR」是**錯的**，實情更糟）。它不是 ADR：`決策 0013` 講硬刪除要記
      audit_log，ADR 0013 講設定頁重用規則卡；`決策 0015` 講品牌連鎖刪除，ADR 0015 講檔期跳過。
      **兩套編號互相撞號，指向完全不同的東西。** 來源文件在 `5eca0db`
      「乾淨重啟：保留程式與資料，清除所有流程紀錄與規範文件」被刪，而那個 commit 就是可見歷史的
      **根**——`docs/decisions/` 在整個 git 歷史裡零命中，**救不回來了**。
      分布：84 處、36 個檔，含 production、測試、前端（`tokens.css`、`AppShell.tsx`、`useEchart.ts`）。
      adr-sweep 只掃 `.md`，所以這些永遠不會紅。
      **最省事也最誠實的補法**：在 `CONTEXT.md` 加一行說「`決策 NNNN` ＝ 已銷毀的舊決策紀錄編號，
      解析不到任何東西，**不是 ADR id**」——因為那些註解大多**本來就把規則寫在句子裡了**
      （「硬刪除…before 全文記 audit_log，決策 0015」），死掉的只是footnote。
      另外約 5 處寫的是「**ADR** 0017」而不是「決策 0017」（`brand_web/routes_products.py:18,173`、
      `brand_intelligence/report.py:1`、`repository.py:1244`），那幾處會真的把人帶去讀錯的檔，要逐條改
- [ ] **十幾個檔引用 `5eca0db` 刪掉的文件**：`docs/design/*`、`architecture-rules.md`、
      `rule-checks.md`、`workflow-diet.md`。最糟的一處是
      `test_architecture_boundaries.py:988`——**最常紅的那道閘門，錯誤訊息叫人去讀不存在的
      `docs/workflow-diet.md`，還印出「目標 0.7」，而 ADR 0041 明文寫「沒有任何文件再訂這個數字」**
- [ ] **`docs/tech-debt.md` 四筆事實已錯**（它是 `CLAUDE.md` 指定「動超標檔前先讀」的檔）：
      `TEST_LINES_CEILING` 寫 14,305（實際 **17,823**）；`brand_intelligence/repository.py`
      寫 1667 行（實際 **1387**）；§〇 那兩筆「沒有閘門守的欠帳」——`cycle_shopee_code` 已在
      `20260829000005` DROP、`app/dashboard/campaign_calendar.py` 整支已刪，兩個都不存在了
- [ ] **前端完全沒有行數閘門**：`FileLineCapTest` 只掃 `app/**.py`。
      `frontend/src/components/schedule/SchedulePage.tsx` 已 851 行、超過 800，而 U2 還要再動它
- [ ] **棘輪餘裕實測（2026-09-03）**：`TEST_LINES_CEILING` 17823／實測 17823＝**0**；
      `app/core`／`app/identity`／`app/background`／`app/storage`／`app/tools` 五個模組也是 **0**，
      `app/llm` 剩 2 行。ADR 0041 允許「寫理由調高」所以不是死結，但 **T4～T6 每一張票都得動閘門
      常數行**，每次都要重打一次「這算不算放寬容忍清單」的官司。測試／production 比值 **0.949**
- [ ] **`app/identity/` 沒有任何 ADR 管**（`adr-index.mjs` 對它零列）。認證、組織解析、兩個開發
      後門都在裡面，一條決策紀錄都沒有。已寫進 `docs/contracts/identity.md` 當事實記著
- [ ] 記憶 `model-assignment-preference`（「Opus 只協調與審查」）**已與 hook 對撞**：
      `ticket-fields.mjs:88` 擋掉任何帶票路徑的 opus 派工，route C 審查者是 **sonnet**。要更新記憶
- [ ] 殘留 worktree：`C:/Users/User/orca/workspaces/marketing/t3-frontend`（分支
      `beastgummy0321-stack/t3-frontend`）。**已確認完全併進 `saas`，沒有未合併的工作**，
      `git worktree remove` 即可

## 小債（順手做，不排優先）

Dependabot #1（`nanoid`，修補版 3.3.18）：**`saas` 這邊已經是 3.3.18、`npm audit` 零漏洞**，
但 GitHub 掃的是預設分支 `master`，那邊還凍在 `v0.1-desktop` 的 3.3.17。警示會亮到 `saas` 併回
`master` 為止——**不是還沒修，是修在另一條線上**。不為了關掉警示單獨去動凍結的 master。

- [ ] **上線前必刪（2026-09-02 建，使用者要求）** `supabase/seed.sql` 尾巴那段排查用帳號：
      `123@example.com` ／ `123456`，固定 UUID、固定組織 `org_bughunt`、固定品牌 `brd_bughunt`。
      每次 `supabase db reset` 自動重建，這正是它存在的理由——重置資料庫來查 bug，不會連查 bug
      的工具一起炸掉。**`supabase db push` 不會跑 seed 檔**，所以它到不了雲端，但它仍然是一組
      進了版控的已知帳密：**任何一次真的部署之前，這整段連同這一行一起刪掉**
- [ ] **U2（route C）前端版面規範落地**——決策已簽：`docs/adr/0051`（2026-09-02 訪談口述，
      13 條規則＋量到的數字＋沒量到的但書都在裡面）。這張票做四件事：
      1. `AppShell.tsx:10` `w-[var(--width-shell)]` → `w-full max-w-[var(--width-shell)]`，
         `tokens.css:66` `--width-shell` 1440px → 1920px，寫死欄數的 17 處格線改 `auto-fit`；
         順手清掉 `AppShell.tsx:6`、`useEchart.ts:5`、`tokens.css:65` 對死掉的「決策 0038」的引用。
      2. 灌測試資料進 `orders`／`products`，補測 ADR 0051 那條但書（塞滿的表格擠進 1024）。
      3. 閘門：15 條路由在 1280 下驗 `document.documentElement.scrollWidth <= window.innerWidth`
         ——**先弄紅一次才算數**。沒有閘門它會漂回去。
      4. 1920 目前**在 1440 以上完全沒量過**，這張票要補一輪。
      **配色與字體不在本票**（ADR 0051 規則 13，另開一張）。
      驗證要開乾淨的瀏覽器 session——快取住舊 bundle 會量到跟沒改一樣的數字。
- [ ] **上雲前必還（ADR 0039）** 每日 Meta 花費拉取的 worker 跑在網站行程裡：網站沒開就不拉，
      那天沒有數字（手動補：`uv run python -m app.meta.daily_pull`）；cron `0 3 * * *` 觸發的**時刻**
      仍是機器本地時間。上雲時 worker 要拆成自己的行程
- [ ] **上雲前必還（2026-08-28 裁決：本機單人階段不修）** 邀請連結是「持有即可用」：
      `app/identity/routes.py` accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage`
      一掛載就自動接受，沒有確認步驟
- [ ] 用自己金鑰（`own`）的組織看不到「調整月上限」欄位，切回 `platform` 時不好調——
      跟「設定頁切換金鑰來源」同一張做
- [ ] AI 成本對帳：`llm_task.cost` 是我們自己用 `app/llm/pricing.py` 算的**估算值**，不是 Anthropic
      實際帳單。官方有 `/v1/organizations/cost_report`（約 5 分鐘延遲，需 Admin API key）——
      上雲收費前要拿它跟自己的估算對一次帳，否則「每月上限」擋的是估算不是真錢
- [ ] 五個記憶體背景工作（品牌智庫抽原話、產品調研、顧問報告、建檔精靈初掃與出題）還是
      「一張 dict＋一條執行緒」：重開後端就整個消失，狀態不進資料庫。排程那三支已搬上佇列
      （ADR 0042），這五支**沒有量到痛過**所以沒搬——真的痛了照 ADR 0042 同一個做法搬
- [ ] **需批准（schema）** `DROP TABLE decision` **2026-09-01 改判：不刪**——這輪要拿它當「建議落表」，
      形狀剛好（action_json／risk_level／dedupe_key／outcome），補幾個欄位就能用。仍要刪的是： `order_record.attribution_override`、
      `interrupt.kind`／`visible_from`／`campaign_cycle_id` 四個沒人用的欄位。欄位還在，
      所以 `enqueue()` 那三個沒有生產呼叫端的參數也還留著
- [x] ~~`FILE_LINE_CAP = 800` 與「line count never orders a split」相撞~~ **2026-09-03 由新版
      工作流規範自己解掉**：規範「A boundary escalation is not a menu」一節明講**行數上限是警報、
      不是命令**，撞到時的正確回應是派一支 READ-ONLY 問「這個檔該裝什麼、每個函式去哪、哪些碰錢」，
      把它的表變成一張 route C 模組邊界票，排在觸發警報的那張票**前面**——不是登記成
      known-oversized，也不是搬走最小的那個函式。閘門留著，只是它說的話換了意思。
      唯一要改的是 `FileLineCapTest` 的錯誤訊息（現在寫「先拆再加」＝命令）
- [ ] `meta-format-specs.md:52-53` 的 `script`／`hook_pool` 也掛著「無字數預算」（同一次實跑佔 18.1%／7.3%）。
      ADR 0047 只處理圖片提示詞那一項。**2026-09-01 裁決：這批不收**——0047 已經拿掉約六成輸出，
  「太長會被截斷」的痛小很多，而且實跑從沒真的被截斷過。T1b 的閘門只擋圖片欄位，不做全域字串禁令。
  真的被截斷一次再回頭收
- [ ] T1 收尾時記下、不擋合併的四條（票已刪，留在這裡）：`creative.py:77` 的 `all([])` 是 True，
      所以 `value: []` 與 `value: ["", ""]` 會過關、畫面出現空欄位；七個維度名住三個地方
      （`COORDINATE_KEYS`、TS 介面、前端中文標籤）沒有同步閘門；
      `test_creative_task_gets_methodology` 斷言方法論檔的行文，上游改標題就無故變紅
      （改斷言 `【方法論：creative-matrix.md】` 這個穩定標記就不脆）。
      第四條（`ad_creative.md` 掉了「誠實優先於好看」）**2026-09-01 查證為誤報，那句還在
      `app/departments/creative/ad_creative.md:35-36`**，已結案
- [ ] `assets` bucket 沒設 `file_size_limit`（`supabase/migrations/20260830000002_core_storage_assets_bucket.sql`
      的 insert 只給 id／name／public）。**上傳端已經擋兩道 50MB**（`app/brand_web/routes_library.py:57`／`:79`／`:273`），
      所以這是第二道防線不是沒有防線——架構圖說「上傳無大小上限」是錯的。順手補一行
- [ ] **同名的最深層節點，哪份內容配哪個位置是任意的（2026-09-03 T3d，使用者裁決「先不根治」）**：
      代理的回覆只帶節點**名稱**、不帶編號，所以同一份方案裡兩個廣告取了一模一樣的名字時，
      「先出現的那段配第一個節點」——穩定，但無法證明是對的（審查原話：構造上無法證偽）。
      規則寫在 `docs/contracts/schedule.md`。**根治法是讓代理把 `node_key` 一起回傳**
      （要改部門提示詞檔＋解析＋測試，動到 ADR 0047 的地盤）。今天一次都沒咬到人，
      真的咬到再開票
- [ ] **租戶防線不對稱（2026-09-03 T3c 審查發現，已查證今天咬不到人）**：
      `ad_set_ids_by_exact_name`（`app/meta/repository.py`）只拿 `org_id` 去取權杖，呼叫端給的
      `campaign_id` 原封不動送去 Meta，函式自己不驗證那顆活動是不是這個組織的。它的姊妹函式
      `campaign_ids_by_exact_name` 有驗（先 `SELECT ... FROM meta_ad_account WHERE org_id = %s`）。
      擋住跨組織的是**呼叫端的形狀**（唯一呼叫點只可能傳自己組織的活動 id），不是函式本身——
      審查逐條追過整條路徑，**沒有任何請求構造得出跨組織的輸入**，所以是欠帳不是漏洞。
      補法：在函式裡加一道「這顆活動屬於這個組織」的檢查，一次查詢。`docs/contracts/meta.md`
      已經逐字記下這個不對稱，不再宣稱「每支都篩 org_id」
- [ ] `frontend/src/components/layout/FluidCard.tsx` 現在只剩 Storybook 在用。要留當設計素材還是刪，
      下一輪順手決定
- [ ] `frontend/src/lib/auth.ts` 的 depcruise 註解已改成「規則還沒建」並指向 07-1——
      真正把規則建起來還是 07-1 的工作

## 使用者待辦（不是程式債，做的人是你；我做不了）

- [ ] **設這個品牌的 `conversion_goal`**（1 分鐘）。現在 NULL，所以任何地方的 CPA（每次成交花多少錢）
      都是空白——那是「不知道什麼算成交」，不是「沒有成交」。**這是資料不是程式**
- [x] ~~跑 `claude plugin update`~~ **2026-09-03 查證已完成**：cache 裡有
      `skeleton-slice-pencil/5.7.0/`，`hooks/` 下 `adr-index.mjs`／`ticket-fields.mjs` 都在，
      session 注入的規則就是 5.7.0 那份。plugin repo 在
      `D:\0UserProfile\Desktop\Default\skeleton-slice-pen`（**不是** `skeleton-slice`，
      那個停在 v3.1.0）。其他機器或重裝之後仍要跑 update 才拿得到
- [ ] **2026-08-30 承諾：這幾天真的貼一則廣告到 Meta**（用排程頁產出的圖片提示詞生一張圖 →
      上傳進品牌智庫的官方素材 → 手動貼進 Meta 建一則廣告）。這條走過之前，**「把圖掛到廣告節點上」
      一律判「不做」**——圖的落腳處蓋好了，但圖片這件事一次都沒真的痛過，沒走過就蓋下一層＝
      替沒人跑過的系統猜門檻
- [ ] **Beast Prime 也要重建（2026-09-02）**：T2 這輪的 RLS 紅綠證明跑過 `supabase db reset`，
      `123@gmail.com` 那個帳號、它的組織、品牌「Beast Prime 野獸至尊」、Meta 廣告帳戶綁定
      **全部歸零**（實際查過，各 0 筆）。CLAUDE.md 原本寫「洗掉後重設密碼就好」是錯的，已改成事實。
      要重來就是：註冊 → 建檔精靈建品牌 → 重綁 Meta 廣告帳戶。**這是設計上允許的**（憲法「資料狀態」
      那節：發布前資料庫內容全為測試資料），只是你得知道它沒了
- [ ] 晨光咖啡要重建：2026-08-30 跑過 `supabase db reset`，8/29 那次實跑的資料全部消失。
      品牌、已確認事實、規則都要重來——去建檔精靈把品牌事實填起來，方案才會再準一階
- [ ] 變異度（同一份輸入跑 N 次結果差多少）從沒量過：探針在
      `D:\0UserProfile\Desktop\MarketingOS Shell\variance-probe\`，一次都沒跑過。排程會做即時網路查詢，
      兩次跑本來就看到不同素材，重試預算現在是猜的。
      **這條也是「提示詞指紋」的前置**：`llm_task.methodology_hash` 是用來回答「為什麼這個月的方案
      跟上個月不一樣」，但差異本來有多大都還沒量過，先蓋工具去解釋差異＝替沒人跑過的系統猜門檻。
      **2026-08-30 判定不做**；這條探針跑出數字之後才回頭重判

## 里程碑之後（上雲後才動）

- [ ] U1 介面文案大掃除：禁用詞機器閘門（擋 ADR 0051 規則 9–11 的口語問句式按鈕文案）
      ＋全站術語一致化。驗收看 `docs/adr/0051`，原本寫的「契約鐵則 11–12」那份契約已刪除
- [ ] 設定頁切換金鑰來源（`platform`／`own`）：前提是「自帶金鑰」真的是一個在賣的方案，
      那還不存在——今天要切只能直接改資料庫，而全系統只有一個組織。做這張時一併補上面小債那條
      「用自己金鑰的組織看不到調整月上限欄位」
