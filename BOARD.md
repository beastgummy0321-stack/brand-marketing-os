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

- [>] **T3（route C）節點身分：一個節點只有一個身分，而且帶通路**——決策已簽：`docs/adr/0055`
      （2026-09-03 站① 凍結，同時更正 ADR 0050 三處 Meta 專屬寫法）。站②，四張票已開、循序做，
      第五張（T3e，金流）等使用者回答一個問題才開：
      - **T3a 表（全部休眠，零寫入端）**：`ad_channel`（最小、每組織一組、用到才建列，
        讓外鍵第一天就是真的）＋ `channel_entity_map`
        （`unique(org_id, brand_id, channel_id, node_key)`＝冪等鍵；`depth` 是 GENERATED 欄位，
        **不准出現 campaign／adset／ad 這三個 Meta 字**）＋ `ad_set_period_membership` 改名
        `period_node_membership`、`ad_set_external_id` 換成 `channel_id`＋`node_key`
        ＋ `brand_meta_ad_account.allocation_weight`。既有測試全綠就是它的證明
      - **T3b 綁定改吃節點鍵**：`node_key` 從樹的文件順序算出來，綁定寫進 `channel_entity_map`
        （第 1 層；`external_status` 存 Meta 的 `effective_status` 原話），讀樹改讀表。
        重展樹時同位置沿用、但節點名字要對得上，對不上轉 `orphaned` 並在畫面顯示未綁定。
        **前端 diff 必須為零**
      - **T3c 第 2 層（扛預算的那一層）**：新增 `graph.list_ad_sets`
        （`GET /{campaign_id}/adsets`，官方頁面 2026-09-03 查證），把廣告組合綁進
        `channel_entity_map`，只在自己父活動底下比對
      - **T3e 檔期分帳細到節點（金流路徑）**：`period_node_membership` 在綁定時寫列、結算時
        讀列，`period.py:125 compute_money()` 的主詞從「整個品牌那天的花費」細到「這個節點
        那天的花費」（ADR 0053 §4 的規則本身不變）。沒登記在任何檔期底下的廣告，那天的花費
        照舊算給「那天歸誰」的檔期——2026-09-03 使用者裁決，記在 ADR 0055 §11。營收不分節點
      - **T3d `creative_slot` 改吃節點鍵**：`ad_node_name` → `node_key`＋`channel_id`。
        今天兩個同名的葉節點會被 `creative.py:138` 的 `set()` 壓成同一格
      第 3 層（廣告）**這輪不綁**：它唯一的用途是接七維座標，那是 T5，而且沒有真實成效數字驗不了。
      schema 位置已留好，開它是多幾列、不是 migration
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
- [ ] **跑 `claude plugin update`**（30 秒）。規則已進 plugin repo **v5.6.0** 並已 push（`6c21ae6`）。
      repo 在 `D:\0UserProfile\Desktop\Default\skeleton-slice-pen`（**不是** `skeleton-slice`，
      那個是停在 v3.1.0 的舊代；記憶裡寫錯過一次）。內容兩批：
      v5.5.1＝2026-09-02 壓測後的三種判決／第二次紅換工作種類／派工單帶 `agent-brief.md`／模型閘門
      （證據在該 repo 的 `STRESS-2026-09-02.md`）；v5.6.0＝這輪 RLS 切片反推的四條
      （記住的「配方」跟記住的數字一樣是填空白且票的作者同樣受約束／route C 審查者要動手打一次／
      未知波及面先丟棄式實測再開票、全域開關拆成休眠＋開燈兩張／派工進行中不得 `git add -A`）。
      這台機器的 cache 目錄名仍是 `5.4.0`，但檔案已就地同步過，**本機現在跑的就是新規則**；
      跑 update 只是讓版號對得上。其他機器或重裝之後必須跑它才拿得到新規則
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
