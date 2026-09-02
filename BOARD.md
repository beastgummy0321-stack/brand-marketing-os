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

- [ ] **T2（route C）** `campaign_period`（含結算快照與四值狀態機）＋ `campaign_period_budget_version`
      ＋ `ad_set_period_membership`（**絕不加 `unique(ad_set_id)`**）＋ `product_economics_version`（半開區間，
      現行 `save_product_economics` 是原地改同一列）＋ `holiday` ＋ `interrupt.dedupe_key` 含檔期 id
      ＋ `llm_task.campaign_period_id`。**`approval.max_daily_amount` 不在本票**——見下面「需批准」那條
- [ ] **T3（route C）** `channel_entity_map`（`node_key` 路徑式、`external_status` 存平台原話、
      `learning_reset_at`、`unique(org_id, brand_id, node_key)` 就是冪等鍵）＋ `brand_meta_ad_account.allocation_weight`
      ＋綁定改吃 id 不吃名稱——一鍵建立不再建出兩份
- [ ] **T4（route C）** `ad_channel` ＋ `ad_channel_format_spec`（鍵是 (channel, format)）＋ `channel_credential`
      取代 `meta_credential`（現在主鍵是 org_id＝一個組織只能一個 token）＋ `meta_ad_account` 補 `timezone_name`
      （Meta 回的日期是廣告帳戶時區，現在沒有這欄）
- [ ] **T5（route C）** 成效回流接座標 ＋ 診斷（程式先壓縮、三個 agent、程式排序取前 5）
      ＋ `meta_entity_spend` 補 `currency` 與 `(adset_id, spend_date)` 索引 ＋ `channel_revenue` 補 spend／檔期／幣別／
      通路／來源雜湊與唯一鍵（現在手填列完全不去重）＋ `learning_ledger` 趁 0 列一次補齊
      ＋ 破除 `_latest_task_row`（`app/schedule/routes.py:133-139`）的「最新一列即真相」。**閉環在這裡合攏**
- [ ] **T6（route C）** 四象限泡泡看板 ＋ 建議落 `decision`（補六欄，不新開表；該表 0 列、程式零引用）
      ＋ `order_record.utm_json`。**現在畫不出來的五個理由，票裡要逐條有解**：`spend_summary` 的
      `bool_and(roas IS NOT NULL)`（`app/meta/repository.py:424,437`）讓整支回 None；`roas = 0` 的列一列都沒有，
      賠錢象限畫不出來；真實毛利接不到廣告（就是 utm_json 那條）；`daily_pull` 只拉今天但歸因窗是 7d_click；
      `frontend/src/lib/echarts.ts:11` 沒註冊 ScatterChart——**沒註冊的圖種靜默不畫也不報錯，閘門會是綠的**

## 仍然成立的事實（不是票，是量到的東西）

- 里程碑第一段 2026-08-29 用真帳號整條走通過。**這輪踩在它上面，不是取代它。**
- worker `concurrency` 是 procrastinate 3.9.0 預設值 1（`app/background` 沒指定）——N 個工作項
  仍一個一個跑。要真的同時跑得調它，而同時開 N 個代理＝同時花 N 份錢。**先量一次真實單次耗時再決定。**
- `graph.fetch_page` 的 `timeout=10.0` 還沒量過。真不夠時官方寫的下一步是切更小的日期區間，不是加大逾時。
- `app/methodology/README.md` 的「成效判讀／下期草案」與「期中檢查點」兩列**零個呼叫端**，
  `providers.py:154` 的 `performance_reading` 標籤空著。覆盤要的方法論早就寫好了。
- 心智圖的 C 診斷、D 市場競品、E 客群、P 週月報**摘要留存不排票**，閉環跑起來再判。
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

## 租戶隔離與 RLS（2026-09-02 工作流壓測後新增）

背景一句話：`test_org_isolation_all_tables.py` 守的是「每張表有沒有 `org_id` 欄位」（schema 層），
2026-09-02 新增的 `UnscopedTenantReadScanTest`（`test_architecture_boundaries.py:257`）守的是
「讀租戶表的函式有沒有帶租戶欄位」（查詢層）。**兩層都守到了，但資料庫本身一條 RLS 都沒有**——
20 個 migration、99 張表、0 條 `row level security`，後端用 `postgres` 超級使用者連線
（`app/core/db.py:92-94`），超級使用者無視 RLS，連 FORCE 都無視。

急迫性判定：前端只跟 FastAPI 講話（憲法 3），**沒有不受信任的客戶端握有 DB 連線**，
所以 RLS 在這裡是第二道防線，不是主要門禁——這跟瀏覽器直連的一般 Supabase 專案不同，低一階。
但 T2～T6 要新增約 25 張表（ADR 0050），**現在不帶，將來要補的是 124 張而不是 99 張。**

- [ ] **R1（route C，半天）RLS 追蹤切片：只做一張表。**
      挑一張現有的表，開 RLS ＋ 寫 org policy ＋ **用非超級使用者角色連進去**，
      測「B 組織看到 0 列」。沒跑過的 policy 是沒驗過的碼——先在一張表上證明形狀對，
      才知道換連線角色會炸到什麼、真實代價多少。**排在 T2 之前**，因為 ② 要照抄它的形狀
- [ ] **R2（跟著 T2～T6 做，每張新表約 3 行）新表出生就帶 RLS ＋ policy。**
      今天完全不作用（超級使用者無視），零行為改變、零風險；價值是「開啟它是打開開關，不是改 schema」。
      **配套棘輪**：`test_org_isolation_all_tables.py` 加一條「新表必須開 RLS」，既有 99 張凍住——
      沒有棘輪，做到 T4 就會忘
- [ ] **R3（route C，排進 07-2 部署前，1～2 天，需批准）真正的開關。**
      連線角色 `postgres` → 帶 org claim 的 `authenticated`、補完 99 張舊表的 policy、
      `FORCE ROW LEVEL SECURITY`、寫自己的 ADR。排這裡的理由：跟 Sentry／staging／CD 同一批，
      是 RLS 第一次真的承重（多組織共用雲端）的時刻，而且**還沒有真實客戶資料**。
      **絕對不要排在上雲後**——帶著付費客戶資料 retrofit，中間任何一條 policy 寫錯就是 A 看到 B。
      **豁免四張佇列表**（`procrastinate_events`／`_jobs`／`_periodic_defers`／`_workers`）：
      沒有 `org_id`，開 RLS 會把 worker 鎖死
- [ ] **R4（調查，非 route C）四處凍結的無租戶欄位讀取，去看呼叫端有沒有先驗。**
      `KNOWN_UNSCOPED_TENANT_READS`（`test_architecture_boundaries.py:277`）凍了四項：
      `routes_report_api.py::_report_shape`、`intake/repository.py::list_llm_cost_items`、
      `intake/repository.py::get_draft_spend`、`llm/gateway.py::get_task`。
      四個都是「id 由呼叫端給、函式內沒有租戶欄位」的形狀。**要清掉是去追呼叫鏈確認 id 驗過，
      不是把它們從清單刪掉。** 追完若真的沒驗＝跨租戶讀取，當場升 route C

## 需批准（金流路徑）：核准的到底是「上限」還是「當時那個數字」——T2 動工前要答

`_tree_signature`（`app/schedule/routes.py:213-224`）把每個節點的 `daily_amount` 算進 `content_hash`，
所以預算一動，已簽過的核准就失效。**今天咬不到人**——repo 裡沒有任何程式會自己改 `daily_amount`
（grep 零命中），所以架構圖說它「現在就壞」是未來式。但 ADR 0050 的表清單裡有 `campaign_period_budget_version`
帶 `change_type = auto_decrease`：那張票一落地，系統就會自己調預算，這條當天生效。

要改的是核准的語意（`approval` 加 `max_daily_amount`，核准的是上限而不是當下的數字），
**那等於修改 ADR 0040 那道錢煞車**，是金流路徑：先提計畫、等批准、寫自己的 ADR，不併進 T2 順手做。

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
- [ ] `FILE_LINE_CAP = 800` 仍用行數下令拆檔，工作流規範卻寫「line count never orders a split」。
      2026-08-31 裁決留規範那份；已超標檔已改棘輪，新檔還是被行數逼拆。要不要收掉是你的決定
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
- [ ] `frontend/src/components/layout/FluidCard.tsx` 現在只剩 Storybook 在用。要留當設計素材還是刪，
      下一輪順手決定
- [ ] `frontend/src/lib/auth.ts` 的 depcruise 註解已改成「規則還沒建」並指向 07-1——
      真正把規則建起來還是 07-1 的工作

## 使用者待辦（不是程式債，做的人是你；我做不了）

- [ ] **設這個品牌的 `conversion_goal`**（1 分鐘）。現在 NULL，所以任何地方的 CPA（每次成交花多少錢）
      都是空白——那是「不知道什麼算成交」，不是「沒有成交」。**這是資料不是程式**
- [ ] **跑 `claude plugin update`**（30 秒）。規則已進 plugin repo **v5.5.1** 並已 push（`ab8d8a0`）：
      2026-09-02 壓測後的三種判決／第二次紅換工作種類／派工單帶 `agent-brief.md`／模型閘門，
      證據與失敗數據在該 repo 的 `STRESS-2026-09-02.md`。
      這台機器的 cache 目錄名仍是 `5.4.0`，但檔案已就地同步過，**本機現在跑的就是新規則**；
      跑 update 只是讓版號對得上。其他機器或重裝之後必須跑它才拿得到新規則
- [ ] **2026-08-30 承諾：這幾天真的貼一則廣告到 Meta**（用排程頁產出的圖片提示詞生一張圖 →
      上傳進品牌智庫的官方素材 → 手動貼進 Meta 建一則廣告）。這條走過之前，**「把圖掛到廣告節點上」
      一律判「不做」**——圖的落腳處蓋好了，但圖片這件事一次都沒真的痛過，沒走過就蓋下一層＝
      替沒人跑過的系統猜門檻
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
