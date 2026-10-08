# 投放中心：Campaign、策略、投放與結案

F13 待核准設計見 §6.9；該節未實作，不代表既有功能已改變。

本頁是此領域的現行決策；只在任務涉及此領域時讀取。邊界與所有權見 [架構入口](../../ARCHITECTURE.md)。
保留原 §6 編號供既有票引用；其他 § 編號由架構入口定位。舊 Feature 編號是來源標記，不是必讀文件。

## 6. 投放中心 (Ads V2) — settled decisions (2026-09-12)

Current implemented decisions are below. Approved but unimplemented closed-loop changes remain in
`docs/backlog/issue-drill-4-root-causes-pending-rulings.md`; read that only when planning those changes,
and do not present them as already shipped.

These are decided. A worker implements them; it does not re-open them. The user's rulings are in
git history (retired F03 plan). Current visual references are in `docs/design/ads/`;
§6.1 and later refinements supersede the original prototype. Do not require old scratch to start work.

1. **New module, not a reshape.** The thing being replaced is the model itself — today's plan and
   tree live as JSON inside `llm_task` rows and 93 tests in `test_schedule.py` are coupled to those
   shapes. `ads` therefore starts clean with real rows; `schedule` is not patched. What is reused is
   reached through legacy facades (`app/meta/repository.py` for exact-name binding and daily spend,
   `app/brand_intelligence/repository.py` for facts, product economics and learnings), not by
   importing `app.schedule`.
2. **Four levels, three tables.** Campaign → 通路 → 投放組 → 廣告 is the model; the 通路 level is a
   column on the 投放組, not a table — it has no state of its own. Nothing is platform-specific:
   a channel is a key with a label (Meta, Google Ads, TikTok, 蝦皮, momo…); only Meta is connected,
   the rest read 未接上, and no platform name is baked into a column name or a CHECK.
3. **Budget lives in 投放中心.** Money is allocated at the 投放組 level only; the 廣告 level shows
   observed spend share. Breakeven CPA uses the conversion-value formula in `docs/architecture/intake.md` §8.2
   (goods omit close_rate; services multiply by it), target CPA =
   breakeven × 0.7. No spend history → 日預算 = Campaign 目前明確設定的 CPA × 每天想要的購買數 (最低 2 ／推薦 5 ／
   積極 10), labelled 冷啟動估算; with history → 近 30 天 CPA 中位數, scenarios ×0.6 ／×1 ／×1.6.
   F09: 商品損益推算可供設定目標參考，但不能冒充 Campaign 已確認的 CPA。成功條件或日期改變時，
   情境讀取與選用皆重算；沒有有效 CPA 就回未知。已選 `budget_planned` 與投放組預算不自動改動。
   畫面列出公式、天數、原選金額與超出上限的情境。歷史模式保留原日預算依據，只重算期間總額。
   Every number is editable; the AI only prefills. The 設定 page's 檔期日預算 card goes away.
   After 採用策略 the **group daily budgets are the single source of truth**; the campaign row keeps
   the adopted scenario amount as `budget_planned` for the record, and the total on screen is
   `sum(daily) × days`, derived in one place.
4. **Channel adapters, one interface.** `manual` (checklist with copy buttons → the user builds on
   the platform → 配對 by exact name, the existing algorithm) and `simulated` (publishing binds fake
   entities **and** writes the daily outcome rows for the days already elapsed, so a walkthrough
   reaches 成效 in the browser with no command line) ship now; the auto-Meta adapter is a reserved
   third that reports 未接上. Binding columns live on all three levels (campaign, group, ad) because
   the platform's name lookups are hierarchical, and the campaign node is bound first. Nothing in
   the product ever asks the user to run live ads to see a result.
5. **Every platform-bound change is an `ads_action` row** — what changed, before, after, who
   approved, sync state (`pending_manual` / `confirmed_manual` / `auto_synced`), platform ref,
   reversible by a reverse action. It replaces `campaign_period_budget_version`. Budget raises still
   pass through `app/core/approval.py` (`max_daily_amount` stays the brake).
6. **Outcome attribution is by bound entity** (superseded by §6.41, F37: platform sync rows; `ads_outcome_daily` dropped). One `ads_outcome_daily` row per (entity, day), fed
   either by the Meta ingest (read `meta_entity_spend` through `app.meta.repository`) or by the
   simulated adapter. 重疊分帳 (ADR 0053's day-splitting between overlapping 檔期) does not come
   along; a campaign owns the entities bound to it.
7. **Learning is inference, never a brand fact.** Written at 結案 (and at 採用建議, from F04) into
   `learning_ledger` through the brand_intelligence facade; level by fixed rule — 1 campaign =
   已觀察, ≥2 same-direction = 可能成立, 已驗證 needs a same-period comparison or ≥3 campaigns (a
   human tick also counts); `needs_revalidation` when older than 180 days or the source offering's
   price changed. Adopting a suggestion never writes a `rule` row — only the user's own typed
   feedback does.
8. **Confidence is a sample bucket (低／中／高), never a percentage**, and no model reads raw ad
   history (ADR 0067): evidence tables are program-computed.

### 6.1 Second round — 基座 (settled 2026-09-13, F04)

The visual source of truth for 投放中心 is now `docs/design/ads/01-home.png` … `10-strategy-advanced.png`
(01 首頁, 02 所有 Campaign, 03 建立投放計畫, 04 理解如下, 05 推薦策略, 06 Campaign 工作區總覽,
07 素材交接 = F05, 08 發布前檢查 = the 閉環 feature — F06 borrows only its warning band, §6.2 —
10 進階設定). `09-performance-overview-not-built.png` is
recorded as **not built**: suggestions live inside 投放中心, not behind a new nav item. Where an
image and the 09-12 prototype differ, the image wins; the prototype is history.

9. **One page, two depths.** Every screen shows the simple face by default — a recommendation, one
   primary button, an honest sentence — and the expert's knobs live in a collapsible *inside that
   same page*, closed until opened. Never a mode switch, never a second page, never a second data
   model (rows are the truth; simple and advanced are two projections of them), and never a layout
   that reads like another Meta/Google console.
10. **The judgment sentences are the program's, not the model's.** 一句整體判斷 (home), the
    per-campaign 一句判斷 (list, 總覽) and every 最近做了什麼 line are composed in
    `app/ads/judgment.py` from status, dates, budget progress and `ads_action` rows, shipped as
    text with the payload, and rendered verbatim by the browser (the §5.3 rule: text the user
    reads is produced once, by the side that owns the rule). No LLM call is made to write them,
    and a correlation is still never reported as a cause (§0).
11. **Two model calls per new Campaign, no third.** 建立投放計畫 parses the sentence
    (`ads_brief_parse`) into 商品／目標/平台／預算／時間／受眾方向 with a 數字優先 rule — a number
    in the sentence becomes that field, `null` only when the sentence has none — and 理解如下 is a
    confirm screen over those six editable field cards, each labelled 你說的 or 系統帶入
    (`context_json.field_sources`). Only 「產生策略建議」 spends the second call (`ads_strategy`).
    Editing a card is a `PATCH`, never a re-parse. Dates are optional input: when the sentence has
    none the system fills today…+30 天 and labels them 系統帶入. Parsed 預算上限 and 平台 live in
    the existing `constraints_json`; no column is added for them.
12. **「這輪想學到什麼」 ships with the strategy.** `strategy.md` returns `learning_goals[]`
    (≤3 sentences) next to `why[]` and `unknowns[]`, stored inside `budget_basis_json.strategy`,
    rendered as the strategy page's third column so F05's 結案 can answer it. 預估購買 =
    採用總額 ÷ 目標 CPA, captioned 推估（CPA 不變的算術）, computed in code, never 預估觸及.
13. **人工上架設定不等待自動發布（F09）**。策略頁進階區連到投放結構的「人工上架設定與平台對應」。
    既有「MarketingOS 為你執行中」仍為自動執行預留位置。人工紀錄規則見 §6.4，
    不新增 `ads_delivery_group.platform_settings_json`，也不代表自動 Meta 發布已接上。

14. **The strategy page's buttons do what they say.** 照這個方式進行 = adopt the recommended
    scenario if none is chosen, adopt the strategy, land on 投放結構 — one click from a newcomer's
    point of view. 調整建議 = edit the allocation percentages inline before adopting (sum 100, the
    program re-splits the money). 查看完整判斷 = the existing 查看策略依據 panel. The permanently
    disabled 採用 button is gone.

### 6.2 Third round — 工作區的快樂路徑 (settled 2026-09-14, F06)

Measured on a live campaign: after 策略 → 投放結構 the user did not know what to do next. The
next-step rule had one producer, rendered on 總覽 only, and its 「素材已就位」 target pointed at a
tab with no publish affordance; 投放結構 and 素材 ended with no next step, and the header's
發布 Campaign only printed 自動發布未接上 while the working paths hid in a ⋯ menu.

15. **One next-step rule, every tab.** `frontend/src/components/ads/nextStep.tsx::nextStep(campaign)`
    is the only producer of 「下一步」 in the Campaign workspace: 總覽's 下一步 card and 狀態時間軸,
    and the full-width primary button at the end of 策略／投放結構／素材／成效 all read it. Order:
    closed／live／ended → 成效; no strategy or no groups → 策略; groups but not a single ad →
    投放結構 (新增廣告); every ad ready → 發布; no pack yet → 投放結構 (開始做素材); pack dispatched
    but not every ad ready → 素材. A tab whose own step is the answer shows that step's in-place
    action instead, chosen by the step's `id` (策略 照這個方式進行, 投放結構 新增廣告／開始做素材,
    素材 前往素材工作檯). **It is navigation, not a judgment sentence** — decision 10 is unchanged:
    its output is a tab and a button label, its inputs are fields the server already ships
    (`budget_basis_json.strategy`, `groups`, `status`, `asset_readiness`), the tabs exist only in
    the browser, and its sentences name the step without judging the campaign or re-spelling a
    server rule (總覽's old next-step line 「投放已結束，7 天後自動結案…」 is replaced by the rule's
    sentence; 成效's own 結案 card is not a next step and keeps its copy). Whether a pack exists is
    a server fact read **from the pack itself** — `asset_readiness.pack_id` via `assets.pack_id()`,
    the same `pack_for_source` lookup `dispatch_pack` guards with — never derived from readiness
    rows (an ad added after the handoff has no set, so every row can be empty while the pack
    exists), never a second request, never a parsed 400.
16. **投放結構 stays on the newcomer path, in the strategy page's shape** (`05-strategy.png`). The
    default face is a plain summary of what the system built (投放組, 廣告, 每日合計, 投放期間),
    「不用改也可以」 and one full-width 「開始做素材 →」 that dispatches the pack (the existing
    `POST .../campaigns/{id}/pack`) and lands on 素材 — offered only while no pack exists, so the
    handoff never repeats; with no ad at all the button is 「新增廣告 →」 and opens the existing add
    dialog. An ad added after the handoff is not in the pack (adding sets to an existing pack is not
    built): 素材 says so on its row and the 素材已就位 tick makes it ready. The tree, the group／ad panels, add／delete
    and the budget comparison live in 「調整結構（進階）」, closed by default (decision 9). Inside
    it a blank group date reads 「跟活動同期間」 (blank already means the campaign's dates —
    `repository._budget_total`, `adapters/manual.py::_group_field`), 「儲存變更」 appears only
    while a panel has unsaved edits, and binding badges appear only once the campaign is published.
    Dispatching from 素材 is gone: the handoff has one button, on 投放結構; 素材 keeps its
    「查看素材任務包」 link.
17. **Readiness warns, never blocks** (F03's rule kept). The publish screen, for every adapter
    except 模擬發布, shows 「還有 N 則廣告沒有素材」 in the red band of `08-preflight.png` with
    「回到素材」; nothing is disabled. 模擬發布 is a drill and carries no warning. The band is
    composed inline on the publish screen; it becomes a shared pattern only when a second screen
    needs it.
18. **The auto-publish screen is not a dead sentence.** While auto publish is not connected it
    prints the adapter's own message verbatim and offers 手動發布 and 模擬發布（演練） as buttons
    (decision 1: "not connected", never a refusal). The header's ⋯ menu is gone — the publish
    screen is the one place the path is chosen.

### 6.3 Fourth round — image work and visual learning (settled 2026-09-15, F07)

Prompts do not rewrite themselves. What evolves is (a) the visual learnings the image-prompt call
reads — the slot plan and ≤5 lines (§5.9) — and (b) the image-task table, only by a
planner-reviewed edit once a learning is 已驗證. The traces that cannot be retrofitted ship with
F07: the fingerprint on every item (§5.7) and which item became the hero (the 選定 on its row).

19. **Visual learning is written at 結案, by fingerprint, inside one audience.** After the campaign
    learning, `closeout.close` groups the campaign's ads by `audience_key`. Only ads whose image set
    has an adopted row count — `workbench.adopted_output(...)["is_adopted"]` must be true, because
    that entry falls back to the latest round when nothing is selected, and a fallback is not a
    hero. Within one audience, for each of `look`, `device`, `layout`, `subject_role` and
    `persuasion` that has ≥2 distinct values, the ads are grouped by value. Each group's ad-level
    outcome rows go through `outcome._bucket`, the campaign's own success metric is applied (ROAS =
    the conservative value, §6 item 8), and `outcome.sample_bucket(purchases, days)` labels the
    sample. A group at 低 or with the metric untracked is listed, not compared.
    - Two or more comparable groups with a strict best → one row, scope
      `visual；audience=<audience_key>；<dimension>=<value_key>`.
    - Anything else → one row, scope `visual；audience=<audience_key>；<dimension>=看不出`, at
      `observed`.
    Confidence reuses §6 item 7's count: prior non-expired `visual` rows with the identical scope
    from other campaigns, plus this one — 1 `observed`, 2 `likely`, ≥3 `validated`; 看不出 is always
    `observed`. `needs_revalidation` follows the campaign learning's rule; readers also ignore rows
    learned more than 180 days ago.
    **A winner that later loses is downgraded.** When this campaign has a strict best B in one
    audience and dimension, every other compared value A that has non-expired prior rows with scope
    `…；<dimension>=A` loses its newest such row (`bi_repo.expire_learning`). Confidence is the
    stored value of the newest surviving row, so each contradicting campaign lowers A one step
    (validated → likely → observed, and below likely the image prompt stops reading it).
    The sentence is built by the program from labels — audience labels from
    `ads.repository.coordinate_vocabulary`, value labels from the fingerprint's own `{key, label}`.
    It names the numbers, counts and sample buckets, and says the result is a correlation, not a
    cause (§0). No model call. It is written through `record_learning(..., source_track="visual")`.
20. **Why inside one audience.** The image task is derived from the audience (§5.7). Comparing
    fingerprints across audiences would learn audience effects as look or layout effects, so the
    audience is the stratum and never a compared dimension.
    Not learned:
    - variants (one entity to Meta; small deltas are noise);
    - 自由創作 organic posts — no post-insights source exists, and PRODUCT.md forbids fabricated
      sources. Both are backlog entries.
    Early samples are mostly 低, so early rows are mostly 看不出. That is honest and is what the
    image prompt then does not read; the slot plan keeps exploring regardless.
21. **The dispatch decides the image work, the workbench renders it.** `app/ads/assets.py::_ad_set`
    sends, per ad, by `format_key`:
    - `single_image` (and a stored `flexible`): `required_outputs = {copy: 1, image_prompt: 1}` and
      `request.variant_count` = run days ≤7 → 3, 8–21 → 6, >21 → 9; +3 when the group's `role` is
      `retarget`; capped at 9. Run days come from the group's dates, else the campaign's
      (`plan._days`); no dates → 6.
    - `carousel`: `{copy: 1, image_prompt: 1}`, `variant_count` 0.
    - `video`: `{copy: 1, video_script: 1}` with `request.video_script_count` 3
      (`meta-format-specs.md` §3: 3 scripts per angle), no `image_prompt`. Script generation itself
      is unchanged (「影片廣告要產投放時需要的影片本體的腳本與資訊欄位的主要文案、說明、標題欄位(Meta來說)，
      和圖片廣告是一樣的邏輯」).
    No `style_key`, no `image_prompt_count`. The manual checklist's 圖片提示詞 is the adopted row's
    `body_json.text`, only when `is_adopted`.



### 6.4 瀏覽器稽核 P1：人工上架交接（F09）

- 每個 Campaign 的 `context_json.manual_delivery[group_id]` 保存該組的受眾來源與納入條件、
  回溯、排除、受眾 ID、版位、出價、優化事件、歸因、追蹤、落地頁、UTM 及上架後差異。
  原有投放組名稱、預算與日期是唯一來源，手動清單採用它們；不在設定另存一份。
- 平台活動／投放組 ID 與廣告 ID 對應是手動紀錄，不能冒充 `external_id` 綁定、平台已存在或已同步。
  廣告對應僅接受該投放組的廣告；品牌、組織、Campaign、投放組必須同屬。結案後不可改寫。
- 欄位可先部分保存；缺漏顯示待補，再行銷額外要求受眾 ID。欄位填齊只代表「資料已填齊，待平台核對」，
  不是系統已驗證受眾池存在或可投放。缺漏與完整紀錄一起進入既有人工發布清單。
- 不對外寫入、不呼叫模型、不改變預算或發布／同步狀態。本輪不擴充模擬回收、正式 CSV 匯入或自動發布。

### 6.5 P2 操作保護（F10）

- 新計畫未提交內容以使用者、組織、品牌為鍵保留在目前瀏覽器分頁的 sessionStorage；無儲存權限時退回記憶體。包含目標、日期、已展開限制及其值；成功建立後清除，失敗保留。這是本機草稿，不是已建立的 Campaign，不跨裝置。
- 上架入口標「選擇上架方式」。手動清單開頁只讀；「確認並記錄手動上架準備」才呼叫既有 manual publish，記錄意圖與目前預算核准上限。確認前顯示期間、每日／期間預算及不會寫入平台帳戶或花費的後果；不宣稱已上線。配對仍沿用既有規則。
- 切換品牌回相同區域列表，捨棄原品牌的資源 ID 與篩選；智庫只保留分類 tab。建檔流程則回新品牌概況。
- 使用者於 2026-09-18 選定「隔離模擬入口」作為後半循環驗收方向；先複用既有模擬通路，補足正常 UI 回收、來源標示與測試品牌隔離，不擴為正式人工／CSV 回收。A/B 設計應在回收與學習可驗證後依實測缺口定案，不在 F10 五項操作修復內。

### 6.6 隔離模擬回收（F11）

- 使用者選定本機隔離模擬入口，僅供測試品牌；啟用需明確確認永久隔離，以組織設定保存品牌標記。已有真實帳戶、平台綁定或成效的品牌不能啟用；隔離後禁止手動平台配對與真實回收。不對外投放、不呼叫付費模型。
- 成效頁按活動的實際廣告 ID 逐日填五項指標。只接受每日增量，整日快照取代；重送不累加，版本衝突要求重讀。缺回收的廣告不寫零，真零需明填；初版不支援個別指標缺值。每次修正記錄最新版本、時間與操作者。
- 啟用綁定模擬 ID，但不自動產生隨機成效。既有示意成效不能混入此入口；另建活動演練。
- 結案凍結回收與來源收據；缺日／缺廣告判「看不出」，不建立視覺優勝學習。完整數字沿用既有判讀，文字學習持續標明「隔離模擬，非市場實證」，只供同品牌下一輪讀取。
- 這是後半循環的本機驗收入口，不是正式人工／CSV 匯入，也不代表真實平台成效驗證。

### 6.7 系統比較提案與使用者確認（F11；介面分層及參數契約以 F12 §6.8 為準）

- 成效頁在上架前也可查看「單一變因比較計畫」。只選同投放組、同受眾、同商品，六項非受眾座標恰好一項不同的兩則現有廣告；缺少對照時導回投放結構，不自動造素材或改預算。
- 提案列假設、A/B 廣告及唯一變因、共同條件、活動指標、共同觀察窗、停止及判讀門檻。初版採至少 7 天、兩則各日齊全、各 10 次轉換，相對差異（差值／兩值較大者）至少 10%。這是明示的操作門檻，不是統計顯著性檢定。
- 使用者先核對實際素材及共同投放條件，再按確認。只在確認時保存於活動 context，含確認者、時間、結構／素材／手動設定快照指紋。條件變更會過期，舊指紋拒收；重新確認覆寫目前計畫。已有成效後確認標「事後觀察」，不冒稱事前實驗。
- 預算觸頂、觀察窗未完成、缺日、樣本不足、真實平台轉換未追蹤或計畫過期都判「看不出」。符合操作門檻才標「觀察到差異」。每日預算停止條件只停止判優劣，不操作外部平台。
- 同組不等於隨機分流或平均花費；設定相同不證明實際素材只改一處。初版明示這些限制，由使用者核對。模擬比較只驗證流程，不宣稱市場優勝、因果或統計顯著。

### 6.8 一般／進階與可選比較（F12，已實作）

保留建立、需求確認、策略採用、派工、選定、上架準備順序。一般層只精簡資訊，不自動代替核准。完整推理／學習目標與配置在同頁詳情；必要預算、日期、未知、缺漏仍直接顯示。沿 channels／adapter 的真實資料顯示平台，既有平台專屬能力不冒充全平台。Full auto 與新平台整合不在本輪。

手動準備清單可呈現既有 channels 的平台資料；目前 manual adapter 的配對仍是 Meta 專屬。介面明示此限制，非 Meta、未連線或連線未知不提供配對動作；這不是新增其他平台的配對能力。

**比較屬於選用功能。** 未使用僅有入口，不先讀完整提案；展開是唯讀，不等於啟用或確認。已有確認顯示簡短結果。缺對照只在比較內提供補充路徑，不加入主流程阻擋。一般卡包含 A/B 內容、唯一變因、觀察期間、結果與限制；公式、ID、快照在詳情。人工核對實際素材與共同條件仍是明確動作，不由系統代勾。

**所有者與統一接口：** 沿既有 `/api/ads/brands/{brand_id}/campaigns/{campaign_id}/comparison`（實際 router prefix 與現有 client BASE 一致），GET/POST 不改語意；新增 PUT 保存設定。僅 `app/ads/experiments.py` 管理有效值、驗證與判讀，routes 只作身份／輸入邊界；前端只透過 `frontend/src/lib/adsExperimentApi.ts`。不直接讀別的模組表，不加跨模組依賴或 schema。

- GET `settings` 形狀：`{revision: string, scope: "campaign", defaults, effective, overrides, customized: string[]}`。四項可調鍵為 `min_days`、`min_conversions_each`、`relative_difference`、`window`；`window` 為 `{start,end}`。未設定的 defaults 來自既有規則與共同投放期間；既有初版 7／10／0.10 作為明示預設，不散落 UI，不宣稱自動算出統計樣本。值不以平台為判斷分支。
- PUT 輸入 `{revision: string, overrides: {...}}` 是整份 overrides replacement；省略鍵代表恢復該項系統預設，前端單項還原時保留其他鍵。只允許四項，未知鍵拒絕。回應與 GET 同形；POST 維持 fingerprint／controls_checked 確認。
- `min_days`／`min_conversions_each` 為正整數，前者不得超過有效觀察窗日數；差異是有限數字且 `0 < value <= 1`；日期為有效 ISO 日期且不超出共同投放期間。若原期間不足預設天數，允許讀取原提案並顯示不能判讀；明確自訂則驗證一致性。相同有效值不得憑來源標籤就改變實驗指紋。
- 保存於 ads 自有 `ads_campaign.context_json.comparison_settings`：`overrides`、遞增版本、更新人／時間；用 row lock 與 revision 拒絕過期保存（409），保留 context 其他鍵。GET 無寫入。無 schema migration；保存不觸發生成、預算修改、平台操作或確認。已結案只讀。
- 提案文字、快照、fingerprint 與 judge 全部使用同份 effective。舊 `comparison_plan.rules` 保留原形狀並兼容舊 `min_purchases_each`，公開參數轉為一般語意；未自訂且原資料未變的舊計畫不因部署而失效。設定改變且影響有效條件時要求重確認，保留目前已存確認至新確認；原設定恢復且指紋相同可復用原確認。
- 指標取自活動既有 success_metric 與成效投影；未支援或未追蹤回傳不可判讀，不以購買數代替未知指標。真實來源、缺日、預算停止條件、非隨機、事後觀察、模擬限制全部保留。判讀與參數操作不呼叫 LLM。

**內部驗收入口：** 一般成效頁不掛載模擬回收、不顯示停用原因；只在既有 `campaign.simulation_mode` 已隔離品牌的進階區提供。初次隔離由內部本機 fixture／既有 API 經原 eligibility 與明確確認完成，不依品牌名稱、不在普通 UI 提供轉換入口。移除普通上架頁並列模擬選項，保留 adapter 與伺服器限制。不得僅以 DOM 隱藏宣稱建立權限隔離。

驗證包含契約、租戶／品牌、closed、revision、舊快照、非預設判讀與零 LLM 呼叫；UI 測試覆蓋比較未使用主流程仍可完成、進階設定回讀、生效值與判讀一致。

### 6.9 既有活動與自帶成品（F13，已實作／人工驗收保留）

本節承接 [近期工程交接](../backlog/engineering-existing-campaigns-user-assets.md)。使用者於
2026-09-18 呼叫 crank 核准 F13 計畫，並確認下方 Codex CLI 的用量限制例外。
以下記錄本期實作；大型重構或原範圍的重大改變仍須停止並回主對話。
本節只限定既有活動／自帶成品路徑，不重寫一般策略生成及 F07 的圖片提示詞規則。

#### 6.9.1 所有權與狀態

- 保留一個 ads_campaign 作為品牌工作區。新增 origin=internal/imported（舊列為 internal）；
  imported 的目標、成功指標、日期允許未知，不填造假的 CPA／日期以通過既有建立流程。
  平台原生目標留在來源快照，不直接當內部成功指標。內部活動的現有必填 API 規則不放寬。
- ads 擁有 ads_external_entity：org、brand、campaign、platform、source_account、native_id、
  parent_native_id、native_kind、native_label、name、原生預算／日期／狀態與欄位可用性、
  creative 摘要及 last_success_at、last_attempt_at、sync_status。唯一鍵為
  (org,brand,platform,source_account,native_kind,native_id)，父子及帳號關聯須同租戶同品牌。
  這是掛在同一 Campaign 的外部來源紀錄，不是另一套可修改投放計畫。
- 匯入不替外部節點偽造 ads_delivery_group.daily_budget 或 new/retarget 身分，不將平台
  階層轉成固定三層。外部結構直接用 parent 關係呈現；內部安排引用外部目的節點。
  平台預算保留掛載節點、daily/lifetime/unknown、金額、幣別及來源，不由日預算反推總額。
- ads_external_daily 保存同一外部節點的按日來源觀測，唯一鍵加 day、metric scope／
  attribution key；數值 nullable 並帶 available/unknown/unavailable。不同幣別、層级、
  歸因窗不得相加。目前呈現各層原始觀測，不自動跨層彙總；imported 的舊活動小計保持未知。
  無資料不補零，亦不把父子層的數值重複計入。
  Meta 資料仍透過 meta 公開 facade 讀取；ads 不查寫 meta 表。
  不把這份原生觀測灌進舊 outcome 的 purchases=0 路徑，也不另修完整 RC-D／結案學習。
- imported 不進自動結案、舊 freeze、策略自動重建及模擬發布；內部工作區狀態與平台狀態
  分開，平台暫停／日期已過不關閉工作區。未確認成功條件顯示待補，不強迫先補才能查看。
  防護須同時在 API、排程與前端，不能只藏按鈕。一般 internal 活動維持現有行為。
- 新表皆為 ads_*、具租戶隔離與品牌清理；原檔用 app.storage 公開入口，品牌事實透過
  brand_intelligence facade，背景工作由 ads.register_tasks 登記。文案承諾檢查僅透過
  workbench 公開的唯讀 validate_claims 入口，先核對 org／brand／product 歸屬；
  不改工作檯內部驗證程式，不新增跨模組 SQL。所有權見 ARCHITECTURE.md 的 ads manifest。

#### 6.9.1a 共用前端工作區（F14）

- 納入視窗不變；匯入後與 internal 共用同一 URL、五個分頁及原有元件，移除 imported 專用面板分流。首頁沿用 Campaign 卡片區，不再另列專用面板。
- Workspace 讀完 external 的兩組分頁後，將原生資料交給原總覽、策略、結構、素材、成效。頁面讀取不新增平台請求；「重新讀取平台」沿用既有同步工作。
- 原結構樹与明細以來源 ID 呈現唯讀節點，不建立假的 internal group/ad；原生預算缺值顯示未知，不換算 raw 或用日預算推總額。
- 原成效元件按層級、幣別、歸因選取單一範圍，保留 null；不虛構保守／樂觀值或完整涵蓋率。原生狀態與內部流程分開呈現。
- 策略分頁保留原版型、目標與成功條件編輯；不支援的策略／預算／發布／結案動作如實限制。自帶素材仍走原 revision/confirm/handoff，與內部 readiness、平台上架各自獨立。
- 此次只改前端接線；API guard、同步、儲存及 Meta 零寫入邊界不變。

#### 6.9.2 平台讀取與同步

- 通路能力入口提供 list_existing、read_structure、read_creatives、read_observations，
  接受經伺服器驗證的品牌綁定來源帳號，回傳能力／缺漏與分頁游標。Meta 實作放 adapters，
  Graph 呼叫留 app.meta.graph；不可把 token、外部任意 URL 或平台名稱規則放共用核心。
- 開啟「加入既有活動」先呈現快取並自動排刷新；選取後依原生鍵冪等納入，不呼叫 LLM。
  清單含暫停及無花費活動。初次讀成效預設近 30 天，可按日期分批補讀，僅到來源允許範圍。
- 已納入者每日更新，頁面可手動刷新；同帳號工作合併、同時最多一個，單批 100 節點，
  續跑保存游標。API 對頁面立即回 job id，由背景 worker 執行；不是每次 GET 同步整個帳號。
- 結構、素材、成效各自記成功時間／錯誤／覆蓋範圍。分頁或部分物件失敗只提交完整成功
  子批，保留舊紀錄；未返回、權限不足及不支援各自標示，不推論刪除或停投。
  只接受平台明確回覆的原生狀態；重新同步可恢復，重試不重建節點。
- Meta 首期讀一般單圖、影片、輪播能取得的文字與媒體參照；動態／商品目錄素材保留
  類型和可讀原始摘要、標「無法完整還原」，不拼造一張代表成品。縮圖不是影片原檔。
  實際讀回已確認一筆動態廣告及其廣告組／活動父鏈與帳號時區。這不代表所有帳號／類型都有權限，
  影片原檔、媒體等價及連續版本歷史仍未取得；其餘分支的 fixture 證據另列。
  預算原始數值保持平台格式，換算規則見 §6.12；沒有可靠幣別換算分母時，金額標未知，不推造換算值。
- 只有平台 GET；無 CSV 備援、無建立／停投／續跑／改預算 API。解除帳號綁定後拒絕新讀取，
  舊資料保留並標連線已解除，不跨品牌重新授權。

#### 6.9.3 原檔、安排及補文案

- ads_user_asset 保存品牌原檔與 SHA-256、MIME、尺寸／時長、縮圖 key、處理狀態；
  ads_asset_placement 連到 Campaign、asset、版本、必用旗標、已有文案、建議文案、
  建議目的節點／用途／日期、unknowns、確認者與修訂號。建立前可保存品牌暫存素材，
  建立 Campaign 後明確掛入；未掛入仍可找回，不能只有瀏覽器記憶體。
- 每次最多 10 檔、並行上傳 2 檔、單檔沿用 Storage 50 MiB 上限，可分批繼續；
  描述 JSON 上限 64 KiB，介面同時按 10 檔與約 60 KiB UTF-8 大小拆批，原文不截斷。
  支援 JPEG/PNG/WebP 圖片與 MP4/MOV 影片。以內容探測格式，不信副檔名；FFprobe／FFmpeg
  執行受限時長、無 shell 字串拼接，產縮圖與必要的瀏覽器預覽，原檔不覆寫。
  影片衍生預覽為最多前 15 秒、720p／30fps 的 H.264／AAC；下載仍取得完整原檔。
  大小超限／損毀逐檔回報，永久解碼錯誤不自動重試；暫時失敗最多重試三次。
  工具缺失則處理標待重試，不能聲稱尺寸或預覽已完成。
- 同品牌同 hash 共用原檔，不跨品牌查重；同 Campaign 重傳不重複建立必用安排，
  不同 Campaign 可各自引用。同檔不同文案是不同版本；修改已確認內容撤銷該版本確認，
  舊確認及對應證據保留。Storage 與 DB 失敗有補償／可重試，不遺失成功的其他檔。
- 每件必用素材皆須有可確認安排或明確待處理原因；批次上限、預算不足、資料缺漏只讓它
  留在待處理清單，不將必用改可選。安排可分批確認，不保證曝光或花費。
- 原文逐欄沿用，系統只補缺欄；既有文案若有未核實承諾另標待確認，不偷改原文。
  缺少內容理解時只用已知品牌／活動事實寫投放文案，不描述未看懂的畫面或影片情節。
  第一版不要求視覺模型掃描：可使用使用者選填的整批說明及有限文字摘要，
  明示 image/video 未分析；未來視覺判讀不在本票偷偷追加。
- 一批最多 10 個安排、1 次模型呼叫、最多 12,000 字元整理輸入；支援硬限制的 API 最多 4,096 output tokens；
  超出保留剩餘待處理。模型只補文案與建議用途，程式核對每個必用 ID 有結果，
  計算日期／排序／預算，不自行改平台或已採用配置。不要求使用者填座標。
- **2026-09-18 使用者確認的 Codex CLI 例外**：保留現行線路，不自行切換模型；完整整理輸入最多 12,000 Unicode 字元、執行最多 120 秒、單次呼叫、不自動重試，回傳後最多接受 16,384 字元。此線路不能強制生成 token 上限，不能把回傳後檢查宣稱為生成用量硬限制；零 API 美元費用仍會消耗訂閱額度。以下付費 API 費用護欄維持。
- 經既有 gateway／事實與禁語驗證，未知標記跟著輸出；相同輸入 hash＋版本重用成功結果。
  單批美元費用上限為 US$0.50，並檢查既有組織剩餘上限；呼叫前按已知模型的完整 context window
  與最大輸出估算保守費用，再預留。沒有可靠上界或上界超限就拒絕，不自動換模型。
  F13 批次共享組織預留鎖；已知失敗費用仍計入，未知結果保留預留。這不代表所有舊功能
  已共享同一套嚴格並行費用鎖。失敗不自動重送，執行超過十分鐘標 unknown，不直接釋出額度。
  這是產品護欄，非本輪付費測試授權。
- 補充文案須能逐字追溯品牌來源或中立 CTA，並通過禁語與既有優惠／背書承諾檢查；
  這是保守驗證，不能當作完整語意正確保證。可完全不呼叫模型，填妥文案後用 batch_id=null
  做手動檢查與確認。執行中、失敗及未確認建議批次皆可從清單重開。
- 一般 UI 為待安排 → 待確認 → 待手動上架 → 平台已確認，處理中／失敗另列原因。
  使用者確認只記錄內部決定；「我已上架」只記自述。已有文案與自帶成品不再被強制送去
  產圖／腳本；未使用自帶素材的一般工作檯派工維持 F07。

#### 6.9.4 手動上架與版本對應

- 每個確認版本提供原檔下載、原／補齊文案、建議用途、目的活動與可複製的版本追蹤名稱。
  名稱只供找候選；不靠名稱、缩圖相似或本機 hash 自動證明平台素材相同。
- ads_asset_binding 保存 placement revision、來源帳號／原生廣告 ID、觀測到的 creative
  版本摘要、確認來源／時間、有效區間與失效原因。同一平台廣告在相同時間只准對應
  一個已確認的安排版本。多素材動態廣告不能拆成各素材各自的成效。
- 使用者從已讀回的同品牌同帳號廣告候選選定，後端重新讀該廣告及父層並核對範圍，
  才能標「平台已確認：廣告存在」。讀不到則仍待確認，不能用自述代替。
  另列「素材版本：使用者核對／平台可驗證／無法核對」，不把廣告存在等同成品完全一致。
- 素材版本成效只納入能證明對應的廣告版本與觀測期間；沒有可靠媒體／creative 對應、
  首次同步前歷史、一天內版本混用或多素材不可拆時，顯示「無法分到此素材版本」。
  廣告本身的原始成效仍可查看，不能全灌給新素材，也不回寫 F07 視覺學習。
- creative 摘要變更、跨帳號、重複占用、使用者改文案／原檔時重新核對；
  明確只改平台狀態不抹除歷史證據。同步失敗保留上次確認並標過期。
  歷史版本與已結案活動仍可明確結束既有對應，解除後續安排的占用。
  兩次相同快照或使用者自述都不是連續歷史；歸屬還需平台媒體／文案等價、完整已過日期、
  時區、有效區間及連續版本證據。同一原生觀測不可重複領取。

#### 6.9.5 介面與驗證

沿用 Campaign 工作區／素材頁與同頁進階區；列表提供「加入既有活動」。
新建流程與既有 Campaign 均可批次加入自帶素材，不能被「還沒有廣告」空畫面截斷。
總覽優先呈現來源、更新時間、缺漏、下一步；原生結構與參數收在進階區。
最近成功時間取同步分區已保存的時間，並保留節點時間作補充；分區錯誤與覆蓋範圍分開顯示。
建立活動後若部分素材加入失敗，保留已建立活動 ID 供重試／重開，不重建活動。
文案版本衝突保留本機編輯供使用者明確處理；一般連結、工作區分頁及關頁有未存內容提示。
整合必須包含暫停／無花費、活動層 lifetime 預算、未知指標、分頁部分失敗、重複同步、
跨品牌拒絕、批次檔案重開、混合影片／圖片、必用未漏、修改撤回確認、版本衝突及零平台寫入。
測試 fixture 證明分支，平台實讀另報帳號能力；兩者不能混稱。
詳見 F13 票序與 [驗證指引](../verification.md)，不要求真實投放。

#### 6.9.6 變更清單與每月品牌總額

- `ads_change_set` 保存不可變的核准快照；`content_hash` 是內容指紋，
  `operation_id` 是一次提交的識別。同識別同內容重送讀回原紀錄，異內容拒絕。
  核准、既有 `approval` 與逐項 `ads_action` 在同一交易完成；舊 action 維持 legacy 證據，
  不回填成平台已確認。修改建立新清單，保留舊核准及其快照。
- 文案、預算、暫停分別保存相關設定前提；一般同步時間不列入指紋。
  已核准的未執行動作先讀回目前設定才能安全重新規劃；結果未知不能假定尚未執行。
  回報完成與平台核對分開；每項可為待操作、已回報、設定相符、偏離、失效或未知。
  每次讀回有獨立識別，遲到回應不覆蓋較新核對。設定相符不代表投遞、素材等價、
  足夠成效或因果改善；可證明生效時間未知時保留未知。
- `ads_month_budget` 是使用者確認的品牌／月份／幣別總額，节慶包含其中。
  程式計算已知花費、至月底的持續投放預估與已核准增額差額；降額未讀回不釋額，
  相同預算來源不重複加總。缺少帳戶完整月花費覆蓋、歸屬、時區或預算單位時，
  餘額維持不確定，阻止新增花費核准，但仍可檢視、補資料及核准降低風險的操作。
  這是本地提醒／核准前檢查，不是平台限額或自動停花保證。
- 首次投放沿用人工交接入口、內容核准與防重；逐層對應與新增廣告以
  `ads_handoff_item` 保存每項預期設定和讀回證據，平台操作由使用者完成。
- 帳戶月花費按活動／日期分頁讀取，保存月份、帳戶幣別／時區、開始與完整完成時間。
  未歸屬、跨品牌或分頁途中才匯入的活動不當成零花費；需完整重讀確認歸屬。
  月底後保存完整歷史月；持續投放估計仍需已確認預算單位，不能只因取得花費就顯示確定餘額。

#### 6.9.7 單則廣告檢討與商城證據

- `ads_review_round` 連到既有來源廣告、活動及可選前回；保存觀察期間、不可變證據包、
  指紋、gateway 任務、建議及人工決策。`ads_change_set.plan_json` 保留檢討／建議關聯，
  並納入核准內容指紋；下一回讀回這些清單各項實際結果，不以檢討完成代替操作完成。
- 觀察單位是單一平台 ad；前後期按來源、歸因口徑與幣別分開計算，不合併未知值。
  最多 31 個完整日，來源帳戶時區未知就標未知。素材歷史不完整或混合期間不能歸因給
  圖片／文案；下一輪假設可由商城反證、資料不足或實際操作偏差而改變。
- 商務資料沿用 `orders.review_evidence` 公開彙整接口，限定組織、品牌及日期；
  讀既有訂單／退款及通路報表，不把訂單鏡像通路重複加總。明確付款、未付款、
  未知付款與作廢分列，未知金額不補零。舊匯入固定儲存 TWD 不等於來源已證實幣別，
  完整期間覆蓋亦未證實；日期依訂單日，退款不冒充實際退款日現金流。
  商城證據是品牌層級，不分配為單則廣告營收；沒有可核對來源就不宣稱真實 ROAS。
- AI 收整理後的前後期指標、品牌必要背景、商城對照、缺漏、前回建議與操作證據，
  不收訂單逐列或顧客資料。沿用 gateway 與現有供應商，單回一次、零自動重試、
  最多 12,000 字元輸入、4,096 output tokens（Codex CLI 例外沿 6.9.3）、120 秒。
  超量拒絕並請縮小期間，不截斷反證。gateway 保存可取得的用量／費用／耗時。
- 相同有意義證據重用既有回合；純匯入刷新時間不改指紋，實際值與操作證據變更會改。
  缺目標或沒有已知投放樣本先保存待補狀態，不呼叫 AI。模型輸出需對應原廣告及證據，
  通過格式、因果斷言與文案來源檢查；其保守檢查不是完整語意正確保證。
- 前台從成效頁檢討、保留圖片只改文案、核准清單、人工回報及逐項讀回；
  可完成本回、延後至明確時間或記錄無法判定與處理出口，不改活動生命週期。
  持久請求由既有 worker 執行；定期觸發、重看條件與恢復見 6.9.9。
  隔離替身的兩期資料及假模型不冒充真實平台改善。


#### 6.9.8 素材需求與逐項人工交接

- 冷啟動入口沿用建檔與首次計畫；既有廣告從匯入活動工作區進入。素材頁提供已有成品、
  外部生圖回收、工作台圖片提示詞、獨立文案四條路徑，不以生圖當所有任務的前置條件。
  `ads_material_task`／`ads_material_revision` 保存需求及歷史，`ads_material_operation`
  分開保存同次操作識別與請求指紋；回應遺失沿用同操作重試，內容不同拒絕。
- 原檔沿用 `ads_user_asset`；每批最多十張候選，各自保存提示詞與參考圖。工作台來源由
  公開接口讀回精確版本，手動修改另列手動來源；未知來源保持未知。選定成品沿用
  `ads_asset_placement`，不複製另一套素材庫。版本修訂保留原候選與實際採用版本的差異。
- 明確交棒後才用既有工作台任務包及 gateway；單純保存、上傳、選圖、切頁不呼叫 AI。
  檢討建議交棒時攜帶原回合、建議、待驗假設和證據來源；下一回仍可反駁，不能視為結論。
- 內部計畫 `ads_ad.material_placement_id/revision` 指向使用者明確選定的已確認成品。
  素材內容、文案及檔案指紋進入首次投放快照，版本過期須重新指定；未指定保持未知。
  不刪除重建既有計畫廣告來配合素材。
- `ads_handoff_item` 將首次投放的活動／投放組／廣告及新增 B2 分開核對；新增 B2
  使用已知、持續投放且預算可確認的父層，不暗中暫停原 B 或額外建立預算。
  原 B 的暫停／降額仍是獨立核准項目。來源廣告、原生父層、帳號與品牌均須讀回相符。
- 自述完成、首次觀測、設定相符、素材身分與實際投遞分開保存。讀取失敗只有嘗試時間，
  不產生首次觀測。未知結果或外部仍 ACTIVE 不可直接撤掉原交接再建立另一則；重新規劃
  前先讀回原對象狀態，保留失效理由和舊核准。舊版名稱配對僅作歷史／進階工具。
- C 的 HTTP／瀏覽器隔離驗收使用平台及模型替身；不代表真 Meta 發布或真實營收改善。
  共用連線池的非同步借還必須允許十張預覽並行與頁面重新讀取，不能靠擴大池容量通過。


#### 6.9.9 持續追蹤與背景恢復

- 沿用 Postgres／procrastinate 與獨立 `app.worker`，不依靠頁面計時器。每分鐘派送到期檢討；
  已對應活動每十五分鐘檢視健康與有限逐項讀回，來源帳戶每六小時補讀。共用帳戶合併各活動
  所需前後觀察窗，單段最多三十一日，保留分頁游標／代次；斷線也保存退避時間。
- 首次明確提交檢討才建立 `ads_review_monitor`，預設七個完整日期／七日重看，可同頁修改、
  暫停與恢復。完成本回／暫緩不停止活動；停用自動判讀亦不停止來源、月額、期限與待辦追蹤。
  原每日日期到期 handler 保留相容名稱，但不再自動結案活動或生成結案學習。
- 固定未完成觀察窗，資料未實質改變不重複呼叫模型；缺時區、日期、來源或投放樣本時，
  保存原因並等補回。模型失敗／結果未知停在需要處理，不自動重付費；使用者可檢視、調整
  追蹤條件或明確再提交檢討。背景啟動／最近檢查時間是觀測，不能推造停機開始時間。
- 新 B2 透過既有核准清單／交接項、素材修訂及原建議承接 `source_review`；繼承原 B
  的追蹤條件。首窗從首次觀測之後的完整來源日期開始；原 B 的歷史不能冒充 B2 前期。
  首窗完整而 B2 尚無前期時可提出有限判讀，明示不可比較；後續回合仍須檢查前後期。
- worker 取得既有唯一鎖後恢復精確允許的唯讀任務；中斷的同步續原游標，人工中止不重跑。
  已保存且證據指紋／品牌／任務類型相符的 AI 結果可重新掛回；排隊記錄與佇列間隙可補排。
  不確定是否已呼叫模型者保留 unknown／費用預留，不以重新請求掩蓋回應遺失。
  gateway 只將明確標示由 worker 執行的任務判定為 worker 中斷，不誤傷前台直接請求。
- 啟動器只對自己啟動而異常退出的 worker 有上限重啟；單次最多十批、每批一百筆恢復，
  超量會記錄尚待恢復，不宣稱無上限恢復或服務可在關機後繼續。詳見
  [Windows 啟動](../boot-autostart.md)。
- 讀回失敗逐項保存本次未知與輪轉時間，保留過去觀測；一筆失敗不阻塞其餘項目。
  一般同步時間不讓核准失效；相關設定競態需重審，不相關父層更新只待再讀，不覆寫較新資料。
  平台存在、設定相符、素材等價、開始投遞及足夠成效仍是不同證據。
- 本地驗證使用真 Postgres 佇列與獨立 worker，但外部平台與模型是隔離替身；商務對照
  沿用品牌訂單證據，不把兩回流程成功描述為真實營收或因果改善。

### 6.10 F16-I01 — 成效追蹤欄位可為空值（settled 2026-09-20，ruling RC-D 第一階段）

- `ads_outcome_daily.purchases`／`revenue` 從 `NOT NULL DEFAULT 0` 改為可空
  （`supabase/migrations/20260920000001_ads_outcome_nullable.sql`）：`NULL` 表示未追蹤、`0`
  表示真的是零，兩者不再共用同一個位元。`ingest_meta` 對 Meta 來源列一律寫 `purchases=NULL`；
  `revenue` 有 `roas` 才算得出數字，否則也是 `NULL`。第一支 migration 本身不改寫任何舊列；
  接續的第二支 migration `20260920000002_ads_outcome_legacy_meta_unknown.sql` 把「F16 之前、
  `ingest_meta` 對每一筆 Meta 來源列無條件寫入」的舊 `purchases=0`／`revenue=0` 字面值正規化
  成 `NULL`——這些字面值從來沒有代表過一次真的觀測，正規化只是把讀者原本靠
  `source == 'meta'` 猜出來的「未追蹤」還原成欄位本身誠實的 `NULL`，不是回填真資料，也不會
  改變任何現有讀者今天算出來的結果。
- 讀者（`outcome._bucket`、`repository._outcome_totals`、`repository.budget_history`、
  `experiments.judge`）一律用「這欄是不是 `NULL`」判斷追蹤與否，不再用 `source == 'meta'`
  或 `revenue != 0` 這類猜測性 sentinel；`closeout.close()`／`_judge()` 本來就正確處理
  `None`，這次沒有改動判讀邏輯本身。
- 這一票之後真實 Meta 活動的 `purchases` 仍然恆為 `NULL`（結案仍判「看不出」）；讓
  `daily_entity_spend` 真的吐出購買數是 F16-I05 的範圍，見 §6.11。

### 6.11 F16-I05 — 真實 Meta 購買數接上結案判讀（settled 2026-09-20）

- `app/meta/repository.py::daily_entity_spend`（facade 新增，非 refactor）多回四欄：
  `purchases`／`revenue`／`action_type`／`attribution_window`。沒有新讀取——
  `meta_entity_spend.actions`／`action_values`／`attribution_window` 是既有每日拉取早就存好
  的欄位，這次只是也選出來；同義字判定整段沿用 `external_purchase_values()`（`purchase` 目標
  的唯一定義是 `graph._ROAS_ACTION_PRIORITY`），`app/ads/**` 沒有另外維護第二份同義字清單。
  `(spend_date, entity_id, currency)` 一個 group 內任何一個 physical row 沒追蹤到購買，整組
  就是 `NULL`（跟 `roas`／`cpa` 同一條 all-or-nothing 誠實規則）——未追蹤永遠不是 0。
- `ingest_meta`（`app/ads/outcome.py`）改寫 `purchases`：`NULL`（列沒有任何購買同義字）／
  `0`（追蹤到真的零）／真的數字，三選一，不再對 Meta 來源列一律寫 `NULL`。`revenue` 只認
  `action_values`——不再從 `roas` 反推（`revenue = spend * roas` 這行整個刪掉）：`roas` 是
  Meta 自己算的比率，`action_values` 是跟 `purchases` 同一個 action_type 配對的原始金額，
  兩者都用會依當天哪個先追蹤到而悄悄換來源，讓同一支活動的 CPA／ROAS 失去一致的定義。
  `action_type`／`attribution_window` 隨號碼一起從 facade 回來（跟
  `app/ads/adapters/meta_read.py:observation()` 對外部活動已經在用的 `attribution_key`／
  `action_type` 同一種形狀）；`ads_outcome_daily` 沒有欄位可以逐列存這個歸因說明——這是讀寫
  變更，不是 schema 變更（沒有新 migration），所以目前只在 ingest 當下的記憶體裡看得到、寫進
  程式註解，還沒有持久化到資料庫；要逐列留存需要另開一張票加欄位。
- 沒有雙重計算：`ads_campaign.origin` 是單一開關，一個 Campaign 只會走其中一條路徑，不會兩條
  都寫。`origin != 'imported'`（內部 Campaign）由 `POST .../ingest` 呼叫 `outcome.ingest_meta`，
  從本模組每日排程已經拉好的 `meta_entity_spend` 灌 `ads_outcome_daily`（campaign/adset/ad
  三層都有，不即時打 Graph API）。`origin == 'imported'`（自帶／既有活動）完全不會進到
  `outcome.ingest_meta`／`ads_outcome_daily`——`routes.py` 對這類 Campaign 直接回
  `external_view`，成效由 `external_sync` 另外直接呼叫 Graph API 灌 `ads_external_daily`，兩張
  表、兩條讀寫路徑不相交；額外一層保護是 `ingest_meta` 內的 `_conflicting_campaigns`：同一個
  平台實體（`ads_delivery_group`／`ads_ad`）綁到兩個不同 Campaign 一律拒絕，不會有一筆 Meta
  花費被算給兩個不同 Campaign。
- 「活動過了結束日 7 天自動結案」是三處過期敘述，這次改成文字，行為本來就沒有這回事
  （`app/ads/jobs.py::close_expired_campaigns` 早就只排監控、從不自己結案）：
  `app/main.py:454`（註解）、`app/ads/__init__.py:63`（docstring）、
  `frontend/src/lib/adsApi.ts:726`（JSDoc）。
- 驗證：`app/tests/test_meta_daily_spend.py::DailyEntitySpendPurchasesTest`（facade 本身，
  真實 jsonb 形狀）、`app/tests/test_ads_outcome.py`（`ingest_meta` 寫入 NULL／0／真數字三種
  情境，`RealMetaPurchasesReachCloseoutTest` 端到端驗真實購買數能通過樣本門檻判「達成」／
  「未達成」）。

### 6.12 F16-I02 — Meta 預算換算成帳戶幣別真實金額（settled 2026-09-20）

- 換算歸屬 ads 自有 adapter：`app/ads/adapters/meta_read.py::_budget_minor_unit_amount()`，在
  `_entity()` 組好 `budget_raw` 之後就地換算；`app/meta/**` 是舊模組，這次沒有改動，也沒有任何
  新的 Graph 呼叫或新欄位——換算只用既有 `daily_budget`／`lifetime_budget`／帳戶 `currency`。
- 換算規則：官方文件 <https://developers.facebook.com/docs/marketing-api/currencies>（取得於
  2026-09-20）——「Each currency has an offset which specifies how the platform handles its
  subdivisions.」平台單位除以該幣別的 offset 得到帳戶幣別金額。offset 1（零小數）：CLP、COP、
  CRC、HUF、IDR、ISK、JPY、KRW、PYG、TWD、VND；offset 100（兩位小數）：DZD、ARS、AUD、BHD、
  BDT、BOB、BGN、BRL、GBP、CAD、CNY、HRK、CZK、DKK、EGP、EUR、GTQ、HNL、HKD、INR、ILS、JOD、
  KES、LVL、LTL、MOP、MYR、MXN、NZD、NIO、NGN、NOK、PKR、PEN、PHP、PLN、QAR、RON、RUB、SAR、
  RSD、SGD、SKK、ZAR、SEK、CHF、THB、TRY、AED、UAH、USD、UYU、VEF、FBZ、VES。兩份清單都是窮舉；
  不在任一清單、幣別缺失或格式不是三位大寫字母，一律 `budget_amount=None`，不猜 1 也不猜 100。
- 讀回交叉核對（唯讀、零寫入，一次性）：TWD 帳戶 `368741390835357` 的活動
  `120250284145340671`（「【銷售】1150706 Beast Prime 最高數量」）`daily_budget` 回傳 `"1900"`，
  同活動 `ads_external_daily` 實際單日花費落在 1,639～2,383 TWD 之間。offset 1 換算成
  NT$1,900／天，與花費量級一致；offset 100 會是 NT$19／天，對不上同一活動 1,639～2,383 的實際
  花費——offset 1 對 TWD 成立，文件與讀回互相印證，此後不需要再對這條規則本身提出疑問。
  （這是一次性讀回核對，不是要求使用者投放才能看到結果；帳戶資料狀態僅作為既有事實記錄。）
- 金額計算全程用 `Decimal`：平台單位一律是整數，除以 offset 通常整除；`ROUND_HALF_UP` 只是防禦
  性設定、非精度來源。結果依 offset 對應小數位（offset 1 → 0 位、offset 100 → 2 位）量化後才轉
  `float` 存入 `budget_amount`，兩位小數幣別不會被二進位浮點誤差吃掉尾數。
- `budget_raw.conversion` 一律是機器可讀的判斷依據：換算成功是 `offset_table:<offset>`；未成
  功依序是 `currency_absent`（幣別缺失或格式不對）、`currency_not_in_offset_table`（幣別不在兩
  份清單內）、`no_budget_value`（平台沒有回傳日預算或總額預算數值）。`availability.budget_amount`
  只有在真的換算出金額時才是 `available`，其餘都留 `unknown`。
- `month_budget.py:168-169` 的「持續投放的預算金額、單位或幣別未核實」判斷本來就是逐一實體檢查
  `budget_amount is None`；換算成功的實體自然不再觸發這條提醒，未換算成功的實體不變、繼續明確標
  未核實——這次沒有改動 `month_budget.py` 本身的邏輯，行為變化完全來自 `_entity()` 現在真的能給
  出金額。
- 變更清單／讀回核對（`change_control_data.before()`、`change_control_verify.check()`）沒有改
  動：兩者本來就直接讀 `entity.get("budget_amount")` 做比對，換算前後都是同一段程式碼；新增
  `test_ads_change_control.py::ChangeControlTest.test_meta_budget_conversion_flows_through_
  confirmed_readback` 端到端證明用 `_entity()` 產生的真實換算金額走到 `check()` 也能判「已核對
  一致」，不是只用測試自訂的假數字。
- 驗證：`app/tests/test_ads_external_metrics.py`（零小數 TWD、兩位小數 USD、不在清單的幣別、幣
  別缺失、無預算數值五種情境）、`app/tests/test_ads_change_control.py`（端到端讀回）。

### 6.13 F16-I03 — 依活動目標判讀成果，不再只看購買（settled 2026-09-20）

- 問題：Insights 的 `actions` 早就整包拉回來了（`graph.py:556-558`），但除了購買同義字之外全部
  被丟棄；`ads_external_daily` 只有 `purchases`／`revenue` 兩欄，`review_evidence.aggregate()`
  寫死 CPA／ROAS。非購買目標的活動因此完全無法判讀，而且一則廣告偶發一次購買，會被讀成「這活
  動的成果」，觸發不該有的變差／停損判斷——這正是本票要拔掉的假訊號。
- Schema：`supabase/migrations/20260920000003_ads_result_metric.sql` 對 `ads_external_daily`
  新增 `result_kind`（text，可空）／`result_count`（numeric，可空）兩個平台中立欄位；既有
  `purchases`／`revenue`／唯一鍵不變。這支 migration 不回填任何舊列——舊列的 `result_kind`／
  `result_count` 保持 `NULL`，直到那個活動被用新版 adapter 重新同步一次；migration 沒有辦法知
  道一列舊資料當初「應該」對到哪個成果，回填等於用今天的規則假造昨天沒發生過的判斷。
- 目標 → 成果動作對照表整份住在 `app/ads/adapters/meta_read.py`
  （`_SALES_OBJECTIVES`／`_OBJECTIVE_RESULT_ACTIONS`）——這是 Meta 專有的名詞轉換，跟品牌自己
  的 `conversion_goal`（`app/meta/repository.py::_CONVERSION_ACTION_PRIORITY`）是不同的鍵、不
  同的用途，這次沒有動、也沒有 import 對方：
  - 銷售類目標（`OUTCOME_SALES`／`CONVERSIONS`／`PRODUCT_CATALOG_SALES`）→ 成果 `purchase`，
    直接沿用 `source.external_purchase_values()` 已經算好的購買數，不另外重新掃一次
    `actions`——購買同義字的唯一定義還是那一份，這裡不維護第二份。
  - `OUTCOME_ENGAGEMENT`／`POST_ENGAGEMENT` → `engagement`（`post_engagement`／
    `page_engagement`）；`OUTCOME_TRAFFIC`／`LINK_CLICKS` → `link_click`（`link_click`／
    `landing_page_view`）；`OUTCOME_LEADS`／`LEAD_GENERATION` → `lead`；
    `OUTCOME_APP_PROMOTION`／`APP_INSTALLS` → `app_install`；`VIDEO_VIEWS` → `video_view`；
    `MESSAGES` → `message`；`STORE_VISITS` → `store_visit`。
  - 不在表裡的目標（含 `OUTCOME_AWARENESS`／`BRAND_AWARENESS`／`REACH` 這類本來就沒有離散成果
    可數的目標）一律 `result_kind=result_count=None`——**絕不**退回去算購買數；這是本票最重要
    的一條規則，用一個物件哨兵（`_NO_OBJECTIVE`）跟「呼叫端沒有要求算成果」區分開來。
- 讀取端只有 `MetaReader.read_observations()` 會查目標並往下傳：每一頁只查一次
  `external_repository.campaign_objective()`（讀 `ads_external_entity.objective`，campaign 層
  已經在既有 structure 同步時存好），同一頁 campaign／adset／ad 三層共用同一個活動的目標。
  `read_monthly()` 刻意不查、也不傳目標——月結只做帳戶級花費核對，不逐廣告判讀，維持
  `_save_monthly()`／`ExternalObservation` 既有的嚴格欄位形狀不變。
- `result_kind`／`result_count` 沒有進 `ExternalObservation`（`app/ads/external_models.py`，這
  次沒有動）：那個模型是 `extra="forbid"`，硬塞兩個大多數來源都沒有意見的欄位，會逼每個既有測
  試替身跟著長出這兩個 key。改成 `external_repository.upsert_observation()` 多兩個獨立關鍵字參
  數，直接補進 `model_dump()` 之後的 dict 再組 SQL；`external_sync.py::_save_page` 把
  `MetaReader` 回傳的 `result_kind`／`result_count` 從 observation dict 裡摘出來，轉成關鍵字參
  數傳過去，其餘來源（測試替身、既有 fixture）沒有這兩個 key 就一律是 `None`，行為不變。
  `availability["result_count"]` 比照其餘欄位規則自己補（有數字才是 `available`）。
- **文件更正（F18-I01 發現的落差）**：本節原稿寫「`review_evidence.aggregate()`：`METRICS`
  加入 `result_count`」，程式實際上沒有這樣做（`METRICS` 從頭到尾只有
  `spend`／`impressions`／`clicks`／`purchases`／`revenue` 五項，`app/ads/review_evidence.py:18`；
  `aggregate()` 本身依 `attribution_key` 分組算 `series` 與 ctr／cpc／cpa／roas 那個比率清單在
  `app/ads/review_evidence.py:135-154`）；`result_count`／`cost_per_result` 從來沒有進過依
  `attribution_key` 分組的 `series`。這兩個欄位只活在下面 6.13.1 新增的、不看 `attribution_key`、
  依 `(metric_scope, currency)` 分組的 `result_views` 裡（`_result_view()`，一個獨立函式，
  `app/ads/review_evidence.py:45-120`）——這才是實際落地的設計，本節這句舊敘述作廢，不要依它推斷
  `series` 的欄位形狀。

#### 6.13.1 修復輪：撕裂的 series 與跨動作加總（settled 2026-09-20）

探針發現兩個缺陷：`attribution_key` 是拿購買動作類型組出來的，一則互動類廣告只要某天出現一次偶
發購買，`attribution_key` 就會在 `…:unavailable` 與 `…:omni_purchase` 之間翻面，`aggregate()`
照這個鍵分組，一則廣告的 series 因此被撕成兩組，前後期比較等於只比了半則廣告。另外，同一個
`result_kind` 標籤底下可能來自不同的平台動作類型（例如 day1 是 `post_engagement`、day3 是
`page_engagement`），而 Meta 的 `page_engagement` 本身就**包含** `post_engagement`，把兩者加總
出來的數字在平台上從不存在；原本的「這組裡第一個非空 `result_kind`」寫法完全看不出這種混用。

- 第二支 migration `supabase/migrations/20260920000004_ads_result_definition.sql`（沿用
  §6.13 的規則：不改已套用的 `…0003`，開新檔修正）再對 `ads_external_daily` 加兩個可空文字欄
  位：`result_action`（真正被算進 `result_count` 的那個平台動作類型，例如
  `post_engagement`）／`result_attribution`（這個數字是在哪個歸因設定下讀到的，由 adapter 直接
  當成不透明字串提供）。同樣不回填舊列。
- `meta_read.py` 新增常數 `_ATTRIBUTION_WINDOW = "7d_click+1d_view"`：`attribution_key` 前綴與
  `result_attribution` 都直接引用這個常數，共用層絕不會反過來解析 `attribution_key` 字串去猜歸
  因設定。`_objective_result()` 回傳 `(result_kind, result_count, result_action,
  result_attribution)` 四個值；`result_action`／`result_attribution` 只在 `result_count` 真的
  有值那天才填，成果數未知的日子兩者也保持 `None`（呼應「未知不是零」）。
- `aggregate()` 新增第二種分組：**不看** `attribution_key`，只依 `(metric_scope, currency)` 把
  整個窗口的所有列分成一組，對每一組算出「這則廣告自己的成果」一份 result view（`result_kind`／
  `result_action`／`result_attribution`／`result_count`／`cost_per_result`／`days_present`／
  `days_known`／`reason`），放在 `aggregate()` 回傳值新增的 `result_views` 陣列。前後期比較「活
  動自己的成果」一律讀這個 view，不讀 per-`attribution_key` 的 series；`review_evidence.py` 的
  `_result_view()` 是唯一實作。失效即關閉（fail-closed），跟既有「這組只要有一天未追蹤整組就是
  `None`」同一家族，不特例：
  - 組內已知的 `result_kind`／`result_action`／`result_attribution` 只要有一個出現兩種以上不同
    值 → `result_count`／`cost_per_result` 都是 `None`，`reason="mixed_result_definition"`；不
    再有任何「挑第一個非空值」的寫法。
  - 窗口內只要有一列 `result_count` 未知（不論那列有沒有花費），整組就是 `None`，
    `reason="result_unknown_days"`；絕不用部分列的和去除以部分或全部花費。
  - `cost_per_result` 的分母永遠是「被算進 `result_count` 那些列」的花費總和，不是整個窗口的花
    費。
- `frontend/src/lib/adsExternalApi.ts`／`adsReviewApi.ts` 型別同步：`NativeObservation` 加
  `result_action`／`result_attribution`；新增 `ReviewResultView` 型別、`ReviewPeriod` 加
  `result_views` 欄位；`ReviewSeries` 移除 `result_kind`（後端已不再輸出）。沒有動任何元件。
- 驗證：`app/tests/test_ads_external_metrics.py`（adapter 層 `result_action`／
  `result_attribution` 跟著 `result_count` 一起有/沒有）、`app/tests/test_ads_review_cycle.py`
  （撕裂 series 情境下 view 仍是一份、跨動作類型混用判 `mixed_result_definition`、SALES 的
  view 跟既有購買指標一致）。
- 提示詞（`app/departments/ads/review_round.md`）新增一句：cpa／roas 只認購買，
  `cost_per_result` 才是活動依自己目標算出的成果與成本；沒有成果定義時是 `null`，偶發的購買不
  是該活動的目標成果，不能當成效變好或變差的證據。`review_policy.py` 的驗證器沒有改——它驗證
  的是模型回覆的形狀，跟評分用哪個指標無關。
- SALES 不變性：新增回歸測試直接比對「不傳 objective」與「傳 `OUTCOME_SALES`」兩次
  `observation()` 呼叫，除了新增的 `result_kind`／`result_count` 之外，其餘每一個既有欄位（含
  `purchases`／`revenue`／`attribution_key`）逐一斷言相等——這保證 SALES 活動今天算出來的
  CPA／ROAS／購買數，一步變化都不會有。
- 驗證：`app/tests/test_ads_external_metrics.py`（SALES 不變性、目標對照表逐項、`OUTCOME_
  ENGAGEMENT` 活動混了一次偶發購買仍判成 `engagement` 而非購買、未對照目標不落回購買）、
  `app/tests/test_ads_external_sync.py`（`result_kind`／`result_count` 經由通用同步流程真的落
  進 `ads_external_daily`）、`app/tests/test_ads_review_cycle.py`
  （`review_evidence.aggregate()` 的 `result_kind`／`cost_per_result`／未追蹤誠實規則）。

### 6.14 F16-I04 — 每個 Campaign 都能算出目標成本（settled 2026-09-20，2026-09-20 再裁一輪）

- 問題：`success_metric` 原本只認 cpa／roas／purchases（`20260913000001_ads_tables.sql:22`），
  既有活動（`origin='imported'`）完全沒有目標成本可比。
- **架構裁決（2026-09-20 review 修正）：目標成本用自己的欄位，這個 feature 永遠不再寫
  `success_metric`／`success_target`／`success_basis`。** 第一版（`20260920000005_ads_
  campaign_target.sql`）借用這三個欄位（`success_metric='cost_per_result'`）存放目標成本，
  review 證實這會在票外靜默壞掉：`closeout._metric_value` 沒有 `cost_per_result` 分支，會落到
  `totals["purchases"]`（一個「數量」）用 `>=` 跟金額目標比，判出捏造的達成／未達成；
  `learning.py` 把這個原始字串直接印給使用者看、還拿它分群學習世代；`budget.py` 冷啟動與
  `asset_suggestions.py` 都認 `success_metric=='cpa'`／`success_target is not None`，一被改成
  `cost_per_result` 就悄悄失效。修正開新檔 `20260920000006_ads_campaign_target_columns.sql`
  （不改已套用的 `..._0005`）：
  - 新增 `ads_campaign.target_cost`（numeric，可空）／`target_basis`（text，可空，
    CHECK IN `break_even`／`trailing_30`／`own`），外加 CHECK
    `ads_campaign_target_cost_only_for_own`：`target_cost` 只在 `target_basis='own'` 時有值
    ——`break_even`／`trailing_30` 永遠在讀取當下重新算（`resolve()` 本來就這樣做），這張表
    只記「使用者上次要求哪一種」的標籤，不記算出來的數字，避免存的數字跟重算的數字兜不起來。
  - 先用 `DO $$ ... RAISE EXCEPTION ... $$` 斷言沒有任何列的 `success_metric='cost_per_result'`
    （有就中止，不靜默改列），再把 `ads_campaign_success_metric_check` 收回
    cpa／roas／purchases、砍掉 `ads_campaign_cost_per_result_basis` 這條 CHECK。既有
    cpa／roas／purchases 列的 `success_basis`（一句話說明）不受影響。
  - `result_kind`／`target_revision`（`..._0005` 加的）原樣保留，不動。
- `app/ads/targets.py::resolve(conn, org, brand, campaign, *, product_id=None)`：純函式、不打
  模型、不寫任何表。固定優先序（不可被呼叫端重排）：① `target_basis='own'` 且 `target_cost`
  有值時永遠贏；② 這個 Campaign「自己的結果是購買」（`result_kind=='purchase'`，或
  `result_kind` 未知且 `origin!='imported'`——既有內建 Campaign 向來只認購買，
  `brief.py::_OBJECTIVES` 五種目標全部走 cpa／roas／purchases，系統裡沒有第二種可數的轉換
  事件）時，帶著商品（既有 `context_json.product_ids`，或既有活動由呼叫端明講的
  `product_id`）走 `budget.breakeven_cpa()` + `budget.economics_for()`（`_economics_for` 的公開
  包裝，跟 `scenarios()` 共用同一套「多個商品挑第一個算得出來的」規則，不重寫第二份）；③ 否則
  這個 Campaign 自己近 30 個完整日的實際 cost per result（`_trailing_30`：只取
  `metric_scope='campaign'` 那層、重用 `review_evidence.aggregate()`
  的 `result_views`——NULL-aware，未知日永遠不進分子也不進分母，`reason='result_unknown_days'`
  一律回報 `missing=['needs_resync']`，絕不是零）；④ 都不成立時 `value=None`，`missing` 列出
  卡住的原因（`"product"`／`"product_cost"`／`"needs_resync"`／`"trailing_30"`／
  `"mixed_result_definition"`）——絕不是預設數字、絕不是零。
- **`result_kind` 的來源**：目標→結果的對照表只住在 Meta adapter
  （`app/ads/adapters/meta_read.py::_SALES_OBJECTIVES`／`_OBJECTIVE_RESULT_ACTIONS`），透過既有
  reader／capability 介面對外露出唯一一個函式 `MetaReader.result_kind(entity)`（吃這個
  Campaign 自己根節點 entity 的 `objective` 欄位）——共用層（`app/ads/external_sync.py`）永遠
  不直接讀 Meta 目標字串。同步（`_save_page`）在「structure」任務裡遇到這個 Campaign 自己樹的
  根節點（`parent_native_id` 是空的那一列，不寫死 Meta 的 `native_kind=='campaign'`，其他平台
  的根節點可能叫別的名字）時，呼叫這個函式，**只在 `ads_campaign.result_kind` 目前是 NULL 時**
  寫回去——使用者事後用 `PUT .../target` 選的 `result_kind` 永遠不會被下一次同步蓋掉。沒有這個
  能力的 reader（通用／手動 adapter）不受影響，維持原樣。
- 讀寫：`repository.get_campaign_target()`／`save_campaign_target()`（只寫
  `target_cost`／`target_basis`／`result_kind`／`target_revision` 四欄），路由
  `GET`／`PUT /api/ads/brands/{b}/campaigns/{c}/target`（`routes.py`，`_legacy_campaign_guard`
  白名單沒有 `target` 這個 suffix，兩條路由自己做 `require_actor`／`require_brand`，跟月預算
  同款）。`PUT` 的 `price`／`variable_cost` 只轉交
  `app.brand_intelligence.repository.save_product_economics`（既有公開寫入路徑，先讀現有
  `product_economics` 補齊必填欄位再存，`ads` 這邊不直接碰那張表）。
- Frontend：本期不加前端 client。原先加在 `frontend/src/lib/adsApi.ts` 的 `CampaignTarget`／
  `getCampaignTarget`／`saveCampaignTarget` 會讓該檔超過 800 行上限（`architectureBoundaries.test.ts`），
  且目前沒有任何畫面使用；phase 2 做「設定目標」畫面時，以獨立的 `frontend/src/lib/adsTargetApi.ts`
  加入並同步更新 `ARCHITECTURE.md` 的 ads `owns`。`SuccessMetric` 沒有加寬。
- 驗證：`app/tests/test_ads_targets.py`（銷售有／無成本、engagement 走 trailing-30、完全沒資
  料、既有活動缺商品、使用者覆寫、F16-I03 前的 NULL 列回報 `needs_resync` 而非零、
  `result_kind` 經真的 adapter 對照表跟真的寫入路徑落地而非手塞 dict、`PUT` 不動
  `success_metric`／`success_target`／`success_basis` 一個字元）、
  `app/tests/test_ads_closeout.py`（`PUT` 前後同一顆內建 CPA Campaign 結案 verdict 一致）、
  `app/tests/test_ads_external_sync.py`（同步只在 `result_kind` 是 NULL 時填、不蓋使用者已存的
  選擇）、`app/tests/test_ads_external_schema.py`（新舊兩份 migration 的 CHECK 約束）。

### 6.15 F16-I06 — 月讀列與被取代的攻擊列污染活動自己的成果（settled 2026-09-21，真實資料人工驗收發現）

- 問題：人工驗收在使用者自己同步的既有 SALES 活動上，重新同步成功後 `GET .../target` 仍回
  `missing: ["product","needs_resync"]`。兩個各自獨立的成因，都在 `ads_external_daily` 的
  `metric_scope='campaign'` 那一層：
  1. `attribution_key='account_monthly_spend'` 的月讀來源列（寫入端 `meta_read.py::read_monthly`
     ／`external_sync.py::_save_monthly`，讀取端 `month_budget.py::_inventory`）跟一般逐日觀測列
     共用 entity／day／`metric_scope`／currency——F16-I03 的 `_result_view()`／`aggregate()` 依
     `(metric_scope, currency)` 分組時**沒有排除**它們：花費被算兩次，它們永遠 `NULL` 的
     `result_count` 又讓整個窗口的 `reason` 卡在 `result_unknown_days`。
  2. `attribution_key` 內嵌了 Meta 的購買動作類型（`_ATTRIBUTION_WINDOW + ":" + action_type`），
     同一天先讀到「還沒有購買」（`…:unavailable`）、後讀到「有購買」（`…:omni_purchase`）會落成
     唯一鍵下的兩列而不是一次 UPDATE；兩列都留著，同一天的花費因此被算了兩次。真實資料重現於
     2026-09-19：`…:unavailable` 花費 722、`…:omni_purchase` 花費 1747，兩列同時存在。
- 修復點都在**共用層**，不是每個讀者各自修：
  - **一份共用、跟平台無關的定義**：`external_repository.py` 新增
    `MONTHLY_BUDGET_ATTRIBUTION_KEY` 常數與 `is_monthly_budget_row()` 判斷式，取代原本散在四處
    （`meta_read.py`／`external_sync.py`／`month_budget.py`／
    `app/tests/fixtures/ads_external/cycle_reader.py`）各自硬寫的
    `"account_monthly_spend"` 字面值。`month_budget.py::_inventory` 的規則不變（帳戶整月讀到時，
    根節點只留月讀列，因為月讀是權威花費口徑）。`review_evidence.aggregate()` 在分組前先過濾掉
    月讀列，一次涵蓋「依 `attribution_key` 分組的 series」跟「不看 `attribution_key` 的
    `result_views`」兩邊；`targets.py` 透過呼叫 `aggregate()` 自動吃到這個排除，本身不直接讀
    `attribution_key`（沿用 §6.14 的中立原則）。
  - **同步路徑自己修復被取代的列**：`external_repository.upsert_observation()` 新增關鍵字參數
    `heal_superseded_attribution`（預設 `False`，行為不變）；只有
    `external_sync.py::_save_page()` 寫「observations」任務（每個平台 reader 的一般逐日觀測都經
    過這一個進站點）時打開它——寫入新列後，在**同一個交易**裡刪掉同一身分
    （entity／day／metric_scope／currency／source）下 `attribution_key` 不同、且不是月讀列的舊
    列。唯一鍵與 `attribution_key` 格式都沒有變；月讀寫入（`_save_monthly`）不使用這個參數，永
    遠不會刪到、也不會觸發刪月讀列。重新同步一次受影響的窗口就會自己吃掉重複列，不必手動改資料。
  - **`missing[]` 三分**：`_result_view()` 現在把「未知」拆成三種各自誠實的 `reason`：組內
    `result_kind`／`result_action`／`result_attribution` 不一致仍是 `mixed_result_definition`；
    花費未知，或某列缺 `result_count` 但那列本來就有結果對照（`availability` 有記錄
    `result_count`，只是值是 `unavailable`／`unknown`）→ `result_unknown_days`；某列缺
    `result_count` **且**四個成果欄位全是 `NULL`、`availability` 完全沒有 `result_count`
    這個 key（新的判斷式 `_predates_result_columns()`，只認列本身的形狀，不猜日期）→ 代表這是
    F16-I03 加欄位以前寫的舊列，回報 `needs_resync`。`targets.py::_trailing_30` 不再自己把
    `result_unknown_days` 硬轉成 `needs_resync`，直接原樣轉發 `_result_view()` 給的
    `reason`——三個 `missing` 字串現在都可能出現，各自對應不同的下一步（`needs_resync` 表示重新
    同步會修好；`result_unknown_days` 表示這是真的不知道，重新同步不保證解決）。
  - `targets._trailing_30` 的「今天永遠不算完整日」（`end = today - 1 day`）這條規則本來就是對
    的，這次沒有改，只補了鎖定它的測試。
  - 真實資料唯讀重現（org `org_bughunt`／brand `brd_bughunt`，campaign
    `adc_01M2T370NSGZDS0YXWTATKCN3T`）：同一天（09-19／09-20 等）確實同時有月讀列與逐日觀測
    列、且逐日觀測列確實從 `…:unavailable` 換成 `…:omni_purchase` 但舊列沒被刪；另外發現
    2026-08-22 那天的觀測列 `availability` 完全沒有 `result_count` 這個 key（`result_kind`／
    `result_count` 皆 `NULL`），是真實環境裡「F16-I03 以前」形狀的活樣本，跟本票模擬的測試資料
    形狀一致——這天要等下一次重新同步整個 30 天窗口一起補齊，`missing=["needs_resync"]` 是正確
    的誠實回報，不是本票要另外修的資料。
- 驗證：`app/tests/test_ads_targets.py`（月讀列與觀測列同天不污染 trailing-30、預先移除
  `availability.result_count` key 模擬真正的舊列才回 `needs_resync`、有 `result_kind` 但當天無
  計數回 `result_unknown_days` 而非 `needs_resync`、鎖定 trailing-30 排除今天）、
  `app/tests/test_ads_review_cycle.py`（純函式層級：`aggregate()` 排除月讀列，series 與
  result view 都不被污染）、`app/tests/test_ads_external_sync.py`（重新同步真的刪掉被
  `attribution_key` 取代的舊列；月讀寫入不觸發、也不會被這個修復刪除；同一天但
  `metric_scope`／`currency`／`source` 任一不同的列都活下來）、既有
  `test_ads_external_monthly.py`／`test_ads_month_budget.py` 全數維持通過，確認月預算總額不受
  這次重構影響。
- **Known limit（刪除規則比證據寬）**：修復把「同一身分下 `attribution_key` 不同」一律當成被
  取代。這等同於「只有動作類型後綴變了」**只在** adapter 的歸因視窗是單一常數時成立——今天
  `app/ads/adapters/meta_read.py` 的 `_ATTRIBUTION_WINDOW = "7d_click+1d_view"` 是模組層級常數，
  而且整份檔案只有一處組出觀測列的 `attribution_key`（`_ATTRIBUTION_WINDOW + ":" + 動作類型`），
  所以目前不可能出現兩個合法但不同歸因視窗的列。**不能**用 `result_attribution` 收窄：
  `_objective_result()` 只在計數已知時才填它，而被取代的正是計數未知那種列（`…:unavailable`），
  對那些列它永遠是 `NULL`。共用層又不准去拆 Meta 格式的 `attribution_key` 字串（§6.14）。因此哪
  天平台或個別帳戶開始回報一種以上的歸因設定，**必須先加一個跟平台無關的「歸因視窗」欄位**
  （schema 變更），再把刪除條件收窄成「同視窗、只有動作類型後綴不同」；在那之前這條寬規則是
  已知且刻意接受的取捨，邊界由 `metric_scope`／`currency`／`source`／entity／day 守住（上面的
  `test_heal_only_reaches_the_identity_it_replaces` 鎖定）。
- **最新平台狀態為準**：同一身分重新同步時，新讀到的那列勝出，舊列被刪。後果要講清楚——如果某次
  重新讀取的資料反而比較差（例如平台這次沒回報購買動作），它會取代掉比較好的舊列。這是刻意沿用
  本模組既有慣例，不是這次的瑕疵：`app/ads/month_budget.py::_inventory` 對月讀列採同一條規則
  （「完整重讀時被省略的舊列，不可以當成還有效的月花費留著」）。

### 6.16 F18-I01 — 條件式推定 0（settled 2026-09-21）

- 問題：平台某天沒回報這則廣告的成果動作，跟平台回報「有這個動作、次數是 0」在資料上長得一樣
  ——`result_count IS NULL`。前者是「不知道」，後者才是「知道是 0」；共用層一律誠實回 `unknown`，
  導致一則廣告明明持續花錢卻始終沒有成果的窗口，永遠卡在 `result_unknown_days`／`missing`，判不
  出停損。
- 規則（三條件缺一不可，`app/ads/tracked_zero.py::apply()`，平台中立、不 import 任何 adapter）：
  1. **先證明這個 Campaign 真的在追蹤這個動作**：over 這個 campaign 自己的 entity 列，取
     `day BETWEEN end-27 AND end`（`OBSERVATION_WINDOW_DAYS=28`，`end` 是本次完成同步的涵蓋窗尾
     日）內 `availability.result_count='available'` 且 `result_count>0` 的列，取
     `(result_kind, result_action, result_attribution)` 相異值。剛好一種 ⇒ 這是「已示範的定
     義」；零種或一種以上 ⇒ 不寫任何東西，回報 `no_demonstrated_definition`／
     `mixed_result_definition`（絕不用猜的或挑第一個）。
  2. 只在同一次同步「observations」任務**乾淨完成**（無 cursor、無 errors，涵蓋範圍已記錄）的
     同一交易內，對這次同步涵蓋的 `[start, end]` 窗口逐列判斷：`result_kind` 等於已示範的定義且
     `result_count IS NULL`；`availability` 確實有 `result_count` 這個 key（排除 §6.15 的
     `_predates_result_columns` 舊列形狀）；`availability.spend='available'` 且
     （`spend>0` 或 `impressions>0`，代表這天真的有花錢／有曝光，不是活動還沒開始）；
     `day` 不晚於**這個廣告帳戶自己時區**的昨天（今天永遠不算完整日，沿用 §6.15
     `targets._trailing_30` 同一條規則，但這裡刻意不沿用它的組織時區口徑——見下方時區裁決）；
     `day` 落在這次同步實際涵蓋的窗口內；不是 §6.15 的月讀列（`is_monthly_budget_row`）。
  3. 全部成立才寫：`result_count=0`、`result_action`／`result_attribution` 填已示範的那組值、
     `availability.result_count="derived_zero"`——**不是** `"available"`（平台真的回報的 0）、
     **不是** `"unknown"`（真的不知道），三種狀態永遠可分辨。只動這四個欄位，`spend`／
     `purchases`／`revenue`／`attribution_key`／唯一鍵完全不碰。
- **時區裁決（review 修正 2026-09-21，偏離原票 Done #3 的 `today_for_org` 字面寫法）**：
  「今天還沒過完」不能問組織的時區，要問**這個廣告帳戶自己**的時區——組織與底下接的帳戶時區可以
  不同，用組織時區會把帳戶那邊其實還沒過完的一天當成已完整，錯誤推定 0。`tracked_zero.apply()`
  因此不再自己算日期，改收呼叫端傳入的 `last_complete_day: date` 參數，模組本身仍平台中立、不
  import `zoneinfo`、不查任何時區設定。唯一呼叫點 `external_sync.py::run_sync` 用這次同步已經
  讀回的帳戶物件（`current_account["timezone_name"]`）換算：
  `(now_utc().astimezone(帳戶時區) - 1 天).date()`，跟 `review_evidence.py::snapshot()`
  （約行 241）「觀察結束日於來源帳戶時區尚未完整結束」同一種算法，差別只在這裡問的是帳戶今天，
  不是使用者選的觀察結束日。
- 呼叫點只有一處：`external_sync.py::run_sync`，「observations」任務完成、記錄 `coverage` 的同一
  段程式碼、同一個交易裡（不是獨立背景工作，也不是每個 reader 各自呼叫）；兩層各自負責一種失敗：
  - **帳戶時區本身未知或無法解析**（`ZoneInfo(...)` 拋 `ValueError`／`ZoneInfoNotFoundError`，例如
    帳戶尚未回填時區）——fail-closed：整批跳過推定，不呼叫 `tracked_zero.apply()`，這些列停在
    `unknown`；已經讀回、已經寫進 `ads_external_daily` 的那一頁成效**照常保留、照常算成功**，不是
    錯誤，也絕不是 `derive_failed`（review 修正 2026-09-21：時區未知不代表平台讀取失敗，不該把
    已經讀到的資料回滾）。
  - **時區可以解析，但 `tracked_zero.apply()` 本身丟例外**——這才包在 try/except 裡轉成
    `SourceReadError(..., "derive_failed")` 往外拋，交易整批回滾（跟這個函式既有的例外處理規則
    一致），`error_code` 是專屬的 `derive_failed`，不會跟平台真的讀取失敗（`invalid_source_page`
    等既有代碼）混在一起誤判。
- `review_evidence._result_view()`：`availability.result_count` 是 `"available"` 或
  `"derived_zero"` 都算「已知」，同一條「整組只要有一天未知就是 None」誠實規則不變；新增
  `derived_zero_days` 回報這組已知天數裡有幾天是推定出來的，讓前端／人工判讀能把「真的回報 0」
  跟「規則推定 0」分開看，不需要另外查。`_predates_result_columns()`／`mixed_result_definition`／
  三分 `missing[]` 規則（§6.15）不變。
- `app/ads/targets.py`／`app/ads/month_budget.py` 未修改也不需要修改：`targets._trailing_30` 透
  過 `aggregate()` 的 `result_views` 自動吃到 `derived_zero` 已知列，能在窗口內只有推定 0（沒有
  一天真的回報過)時仍算出 trailing-30 成本；`month_budget.py` 完全不讀 `result_count`／
  `availability.result_count`，只認 `spend`／`availability.spend`，不受影響（已逐一確認）。
- 冪等：對同一涵蓋窗口重複同步，第二次執行時已推定的列 `result_count` 已經是 `0`（非
  `NULL`），不再符合寫入條件，不會重複改寫；若中間真的讀到平台回報的真實值，`upsert_observation`
  在 `tracked_zero.apply()` 之前就已經覆蓋掉那列，推定規則自然不會再套用。
- 驗證：`app/tests/test_ads_tracked_zero.py`（三條件各自單獨擋下推定、28 天示範窗口的邊界
  27／28 天與更久以前都各自驗證、示範定義零種／多種、只涵蓋窗口內的列、不碰月讀列、冪等重同步）、
  `app/tests/test_ads_review_cycle.py`（`derived_zero` 在 result view 算已知、`derived_zero_days`
  計數、跟平台回報的 `"available"` 0 可分辨）、`app/tests/test_ads_external_sync.py`（`run_sync`
  在 observations 任務乾淨完成時真的呼叫 `tracked_zero.apply()`，涵蓋範圍就是同步窗口；帳戶時區
  跟組織時區不同時用帳戶時區當截止；`tracked_zero.apply()` 內部例外回報 `derive_failed`；帳戶時區
  未知或無法解析時整批跳過推定但成效頁照常成功、不回報任何錯誤代碼）、
  `app/tests/test_ads_targets.py`（`_trailing_30` 在窗口只有推定 0 時仍能解出，不再卡 `missing`）。
- **型別落差已補（F18-I02）**：`app/ads/external_models.py::Availability` 這個 `Literal` 現在包含
  `"derived_zero"`（原本只有 `"available"`／`"unknown"`／`"unavailable"` 三種、`tracked_zero.apply()`
  用原生 SQL `UPDATE` 繞過驗證直接寫這個值的落差，見 `app/tests/test_ads_external_models.py`）。

### 6.17 F18-I02 — 程式分流：每則廣告對自己前一期做判讀（settled 2026-09-21）

- `app/ads/triage.py::classify(conn, org_id, brand_id, campaign_id) -> {"window_days", "items"}`：
  純讀取、不呼叫模型、不寫任何表（ARCHITECTURE.md §0「程式整理，LLM 判斷」）；平台中立
  （§6.14）——這支檔案不 import 任何 adapter、不出現平台字面字串，時區與平台讀取都透過既有
  `external_sync.account_reader()` 轉手。一個 Campaign 底下每個 `native_kind='ad'` 的
  `ads_external_entity` 各出一個 item；class 六選一
  `stop_loss｜worse｜better｜flat｜insufficient｜no_target`，中文標籤
  停損／變差／變好／持平／資料不足／尚未設定目標 由這支檔案自己產生（feature Decisions 凍結的
  共用契約，逐字實作）。每個 item 另帶 `campaign_name`（F19-I07：這個 Campaign 自己的
  `name`，`classify()` 已經讀過的那筆 `campaign` row 上直接取，不是第二次查詢），供品牌層佇列
  （跨多個 Campaign）標示每列所屬活動、逐活動篩選用。
- **窗口與截止日**：`WINDOW_STEPS=(7,14,28)`；`window_days`（回傳最外層）固定是這三步裡最大的一個
  （28）——只代表「最多可能看多遠」，每個 item 實際用到的窗長要看自己的 `window.days`。第一個窗口
  的結束日是**這個 Campaign 所接帳戶自己時區**的「昨天」（沿用 §6.15、
  `review_evidence.py::snapshot()` 同一種算法，只是改問這個 Campaign 的實體所屬帳戶，不是使用者選
  的觀察結束日）；帳戶時區未知或無法解析時 fail-closed 退回 `today_for_org - 2 天`（review 修正
  2026-09-21：真實時區落差最大到約 26 小時，只退一天不保證真的是完整日）。樣本門檻沒通過就依序延
  到 14、28 天（`window.extended_from` 記上一步窗長）；28 天仍沒通過 ⇒
  `insufficient`／`below_sample_gate`。
- **同步涵蓋率門檻（review 修正 2026-09-21，blocker）**：使用者一次同步最多只選 31 天，28 天的判
  讀窗口底下可能只有 7 天真的同步過；`_result_view` 只看存在的列，沒同步的那幾天不會被算進「已知」
  也不會被算進「未知」，會被誤讀成「證明過的東西」。`classify()` 對每個 Campaign 只讀一次這個
  Campaign 自己的 `ads_campaign.context_json->'external_sync'->'observations'->'coverage'`
  （`external_sync.py::run_sync` 在 observations 任務乾淨完成時寫入，同一個位置 §6.16 已在用）。
  目前判讀窗口沒有完整落在涵蓋範圍內（含完全沒同步過）⇒ `insufficient`／`needs_resync`，**在那一步
  就地回報，不繼續延到更長的窗口**——窗口越長，涵蓋率只會越差，不會變好。前一期沒有完整落在涵蓋範
  圍內 ⇒ `insufficient`／`no_previous_window`。這個門檻刻意不看 `aggregate()` 的
  `missing_days`——沒有列可能是那天真的沒投放（合法的 0 筆），不是沒同步。
- **樣本門檻**（`MIN_RESULT_EVENTS=10`）：`spend ≥ 3 × target.value` 或（`window.days ≥ 7` 且
  `result_count ≥ 10`）。停損門檻用同一個 3 倍常數（`STOP_LOSS_SPEND_MULTIPLE=3`），每個窗口長度
  都先過涵蓋率門檻、再檢查停損、才檢查樣本門檻——停損只認**已知**的 0（`result_views` 的 `reason`
  必須是 `None`，含 §6.16 的 `derived_zero`），花費未知或成果未知永遠不算停損。
- **成效只走一個來源**：`review_evidence.aggregate(rows, start, end)["result_views"]`、
  `metric_scope='ad'`、一次一個廣告，絕不第二次自己定義「已知」；花費同理只加總
  `aggregate()` 自己算出的 `series[...]["metrics"]["spend"]`（同一組 attribution_key 子群全部
  已知才視為已知，跟 `_result_view` 的完整性門檻一致；超過一種幣別一律回 `None`，不混加總）。目標
  端 `target.value is None` ⇒ `no_target`／`target_unresolved`（`target.missing` 逐字帶出）；
  `target.result_kind` 與這個廣告第一個窗口的 `result_kind` 兩邊都不知道 ⇒
  `no_target`／`result_kind_unknown`（只在第一個窗口、且該窗口通過涵蓋率門檻時判一次，不隨延窗重
  判）。
- **前一期比較**：前一期不可用（沒有列、`reason` 非 `None`、`cost_per_result` 是 0 或 `None`、或不
  在涵蓋範圍內）⇒ `insufficient`／`no_previous_window`，永遠不除以 0；本期 `cost_per_result`
  本身是 0 或 `None`（今天的常數巧合下走不到這條路——3 倍門檻同時是停損跟樣本門檻的花費子句，已知
  0 一定先被停損攔下；獨立保留這道守門，防止常數以後分岔）也同樣 ⇒
  `insufficient`／`below_sample_gate`，由 `_compare()` 這個獨立小函式守住，不是隱性除以 0。否則
  `change_pct=(本期-前期)/前期`，`> 0.20`（`FLAT_BAND`）⇒ `worse`／`cost_per_result_up`，
  `< -0.20` ⇒ `better`／`cost_per_result_down`，其餘 ⇒ `flat`／`cost_per_result_flat`。
- **一次讀完一個 Campaign（review 修正 2026-09-21，N+1）**：`classify()` 只對
  `ads_external_daily` 發一次查詢（`entity_id = ANY(廣告清單)` 且
  `day BETWEEN cutoff-55 AND cutoff`，55 天涵蓋任何廣告在最長 28 天窗口＋等長前期時可能用到的最
  早日期），在 Python 依 `entity_id` 分組後，每個廣告、每個窗口只是對這份記憶體資料切片，不再對
  每則廣告、每個延窗步驟各自查一次表。
- `GET /api/ads/brands/{brand_id}/campaigns/{campaign_id}/triage`（`app/ads/triage_routes.py`，
  `routes.py` 只掛一行 `include_router`）：跟 `get_campaign_target` 同一種租戶界線寫法
  （`require_actor` → `require_brand`），回 `{"triage": {...}}`。
- 驗證：`app/tests/test_ads_triage.py`（每個 class／reason code 各自的 falsifier、非銷售廣告不被
  一筆意外購買帶偏、沒有目標時停損不會誤發、推定 0 才讓停損真的發得出來、部分／完全沒涵蓋的窗口
  不會冒充停損或前後比較、查詢數不隨廣告數成長）。
- **Known limit（前端還沒接）**：`frontend/src/lib/adsReviewApi.ts` 的 `ReviewResultView` 還沒有
  `derived_zero_days` 欄位，v7 前端批次要把「規則推定」的標記接上（下一批的驗收項目，不是本票
  範圍）。
- **Known limit（重複列會等比例放大）**：如果 `ads_external_daily` 對同一天有未被 §6.15 heal 掉的
  重複列（同一身分、不同 `attribution_key`），花費跟成果會被同時多算一次——比例不變，`cost_per_result`
  本身不會失真，但 `spend`／`result_count`／`sample.spend_multiple` 這些絕對值會偏高；不是本票要
  修的範圍（依賴 §6.15 既有的 heal 規則本身正確）。

### 6.18 F18-I03 — 品牌決策佇列：程式分流併進既有 `interrupts` 收件匣（settled 2026-09-21）

- 兩個新登記類別（`app/core/interrupts.py::CATEGORIES`，本票對這支舊檔唯一允許的改動——登記在
  `ads_runtime_attention` 之前）：`ads_triage_stop_loss`（`severity=money_loss`，標籤「廣告停損待
  決定」）、`ads_triage_worse`（`severity=rule_warning`，標籤「廣告變差待決定」）。本批只有
  `stop_loss`／`worse` 兩種 class 進佇列；`better`／`flat`／`insufficient`／`no_target` 不進。
- `app/ads/triage.py::refresh_queue(conn, org_id, brand_id)`（`POST
  /api/ads/brands/{brand_id}/queue/refresh`）：對這個品牌**每個非結案**（`status != 'closed'`）
  Campaign 各呼叫一次 `classify()`（沒有已匯入廣告實體的 Campaign 自然出 0 個 item，不必另外過
  濾），`stop_loss`／`worse` 的 item 各送一筆 `interrupts.enqueue()`；一個交易（逐筆 enqueue 後一次
  `commit()`）。commit 之後再跑一輪 supersede（見下）。
- `app/ads/triage.py::get_queue(conn, org_id, brand_id)`（`GET /api/ads/brands/{brand_id}/queue`）：
  唯讀，不呼叫 `refresh_queue()`、不寫任何列，也不做 supersede。
- **去重鍵含窗口結束日**：`dedupe_key = f"ads-triage:{class}:{entity_id}:{window_end}"`。
  `interrupts.enqueue()` 既有的去重查詢不分 `status`（見該檔 `enqueue()` 內的 `SELECT`），所以同一把
  key 只要存在（不管 open 還是 resolved）就不會插入第二筆——一筆已 resolve 的決定會維持
  resolved，直到窗口真的往前移動、`window_end` 換了新值、算出一把新 key 才會生出新的 open
  列。這個語意完全來自 `interrupts.py` 既有行為，本票沒有再改它一行。
- **`refresh_queue()` 之後 supersede 陳舊 open 列（lead review 2026-09-21 裁決）**：`interrupt`
  這張表同時餵品牌首頁（`app/dashboard/repository.py::_brand_card` → `list_open`，嚴重度決定
  `brand_health`）跟 `/api/inbox`；逾期自動封存只管 `informational`。去重鍵含 `window_end`、截止日
  每天往前走，代表一支持續 `stop_loss` 的廣告每天多開一筆 `money_loss` 的 open 列、一支已經恢復的廣
  告舊 open 列永遠留著——只在 `GET /queue` 濾掉陳舊列並不會把它們從首頁移除。`refresh_queue()`
  commit 完新／續留的列之後，對這個品牌 `ads_triage_stop_loss`／`ads_triage_worse` 兩個類別各跑一次
  `interrupts.list_open(brand_id=..., category=..., archive_stale=False)`，把 `dedupe_key` 不在這次
  分流結果內的 open 列逐筆呼叫既有的公開 `interrupts.resolve(conn, row_id, actor="system",
  org_id=org_id)`（`resolve()` 自己 commit、自己寫 audit；`"system"` actor 沿用
  `app/llm/methodology.py` 的既有慣例）——全程走公開介面，`app/ads` 不直接 `UPDATE interrupt`
  （`test_architecture_boundaries.py` 的分層檢查）、`interrupts.py` 本身不再多改一行。結果：同一
  (class, entity) 任何時刻最多一筆 open 列；使用者手動 resolve 的列不是 `open`，這輪 supersede 找不
  到它，也就不會重新打開；窗口一換算出新 key，照常補一筆新 open 列。
- **GET 沿用同一套「只回當前分流」過濾**：`get_queue()` 重新對這個品牌全部非結案 Campaign 跑一次
  `classify()`，只把「(class, entity_id, window_end) 仍等於這次分流結果」的 open 列放進回應——這條
  過濾在 `refresh_queue()` 剛 supersede 完之後是多餘保險，但 GET 可能發生在下一次 refresh 之前，此
  時陳舊列還沒被 supersede，過濾仍然必要，且 GET 本身不寫任何東西。
- **Known limit（本批刻意不做，留給下一批的暫停／擴量提案批次）**：supersede 只認得
  `dedupe_key`，不知道「這筆是使用者主動 resolve 還是被 supersede」——只要窗口往前走（每天）、廣告
  仍在 `stop_loss`／`worse`，就會算出新 key、補一筆新 open 列，也就是使用者昨天才處理過的同一支廣
  告，今天分流結果不變的話仍會再冒出來待決定。「使用者做過決定就不要再打擾」屬於暫停／擴量提案批
  次的抑制邏輯，本票不做。
- `counts`：六個 class 在這個品牌全部非結案 Campaign 上的分流結果各自計數（不是只算進佇列的兩類）；
  `total_ads`：全部 item 數；`kinds_available=["stop_loss","worse"]`、
  `kinds_pending=["scale_budget","refresh_creative"]` 兩個路由固定回傳，永遠不是空清單冒充「沒事要
  做」。
- **F19-I01：`items` 每一列自帶 `triage`**——用同一把 `_dedupe_key(class, entity_id, window_end)`
  比對出「當下是哪個 program triage item 產生了這筆待決定」（形狀同 `triage.py:229-235`），前端不解析
  `dedupe_key` 字串；因為只有通過上面「仍等於這次分流結果」過濾的列才會出現在 `items` 裡，`triage`
  永遠比對得到、不是 `null`。
- 訊息：`廣告「{name}」{停損|變差}，待決定`，`name` 超過 20 字截斷加「…」，確保全句 ≤
  `interrupts.MAX_MESSAGE_LEN`（30 全形字）；不出現任何平台字面字串。`action_url`
  沿用既有慣例（同 `app/ads/runtime.py::_health` 的 `ads_runtime_attention`）：
  `/brands/{brand_id}/ads/campaigns/{campaign_id}?tab=performance`。
- 驗證：`app/tests/test_ads_triage_queue.py`（真資料端到端一則、queue 機制用固定 item 隔離測試：同窗
  重跑不重複、已 resolve 保持 resolve、窗口換了才補新 item、GET 過濾陳舊 open 列、比對得上的列附正確
  `triage` item、六類計數、
  `kinds_available`／`kinds_pending` 恆在、非結案／有廣告的 Campaign 篩選、窗口連續前進兩次同一支廣
  告仍是 `stop_loss` 時只留一筆 open、舊列以 `"system"` actor resolve、廣告恢復 `flat` 後開回 0
  筆 open、supersede 不動別的類別或別的品牌、使用者手動 resolve 的列同窗不會被重新打開）、
  `app/tests/test_core_interrupts.py`、`app/tests/test_dashboard_overview.py`（確認新登記類別不影響
  既有跨品牌總覽排序／健康燈號斷言）。

### 6.19 F19-I06 — `result_kind` 的中文詞彙與可選清單（settled 2026-09-21）

- 問題：F19-I02／I05 都發現沒有任何既有 API 或共用常數回答「這個 `result_kind` 中文叫什麼」「這個
  Campaign 能選哪些 `result_kind`」——I05 只能先做唯讀顯示（自己一份小 map），I03／I04 等這票補上
  共用詞彙才能接。
- `app/ads/result_kinds.py`（新檔）：平台中立——不 import 任何 adapter、不出現平台字面字串。
  `LABELS: dict[str, str]` 是目前 Meta adapter 唯一會產生的八種 `result_kind` → 中文名詞
  （`purchase`＝購買、`engagement`＝互動、`link_click`＝點擊、`lead`＝名單、`app_install`＝安裝、
  `video_view`＝觀看、`message`＝訊息、`store_visit`＝到店），詞彙選字都能套進「每次<標籤>成本」這
  個固定句型。`label(kind)`：`None` 或不在表裡一律回泛用的「成果」，絕不回傳原始代碼。
  `options()`：`[{"kind","label"}, ...]`，`LABELS` 的插入順序（穩定），target 頁的分段選單直接讀這
  份清單，不自己排序或另編一份。
- **反向檢查在測試裡，不在這支檔案裡**：`app/tests/test_ads_result_kinds.py` 直接讀
  `app/ads/adapters/meta_read.py` 自己的 `_SALES_OBJECTIVES`／`_OBJECTIVE_RESULT_ACTIONS`
  （唯讀，不改 adapter）重新推導出「這個 adapter 實際會產生的每一種 `result_kind`」，斷言每一種都在
  `LABELS` 裡有標籤——adapter 加一種新的目標對照，這支測試就會因為少了標籤而紅，而不是 silently
  drift 成一份跟 adapter 脫鉤的清單。
- `app/ads/triage.py`：`target`（`_classify_ad::finish` 組出的那份 `targets.resolve()` 結果）、
  `current`／`previous`（`_metrics_view`）三個地方各自加一個 `result_label` 欄位（各自的
  `result_kind` 對照 `result_kinds.label()`），`triage.classify()`／`get_queue()`／`refresh_queue()`
  的回傳形狀因此連帶都多這個欄位，路由層沒有另外改一行。
- `app/ads/repository.py::_campaign_target_view()`：`GET`／`PUT .../target` 回應在既有欄位之外多
  `result_label`（這個 Campaign 目前 `resolve()` 出的 `result_kind` 對照的中文）跟 `result_kinds`
  （固定的 `result_kinds.options()` 清單，跟這個 Campaign 目前選了什麼無關，前端拿它畫分段選單的每
  一個選項）。
- **`PUT .../target` 的 trust-boundary 檢查**：`repository.save_campaign_target()` 在寫入前多一道
  `result_kind not in result_kinds.LABELS` ⇒ `ValueError("result_kind_unknown")`（`None` 維持既有
  語意「不改」，永遠合法），跟 `target_basis_unknown`／`target_value_unknown` 同一種寫法；路由層
  （`app/ads/routes.py::_TARGET_ERRORS`）對應 400。拒絕發生在任何 `UPDATE` 之前、同一個交易裡，不會
  半寫。
- `frontend/src/lib/adsTriageApi.ts`：`TriageTargetView`／`TriageMetricsView` 加 `result_label:
  string`；`CampaignTarget` 加 `result_label: string` 與 `result_kinds: { kind: string; label:
  string }[]`。`putTarget` 的錯誤現在讀後端 `error.code`（`TriageRequestRejected.code`），不再靠比對
  中文錯誤訊息字串認版本衝突——`target_conflict` 的訊息文字未來改了也不會讓前端誤判成別種錯誤。
- `frontend/src/components/ads/target/CampaignTargetPage.tsx`（Card 1「看什麼成果」）：從唯讀徽章／
  「尚未知道」文字改成 v7 原型的分段選單（`prototype-v7-ads-center.html:329` 的 `.seg`），選項讀
  `target.result_kinds`；沒有任何一個 `result_kind` 已知時，選單裡沒有一顆按鈕預選（誠實的未選狀
  態，不是猜一個預設）。刪掉頁面本地的 `RESULT_KIND_LABEL`／`resultKindLabel`，各處標題／own 欄位
  文案一律讀 `result_kinds` 對應的 `label`。改選會讓表單 dirty，跟其他欄位一起經既有的
  `putTarget(expected_revision=...)` 存檔；存檔後用回應更新畫面（不本地假算）。
- 驗證：`app/tests/test_ads_result_kinds.py`（詞彙涵蓋每種 adapter 會產生的 kind、`None`／未知代碼
  回泛用標籤、`options()` 順序、`PUT` 拒絕清單外的 `result_kind` 且什麼都不寫入、`GET .../target`
  回應帶 `result_label`／`result_kinds`）、`app/tests/test_ads_triage.py`、
  `app/tests/test_ads_triage_queue.py`（既有斷言在新增欄位下仍通過，不需要改動舊斷言本身）、
  `app/tests/test_architecture_boundaries.py`、`frontend/src/components/ads/target/
  CampaignTargetPage.test.tsx`、`frontend/e2e/ads-target.spec.ts`。

### 6.20 F20 — 活動詳情頁與「看證據」落點（settled 2026-09-22）

- 路由：`/brands/:brandId/ads/campaigns/:campaignId/detail`（`frontend/src/components/ads/detail/`）。既有五分頁工作區
  的網址 `/brands/:brandId/ads/campaigns/:campaignId` 不變，由詳情頁的「全部資料 ›」進入；首頁活動卡名稱與設定目標頁的
  麵包屑指向詳情頁。
- `app/ads/triage.py`：triage item 多一個 `thumbnail_url`（`creative.fields.thumbnail_url` → `image_url` → `None`，
  不另查詢、無平台分支）；`refresh_queue` 新寫入的 `action_url` ＝ `…/detail?ad=<entity_id>`，既有開放列不改寫。
- 詳情頁的「去處理」不使用 `action_url`（那會指回本頁），在六步流程改版前連到工作區 `?tab=performance`。
- 佇列讀取失敗不拖垮詳情頁（只少「去處理」按鈕）；沒有停損／變差時展開第一個有廣告的分類。

### 6.21 F21 — 資料連線頁（settled 2026-09-22）

Route `/brands/:brandId/ads/connections` (`components/ads/connections/`), v7 `connections()`. The frontend composes
existing GETs — no aggregation endpoint, no backend change (`app/orders` is legacy and may not gain capability).
One card per source; one failed GET fails only its card. Rules (each checked against the code that produces the field):
- accounts: bound = accounts whose `bound_brand_ids` include the brand; 0 → warn 「尚未連接」; else ok. No expired-auth
  state — the backend has no such data (gap).
- budget: `amount === null` → warn 「尚未設定」; `currency === null` → warn 「預算待核實」; else ok. `uncertainties` never
  make the card warn (almost always non-empty, not fixable from this button).
- orders: latest = first NON-NULL `order_date` on page 1 (`ORDER BY order_date DESC` puts NULLs first); before
  yesterday → warn. Dates compare as local-calendar `YYYY-MM-DD` strings, never UTC getters.
- products: only `status === "active"` rows that are not another row's parent (the set the product page shows).
- history: requested only with ≥ 1 bound account (the backfill GET answers 409 otherwise).
- header N = warn cards + failed cards. Button emphasis: warn → `outline`, ok/neutral → `ghost`; ok label 「查看」.
Not built: shell header 「最近同步・N 項待處理」 (no brand-level sync endpoint); `last_pull_at` is a `min()` that ignores
never-pulled accounts.

### 6.22 F22-I01 — Queue row `proposal` and change item `platform_url`（settled 2026-09-22）

Two read-only payload additions for the v7 停損提案三步流程 (F22-I02/I03); no migration, no platform write, no new
route. Neither field is stored — both are computed at read time on every call.

- `app/ads/triage.py::_queue_payload` (`GET/POST .../queue`): every open row gains `proposal`. `null` on a `worse` row
  unless a review round matches (F23-I01, below). On a `stop_loss` row: the newest (`created_at DESC`)
  non-superseded `ads_change_set` of the row's own campaign whose items include a `pause` item targeting
  `triage.entity_id` (`_matching_pause_set`) — `null` when there is none. That set "counts" (returns a `proposal`)
  unless: it's `deferred` and its own `revisit_at <= now()`; it's `rejected` and its `created_at` calendar day (UTC)
  falls outside the row's current `triage.window.start..end`; or its matching item's `verification_state` reads back
  `confirmed` while the entity's own `ads_external_entity.native_status` is no longer `"PAUSED"` (triage itself never
  reads `native_status` — `triage.py:228-307` — so a re-enabled ad needs the row to read as if there were no
  proposal, not a stale `confirmed` one). When it counts: `{change_set_id, campaign_id, kind, status,
  verification_state, reason, revisit_at, multi}` — `kind`/`verification_state` are the matching item's own,
  `reason` is the set's `decision_reason`, `multi` is `len(items) > 1` (a multi-item set is not rendered by the
  three-step pages; the row links to the campaign workspace instead).
  Three queries for the whole brand, never per row: every non-superseded change set (grouped by `campaign_id` in
  Python), every `ads_action.verification_state` of the brand, and `native_status` for exactly the `stop_loss` rows'
  own entities (only a `confirmed` match ever reads it).
- `app/ads/change_control_data.py::get`: every item view gains `platform_url: str | None`, computed from the item's
  own `target` through `app/ads/adapters::platform_url(target)` — a one-line dispatch on `target["platform"]`, lazily
  importing `app/ads/adapters/meta_read.py::platform_url` (same lazy-import seam `channels.py::external_reader`
  already uses, to dodge the `adapters/__init__.py -> manual.py -> change_control_launch.py ->
  change_control_data.py` import-time cycle). Meta: `https://adsmanager.facebook.com/adsmanager/manage/
  {campaigns|adsets|ads}?act={source_account}&selected_{campaign|adset|ad}_ids={native_id}` — `null` when the native
  kind isn't one of those three, or `native_id`/`source_account` is missing. Unknown platform → `null`. Never written
  to `plan_json`; no hash (`content_hash`, `premise_hash`) ever depends on it. `null` → the "↗ 打開平台" button is
  replaced by the target's own name + native id + 「複製編號」 (F22-I03).
- 驗證：`app/tests/test_ads_triage_queue.py::QueueProposalTest`（null／draft／approved-pending／confirmed 及其失效／
  rejected 在窗內外／deferred 過期／superseded／別支廣告的清單／別個活動的清單／multi）、
  `app/tests/test_ads_change_control.py::ChangeControlPlatformUrlTest`（meta 目標有連結／未知平台是 `null`／
  `content_hash` 不受影響）。
- F23-I01 加做：`worse` 列的 `proposal`（`_row_review_proposal`）——這支廣告在目前 triage 窗內（`window_end` 落在
  `[triage.window.start, triage.window.end]`，因為窗尾每天在動，不能用精確相等）最新一筆 `ads_review_round`；沒有就
  `null`。有的話：`{kind:"review", review_id, status, decision, reason, revisit_at, recommendation_id, change_set_id,
  change_set_status, verification_state, multi}`——`status/decision/reason/revisit_at` 是這回檢討自己的欄位；
  `recommendation_id` 是 `result_json.recommendations[]` 第一筆 `recommendation=="adjust"` 的 `id`，沒有就 `null`；
  `change_set_id/change_set_status/verification_state/multi` 來自最新一筆非 superseded、`plan_json.review_id` 等於
  這回 `id` 的變更清單（`change_control.py::create` 把 `review_id` 平放進 `plan_json`，跟
  `review_evidence.py:276`／`change_control_data.py:279` 讀法一致），沒有清單時四者皆 `null`／`false`。一次品牌查
  `ads_review_round`（`_brand_review_rounds`，依 `created_at DESC` 分組成 `(campaign_id, entity_id)`），複用 F22-I01
  已經查好的 `sets_by_campaign`／`action_states`，不新增查詢。驗證：
  `app/tests/test_ads_triage_queue.py::QueueReviewProposalTest`（無回合／queued 無清單／ready 取第一個 adjust
  建議／ready 無 adjust 建議／completed 帶文案清單／completed 無清單／deferred／unjudgeable／failed／窗外不匹配／
  `stop_loss` 列不受影響）。
- 前端型別跟進：`frontend/src/lib/adsTriageApi.ts::QueueProposal` 改成 `kind` 判別聯集——`QueuePauseProposal`
  （`kind:"pause"`，欄位跟改動前一樣）／`QueueReviewProposal`（`kind:"review"`，欄位同上一條）。
  `home/status.ts::proposalAction` 先用 `proposal.kind` 窄化：`review` 分支照 feature Decisions "Queue row state
  for `worse` rows" 給 label／連結（none→看證據；queued/running→整理證據中；waiting→資料不足；failed/unknown→
  證據沒整理成；ready→等你決定；completed 帶文案清單→組一個 `QueuePauseProposal` 重用停損那支 switch 算出
  label／連結，指到 `changes/:change_set_id/<step>`；completed 無清單→選方向／`reviews/:id/prepare`；deferred→
  「M/D 重看」done；unjudgeable→無法判定 done）；`pause` 分支欄位型別不變，原本的 switch 邏輯／輸出沒有變動。
  沒有提案時（`proposal===null`）靠新增的第 5 個選填參數 `kind`（預設 `"pause"`）分流，既有 4-arg 呼叫點
  （`home/QueueRow.tsx`／`detail/CampaignDetailPage.tsx`／`flow/VerifyPage.tsx`，這批仍只對 `stop_loss` 呼叫）
  不用改。`isQueueItemDone` 現在也覆蓋 `worse` 列。`home/QueueRow.tsx` 這批還沒把 `worse` 列接上這支 helper
  （沿用既有的 `action_url`／靜態「看證據」）——邏輯已備妥、驗證見
  `home/DecisionQueue.test.tsx`（review 分支的 `proposalAction`／`isQueueItemDone` 直接單元測試，未透過畫面）。

### 6.23 F22 — 停損提案三步流程（settled 2026-09-22）

Routes (`components/ads/flow/`, v7 `confirmPage()`/`handoff()`/`verify()`): `/brands/:brandId/ads/campaigns/:campaignId/
propose/pause/:entityId` (no change set yet) and `.../changes/:setId/confirm|handoff|verify`. A page opened on the wrong step
redirects to the step the set is in (`flow/changeFlow.ts::stepFromChangeSet`). Only `pause` has an entry this batch (home
stop-loss row / detail 「去處理」, `home/status.ts::proposalAction`); the pages render `budget`/`copy` sets too.
- Draft is created lazily on the first write (核准／拒絕／暫緩), reusing `proposal.change_set_id` when the row has one;
  `operation_id = triage-pause:<entityId>:<uuid held in page state>` so a lost response is retried with the same body.
  A refused approve (409) rebuilds once with a new `operation_id` + `supersedes_id`, then asks again.
- Step rule: draft → confirm; rejected/deferred/superseded → confirm, closed; approved + pending + `reported_at` null →
  handoff; pending with `reported_at` (read-back found the old setting) → verify 「平台上還是原本的設定」; reported/unknown →
  verify 「核對中」; confirmed/deviated/stale → verify ok/warn/bad. 「讀回於」 = `evidence_json.observed_at`. Rail cells
  only from real fields (設定相符 = `setting_matches === true`); 花費停止／學習期／品牌學習 cells are omitted (no data).
- Handoff: 「打開平台」 = `platform_url` (§6.22) in a new tab, else name + native id + 「複製編號」; tick state is local;
  「我做完了」 = `report` then `check`, navigating to verify even when `check` fails.
- Gaps kept honest: brand-learning tags = one `ReservedSlotCard`; `adoptPlatform` waits for the copy step (batch B);
  a multi-item set links to the campaign workspace. Home 「N 件」 counts only rows whose proposal is not done.
- Kit: `patterns/FlowPieces.tsx` (FlowHeader, KindMark, Meter, TodoRow, ResultHero, StatusRail, Segmented,
  DecisionSheet, ActionBar); `frontend/scripts/ui-evidence.cjs --acts` reaches later prototype steps.
- 驗證：`frontend/src/components/ads/flow/*.test.tsx`、`home/DecisionQueue.test.tsx`、`AdsHomePage.test.tsx`、
  `detail/CampaignDetailPage.test.tsx`；並排證據 `.harness/scratch/F22/I0{2,3,4}/`。

### 6.24 F23 — 變差廣告六步流程的前三步（settled 2026-09-22）

Routes (`components/ads/review/`, v7 `review()`/`prepare()`/`copy()`): `.../review/:entityId` (entry from a 變差 row: uses
`proposal.review_id` when present, else `createReview` with the row's triage window — the window end moves daily, so the
round is never re-created from the window alone) → `.../reviews/:reviewId` (看證據) → `/prepare` (選方向) → `/copy` (改文案) →
F22 `changes/:setId/confirm`. Step logic in `review/reviewFlow.ts`.
- Round states: queued/running → async card with polling; waiting → 「資料還不夠」 + `waiting_reasons` (never advances by
  itself); failed/unknown → error card, no retry (evidence dedupe returns the same round); ready → evidence; deferred /
  unjudgeable → closed, 改變決定 offers only 暫緩／無法判定 (`completed` is legal only from `ready`).
- Evidence cards: AI 建議 = first recommendation (title by kind, why = `hypothesis`, 依據與風險 = `risks` + `next_step`);
  這則廣告 = 花費 (sum of `series` with `metric_scope == "ad"`, mirrors `triage._ad_spend`), 成果數／單次成本 from the
  `result_views` ad entry — ROAS omitted; 商城訂單 from `commerce.*.order_summary` (`coverage` is a constant, the warn chip
  keys on `unknown_*_count > 0`).
- 選方向: 只改文案／先觀察 (deferred, requires `revisit_at`)／停掉這則 (→ F22 propose/pause); 換一張圖／用現成素材 are reserved
  cards; the ladder 改文案→換圖→退役 is a grey placeholder (decision A, 2026-09-22: no per-creative handling count yet).
- 改文案: 目前 from `creative_snapshot.copy_fields`, 新版 from `suggested_copy`; createChangeSet sends only non-empty
  fields, the review pair only when the recommendation is `adjust`; `operation_id = review-copy:<reviewId>:<uuid>`.
- Queue `proposal` for `worse` rows (`kind:"review"`, §6.22) drives `home/status.ts::proposalAction`; the confirm page's back
  button becomes 「修改內容」 for a copy set carrying `review_id`.
- Kit: `patterns/ReviewPieces.tsx` (EvidenceRow, Ladder, OptionCard, CopyBlock); `ui-evidence.cjs --settle`.
- 驗證：`frontend/src/components/ads/review/*.test.tsx`、`flow/ConfirmPage.test.tsx`、`home/DecisionQueue.test.tsx`；並排證據

### 6.25 F24-I01 — `data` 唯讀擴充：`triage`／`campaigns` 卡片帶同步狀態（settled 2026-09-22）

`triage.classify()`（因此 `GET .../triage`）新增 `data: {sync, coverage, missing_days}`；`repository.py::list_campaigns` 每張卡另加
`data: {sync}`——同一支 `repository.py::campaign_sync_state`（`_bound_account_ids`／`_campaign_disconnected` 私有輔助），不建 migration，
不打平台。`sync.state` 判斷順序（優先序固定）：`never`（`context_json.external_sync` 完全沒寫過）／`disconnected`（活動任一
`(platform, source_account)` 不在 reader 的已綁定帳戶——純 DB 讀，跟 `external_repository.external_view` 的 `connections` 同一種檢查，
只是換一個地方算，因為 `external_repository.py` 不在這張票的 touch 範圍內）／`failed`（任一 section `status` 是 `record_sync`
實際會寫的 `"error"`／`"partial"`——section 層級從沒有字面 `"failed"`，那個字專屬彙總後的 `sync.state`）／`syncing`／`ok`。
`error` 取第一個失敗 section 自己的 `error`（固定用 `structure`／`creatives`／`observations` 順序當 tie-break，因為 Python `set`
與 Postgres jsonb 鍵序都不保證順序）；`last_success_at` 取三個 section 裡最新的一個——失敗的那次同步保留舊值
（`external_repository.record_sync`），所以 `state` 是 `"failed"` 時這個時間可能是舊的，不代表「剛剛」。
`coverage`／`missing_days` 只在 `triage` 的 `data` 出現，用 `classify()` 判每則廣告的同一個視窗（`cutoff` 往回
`WINDOW_STEPS[-1]`＝28 天）；`missing_days` 是這個視窗裡落在 `coverage` 之外的日期，`coverage` 為 `null` 時固定回 `[]`
（那個情境已經由 `sync.state === "never"` 表達，不用一長串缺日期）。
- 前端型別：`adsApi.ts::CampaignCard.data`／`adsTriageApi.ts::CampaignTriage.data`，共用 `CampaignSyncState`。兩者都設成選填
  （`data?:`）——`do_not_touch`（`frontend/src/components/ads/**/*.tsx`）在 harness 的 `scopeDenial` 比 `touch` 的
  `**/*.test.tsx` 先判定，蓋掉了原本該給、可以改測試 fixture 的例外，既有的手寫 `*.test.tsx` fixture 補不了這個必填欄位
  （同 `CampaignCard.labels?` 的先例）；下一張碰這些畫面的票要嘛拿到能編輯這些檔案的授權，要嘛在讀取端對 `data`／`data.sync`
  做 optional-safe 讀取。
- 驗證：`app/tests/test_ads_triage.py::TriageDataViewTest`、`app/tests/test_ads_repository.py::ListCampaignsSyncDataTest`。
  `.harness/scratch/F23/I0{2,3,4}/`.

### 6.26 F24 — 異常狀態、等待頁、每月回顧、頁首同步晶片（settled 2026-09-22）

Data source = the read-only `data` block of §6.25 (sync state / coverage / missing_days) plus existing GETs; nothing new is
stored. Decision A (user, 2026-09-22): existing facts only — no per-campaign health table, no 「系統剛恢復」 banner (no signal).
- Home card (`home/CampaignCard.tsx`): `sync.state` failed/syncing/disconnected → grey 「暫時讀取不到」 card (chip by state;
  重新讀取 = existing `syncCampaign({})` + job poll until status ∉ {pending, running} + reload; disconnected → 去連接); otherwise
  「資料不足，先不判斷」 when every classified ad is `insufficient` or `missing_days` is non-empty (chip: 缺 N 天資料 /
  尚未同步成效 / by dominant `reason_code`); `no_target`-only campaigns keep the 設定目標 card.
- Header chip (`AdsHomePage.tsx`): newest `last_success_at` among campaigns with `state === "ok"` only (a failed sync keeps its
  old timestamp), links to connections. (F47, §6.49.2: the warning moved to the top bar as 「N 個資料來源要處理」 = the
  connections page's own count; 「N 項待處理」 = `status_summary.open_items`, the home board's not-done rows.)
- Wait page `/brands/:brandId/ads/campaigns/:campaignId/wait` (`components/ads/wait/`): rows only for existing facts —
  disconnected, missing days, orders latest date before `coverage.end` (F21 rule), and one row per insufficient `reason_code`
  (below_sample_gate / no_previous_window / result_unknown_days); `DayTiles` over the 7 days ending at `coverage.end`;
  重新檢查 = the same sync + poll.
- Monthly review `/brands/:brandId/ads/month` (`components/ads/month/`): budget card by selected month (`known_spend` null →
  花費未核實; `amount` null → hatched); orders card labelled with the stats window (`until − 30 … until`); campaign rows sum
  triage `current.spend` only when every ad shares `window.days`, else 「各廣告期間不同，未合計」, no currency; 素材 groups by
  triage class, ≤ 12 tiles + 「＋N 則」; 記入品牌學習 and 下月建議 are `ReservedSlotCard`s (no brand-level learnings GET, no
  suggestion backend).
- Kit: `patterns/ReviewPieces.tsx::DayTiles`, `ResultHero mark` prop. 驗證：`home/CampaignCards.test.tsx`,
  `AdsHomePage.test.tsx`, `wait/*.test.tsx`, `month/*.test.tsx`; 並排證據 `.harness/scratch/F24/I0{2,3,4}/`.

### 6.27 F25-I01 — 佇列剩兩種 kind 落地：program rules A/B、佇列 payload 擴充（settled 2026-09-22）

Two new program rules over the same per-ad `classify()` (`app/ads/triage_scale.py`, kept separate to hold `triage.py`
under its own file-size convention); both pure reads (no LLM call, no platform write). `app/core/interrupts.py
::CATEGORIES` 新增兩筆（本票對這支舊檔唯一允許的改動，登記在 F18 兩筆之後）：`ads_triage_scale_budget`／
`ads_triage_refresh_creative`，兩者皆 `severity=informational`。`QUEUE_CATEGORY`／`KINDS_AVAILABLE`（四種）／
`KINDS_PENDING`（`[]`）同步更新；四種 kind 共用同一套 `interrupt` 去重／supersede 機制（`_supersede_stale_open_rows`
不分 kind），沒有另立第二套。

- **Rule A `scale_budget`**（每個預算 owner，即 `budget_type=="daily"` 且 `budget_amount` 非空的 `ads_external_entity`
  —— 廣告組，或活動自己扛預算時的活動本身）：只看這個 owner 名下**目前活躍**的廣告（`native_status` 不在
  `{PAUSED,DELETED,ARCHIVED}`——停損流程暫停掉的廣告不永久卡住整個 owner）；每支活躍廣告都要是 `better`／`flat`（任何
  其他 class 都讓這個 owner 整批不出列）；至少一支活躍廣告；**不跨廣告合併**（各廣告 `window.days` 不同，
  `triage.py:298-320`）——逐支廣告自己的 `current.cost_per_result` 與 `previous.cost_per_result` 都要 `<= target`；
  不要求一定要有 `better`（長期穩定的全 `flat` owner 也合格）；活動要有 target。提案：`to = ceil(from * 1.2)`（owner
  自己的幣別）；只有 `month_budget.view(conn, org, brand, month, additional=[提案 item])` 回傳 `available` 非空
  且 `>= 0` 才出列——跟 `preflight()` 核准時走的**同一條**路（`month_budget.py:466-470`），列跟核准永遠不會打架；
  `extra_needed` = 帶提案跟不帶提案兩次 `reserved_increases` 的差。去重鍵 `ads-triage:scale_budget:<owner_id>
  :<window_end>`。items 本身不帶 `parent_native_id`（見下「已知缺口」），owner 查找是這批唯一一次品牌全域查詢
  `ads_external_entity`（`triage_scale.py::_owner_lookup`）：廣告的 parent 是廣告組且該廣告組扛日預算 → owner；
  否則退回看活動自己是否扛日預算 → owner；否則沒有 owner，這批廣告整批跳過（lifetime 預算 owner 永遠不合格）。
- **Rule B `refresh_creative`**（每個有 target 的活動）：只要有任何一支廣告（不分活躍與否）讀回
  `reason_code=="needs_resync"` 就整個活動跳過（資料缺口不是素材不夠，那是「資料不足」卡片的地盤）；
  `readable` = 活躍廣告中 class 屬於 `better|flat|worse` 的數量；`readable <= 2` 且活躍廣告 `>= 3` 才出列。去重鍵
  `ads-triage:refresh_creative:<campaign_id>:<window_end>`。沒有變更清單，列的按鈕直接去素材工作檯。
- **佇列 payload**：`_queue_payload` 每列多一個 `kind_key`（四選一，跟 `interrupt.category` 對應但給前端直接判斷
  用，不用解析 `dedupe_key`）；`scale_budget` 列多帶 `scale: {owner:{id,name,native_kind,native_id,ads_count,
  currency}, from, to, cost_per_result, previous_cost_per_result, target, window_days, month:{available,
  extra_needed}}`（`triage` 欄位是這個 owner 名下最好的 `better` 廣告 item，沒有就用第一支活躍廣告）；
  `refresh_creative` 列多帶 `refresh: {campaign_id, campaign_name, readable_count, classified_count, thumbnails}`
  （`thumbnails` 最多 4 個，`null` 表示這支廣告沒有縮圖；`triage` 是第一支可判讀廣告，沒有就是第一支活躍廣告——
  Rule B 的門檻保證至少有 3 支活躍且已分類，永遠不會是 `null`）。`scale_budget` 列的 `proposal` = 這個 owner 所屬活動
  裡最新一筆非 superseded、items 含 `kind=="budget"` 且 `target_id` 等於 owner id 的變更清單，跟停損提案同一種形狀
  （`_matching_change_item` 把 F22-I01 的 `_matching_pause_set` 依 `kind` 參數化，`pause`／`budget` 共用同一段
  walk）；`refresh_creative` 列的 `proposal` 永遠 `null`。
- **Meta adapter 修正 —— ABO 不動 schema（2026-09-22 裁決）**：`ads_external_entity.budget_type` 欄位是
  `NOT NULL DEFAULT 'unknown' CHECK (... IN ('daily','lifetime','unknown'))`
  （`supabase/migrations/20260918000001_ads_external_sources.sql`），`ExternalEntity.budget_type` 也是
  `Literal["daily","lifetime","unknown"]`（不含 `None`）——這兩個檔都不在本票 `touch`，真的寫 `budget_type=None`
  會讓每個 ABO 活動的結構同步在 `ExternalEntity.model_validate()` 直接炸掉。改用不動 schema 的訊號：
  `meta_read.py::_entity` 對「活動物件的 raw payload 既沒有 `daily_budget` 也沒有 `lifetime_budget`」（依 Meta API
  語意即廣告組扛預算的 ABO 活動）繼續寫 `budget_type="unknown"`（不變），只多加一個
  `budget_raw.owner="children_verified"` 標記；廣告組（`adset`）永遠不打這個標記（這個訊號只講活動自己缺預算，不
  帶到任何手足層級）。`month_budget.py:151-161` 的委派條件相應放寬成 `budget_amount is None and budget_type in
  (None, "unknown") and budget_raw.owner == "children_verified"`——`None` 留給 `calculate()` 既有的純函式 fixture
  相容（它從不經過 DB／pydantic），`"unknown"` 才是真正的 writer 路徑；一般「從沒同步過」的 `unknown` 列沒有這個
  標記，照樣落回原本的不確定判定，不會被誤判成已委派。`_entity()` 是 `read_structure()`（正式結構同步）直接呼叫的
  函式；`verify_native()` 走的是另一條局部讀回路徑（`_verified_snapshot`），它的「局部讀回不可抹掉既有值」規則會在
  raw 沒有任何預算欄位時整批濾掉 `budget_type`／`budget_raw`，所以驗這個訊號要測 `_entity()` 本身，不能透過
  `verify_native()`。
- **已知缺口（誠實揭露，feature Decisions "Gaps kept honest"）**：「這則主打什麼？」標籤仍是 `ReservedSlotCard`；
  `lifetime` 預算的 owner 永遠不會出 `scale_budget` 列；不跨廣告或跨幣別合計；items 不帶 `parent_native_id`，owner
  對應改由一次品牌全域 `ads_external_entity` 查詢完成（見上）。
- **前端型別跟進（本票只做型別，未做畫面——`home/QueueRow.tsx` 等產出畫面留給 I02）**：
  `frontend/src/lib/adsTriageApi.ts` 新增 `QueueKind`、`QueueBudgetProposal`（`kind:"budget"`，跟
  `QueuePauseProposal` 同形狀）、`QueueScale`／`QueueScaleOwner`／`QueueRefresh`，`QueueItem` 新增必填
  `kind_key` 與選填 `scale?`／`refresh?`；`frontend/src/components/ads/**/*.test.tsx` 下 9 支既有測試檔
  （`AdsHomePage.test.tsx`、`detail/CampaignDetailPage.test.tsx`、`flow/ConfirmPage.test.tsx`、
  `flow/HandoffPage.test.tsx`、`flow/VerifyPage.test.tsx`、`home/DecisionQueue.test.tsx`、
  `review/CopyPage.test.tsx`、`review/PreparePage.test.tsx`、`review/ReviewEvidencePage.test.tsx`）的
  `queueItem()` 假資料工廠各補一行 `kind_key`（依各檔既有 `category` 對應 `"stop_loss"`／`"worse"`；
  `home/DecisionQueue.test.tsx` 是共用工廠，`kind_key` 隨傳入的 `triage.class` 決定）。
- 驗證：`app/tests/test_ads_triage_scale.py`（Rule A/B 純函式，正例／每種反例／to 公式／paused 不卡 owner／
  ABO 委派廣告組 owner／CBO 退回活動 owner／`month_view` 呼叫次數）、`app/tests/test_ads_triage_queue.py
  ::ScaleRefreshQueueTest`（走完整 `refresh_queue`/`get_queue`：`kind_key`／`scale`／`refresh` 形狀、category／
  severity、跨窗 supersede、budget 提案配對）、`test_core_interrupts.py`（兩個新類別的 severity／label）、
  `app/tests/test_ads_external_monthly.py::AboMonthDelegationTest`（ABO 活動＋廣告組扛日預算，
  `month_budget.view()` 回傳非空 `available`；CBO 活動不變；沒有 `owner` 標記的普通 `unknown` 活動仍讀不確定）、
  `test_ads_external_monthly.py::MetaMonthlyContractTest::test_campaign_with_neither_budget_field_marks
  _children_verified_ad_sets_unchanged`（`_entity()` 直測：ABO 活動打標記、廣告組與 CBO 活動都不打）。
  `docs/verification.md` 既有共用命令未變。

### 6.28 F25 — 佇列的兩種新列：可加預算（三步流程）與補素材（settled 2026-09-22）

Frontend of the rules in §6.27. Queue order is the existing `interrupts._sort_key` (severity, then category
registration order), so the two `informational` kinds sort after 停損／變差; `refresh_creative` rows are additionally
forced last and never count as done.
- `home/QueueRow.tsx` dispatches on `kind_key`: stop_loss/worse unchanged except the stop-loss button now reads 「看提議」
  (home only; the detail page keeps 去處理); scale rows show `KindMark up`, the owner name, a success Meter of
  `scale.cost_per_result` vs the target, and 「看提議」 → `propose/budget/:ownerId`; refresh rows show `KindMark fresh`,
  「能判讀的素材只剩 N 則」, up to four thumbnails (hollow placeholders to four) and 「準備新素材」 → the row's
  `action_url` (`?tab=assets&material_new=1`).
- `home/status.ts::proposalAction` gained the `budget` kind (null → propose route; with a set it reuses the pause
  branch) and `isQueueItemDone` the `scale_budget` branch.
- `flow/ConfirmPage.tsx` takes `proposeKind`; the budget evidence card is the prototype's: 同組 N 則, 每日預算 from → to
  +20%, cost meter, 「主力穩定 2 個觀察期」, 「加碼後等 3–5 天再看」, and the month-budget bar with the 這次加碼 segment.
  A 409 whose message is one of `month_budget.preflight`'s three is shown as-is (no rebuild); other 409s still rebuild
  with `supersedes_id`.
- `flow/changeFlow.ts::nextOpenQueueItem` is the single 「下一件」 rule for all four kinds; ConfirmPage and VerifyPage use it.
- 驗證：`home/DecisionQueue.test.tsx`, `AdsHomePage.test.tsx`, `flow/ConfirmPage.test.tsx`, `flow/VerifyPage.test.tsx`;
  並排證據 `.harness/scratch/F25/I0{2,3}/`.

### 6.29 F26-I01 — 判讀只看投放中的廣告、`closed` 唯讀擴充、「資料不足」佇列列（settled 2026-09-22）

實測根因（`brd_bughunt` 真資料，2026-09-22）：`triage.classify()` 選廣告只憑 `native_kind='ad'`（`triage.py:54` 舊版），
20 支廣告全部照判，但只有 5 支投放中（11 暫停、4 已封存）——首頁長條「資料不足 17」多數來自已關閉的廣告。同一時間
`month_budget.py:131` 已經排除五種狀態，`triage_scale.py:15`（F25）只排除三種，`triage.py` 完全沒排除——一個共用常數、
三個消費端各自抄一份會漂移。

- **共用常數 `app/ads/ad_status.py`**：`CLOSED_STATUSES = {PAUSED, DELETED, ARCHIVED, ADSET_PAUSED, CAMPAIGN_PAUSED}`
  （Meta `effective_status` 的原生詞彙，平台中立檔案，不匯入 adapter）、`is_closed(status)`——`None`（未知）永遠不算已關閉。
  `triage.py`／`triage_scale.py`（取代自己的三值集合）／`month_budget.py`（取代自己內嵌的五值字面集合，行為完全不變）
  三個消費端改為 import 這一個定義。
- **`triage.classify()`**：只判讀 `native_status` 不是已關閉的廣告（`items`）；`closed` 區塊帶回其餘廣告——
  `{paused, archived, other, total, items, truncated}`。`paused`／`archived` 各自算，`DELETED`／`ADSET_PAUSED`／
  `CAMPAIGN_PAUSED` 併進 `other`（`paused+archived+other===total` 恆成立）。`items` 每筆
  `{entity_id, name, native_status, thumbnail_url, spend, cost_per_result, result_label}`，數字取自同一支
  `classify()` 已經讀過的 `ads_external_daily`（`_ad_window`，跟活躍廣告同一次讀，不多打第二次查詢）——固定用最寬的
  `WINDOW_STEPS[-1]`（28 天，跟 `classify()` 自己回的 `window_days` 一致）；沒有資料的那支廣告 `spend`／
  `cost_per_result` 就是 `null`，不當機。`items` 上限 50 筆（同一次活動廣告查詢的 `(name, id)` 排序），超過時
  `truncated=true`。`counts`／`total_ads`（`_queue_payload`）因為只吃 `items` 自動變成只算活躍廣告，程式碼本身不用改。
- **「資料不足」佇列列**：新類別 `ads_triage_insufficient_data`（`app/core/interrupts.py::CATEGORIES`，本票對這支
  舊檔唯一允許的改動，`severity=rule_warning`、label「活動資料不足待處理」，登記在既有 `rule_warning` 之後）。
  `triage.py::_insufficient_candidates`：每個非結案活動、至少一支活躍廣告（`by_campaign` 本身就只含活躍廣告的
  triage item，天然滿足這個門檻）、`data.missing_days` 非空或 `data.sync.state` 屬於
  `{"failed","disconnected"}`（複用 `classify()` 同一套 `_data_view`，不碰 `ads_external_daily`，成本低）就出列。
  `window_end` 用這個活動自己的帳戶 cutoff（跟其他列一樣每天往前移，去重鍵隨之翻新）；去重鍵
  `ads-triage:insufficient_data:<campaign_id>:<window_end>`。payload：`kind_key:"insufficient_data"`，
  `insufficient:{campaign_id, campaign_name, missing_days, sync_state, coverage}`；`triage` 是第一支活躍廣告的
  item；沒有變更清單，`proposal` 恆為 `null`，按鈕留給前端接到既有 F24 等待頁
  （`/brands/:b/ads/campaigns/:c/wait`）。`QUEUE_CATEGORY`／`KINDS_AVAILABLE`（五種）／既有 supersede 機制
  （`_supersede_stale_open_rows` 迴圈 `QUEUE_CATEGORY.values()`，本來就不分 kind）同步更新，沒有另立第二套。
- **前端型別跟進（本票只做型別，未做畫面——`home/CampaignCard.tsx`／`detail/CampaignDetailPage.tsx`／
  `home/QueueRow.tsx`／`home/status.ts`／`month/MonthReviewPage.tsx` 等產出畫面留給 I02／I03）**：
  `frontend/src/lib/adsTriageApi.ts` 新增 `TriageClosedItem`／`TriageClosedBlock`，`CampaignTriage.closed` 設成必填
  （後端永遠會帶，不像 `data` 有 `do_not_touch`-vs-`touch` 衝突要留選填）——`frontend/src/components/ads/**/*.test.tsx`
  下既有手寫 `getTriage()` fixture（`detail/CampaignDetailPage.test.tsx`、`home/CampaignCards.test.tsx`、
  `month/MonthReviewPage.test.tsx`、`wait/WaitPage.test.tsx`）各補一個空 `closed` 區塊。`QueueItem` 新增選填
  `insufficient?: QueueInsufficient`；`QueueKind`／`QueueItem.kind_key` 這次刻意**不**收 `"insufficient_data"`——
  `home/QueueRow.tsx` 等既有消費端拿它當 `Record<QueueKind, ...>` 的窮舉鍵，不在本票 `touch`，貿然加值會逼著改那些
  檔案；產出這一列畫面的票再一起把 `QueueKind` 加寬、把那些 `Record`／`switch` 補上第五個分支。
- **已知缺口（誠實揭露）**：沒有「關掉時間」（Meta entity payload 沒有這個欄位），`closed` 區塊不含任何日期；
  已關閉廣告的畫面呈現（清單、摺疊、「看紀錄」連結）與「資料不足」列的畫面呈現都留給後續 I02／I03。
- 驗證：`app/tests/test_ads_triage.py::AdStatusTest`／`TriageClosedAdsTest`（5 活躍+11 暫停+4 已封存的實測形狀、
  `null` 狀態仍判讀、`other` 桶、items 上限＋`truncated`、無資料廣告不當機）、
  `app/tests/test_ads_triage_queue.py::InsufficientDataQueueTest`（缺天／同步失敗／斷線都出列、沒有活躍廣告不出列、
  同窗去重、恢復後 supersede）、`test_ads_triage_scale.py`（`ADSET_PAUSED` 現在也排除 Rule A／B，舊三值集合抓不到
  的反例）、`test_core_interrupts.py`（新類別 severity／label）。`cd frontend && npm run build`／
  `npm test -- src/components/ads`。

### 6.30 F26 — 只判讀投放中的廣告（前端）與「資料不足」佇列列（settled 2026-09-22）

Reference: `docs/design/ads/prototype-v8-active-only.html` (user-approved 2026-09-22). Backend rule and payload: §6.29.
- `home/CampaignCard.tsx`: the count chip reads 「<目標類型>・投放中 N 則」; the five-class strip and legend cover active ads
  only; a bottom line 「另有 N 則已關閉（暫停 X・已封存 Y），不列入判斷」＋「查看 →」 (omitted when `closed.total === 0`).
- `detail/CampaignDetailPage.tsx`: purpose line 「只判讀投放中的 N 則；已關閉的廣告保留紀錄，不列入判斷」; class groups from
  active ads; a grey collapsed 「已關閉」 group listing `closed.items` with an 已暫停／已封存 chip and 「看紀錄」 →
  `?tab=performance&ad=<entityId>` (user decision A: no new page; the tab does not yet scroll to the ad). A campaign whose ads
  are ALL closed shows that group instead of the empty state.
- `home/QueueRow.tsx` + `status.ts`: the `insufficient_data` row — KindMark warning, 「這個活動暫時無法判斷」, `DayTiles` over
  the 7 days ending at `insufficient.coverage.end` with `missing_days` hollow, captions 「缺 M/D、M/D」 and the sync state,
  「去處理」 → the wait page; never done.
- `month/MonthReviewPage.tsx`: 素材 groups are 有效 = active `better`, 無效・已停 = `closed.items` (count `closed.total`),
  還看不出 = active `flat`+`insufficient`; no 「這個月關掉 N 則」 line (no closed-at date from the platform).
- 驗證：`home/CampaignCards.test.tsx`, `home/DecisionQueue.test.tsx`, `detail/CampaignDetailPage.test.tsx`,
  `month/MonthReviewPage.test.tsx`; 並排證據 `.harness/scratch/F26/I0{2,3}/`.

### 6.31 F27 — 原型完全落地（settled 2026-09-22）

User ruling 2026-09-22 (「全部照建議」): every part of `prototype-v7-ads-center.html` / `prototype-v8-active-only.html` works on
real data; only Google Ads stays a grey card. Contracts below are the authoritative field shapes (the feature file's
contract text as corrected by its pre-dispatch challenge).
- A. Ladder & history (`app/ads/triage_ladder.py`): active triage items carry `ladder {step 0|1|2, copy_changes, image_changes,
  lineage_from}` and `history[]` (items that target this ad or its lineage; budget items excluded; cost 7 d before / after,
  null when < 7 known days). step 2 if an image replacement was confirmed, else 1 if a copy change was confirmed, else 0.
  Lineage: `ads_handoff_item.entity_id` of a confirmed new_ad item whose set carries `replaces_entity_id`.
- B. Copy variants: dynamic creatives edit as `{titles[], bodies[]}` (0–5 each, ≥ 1 non-empty); the Meta adapter parses
  `asset_feed_spec`, and `change_control_data.copy_fields` derives variants at READ time for creatives stored before the
  parser existed (`adapters.copy_variants`). `evidence_json.conditions.copy_editable {ok, mode single|variants, reason}` is
  computed at read time; catalog-only and carousel creatives are not editable. Verify compares variant sets order-free.
- C/D. Angles & learnings: `GET …/entities/{e}/angles` (one cached background LLM task per ad per copy hash, 3 phrases ≤ 12
  chars; e2e's scripted provider yields `failed` → 自訂 only). A pause item may carry `angle`; when it is confirmed,
  `ads_learnings.record_for_item` writes one learning after `check` commits (idempotent by item id; confidence by the count
  of earlier same-text learnings: observed → likely → validated). `GET …/learnings` lists them.
- E. Replacement: `POST …/new-ad-handoffs` takes `replaces_entity_id`; the set view exposes `replaces` and, after the new ad
  is confirmed, `follow_up {kind: pause_old}` until a pause set for the old ad exists. The review link is sent only for a
  `new_test` recommendation.
- F. Capacity & cleanup (`triage_capacity.py`): `capacity {daily_budget, currency, target, can_support = floor(daily ÷ (target × 2)),
  active_ads}` (daily_budget null if any active ad lacks a daily owner); cleanup row (`ads_triage_cleanup`, informational)
  proposes pausing the lowest 7-day-spend active ads (never a not-fully-covered ad or an open replacement lineage); refresh
  rows are suppressed while a cleanup row is open. A cleanup set is created with `source: "cleanup"` (pause items only).
- G. Month summary (`month_summary.py`): calendar-month spend/results of every ad (`metric_scope='ad'`, monthly-budget rows
  excluded), verdict met/missed/unjudged, orders like-for-like via the existing commerce evidence function, closed-this-month
  from `status_changed_at`, suggestions (refresh / cleanup / no target) with per-month dismissal in `context_json` (jsonb_set).
  Only imported campaigns are listed (internal campaigns report through `ads_outcome_daily`) — known limit.
- H. Timeline (`change_timeline.py`): read-time `spend_stopped` (pause, coverage-aware), `delivery_started` (copy/new_ad),
  `next_review_at` (budget approved + 3 d, copy/new_ad verified + 7 d). Nothing is scheduled; the daily queue refresh re-judges.
- I. Daily 06:30 `refresh_queue` for every brand; sync state `auth_expired` from the stored `permission_denied` code (raises
  the 資料不足 row); `GET …/status-summary` for the top bar; `campaign_objective` family (sales / engagement / traffic / other)
  on triage items, campaign cards, month summary and learnings — one function, `repository.campaign_objective_family`.
- J/K. `ads_runtime_event` (tenant-scoped: NOT NULL org_id and brand_id, per the isolation gates) holds a `beat` per active
  brand per minute and `queue_refresh`; `ads_external_entity.status_changed_at` marks active↔closed flips. `GET …/recovery`
  reports a > 120-minute gap of the brand's own beats ended within 24 h, with five steps (reconnect, permissions, per-section
  backfill, re-judge, re-check reported items).
- Screens: review ladder + non-sales 「這條素材的紀錄」; prepare recommends by ladder (observe overrides); material step page
  embeds the existing material/user-asset flows (known UX debt: those legacy panels are not v7-styled); copy page variants
  editor + observed prefill; flow pages render new-ad and multi-item cleanup sets, pause angles, learning card, timeline
  rail, 「改用平台現在的內容」; home thumbnails, CampaignChip, cleanup row, capacity chips, recovery banner; detail capacity
  card, mini ladders, own-row-only actions; monthly review fully live; top-bar sync chip; wait-page auth row; performance
  tab `?ad=` scroll with the disclosure opened.

### 6.32 一個上限、對上限分級、預算上限、核准失效出口、卡住的背景工作（ruled 2026-09-23；implemented by F28）
Drill 5 root causes R1／R2／R3／R6. Decided by the user in the 2026-09-23 /dig (the first four bullets) and taken as
reversible agent defaults in the same session (the last two). This section is the rule; the F28 feature file holds the
contract names. This section supersedes §6.14's trailing-30 fallback, §6.17's previous-window-only judgement, and every
earlier mention of `stop_loss` queue rows (§6.17, §6.18, §6.22, §6.23): no new `stop_loss` row is raised; a 白花 ad is
closed through the cleanup decision, whose interrupt `ads_triage_cleanup` now carries `money_loss` severity.
- **One cap per campaign, cost per result only** (screen word 上限). Stored once, in `ads_campaign.target_cost` with
  `target_basis='own'`; `success_metric`／`success_target`／`success_basis` are retired (columns kept, never read or
  written). Set only on the strategy tab — every campaign, imported ones included; every other screen shows it read-only
  with a link there. Triage, cleanup, scale-up, closeout and budget read this one value; ROAS is a reference, never a judge.
- **No cap:** the provisional cap is break-even from product economics (screen: 暫用打平 X). No product cost → no grading;
  the screen asks for a cap and links to entering the product cost. The trailing-30-day fallback is removed.
- **Grades against cap T** per active ad, with §6.17's window steps and sample gate: 划算 ≤ T; 偏貴 ≤ 1.2T; 太貴 > 1.2T;
  白花 = spend ≥ 3T with 0 results; below the gate = 還太新、看不準. The trend against the previous window is a note only.
  **Cleanup** is one decision per campaign (the stop-loss row folds into it): every 白花 ad closes; while active ads exceed
  capacity, 太貴 then 偏貴 close, most expensive first; 划算 never closes — when only 划算 ads remain over capacity, the
  proposal is a budget increase instead. **Scale-up** (+20 %) is offered for a budget owner whose graded ads are all 划算.
- **Budget cap is a soft warning** (`constraints_json.budget`): a scenario above it is never preselected, the 推薦 tag
  moves to 照預算上限, and choosing one needs an explicit confirmation the API checks and records, with the amount over
  shown on screen. The cap stays editable after the wizard, in any status (ruled 2026-09-25). It is an internal planning
  number: changing it never writes the platform, never changes the saved scenario, never makes a handoff stale, and never
  invalidates a confirmed experiment (the experiment snapshot keeps only `constraints_json.platform`). Scenario rows carry
  `over_cap` (0 = within the cap, null = no cap or the total is unknown); the 照預算上限 row is the second row. Edit:
  `PUT …/strategy/budget-cap` (internal campaigns only; imported ones have no scenarios).
- **Stale launch has an exit:** the handoff shows approved vs now; 用現在的方案重新核准 re-freezes the plan as a new
  version (verified, unchanged items keep their result; the month-budget check runs again); 改回核准時的設定 writes the
  approved values back after one confirm. Re-approval moves the platform bindings of unchanged items to the new version.
  The 上架紀錄 fields (platform ids, ad mapping, execution notes) are not part of the frozen content, so recording them
  never makes a launch stale. While a launch is stale, a material may be re-assigned (e.g. revised after approval) and
  then re-approved; a fresh approved launch still refuses re-assignment.
- **Stuck background jobs:** at worker start every interrupted job that is not read-only is re-queued once; a job
  interrupted a second time ends `failed` and is shown as failed. This replaces the earlier start-up rule that paid work
  is never re-sent (`app/worker.py`).

### 6.33 學習閉環、一把尺、拒絕記憶、畫面一致與 v10 詞彙（ruled 2026-09-25；built in F29）
Drill-5 items 4–10, decided by the user in the 2026-09-25 /dig; entries marked "default" were proposed and not objected
to. This section is the rule; the contract names lived in `.work/features/F29.md` (see Git history after close). It supersedes
§6.32's word 白花 (now **沒賣出**) and the F28 deferral that let 變貴 follow the trend.
- **Settle writes learnings.** One period is the calendar month in the org timezone (user ruling). Settling the last ended month grades, in one batch, every ad with enough sample against
  its own campaign's cap (imported campaigns included): 划算 → effective, 太貴／沒賣出 → ineffective; 偏貴 and below-sample
  ads are not written; an ad whose campaign has unsynced days keeps its grade (same as the month review) but is skipped with
  the reason 資料缺天，這期不記. The learning text carries no numbers, so repeated conclusions raise confidence. The user confirms each ad's angle on one page (three AI candidates, the first preselected, or
  their own words). Home shows 「結算上一期」 as a three-step to-do.
- **A/B on real data.** Automatic pairing stays (same ad set, exactly one coordinate differs) with its thresholds
  (7 days, 10 conversions each, 10 %); the simulated-only gate is gone. For real rows a day inside the campaign's
  recorded sync coverage with no row is a zero-delivery day; a day outside it keeps the pair unreadable. A pair has at
  most one open pause set (draft, deferred, or approved with no stale/deviated item). A judged winner produces a "pause the loser"
  proposal through the normal approval flow, and the result is written as a learning. No "declare a test" wizard.
- **One ruler.** Every judgement uses the cap grade. 變貴 means the grade moved from 划算 to 偏貴/太貴; the month
  review's 有效 counts 划算 only; the trend against the previous window is a footnote and no decision reads it.
- **Rejected cleanup memory.** The grade of each ad at the user's rejection is remembered; the ad is proposed again only
  when its grade gets worse, and the screen says so (「上次你拒絕時是偏貴，現在變太貴」). An ad the user unticked in a
  cleanup is remembered the same way. 「先不要」 on such a card in the month review uses the month's existing dismissal.
- **Screen consistency (defaults).** A failed read stays a failure on screen, never an empty state. One per-campaign
  "has data / why not" state feeds every section. Background progress reads the job queue and shows N of M, covering the
  ads jobs; the worker runs three jobs at once.
- **Cleanup and material requests (defaults).** Cleanup ticks every proposed ad; single ads can be unticked in the
  folded advanced area. A material request raised from an ad row is bound to that ad as "replace this ad".
- **Export and notification.** The period and the month review download as CSV (default). A daily digest of the
  decision queue goes to the in-app inbox only (right after the 06:30 queue refresh; the previous digest is closed each day, so the
  inbox holds at most the latest one); later channels (a per-user 「通知」 section in `/settings`, LINE Official
  Account, email; LINE Notify ended in 2025-03) plug in as one sender each behind the same digest builder.
- **Launch settings.** Optimization event, bid strategy, placement (automatic or manual), audience (age, gender,
  location) and pixel are choice fields with a preselected recommended value and a one-line plain note each; UTM stays
  text with a format check. Readback compares them with a Meta read. Read-only fields only: platform writes stay off
  (§6.4).
- **Left open after F28 (defaults).** Home shows an approved change waiting on the platform as a campaign-row state
  (「等你到 Meta 完成」／「等核對」) linking to the changes tab; the cap view carries the product cost so the break-even
  formula can be shown; with no cap, 推薦 falls back to a scenario whose amount is known.
- **v10 vocabulary.** 白花 is 沒賣出 on every screen. Next to a cost per result, a money tag 有賺／剛好打平（±2 %）／在虧
  against break-even sits beside the grade (grades stay against the cap: the user rejected renaming them 虧損/打平/獲利,
  because the cap and break-even are different rulers); it is hidden, never guessed, when the product cost is missing.
  Coined terms have one shared definition shown on the word itself (dotted underline), and every step flow has the same
  exit 「先不要，回投放中心」.
- **Not now.** In-app image generation stays a reserved seat (not a refusal); LINE/email; platform writes.
- **Known gaps after F29.** Past months in the month review show no 「當時給的建議／已採用」 (that history is not stored).
  The publish page got only its three v10 settings blocks (the full page followed in F30, §6.34).
### 6.34 其餘 v10 畫面、AI 說明被擋下、上架批次與一條素材規則（ruled 2026-09-25；built in F30）
Decided in the 2026-09-25 /dig and /carve; "default" entries were proposed and not objected to. The contract names lived
in `.work/features/F30.md` (see Git history after close). UI spec: `docs/design/ads/prototype-v10-ads-center.html` plus
`docs/design/ads/prototype-v10-ai-blocked.html`.
- **AI text blocked by the fact check.** A model reply that fails parsing, the size cap or the review policy leaves the
  round usable without an AI recommendation (`ready` with `rejected`); only a provider failure is `failed`. Direction and
  copy unlock (copy starts from the platform's current copy), and 「再請 AI 看一次」 re-runs the same evidence once
  more as a new round (never on a closed campaign). The fact check accepts 不足以／無法判斷／無法判定／未能 as negations;
  the digit rule stays.
- **New campaign.** Step 1 is a product + objective pick with dates and 「這個活動最多花」 — this campaign's spending cap,
  not the brand's monthly allowance (user ruling). A composed goal never carries a model-read cap. The free-text create stays
  in the step's 進階.
- **One objective catalog across platforms** (user ruling): 購買、名單、流量、知名度 are selectable; 互動、App 推廣、來店
  are reserved seats shown as 「尚未開放」. Each entry names its Meta and Google Ads counterpart. 加購物車 stays accepted
  as a sales optimisation event, not an objective. Drafts can only hold catalog objectives.
- **Launch batch** (default, user asked for the least-conflict option): only ads whose material is ready enter an approved
  launch; the others stay in the plan as deferred and go out with a later version. An ad an approved version already
  handed off never leaves the batch — invalid material blocks re-approval (F28 rule). Zero ready ads cannot be approved.
  Reason: the rule sits in the shared core, and an automatic platform publish cannot create an ad without a creative.
- **One material-readiness rule.** `change_control_launch.ready_material()` decides readiness for the launch batch, the
  slots, the overview and 下一步; an approved workbench pack or a manual 就位 tick without a confirmed material binding is
  progress, not ready. One freeze predicate (`material_frozen`) decides whether an ad can still receive material.
- **Readback.** One call reads back every built item of the batch, matching by exact name under the expected parent;
  a required field the platform read cannot see is confirmed per field by the user; a report can be withdrawn until verified.
- **Connections.** One row per bound account from its own sync state (never a minimum across accounts); a never-read
  account is not ok. Coverage is proven by pull ranges, not by spend rows, ends the day before a pull completed (account
  timezone), and survives a re-sync or a failed pull.
- **Workspace.** A six-station stage rail; the 14-day totals are null when any day in the window is unread. Features the
  prototype does not show moved into same-page 「進階」 folds; nothing was deleted.
- **One daily-budget total** (user ruling 2026-09-26): 「每日預算合計」 on the home row and the workspace counts only the
  daily budget owners that still have an active ad (`triage_capacity.capacity_view`); a group whose ads are all paused
  does not count. A draft still shows its plan's group total.
- **Known gaps after F30.** The publish page's 「第 V 版有改」 chip is not shown: launch items carry no "changed in this
  version" field. The workspace tab bar keeps the site-wide pill style (the prototype draws underline tabs).
- **A campaign keeps at least one delivery group** (user ruling 2026-09-26): `repository.delete_group` — the only
  group-removal path — refuses the last group (`last_group`, 409 「至少要留一個投放組；想換掉請先新增再刪。」) and the
  structure editor disables that 刪除 with the same reason. Adopt runs once, so zero groups after adopt had no way back.

### 6.35 P1 bug batch rules（ruled 2026-09-26；built in F31）
- **What ran, and on which coordinates** (user ruling): an ad's coordinates stay editable after dispatch. Learning never
  reads the ad's current coordinates or `adopted_output` after launch: `live_creative.record_launch` freezes, at launch
  approval, each batched ad's selected workbench outputs into `ads_ad.live_creative_json`, and learning coordinates are the
  dispatched set's `coordinates_snapshot_json` (an ad with no dispatched set uses its current coordinates). Readers:
  visual learning, experiments, A/B pairs, learning scope.
- **One image per ad.** An ads-dispatched image set holds at most its required number of selections (409
  `selection_full`, refuse, never swap); copy and free jobs keep multi-select. A version with its own ❌ check lines is
  selectable after an explicit confirm; round-level ❌ lines do not force the confirm.
- **Orders coverage** (user accepted the default): orders coverage ends at the later of the latest order date and the day
  before the latest import (org timezone). The wait page reads the connections `orders` source; it no longer derives a gap
  from the latest order date. Known risk: importing an old export last marks later empty days ok.
- **No name-match bind.** The ads-center `POST …/campaigns/{c}/bind` and every adapter `bind` verb are removed; launch
  readback (§6.34) is the only way a planned node gets its platform id. `bind` is no longer in `capabilities`.
- **Cross-org platform ids.** The Meta parent-id guard refuses an id another org holds, through two boolean-only
  `SECURITY DEFINER` functions that see past RLS: `schedule_channel_entity_owned_elsewhere` and
  `ads_external_id_owned_elsewhere` (registered by `app/ads/__init__.py` into `app.meta.repository`). A plain SELECT on a
  request connection cannot answer "does another org own this".
- **Brand delete.** `app/tests/test_cleanup_coverage.py` compares the cleanup registry with every live `brand_id` table
  (exempt on purpose: `llm_task`, `audit_log`) and derives the delete order from the database's FK constraints; a
  referrer that must outlive a cleared table needs an `ON DELETE` action (e.g. `ads_ad.product_id` → SET NULL).
- **Known gaps after F31.** `GET …/campaigns/{c}` still returns `live_creative_json` on each ad (internal column, not
  read by the frontend).

### 6.36 Campaign status on the manual path and settle-step state（ruled 2026-09-26；built in F32）
- **`live` = bound by readback** (user ruling A). `repository.bind_campaign`, the one readback binding point (§6.35),
  moves an internal campaign from `ready` to `live`; `live` means "a platform object is bound", never "delivering", and
  judgment copy keeps 不代表已投遞. The runtime health beat that emits `plan_date_passed` moves `live` to `ended`; nothing
  automatic writes `closed` (jobs rule: dates prompt a review, never close). Before F32 nothing wrote `live`/`ended` on
  this path, so `PerformanceTab`'s 結案 block never appeared and a hand-launched campaign could not write a learning.
- **Monitoring is not status-driven.** `runtime.dispatch` picks campaigns by `ads_external_entity` existence;
  `jobs.close_expired_campaigns` is a compatibility handler for already-queued jobs.
- **Settle steps are a query string.** `AppShell` re-keys on `pathname`, so a multi-step page that keeps client state
  across steps must vary `?step=` not the path; `/settle/:month/:step` stays as a redirect for stored `action_url`s.

### 6.37 Strategy starting point, available roles, Taiwan calendar（ruled 2026-09-27；built in F33）
- **The program states the starting point** (user ruling 1A): the strategy prompt carries a program-built
  【這個品牌的起點】 (asked advertising history, spend-history source, 90-day external clicks/purchases, loop purchases,
  cached pixels; 「不知道」 when unknown, never a guessed number) and a 【可用角色】 line. `retarget` is offered only when
  the brand has a retargeting source (`advertising_history = has_history`, or any external clicks or purchases); a reply
  naming an unavailable role is refused. The department example no longer shows a fixed three-role split. The ads module
  reads no order tables for this (it may not import `app.orders`); the prompt says so instead of assuming a buyer list.
- **Calendar is data, not prompt text** (user ruling 2A): `app/ads/calendar_tw.py` is a hand-maintained table (national
  holidays and makeup workdays from 人事總處, 學測／分科／會考／統測 from their centres, exam-week and commerce-peak
  conventions marked `source: "convention"`), covering 2026–2027. Strategy and delivery-plan prompts get only the entries
  overlapping the campaign period under 【投放期間內的行事曆】, and a coverage note when a year is outside the table.
  Extend the table yearly; nothing fetches it at runtime.
- **e2e scripted AI follows the prompt**: the scripted `ads_strategy`／`ads_delivery_plan` replies use the roles the
  prompt offers or adopted, so a fresh e2e brand runs with two roles.

### 6.38 食安法 statutory wording is a soft reminder（ruled 2026-09-27；built in F34）
- **The brand declares its regime** (user ruling 1A): `brand.regulatory_regime` (`'food_tw'` or NULL) is set by the user in the
  intake start step or the brand profile page. It is not inferred from facts, industry or product names; a brand with no
  regime gets no statutory check at all (the common flow stays industry-neutral).
- **Reminder, never a gate** (user rulings 2B + extra): matching wording in uploaded copy or generated copy produces a warning
  the user reads and can confirm past — no block, no fix round, no ❌, and no new prompt constraint (the user: more prompt
  limits make copy generic). Launch approval does not look at it.
- **The list is data, matched by program**: `app/workbench/statutory_tw.py` holds curated trigger patterns per statutory
  category (認定準則 §4 function／「健康」品名, §5 medical efficacy, 健康食品管理法 §6) with the article as `basis` and a source
  URL, plus 附件一's 「通常得使用之詞句」 verbatim as allowed phrases stripped before matching. The regulation defines
  categories, not words, so the patterns are editable; 附件二 nutrient-function phrases are not modelled. One check behind
  `workbench.validate_claims` (`statutory_hits`／`statutory_warning`); surfaces are the workbench version list, the ads
  placement list and 補文案 notes.

### 6.39 文案與廣告格一條路（ruled 2026-09-28；built in F35）
Dig of drill-6 gap #1; prototype `.harness/scratch/prototype/f35-slot-copy/index.html` approved the same day (not in Git).
- **The slot is two halves, 圖｜文案** (user ruling 1). A planned ad's slot reads `copy` from the program: the ad's selected
  workbench copy (the set the campaign pack bound to it) or the copy of the placement in the slot. Visible states 已確認 /
  有文案，缺圖 (`copy_only`) / 有圖，缺文案 (`image_only`) / 缺 1 則. Copy alone never makes a slot ready — §6.34's one
  readiness rule (a confirmed placement, i.e. a file) is unchanged, as is the launch batch.
- **The file is the trigger, the copy rides along** (user ruling 2). When a file lands in a slot (upload; later 站內出圖),
  the program carries the ad's workbench copy into the placement, fills the purpose with the ad's name, confirms it through
  the existing no-AI confirmation and assigns it. No 進階 detour for the common path. A slot with a file and no copy offers
  「選一版文案」 from the brand's workbench copy versions (`workbench.material_options(part="copy")`), written into that
  placement; a ready slot's copy is changed by a new version in the workbench, not in the slot.
- **A draft has no copy-only material task** (user ruling 3): 「只準備新文案」 exits only to 「修改原廣告」, so it is offered
  on campaigns with platform ads only. 「開始做素材 →」 is the bar's primary on 投放結構 (§6.2 as designed; v10 had folded it).
- **As built (F35-I01)**: the copy half prefers, in order, the assigned material's copy, the pending placement's copy
  (blank headline and body → `image_only`), then the ad's *selected* workbench version — which outranks "pack still being
  worked" (`assets.readiness == in_progress`); the pack lock is a separate fact. Purpose auto-fill = the ad's name; a
  confirmation that still has `pending_reasons` (zero budget, missing field) leaves the slot waiting, nothing is forced.
  Ads tests fake the workbench facade (`adopted_output`／`material_source`／`material_options`) — ads-owned files may
  neither import workbench internals nor name workbench tables in SQL.
- Root cause recorded: one placement concept (file + copy), two copy homes (workbench output on the ad's set, placement
  `copy_fields`) and no program path between them; the F30 readiness rule demoted "pack approved" to progress without a
  visible state. Drill-6 gaps #2 and #17 share this cause and mostly dissolve with it.

### 6.40 Drill-6 yellow batch（ruled 2026-09-28；built in F36）
Eight rulings from the dig of report §4 (each claim re-verified in code first; #16 「商品重複」 turned out to be the designed
parent + sell-way pair). Prototype `.harness/scratch/prototype/f36-yellow/index.html` (`#/cap`, `#/upload`, `#/placements`).
- **The user states the cap, break-even is a hint** (#4): wizard step 2 gains an optional 「每賣一筆最多花」 chip, empty by
  default (superseded for the structured create by §6.49.1 Contract D), saved as `target_basis='own'`; the §6.32 provisional break-even still applies when it stays empty. No ROAS input,
  no brand-level default.
- **Account history divides by days that spent** (#15): 「照上一期」 = 30-day spend ÷ days with spend > 0; `sample_days` says so.
  Coupling it to the connections coverage proof waits for the pipeline decision below.
- **Review evidence refuses an uncovered window** (#13-A): same `_window_covered` rule triage grades with; the missing days are
  named. The manual-ingest pipeline for real campaigns (performance tab / `ads_outcome_daily` / closeout source) is a
  separate /dig — two ingestion pipelines is the root cause behind #13 and #15.
- **Self-brought copy has a batch default and an apply-to-all** (#17): 「本批共用原文」 on upload, 「套用到全部待處理」 in the
  fold (overwrites unconfirmed placements only). **The AI block is what it does** (#19): 「補空白文案」, disabled with its reason
  when nothing is blank, pointing to the slot picker; no regeneration (§6.9.3 stands).
- **The checklist shows the plan's audience as a read-only hint** (#8): role + audience coordinate labels, computed at view
  time, never in the frozen snapshot or readback; never a platform targeting mapping.
- **One organisation clock** (#20): `/api/identity/me` carries `timezone` + `today`; date defaults in the ads UI use
  `lib/orgClock`; `revisit_at` inputs keep the browser instant.
- **Same-name parent products are get-or-create** (#16 guard): partial unique indexes on active rows; `create_product`
  returns the existing row on a trimmed, case-insensitive match within the same parent scope.
- Text fixes: the scan step's empty message keys on cards ∪ scanned names (#6); the workbench empty state names
  「投放結構 → 開始做素材 →」 (#5).
- **As built (F36, 2026-09-28)**: `currentBudgetMonth()` takes the org timezone but nine callers outside the six converted
  screens (ChangeControl, ManualHandoffPanel, flow/*, review/*, month/*) still call it without one and get the Taipei
  default — follow-up. A campaign with no recorded observations coverage (never synced) passes the review gate, as triage
  treats it. The manual adapter's 「受眾提示」 row is read through `db.current()` inside `describe(campaign)` (the adapter
  signature takes no connection). `ReviewWindow.missing_days` is on the payload but not yet in the frontend type.

### 6.41 One performance pipeline（ruled 2026-09-28；built in F37）
- **The platform sync is the only performance source** (user ruling 1). `ads_external_daily` + the campaign's recorded
  `external_sync.observations.coverage` feed every performance reader of internal and imported campaigns alike: the
  performance tab, closeout, budget history, A/B pairs, experiments, visual learning, the strategy starting point, the home,
  the workspace, triage and review. Internal campaigns map platform rows to local nodes through `ads_ad`/`ads_delivery_group
  .external_id = ads_external_entity.native_id` (`outcome.rows`, adset rows = group grain). `POST …/ingest`,
  `outcome.ingest_meta` and `ads_outcome_daily` are retired; `app/meta/daily_pull` → `meta_entity_spend` stays for the
  schedule cockpit and the account-history base (§6.40 #15). Supersedes rule 6 of §0 and the "two tables never cross"
  paragraph of §6.11.
- **The simulated channel is a platform** (ruling 1): it registers an `ads_external_entity` chain (platform `simulated`,
  account `sim`), writes observations and records coverage; `channels.external_reader("simulated")` re-reads the same
  deterministic rows, so no reader branches on real／simulated.
- **One refresh action** (ruling 2): the performance tab's button is 「重新讀取平台」 = `POST …/campaigns/{c}/sync`.
- **Closeout refuses missing days** (ruling 3): the window `start_date … min(end_date, org yesterday)` must sit inside the
  recorded coverage; otherwise 409 `coverage_missing` names the days and offers 重新讀取. `skip_missing` is accepted only
  while the last observations read ended in error; the verdict is then 看不出 with the days recorded.
- **Never synced is not covered** (ruling 4): review evidence refuses a campaign with no recorded coverage.
- Prototype `.harness/scratch/prototype/f37-pipeline/index.html` (`#/perf`, `#/close`).
- **As built (F37, 2026-09-29)**: the read seam is `repository.performance_rows` / `outcome.rows` (Contract P); readers never
  query `ads_external_daily` for internal performance themselves. A reader declares `monthly_supported()` (missing ⇒ True);
  `request_sync` schedules `monthly:` tasks only for readers that can prove an account month, so a simulated sync job ends
  `succeeded`. `SimulatedReader` regenerates rows per day from `simulated.day_rng(campaign_id, day)` (idempotent re-read) and
  answers `pixels`/`verify_native` with `unsupported`. Simulated coverage joins a new range only when it overlaps or touches
  the recorded one — disjoint recovery days never mark the gap as read. The close 409 uses the standard `ApiError` envelope:
  `error.details = {missing_days, never_synced, can_skip}`; an isolated simulation recovery can always skip (no platform to
  re-read); a skipped close writes 看不出 and no visual learning. Migration `20260929000001_ads_drop_outcome_daily.sql`.
  Simulated campaigns published before F37 have no entity chain and get no new rows (re-publish; test data).

### 6.42 Drill-6 closeout（ruled 2026-09-29；F38）
Five program rules, no LLM judgment (dig of `docs/backlog/handoff-after-f37.md` Remaining 1–5).
- **Proof is derived from confirmed brand facts** (ruling 1). A 「證據」 brand fact (`fact_type='proof'`, `fact_key` = one of the
  six `proof` coordinate keys) is the only thing that makes that proof kind available; an active customer-voice row makes
  `customer_review` available. `app.brand_intelligence.repository.available_proof_keys(conn, brand_id)` is the one reader. The
  delivery plan (`plan.py`) and the copy prompt (`workbench/jobs.py`) offer only available kinds + 無證明; a stray key in a model
  reply becomes `none`. `coordinate_vocabulary` itself stays the label lookup for existing ads. The coordinate screen's proof
  toggle keeps meaning 「allow this creative kind」; both toggle and evidence must hold.
- **Promo offers are off by default** (drill-4 RC-C, ruling 2): `ensure_coordinates_seeded` seeds the six promo `offer` keys
  disabled, only `none` on; existing brands switched off once by migration `…_schedule_offer_default_off.sql` (test data); a brand
  enables real offers in the coordinate screen.
- **限時限量 carries the campaign's end date and nothing else** (ruling 2b): `assets._ad_set` hands `request.offer_deadline` (group
  end date, else campaign end date) to the workbench for a `limited_time` ad; `prompts.brief_text` prints it as the only allowed
  deadline, or tells the copy to write the 無優惠 version when no deadline arrived. No new coordinate attribute, no screen.
- **The audience hint says who the brief targets and whom the role excludes** (ruling 4, extends §6.40 #8): 「<角色>・<受眾座標>・
  簡報受眾：<context_json.audience_hint>・排除：已購買者｜只投：互動過或買過的人」. Still computed at view time, never in the
  snapshot/readback, never a platform targeting mapping (F36 ruling E).
- **Two performance sources for budget history, named** (ruling 5, closes §6.40 #15): the account base stays on
  `meta_entity_spend` because the sync table's monthly rows only hold campaigns bound to this brand (unbound account campaigns
  would be dropped → undercount); the caption reads 「Meta 廣告帳戶全部活動，近 30 天有投放的 N 天平均日花費」.
- Prototype `.harness/scratch/prototype/f38-proof/index.html` (`#/fact`, `#/coords`, `#/checklist`, `#/budget`).
- **As built (F38, 2026-09-29)**: the gate is `plan._prompt_rows` + `plan._gate_reply` (ads) and `jobs._proof_evidenced`
  (workbench copy branch only; the image task context still resolves old proof keys). `claims.prompt_sources` lists confirmed
  proof facts first, then RISK-word rows, cap 20. `brief_text` prints 「限時截止日：…」 from `request.offer_deadline`, or the
  無優惠 instruction when the coordinates say 限時限量 without one. Migrations `20260929000002_brand_intelligence_brand_fact_key.sql`
  and `20260929000003_schedule_offer_default_off.sql` (the latter disabled 12,624 promo rows on the dev DB).

### 6.43 Drill-7 red items and backend yellows（ruled 2026-09-29；F39）
Root cause (drill-7 report §3 #1–#2): the coordinate-choosing model (`plan.py`) received no learning at all and the strategy
model only the campaign sentence; the ledger knew per-ad grades, the planners never read them. Program tallies, model chooses.
- **(Superseded by §6.49.1 Contract B: ranked 留下／換掉 rows, `v=2` scope.) Per-ad coordinate learnings.** `closeout.close` writes one `source_track='coordinate'` learning per ad graded by the one
  ruler over the campaign window (`period_grades.grade_period`, same sample gate as the month review); ungraded ads write
  nothing. `applicability_scope` = `coord；grade=<g>；audience=…；pain=…；angle=…；hook=…；proof=…；offer=…；format=…`,
  `source_cycle_id = <campaign>:<ad>`, confidence `observed`; the text carries the numbers. Partial data (skipped gap,
  incomplete simulation) writes none, as the visual track already does.
- **(Superseded by §6.49.1 Contract G: 【上幾期的排名】 and a program gate; the per-dimension tally is dropped.) Coordinate
  scoreboard in both planners.** `coordinate_learning.scoreboard_section` (per-dimension tallies + the last closed
  campaign's 划算 and 太貴／沒賣出 ads with coordinates) is inserted into the strategy prompt after the learnings and into the
  delivery-plan prompt before the vocabulary. The department texts require reusing one 划算 combination verbatim, not reusing a
  太貴／沒賣出 one unchanged, and naming the reused ad in `rationale`. No program gate on the reply (drill 8 measures adherence).
- **One scene per ad, distinct across audiences.** The delivery-plan reply carries `scene` (6–60 chars) per ad; ads whose
  `audience` keys differ must have different scenes or the plan is rejected. Stored on `ads_ad.scene`
  (migration `…_ads_ad_scene.sql`), handed to the workbench as `request.scene`; `brief_text` binds the five copy sets to it.
- **The calendar reaches the copy** as `request.calendar_note` (program lines from `calendar_tw.note_lines` for the group's or
  campaign's window; the workbench cannot import ads). Same caveat as the planners: only when it really affects the buyer.
- **Starting point counts closed campaigns**: 「已結案 N 期；最近一期…」 line; the wizard answer is marked an initial value once N ≥ 1.
  Role availability unchanged.
- **One clock** on `month_budget._fresh` and the sync table's `observed_at` (`app.core.db.now_utc()`, which the drill clock
  rebinds); audit `updated_at`/`status_changed_at` stay SQL `now()`.
- Frontend items from the same report (E/D/F, #10, #18) are F40 after its own dig and prototype.
- **As built (F39, 2026-09-29)**: `app/ads/coordinate_learning.py` (write + `scoreboard` + `scoreboard_section`; constants
  `SOURCE_TRACK`, `DIMENSIONS`, `EMPTY_SECTION`); the 上一期 lines print all seven keys. Strategy inserts the section after
  【過去的學習】, the plan after the calendar; `basis.coordinate_scoreboard` and the plan's `knowledge_item_ids` carry the row ids.
  `plan._validate_scene` / `_scenes_differ_across_audiences`; the brief builder is `assets._ad_set` (hands `request.scene` and
  `request.calendar_note`, group window else campaign window); `ScriptedProvider._reply_for` rebuilds a per-role scene for the
  e2e backend. `external_repository` also binds `observed_at` on the insert path (the column DEFAULT would have kept real time).
  Migration `20260929000010_ads_ad_scene.sql` applied to the dev DB and registered.

### 6.44 Drill-7 frontend batch（ruled 2026-09-29；built in F40）
Prototype `.harness/scratch/prototype/f40-screens/` (approved 2026-09-29) is the layout spec; screenshots in `shots/`.
- **成效 tab = the campaign detail page.** `detail/PeriodStatusRow.tsx` sits above the ruler for live/ended/closed campaigns:
  整期合計 (spend, purchases, cost per result with the one-ruler grade from `outcome.summary().totals.grade`, ROAS), data status
  (coverage chip, latest read), 重新讀取平台 and 結案這一期 (the F37 close dialog now lives in `CloseCampaignDialog.tsx`, shared with
  the folded old panel), and the caption 「整期＝活動期間的合計；每月回顧只算當月天數」. Period days = calendar window through today.
  Title 「在投 N 則」 keeps counting platform ads that are not closed; two program lines name local ads never built
  (`local_state !== 'bound'`) and platform ads with no bound local ad (`triage item.bound_ad_id === null`). The fold is
  「進階：每日資料、次要指標與舊版檢討」. Drill-7 #7's premise was wrong: the stand-in had built all 6 entities.
- **Home quality band** picks its sentence from the payload alone (`home/status.ts::bandState`): missing days (link to that
  campaign's 成效), read failure (重試), no spend, normal.
- **Approve page 「本月預算放得下」** (`flow/confirmParts.tsx::BudgetFitCard`): formula headline, 4-segment bar, the 預留 line from
  `month_budget.calculate().ongoing_owners`; no month budget → 「設定 N 月月預算 →」 (links to the ads home money card; no
  dedicated route exists) and the approve button's reason beside it; premise changed → 「重新檢查」 replaces the silent auto-rebuild
  for budget sets only.
- **Assets tab** polls `getSlots` every 3 s while any slot is 處理中; a `format_key='video'` slot asks for a video and refuses a photo;
  one original may back several ads: `ads_asset_placement` is unique per `(campaign, asset, ad_id)` with NULL `ad_id` for library
  attaches (`20260929000011_ads_asset_placement_per_ad.sql`; `attach(ad_id=…)`, `revise` keeps it). The 主力／探索 count chip of the
  prototype is **not built**: the slots payload has no role per slot (backlog: `slots.py` role counts).
- **Pack page 「核准整包」** disabled reason = `blocking_text` naming missing sets and every unticked completion item; the 探索
  ratio stays a warning (F07 decision 29). The prototype's one-click 「改為探索」 is not built (no API changes a set's slot).
- **Readback 「全部標記」**: `POST …/handoff/launch/confirm-all` loops `confirm_field`/`confirm_setting` under `changes.lock`;
  each confirms with its own commit (those functions commit themselves), so the call is idempotent rather than atomic — a call
  cut short is finished by the next one. Frontend bar in `publish/SettingsReadback.tsx::UnreadAllBar`; confirmed rows keep the
  kit wording 「你確認一樣」.
- **(Superseded by §6.47 except the period default.) New campaign copies the previous one** (`brief.create_draft` → `_copy_from_previous`): platform, `audience_hint`, own cap,
  landing URL (`context_json.landing_url`, else the previous first group's manual value); `context_json.copied_from =
  {campaign_id, name, fields}`, `field_sources` values `"copied"`. The PATCH accepts `landing_url`; `manual_settings.handoff`
  shows the campaign default per group with `sources.landing_url = "campaign"`. Form: 「這次怎麼投」 block, 受眾方向 is free text
  (not the prototype's select), 「清空重填」.
- **Small fixes**: truth-card answers survive a panel save (`TruthCardStep.load` keeps answers whose item still exists);
  the workbench regenerate button names the running part (`workbench/regenerateLabel.ts`; after a reload the payload cannot
  tell which part runs — backlog: per-part status in the set payload).

### 6.45 Drill-8 small fixes（ruled 2026-09-30；built in F41）
Prototype `.harness/scratch/prototype/f41-drill8/index.html` screens ②③④ (screen ①, a per-campaign 「這期手上有什麼」 card, was
rejected: offers, proof and media move to onboarding, F42/F43).
- **Preview done → slot ready** (drill-8 #4): `user_assets.process_preview`, after the `ready` commit, calls
  `slots.settle_ready_asset`, which runs the upload's own two steps (`_confirm_if_ready` + `settle`) for every current unconfirmed
  placement an `ads_ad.slot_placement_id` points at; actor = the placement's `created_by`, else `system:preview`. A failure is
  logged; the asset stays `ready` and manual confirm still works. Library placements (no ad points at them) still wait.
- **One rule set for putting a finished asset into a planned ad**: the advanced 「將成品指派給計畫中的廣告」 panel calls
  `POST …/slots/{ad}/upload` with `{placement_id}`; copy order = explicit `copy_fields` → the ad's selected workbench copy → that
  placement's own copy. Slot-path refusals surface unchanged (ad already on the platform → 「換掉這一則」; same file, different copy
  → `placement_copy_conflict`). `PUT …/launch-materials/{ad_id}` stays plain `assign` for the F28 stale-launch exit
  (`LaunchStalePanel.reassign`) and clearing.
- **Learnings in Chinese** (#11): coordinate learning text names coordinates by label (`受眾：…、痛點：…`); the scope gains
  `cpr=`/`cap=` (older rows read `None`); prompt lines print `label（dim=key）`; the strategy basis gains `coordinate_learnings`
  (the last closed campaign's graded ads, labelled; F46 writes `basis.ranked_learnings` instead, §6.49.1). Strategy prompt keeps one period verdict per product (newest); event learnings
  (`ads;` scope: pause, A/B, month settle) pass through. Department rule: no English coordinate codes in `why`/`rationale`.
- **Strategy tab** (#3): 「預算怎麼分」 = thin bar (`AllocationBar legend={false}`) + one row per role (pct, amount, rationale);
  coordinate learning rows sit in 「為什麼這樣建議」 (fold stays closed by default, F28). Strategy types live in
  `frontend/src/lib/adsStrategyTypes.ts` (re-exported from `adsApi.ts`, 800-line cap).
- **Default campaign name** (#5): `<product or sentence, cut at 30>・MM/DD～MM/DD`; the dates are never cut.
- **First-launch 「本月預算放得下」** (#6): `GET …/launch` list step carries `month_budget` = `change_control_launch.month_fit`: the
  month view before this launch + `extra` + `blocker` (`unset`/`uncertain`/`short`, judged with the launch, in preflight's order) +
  `blocker_text`; `PublishList` renders the shared `BudgetFitCard` (launch mode adds 放不下 with 提高月預算／改這期總預算) and puts the
  reason beside 核准上架清單.

### 6.46 Brand onboarding feeds the planner（ruled 2026-09-30；built in F42）
Supersedes §6.42 「Promo offers are off by default」.
- **Offers are derived data.** `bi_repo.available_offer_keys(conn, brand_id, product_id=None)` = offer keys of the brand's confirmed
  store-policy facts (intake.md F42); a threshold policy (滿額免運, 超商免運, 滿額折, 滿額贈) counts only when the product's current
  confirmed NT$ price ≥ the threshold (no product → counts; unknown price → does not). `offer_sources` returns the sentence behind
  each key. The coordinate toggle is a brand veto on top (enabled ∩ available); offers are seeded enabled again
  (`20261001000002_schedule_offer_default_on.sql`, `DEFAULT_OFF_COORDINATES` removed). `limited_time` needs both a policy and an
  end date. F43 adds the sell-way's own discount/bundle.
- **Formats follow media capability**: `plan._prompt_rows` drops `format/video` when `brand.media_capability == 'photo'`;
  `_gate_reply` snaps a stray format to the menu's first format.
- **Copy guard**: store policies reach the copy only as `offer:<key>` rows from `offer_sources` (policy facts are not generic
  sources); a RISK word whose offer family (免運／折扣…N折／贈品…買N送／試用…試吃／退款保證) is available is not flagged. Proof and
  endorsement words keep the exact-sentence rule.
- **Readiness** (`app/ads/readiness.py`): 品牌是誰／證據與政策／素材／廣告帳戶（reason names the 成效目標）／商品, each with a fix link
  (`intake?step=3/4/5/6`, `/products`). The completion screen's chip describes the state: 可以投放／有假設值／還差商品／還要補齊.
- **這期會用**: the campaign payload carries `materials` = {offers (with sentence), proof, media} (`app/ads/materials_in_hand.py`);
  the strategy tab shows it as one chip row in 「預算怎麼分」.

### 6.47 Campaigns pick a sell-way（ruled 2026-09-30；built in F43）
Supersedes §6.44 「New campaign copies the previous one」 for platform / audience / cap / landing (the period default stays).
- Only finished sell-ways are pickable (`wizard_options.sellable_products`): options carry kind, knowledge product, price, break-even,
  cap_per_sale, offer labels, customer groups, landing, thumbnail; `options().default_objective` maps the brand conversion goal
  (purchase→購買, lead→名單, booking→名單, awareness→知名度; unset → no preselection).
- Create defaults from the sell-way, each marked `field_sources = "sell_way"` (platform / cap / budget superseded by §6.49.1
  Contract D: the same sell-way's previous campaign first, then the sell-way, then break-even): `context_json.customer_group_ids` = all groups of its
  knowledge products, landing = the sell-way's effective landing, cap = `cap_per_sale` stored as the campaign's own cap (NULL →
  break-even, `system`); user overrides in 「進階：這期不一樣」 mark `user`. `PATCH …/campaigns/{c}` accepts `customer_group_ids`
  (validated; a sell-way change resets them). Budget no longer falls back parent → first child; it reads the picked sell-way.
- Prompts: strategy and delivery plan get 【這個賣法的顧客】 (≤3 groups per knowledge product, ≤6 in all, pain keys with labels, quote,
  when); department rule: an ad's `pain` comes from a listed group when groups exist. Claims, workbench jobs and the prompt context
  read every product of a bundle (`knowledge_product_ids`).

### 6.48 Ads carry the sell-way（ruled 2026-10-01；built in F44）
Root cause (drill 9 #1＋#2): every step re-derived 「which sell-way this ad sells」 or skipped it.
- **One reader** (`app/ads/sell_way.py`): `of_campaign` = first of `context_json.product_ids`; `of_ad` = the ad's own `product_id`,
  else the campaign's. The campaign owns the sell-way; nothing fills `ads_ad.product_id` at plan time. Readers: planner, pack
  dispatch, learning revalidation, asset confirmation. `budget._economics_for` (first sell-way with economics) stays its own rule.
- **Planner**: the prompt lists 【這期可用的優惠】 — one 「- offer=〈key〉｜〈sentence〉」 line per `bi_repo.offer_sources` sentence whose
  key the filtered menu kept (omitted when the menu has no offer but `none`). Department rule plus program gate: an offer in the
  menu and every ad `offer=none` → `delivery_plan_failed`, nothing written. The scripted (e2e) reply takes the first listed key.
- **The offer coordinate decides the copy** (user ruling): `none` → no offer sentence, no offer price / list price; an offer key →
  that offer's registered sentence. Enforced by the workbench narrowing (`docs/architecture/workbench.md`, `validate_claims(…,
  offer_key=)`) at generation, on the version list, and at asset confirmation; since F46 (§6.49.1 Contract O) asset confirmation
  also refuses an offer ad whose copy writes none of its offer's sentences, and an offer word is backed only by its exact term
  inside the narrowed sentences (the F44 limit — 「優惠」 backed by any offer row — is gone).
- **Asset confirmation** (`asset_suggestion_policy.violations`) judges copy against the placement's sell-way and its ad's offer
  coordinate (a library placement: the campaign's sell-way, no coordinate). Refusals are details `{kind: copy | file | campaign |
  wait, text, terms}`; `pending_reasons` stays their texts. Sentences: 「文案寫了「…」，品牌資料裡沒有登記這個優惠或背書。」 (unbacked),
  「這則規劃的是「〈offer label〉」，文案卻寫了「…」。」 (coordinate mismatch). AI-filled copy may cite the sell-way's approved claims.
- **Blocked slot**: a refused auto-confirmation stores its non-`wait` details in `ads_asset_placement.blocked_reasons`; `GET …/slots`
  returns `state: "blocked"` with `blocked {text, terms, fix: copy | file | null, more}` and every slot's `offer_label`; a failed
  original reads blocked with `fix: "file"`; a file with no copy stays `image_only`. `POST …/slots/{ad_id}/recheck` runs the
  confirmation again. The 素材 tab shows 卡住, the reason with its terms marked, the exit (換一版文案／到工作檯改文案／換一張) and
  再檢查一次; blocked slots do not poll and are not in the launch list.
- The `bundle` offer label is 「組合優惠」 (seed, `OFFER_LABELS`, and a rename migration for rows still carrying the old seed label).

### 6.49 Drill-10 fixes（ruled 2026-10-02；built in F45, F46, F47）
Three parts: F45 the blocking defects (below), F46 the learning channel (§6.49.1), F47 failures that recover (§6.49.2). The
sell-way shapes F45 also built are in `docs/architecture/intake.md` 「F45」.

Pause reads the ad, slots say who is waiting (F45). Root causes (drill 10 §1 #3, #4): the pause page found its ad only through a
home-queue row, and 「system busy」 and 「waiting for you」 were one slot state while only one confirmation path stored a refusal.
- **Pause view (Contract P)**: `GET …/campaigns/{c}/triage/{entity_id}/pause` → `{"pause": {state, entity_id, name, triage,
  closed_at, last_read_at, change_set_id}}`. `state`: `active` (a platform ad of this campaign that `ad_status.is_closed` does not
  call closed — unknown status counts as active), `closed` (closed, not `DELETED`), `gone` (no such ad in this campaign, or
  `DELETED`). `triage` = the `GET …/triage` item shape computed for this one ad over the campaign's own cutoff, coverage and cap
  (closed ads too; `null` when gone). `closed_at` = `status_changed_at`; `last_read_at` = `last_success_at`. `change_set_id` = the
  newest non-superseded plain set (no `source`) of this campaign with a `pause` item on this ad, status `draft`, or `approved` with
  that item not `confirmed`; else `null`. 404 only for an unknown campaign. The home queue is not read for any of this.
- **Pause page** (`propose/pause/:entityId`): built from Contract P; the queue only adds 「第 n 件／共 N 件」 when the ad has a row
  (a failed queue read drops the position, never the page). `active` → the proposal with this ad's own numbers (花費、成交、每筆成本、
  評級, meter against the cap, 「這則廣告自己的數字・〈window〉」) and the angle card; `closed` → 「這則已經停了」 with the same card
  and one back button; `gone` → 「找不到這則廣告」, why, 回投放中心. Entries carry `?from=perf|review|verify&ref=<review id | set id>`
  for the back link: 覆盤「停掉這則」, 讀回頁「暫停舊廣告」／「重新檢討」, and a 「暫停」 button on every active ad row of the 成效 tab.
  The pause set does not carry `review_id` (`proposal_reference` stays copy-only; the round is already decided).
- **Refusals are stored by the confirmation itself**: `asset_suggestions` writes a refused confirmation's non-`wait` details to that
  revision's `blocked_reasons` (manual and batch confirm, upload, copy pick, recheck — one writer). A new revision of a placement that
  backs a planned ad's slot (`PATCH …/placements/{id}`, slot copy edit, copy pick) points the ad's `slot_placement_id` at it and is
  confirmed and settled at once (skipped for a launched or frozen ad). `POST …/slots/{ad_id}/copy` also takes `{copy_fields}`
  (a typed edit) besides `{set_id, version_id}`.
- **Slot states (Contract W)**: `in_progress` only while a background job for that slot runs — its original's preview (asset
  `pending`) or its workbench set's generation (`queued` / `running`); the slot carries `job {kind: preview | copy, done, of}`
  (`done`/`of` null unless the workbench read gives them). Nothing running, nothing refused, not ready → `waiting` with
  `waiting {action: pick_on_workbench | confirm_copy, text}`: 「等你：到工作檯選定一版文案」 (a set with no selected copy) or
  「等你：確認這版文案」 (an unconfirmed placement with a ready original and no stored refusal; the button runs recheck). `blocked`,
  `copy_only`, `image_only`, `missing`, `ready` keep §6.48 / F35 meanings. The 素材 tab counts 卡住／等你／處理中, polls only while
  something is `in_progress`, and edits copy in place (保存後馬上檢查). A dead worker is shown by §6.49.2 「Worker liveness」.
- **Photo-only brands** (`brand.media_capability = "photo"`): single-image and carousel sets require only `{"copy": 1}`.
- **Picker**: `wizard_options` items carry `derived_fields` (the current economics'); a break-even from a derived price or cost
  prints 「（推算）」.
- **As built (F45)**: the pause view lives in `app/ads/triage_pause.py`; the 素材 tab's slot tiles follow the prototype frame
  (picture left, text right, up to 3 columns).

#### 6.49.1 The system learns which kind sells（built in F46）
Root causes (drill 10 §1 #1, #2, #9, calendar part of #10). Supersedes §6.43's grade rows and scoreboard, §6.45's
`basis.coordinate_learnings`, §6.47's create defaults for platform / cap / budget, §6.40 #4's 「cap chip empty by default」 on the
structured create, and §6.48's family-wide offer backing. Prototype `.harness/scratch/prototype/f46-learnings/index.html`.
- **Ranked learning row (Contract B)**, written at closeout (`coordinate_learning.write_coordinate_learnings`, one rule in
  `app/ads/learning_rank.py`). Input = `period_grades.grade_period` rows of the campaign window; a row with unknown results or
  spend is not ranked; partial data (skipped gap, incomplete simulation) writes nothing. Sold rows (≥ 1 sale) by cost per sale asc,
  then sales desc, then name; 沒賣出 (0 sales, spend > 0) after them, spend asc. Verdict: cost ≤ cap → `keep` 留下; when no sold row
  is ≤ cap (or no cap), sold rows ≤ best × 1.3 (`NEAR_BEST`) → `keep_relative` 留下 + 「相對最好，仍高於上限」（no cap: 「相對最好」）;
  the rest incl. 沒賣出 → `replace` 換掉. 樣本少 = 1–4 sales (`SAMPLE_FEW = 5`). Scope
  `coord；v=2；verdict；rank；of；sales；spend；cpr；cap；few；group；` + the seven coordinate keys + `cur=` (currency); text 「第 r／n 名「〈ad〉」
  每筆 X（賣 s 筆、花 Y；上限 C）＝留下（樣本少）；顧客群：〈who〉；〈labels〉」. Rows without `v=2` (F39/F41) are not read; no backfill.
- **Learnings view (Contract L)**: `app/ads/learning_view.py::learnings_view(conn, org, brand, *, campaign_id, sell_way_id, limit=12)`
  → `{campaigns, groups, next}` (campaign rows with `rule_text` / `empty_reason`, per-customer-group totals, the next-campaign
  href `/brands/{b}/ads/new?sell_way=<id>`); numbers come from the stored scope, never recomputed. Served at
  `GET /api/ads/brands/{b}/coordinate-learnings[?campaign_id=][&sell_way_id=]` (`learning_routes.py`). Readers: 品牌智庫 tab
  「投放學到的」, the closeout dialog's exits 「看學到什麼 →」／「用這些學習排下一期 →」, the month review's `next_plan` suggestion (one per
  sell-way, from the newest system-built campaign closed in the month; `month_summary.py`), and the strategy basis
  (`basis.ranked_learnings` = the view it prompted with; `basis.coordinate_learnings` is no longer written and stays readable).
- **Planners (Contract G)**: `coordinate_learning.ranked_section` prints 【上幾期的排名（程式排的；每筆＝花費÷成交）】 in place of
  【座標成績表】 in both prompts — per-group lines, then the newest ≤ 3 closed campaigns' rows. Program gate in the delivery plan
  (`plan._builds_on_learnings`, pairs from `gate_pairs`): an ad's (customer group, angle) may not be a 換掉 pair of the newest
  closed campaign (minus its own 留下 pairs), and when the listed campaigns kept any pair at least one ad reuses one; else
  `delivery_plan_failed`. The strategy has no gate.
- **Customer group coordinate (Contract A)**: `ads_ad.customer_group_id` (migration `20261004000021_ads_ad_customer_group.sql`, no
  FK). The reply's `"customer_group": N` = 第 N 群 of 【這個賣法的顧客】; with groups listed N must be listed, the ad's `pain` must be
  one of that group's pain keys (when that set meets the menu), and all ads of one delivery group share one group
  (`plan._bind_customer_groups`); no groups listed → NULL; hand-made ads NULL. The workbench brief gets `request.customer_group`.
- **Photo count (F46 Contract P)**: the delivery-plan prompt gets 【手上的素材】「照片 N 張、影片 M 支」; rule: ads ≤ photo count when N ≥ 1.
- **What shipped wins (Contract F)**: `app/ads/actual_format.py` (a `video/*` original → `video`, any other file → `single_image`)
  feeds learning coordinates, the handoff list's 「格式」 row (+「（規劃是〈planned〉）」) and every slot's `format_note`
  (「規劃是輪播，只放了 1 張圖，會以單圖上架」). Open: whether the planner should stop offering carousel while a slot holds one file.
- **Offer sentence (Contract O)**: asset confirmation refuses a planned ad whose copy writes none of its offer's registered sentences
  (`asset_suggestion_policy.missing_offer` → workbench `validate_claims(...)["missing_offer"]`), detail `copy`, 「這則規劃的是「〈offer
  label〉」，文案沒有寫這個優惠：「〈sentence〉」。」. Offer-word backing is exact-term (workbench.md, F46).
- **Create defaults (Contract D)**: wizard options carry `previous` (newest non-draft internal campaign of that sell-way:
  platform, cap, budget, spend), `learned` (Contract L counts) and the payload `default_platform`. A structured create, for a value
  the request does not send: platform = previous (`copied`) else the brand's first connected channel (`brand`); cap = previous
  `target_cost` (`copied`) else `cap_per_sale` (`sell_way`) else whole break-even (`break_even`, stored); budget `copied` when it
  equals the previous. Tags 沿用上一期／打平線／已接上的帳戶／你改的; shown = stored (`brief.py`). Platform / cap / budget sit in
  「期間、預算與平台」; 月預算 links open the monthly-budget form; picking a Meta account assigns it.
- **Calendar**: October exam rows added (data). Not built: O3 strategy text check, the strategy tab's per-ad provenance card,
  a monthly-budget default amount, daily budget on create.

#### 6.49.2 Failures say why, offer an exit, keep the data（built in F47）
Root causes (drill 10 §1 #4 except B2, #6, #7, #8; drill 9 #4, #5). Input rules (Contract A, `app/core/input_rules.py`), worker
liveness (Contract C, `app/background/__init__.py`) and the Meta classifier (Contract G, `app/meta/graph.py`) are documented in
those modules' docstrings; the ads-side rules:
- **Queue done-ness (Contract D)**: `app/ads/queue_done.py` owns the rule (deferred / rejected / confirmed proposals done; a
  cleanup row done once its set is done; `worse` done when its round is deferred, unjudgeable, or completed with a done copy set;
  refresh / insufficient / settle never). `triage.get_queue` stamps `done` on every row; `status_summary.open_items` counts
  not-done rows of the home board's kinds (`DECISION_KINDS`: cleanup, worse, refresh_creative, settle); the frontend reads
  `item.done` (「第 N 件／共 M 件」 and 「下一件」 skip done rows; 資料不足 opens its own page). A cleanup candidate with zero closable ads
  is not an open row. 暫緩 creates the set and its decision in one write; the deferred chip links back with 「M/D 再看」.
- **Campaign delivery (Contract E)**: the workspace read carries `delivery: waiting | live | null` (`workspace_reads._delivery`;
  null for a draft, a closed campaign or a failed read; `waiting` = on the platform, no synced day with spend > 0). Overview:
  `waiting` → 「已上架，等平台開始投放」 and money cells 「還沒開始花」; a closed campaign never says 在投 (「已結案」 or 「已結案・平台上還開著 N 則」,
  counting platform ads not `ad_status.is_closed`). Existing-campaign listing items carry the workspace `campaign_id` they are
  bound to (「已在工作區」).
- **Connections (Contract H)**: each `ad_account` source carries `reread {platform, source_account, start, end} | null` (failed,
  missing days, never read); 「重新讀取」 posts `…/existing-campaigns/refresh`; a failed source's note is reason, then gap. The status
  summary's `attention {count, note}` replaces `failing_campaigns` and is the connections page's own `attention_count` and first
  note; the top bar reads 「N 個資料來源要處理」.
- **Launch settings and money**: `launch_settings.bid_amount` (> 0) is required for `cost_cap` / `bid_cap` (an `errors()` entry,
  「選了「〈出價方式〉」要填金額」), cleared for other strategies, written in the handoff copy next to 出價方式, not a readback field. A
  typed pixel id is checked by the platform adapter when the pixel list cannot be read (Meta: digits, 10–20). Monthly budget total
  > 0 (0 reads as unset on the home card; the pace chart draws nothing without a budget); group dates in order; copy apply keeps
  blank fields; a cap edited through the target writer marks its source `user`; approval re-reads after other settings save and a
  409 says the settings just changed. Per-sale figures print through `patterns/csv.ts::perSaleAmount` (whole yuan, rounded, never
  floored); CSV numbers are rounded to 2 decimals. The crumb and step chip share one launch name (`PublishFlow.tsx::launchLabel`);
  the verify step shows the readback reason with its time (`LaunchItem.reason_at`).
- `app/core/db.new_id` is monotonic within a millisecond (rows of one transaction keep creation order).

### 6.50 One ruler, one money calculator, one planner context, one claims guard（ruled 2026-10-04；built in F48）
Audit 2026-10-04 W1–W6 (`docs/backlog/audit-2026-10-04/README.md`; decisions 1–4, 7, 8, 11, 13 user-confirmed). Supersedes §6.32's
「below the gate」 grading and §6.33's sample-gate wording (sample size is a shown flag, never a gate); for the discount family
only, §6.48／§6.49.1 Contract O's exact-term rule. Machine checks: `app/tests/test_ads_one_ruler.py` (AST: ruler numbers only in
`learning_rank.py`／`triage.py`; grade-keyed tables; `record_learning` only in `ads_learnings.write`; money `round`／`floor`／`ceil`
only in `budget.py`), `app/tests/test_ads_planner_context.py` (every `ads_*` planner calls `planner_context`; hand edits call
`planner_context.menu`), `frontend/src/components/ads/oneRuler.test.ts` (ruler literals, label-string branches, number+unit
literals in strings, `Math.round` over money, mirror comments; per-line `NOT_A_RULER` excuses fail when stale).
- **One ruler (Contract R).** `triage.grade_window` grades every known cost: 划算 ≤ T, 偏貴 ≤ 1.2T, 太貴 > 1.2T; a known zero at
  ≥ `STOP_LOSS_SPEND_MULTIPLE`×T is 沒賣出; a known zero below that line is `too_new` 「剛開始」 (reason code renamed from
  `below_sample_gate`); unknown／mixed currency 資料不足; no cap 未判斷. Items carry `sample {sales, few, too_new, …}`
  (`too_new` uses the ad's own days with data). `learning_rank.rank` ranks the same rows: a known zero below the line, or with no
  cap, is not ranked anywhere (cleanup, settle 「還沒賣出，花費也還沒到門檻」, closeout learning; F48-I13). Cleanup closes from the
  bottom of `learning_rank.rank` (every 沒賣出, then `replace` rows most expensive first while over capacity); `keep`／`keep_relative`
  and unranked never close; entries carry `rank, of, sales, few, verdict, verdict_label, flags, reason_text` in served order.
  Settle fates follow `learning_rank.is_keep`, rows served in rank order; closeout verdict is 達成／未達成 on the cap alone with
  `verdict_json.sample {purchases, days, bucket}` shown; `learning._confidence` counts campaigns with ≥ `MIN_RESULT_EVENTS`
  purchases; scale-up skips an owner under `MIN_RESULT_EVENTS` sales and the queue serves it in `scale_hold` 「樣本少，先不加碼」.
  Pause／cleanup／scale `reason_text` is built from the ad's own grade and numbers.
- **Rules served (Contract R-API).** `GET /api/ads/brands/{b}/rules` → `{grade, ab, labels, glossary}` from the ruler modules;
  `frontend/src/components/ads/patterns/rules.ts::useAdsRules()` is the only reader (tests seeded via vitest `setupFiles`); while
  unloaded, words print without numbers. One sample chip only: 「樣本少」; no 「還太新」 chip.
- **One learning writer (Contract W).** `ads_learnings.write(..., product_id=...)` is the only `record_learning` caller in
  `app/ads`; every row carries its sell-way (`None` only for imported campaigns), so `_newest_per_product` works per sell-way.
- **留下 carries the creative (Contract K, decision 2).** `plan.adopt_strategy` carries the newest closed campaign's `keep`／
  `keep_relative` ads of this sell-way before asking the model (same coordinates, name, group, scene;
  `coordinates_snapshot_json.carried_from`), attaches their confirmed original and copy through the slot path (slot 已確認), and asks
  the model only for the remaining ads; a carried ad is skipped when it would leave an uncovered role without a place or its group
  already holds 3; a carried ad whose creative is gone stays normal with `carry_note`. Ads serve `carried_label` 「沿用上一期」.
  When every ad is a ready carried ad, `dispatch_pack` submits nothing (`{pack_id: null, nothing_to_prepare: true}`).
- **Capacity (Contract C, decision 4).** `triage_capacity.can_support(daily, cap)` is the one formula; ceiling =
  `max(can_support + 1, roles)`; a reply over the ceiling is refused; the campaign payload serves `capacity {daily, cap,
  can_support, ceiling, carried}` and `menu`.
- **One money calculator (Contract M, decision 8).** `budget.whole` (half up) is the only money rounding; `budget.daily_of` =
  floor(total／days) (the one exception: never above the chosen total); `total_of` exact. Adopt writes `budget_planned :=
  total_of(Σ group daily, days)`, so `budget_total == budget_planned`; reads never re-split; `budget_preview {daily, total, chosen,
  note}`; a total under one per day → 400 「總預算太少：每天不到 1 元」. After adoption, dates／products／groups／platform PATCH → 409
  `plan_already_adopted` (the cap stays editable) and `ConfirmBriefPage` redirects a non-draft campaign to `?tab=strategy`; a new
  total on a `ready` campaign with unbound groups re-splits them and returns `resplit`; bound → 409 `campaign_bound`.
  `month_fit.extra_basis {month, days, period_total}` prints 「N 月的 D 天要花 X（整期 Y）」.
- **Planner context (Contract P).** `app/ads/planner_context.py` is the one input every planner reads (brief, strategy, plan,
  `create_ad`／`update_ad`): sell-way facts and kind, 【不能講】, offers with sentences, customer groups, sell-way learnings (plus
  brand-level imported rows), previous `learning_goals`, capacity, the one coordinate `menu` (excluded keys carry a reason). Hand
  edits outside the menu → 400 `coordinate_unavailable`; names with a forbidden term → 400 `name_forbidden`.
- **Strategy facts (Contract S, decision 3).** `strategy.facts [{kind, text}]` (groups, offers, numbers, capacity, learnings) are
  built by the program and recomputed on every campaign read; the model's prose is refused when a digit, `%` or `NT$` is left after
  stripping the names it was given (`planner_context.quoted_names`).
- **C／D follow-through built in F50／F51**: the browser arithmetic and copied backend-number exceptions in `PaceChart`,
  `PerformanceTab`, `reviewFlow`, `ReviewPanel`, `ReviewTracking`, `NewCampaignPage`, `CopyPage` and `OverviewBody` are removed.
  The statutory reminder still has no regulation-link field (intake). The active-job queue exception retained by the user is
  documented in §6.53; it does not supply a financial figure.

### 6.51 One lifecycle, one decision queue, one sync outcome, one coverage, readback compared, slot states served（ruled 2026-10-04；built in F49）
Audit 2026-10-04 W7–W10, W17 (decisions 5, 6, 11, 12; user rulings 2026-10-04: `ENDED_GRACE_DAYS = 7`, 加預算 is not a decision).
Supersedes §6.36's `end_date <= today` and 「Monitoring is not status-driven」, every earlier `ad_status` reference, and the
readback rule that listed unprovable fields as 「請到 Meta 看一眼」. Machine checks: `app/tests/test_ads_one_ruler.py`
(`OneLifecycleTest`, `OneSyncOutcomeTest`, `OneCoverageReaderTest`, `SlotStatesTest`, queue-kind and reason-code tables, verification
labels, no `except (ValueError, AttributeError)`), `frontend/src/components/ads/oneRuler.test.ts` (platform status words, lifecycle
compares, sync job reads outside `useSyncOutcome`, local state-word tables, queue-kind／reason tables, slot words, `external_view`
readers). Leftover allowances live one file per owner in `frontend/src/components/ads/oneRulerPending/` (today only `W14.ts`, `W19.ts`).
- **Lifecycle (Contract L).** `app/ads/lifecycle.py` owns campaign state `draft | live | ended | closed` (internal: stored closed;
  draft = stored draft／ready with no root read; ended = stored ended or `end_date < today` once on a platform; imported: draft
  without a root read, ended when the root is off or past its end date, never closed) and ad delivery
  `running | not_running | off | unknown` from the adapter's `STATUS_TABLE` (`adapters.delivery`／`gone`); platform status words
  live only in `adapters/`. `lifecycle.monitored` = live, or ended within `ENDED_GRACE_DAYS`. Campaign reads serve
  `lifecycle {state, label, can_close}`, `running {count, unknown, read_at, stale}`, `delivery_label`, `closed_this_month`. Closing a
  draft → 409.
- **Runtime gate (Contract N).** Dispatch, per-campaign sync and readback ticks cover monitored campaigns only (plus an explicit
  re-read and a just-imported campaign); readback skips confirmed／stale items; runtime alert key
  `ads-runtime:{campaign}:{code}:{since}` (an episode: a cleared alert that returns raises a new row); unmonitored campaigns' alerts
  are swept daily and closeout resolves them; `recovery` counts only monitored campaigns.
- **Sync outcome (Contract O).** `external_sync.outcome` = `running | failed | partial | empty | found` + code + sentence, written by
  `_update_task` (job status／error actually written; request failures stored as a failed `request` task; `not_read` for never
  read). Served by `GET sync-jobs/{id}`, `GET campaigns/{c}/sync-outcome`; `GET existing-campaigns` is read-only. Frontend reads it
  only through `lib/useSyncOutcome.ts` (`refresh()` resets to running until the next answer).
- **Coverage (Contract V).** `app/ads/coverage.py`: a day is `data` (has a row), `empty` (inside a merged clean read range, no row)
  or `missing`; ranges are a merged union (`observations.ranges`), never overwritten; every window is clipped to the campaign's
  start／end; triage serves `data.days`. Month budget and A/B (pads only cleanly read days) read the same module.
- **Decision queue (Contract Q).** `queue_done.DECISION_KINDS = (cleanup, worse, closeout, settle, refresh_creative)`;
  `scale_budget`／`insufficient_data` are notices (served, never inbox rows). Rows carry `decision`, `done`, `position`,
  `campaign_id`; the payload `decisions {kinds, open}`; home count = 「下一件」 = inbox. An internal ended campaign gets one
  `ads_triage_closeout` row (`?tab=perf&close=1`), no new proposals; rows opened before the end stay (matched by their
  `ads-triage:{kind}:{identity}:` prefix) until closeout. A decision, a confirming readback and closeout resolve their inbox rows in
  the same request; decided rows leave the queue at once. `/rules` serves `reasons` (code → sentence + fix kind).
- **Readback (Contract B).** Material is confirmed once at approval (`approval_confirms`); landing URL and audience are compared by
  the program through `adapters.creative_links／audience_ids` (URL: host without `www.`, path without trailing slash, query without
  `utm_*`／`fbclid`／`gclid`); mismatch → `deviated` with a coded reason, nothing read → `unknown` with a coded reason, never an eye
  check. Every refusal has a reason code from `handoff_check.READBACK_REASONS`; `worst_state` order deviated > stale > unknown >
  reported > pending; `VERIFICATION_LABELS`／`STATE_LABELS` served; `launch_view` names a reason only when it carries a code;
  `upsert_entity` bumps `updated_at` only on a real change. Handoff serves `destination_by_ad` and `destinations_note` for any
  origin (C1: review 「換一張圖」 works on system-built campaigns); `external_view` is read only by imported-only screens.
- **Slot states (Contract T).** `slots.STATE_TEXT` is the one state → label＋sentence table (`retrying` with its retry time, `failed`
  with the workbench exit, a refused assignment stored as reason kind `assign`); a ready slot's copy is editable until launch
  approval (new revision); copy options are this sell-way's only; structure ads serve `slot_state`／`slot_label`; a material hand-off
  left `unknown` retries on the same pack.
- **Drill tool.** `scripts/drill/fake_meta.py` mirrors the planned landing URL and audience so drill readback can confirm them.

### 6.52 One clock, one input-rule table, one readiness, one background outcome（ruled 2026-10-04；built in F50）
Audit 2026-10-04 W11–W14 (decisions 9, 11; C rulings 2026-10-04: margin default 45 %, one automatic retry of a program-refused
strategy／plan, archived lists with restore, SKU cost 0 kept, list price below selling price refused). Machine checks:
`app/tests/test_clock_rule.py`, `test_input_rules_gate.py`, `test_readiness_gate.py`, `test_background_outcome_gate.py`,
`frontend/src/lib/clockGuards.test.ts`, `frontend/src/lib/clientRules.test.ts` (allowlists name the removing issue; stale fails).
- **Clock (Contract K).** `app/core/settings.py` holds the which-clock-for-which-question table: instants from `db.now_utc()`;
  the user's day／month from `today_for_org`／`org_month_start`／`org_day_start`／`day_window`; "which platform day is complete"
  from `app/ads/coverage.last_complete_day` (account zone; no zone → org's yesterday minus one, fail-closed); a queued job's run
  time from the queue's own clock (SQL `now()`, `background/recovery._queue_now`) — never the product clock, which drills move.
  Read ranges are clipped to the last complete day when recorded. Frontend: `lib/orgClock` (`useOrgClock`, `formatInstant`,
  `formatDay`, `addDays`, …) is the only `Date` maker; elapsed counters carry `ELAPSED_OK`. Deferrals send `revisit_on` (an org
  calendar date after today; `revisit_at` input removed). An ended campaign's totals say 「結束前 n 天」; a not-started one has no
  window (「還沒開始」).
- **Input rules (Contract I).** `app/core/input_rules.py` is the one table (money, count, percent 0–100, ISO date, `date_within`,
  enums via `vocab.require`, URL, uploads `UPLOAD_CAPS` with separate empty／oversize sentences, API key). Stores call it; the
  frontend sends the typed text (`lib/typedNumber.typedValue`) and prints the server's sentence (`field_errors` keyed per row on
  intake routes). Percentages are stored 0–100 (`close_rate`, the margin card; data migrated). `/rules` serves `limits`. Ad-set
  dates must sit inside the campaign (400 `group_dates_outside`). Model-read brief fields are stored `parsed`.
- **Readiness (Contract R).** `brand_intelligence` facade `product_readiness`／`sellable_products`／`knowledge_products` are the
  only readers; zero customer groups is not ready (complete and the who step refuse); archived products' sell-ways and bundles are
  not sellable (derived, no cascade write); knowledge products hold no money (409, money lives on sell-ways); every root product
  is born through onboarding; the product list items carry `kind`. Archived products／brands are listed and restored on existing
  screens (`?status=archived`, `GET /api/dashboard/archived-brands`, `POST /api/library/brands/{b}/restore`).
- **Background outcome (Contract J).** Every job registers through `background.register`; a handler returns `Empty(code, text)`
  or `Failed(code, text)` (or raises `JobFailed`), stored in `background_job_result` and read by `background.outcome`／`job_state`
  (`unknown` is never invented). Failures fail the job and reach the bell. `llm_task.error_code` is written on every failure;
  program refusals go through `gateway.record_refusal` (`program_refused`). Planner refusals carry codes (`plan.REFUSALS`,
  `strategy.REFUSALS`, `brief.REFUSALS`), are retried once with the reasons fed back (never `llm_failed`), and a second refusal
  returns 502 with `details {refusal, reason}`; a campaign being planned holds an advisory lock and serves `busy`. Ads queue
  refresh runs per brand (`background.ads_queue_refresh`); ads job codes include `runtime_error`, `queue_refresh_failed`,
  `preview_retry`, `original_missing`, `preview_failed`, `input_changed`, `reply_invalid`, `nothing_to_judge`. Meta backfill and
  daily pull, schedule pack submission and workbench rounds store their outcome; a stuck workbench round recovers after
  `repository.GENERATION_TIMEOUT_S`.
- **Known limits.** The Meta backfill outcome is per org while rows are per brand; a retried customer-voice failure stays listed
  for 24 h.


### 6.53 One HTTP translator, explained controls, canonical routes, named figures and platform ratchet (built in F51, 2026-10-06)
Audit W15, W16, W18, W19; W18's wizard contract is in `intake.md` under F51. Rule authorities remain the docstrings of
`frontend/src/lib/http.ts`, `app/core/figures.py` and `app/shared/web.py::app_path`, not copies in screen components.
- **Failure codes (Contract C).** API errors preserve `code`, `details`, keyed field errors and rejected values. Components
  branch on those fields instead of matching error sentences. Network failures, expiry and pending-path restoration all use
  `lib/http.ts` (Contract H). Failed writes are never replayed automatically.
- **Routes (Contract R).** Served links are router paths without `/app`; `app_path` builds them. `app_url` adds the prefix only
  for links leaving the SPA. Migration `20261006000101_core_interrupt_href_app_relative.sql` converts old inbox links.
  `lib/adsRoutes.ts` builds campaign and flow paths, with `perf` as the performance tab; old `performance` bookmarks redirect.
- **Figures (Contract F).** The seven bases at `GET /api/figures` own captions, formulas and units. `layout/Figure` prints them,
  preserves currency and shows null as unknown. ROAS payload keys identify the basis. All-channel ROAS is unknown for mixed
  currencies; platform spend totals are per currency. Earnings deduct both product cost and advertising spend. Review periods
  serve `ad_spend` and `ad_result_view`; the browser does not reconstruct missing values from raw rows. Historical review
  snapshots without the new keys remain unknown. `lib/figures` owns the two narrow preview/native-row ratio helpers.
- **Controls and feedback (Contract D).** Shared buttons accept `busy` or `disabledReason`, never bare `disabled`; idle disabled
  controls show an accessible reason. Save-in-place and clipboard actions acknowledge success or explain failure (design-system
  sections 6-7). All F51 per-issue guard allowances and F51 one-ruler pending files are removed.
- **Platform ratchet (Contract P).** `test_ads_no_platform_literal.py` scans native status words, platform imports and tokens
  outside adapters, with counted `(file, token)` allowances. Counts may only shrink; stale counts fail too. Full adapter
  migration remains deferred; `oneRulerPending/W19.ts` still records the two existing pause payloads.
- **Retained active-job exception (user confirmed 2026-10-06).** `SettleAngles` reads `found?.job.status` to show its position
  in the active AI queue. That API does not serve an outcome field. `oneRulerPending/W14.ts` is intentionally retained;
  converting this read to a background-result contract would require separate backend scope.
- **Checks.** Frontend `feedbackGuards.test.ts`, `figureGuards.test.ts`, ads `oneRuler.test.ts`; backend
  `test_figure_basis.py`, `test_action_url_targets.py`, `test_ads_no_platform_literal.py`. Machine checks and component screenshot
  pairs are implementation evidence, not independent drill scores or human visual acceptance.

### 6.54 Drill 12 remediation contracts (F52, planned 2026-10-06)

Status (2026-10-07): all 24 F52 repair issues are implemented and locally merged with scoped
checks and independent reviews. Final integration/drill/human acceptance is deferred by the
user's pause instruction. The heading retains its planning date and link anchor; it is not a
claim that all acceptance scenarios or quality thresholds have passed.
[F52](../../.work/features/F52.md) owns the queue;
[finding disposition](../drills/drill-12/remediation-findings.md) owns evidence reconciliation;
[acceptance A01–A14](../drills/drill-12/acceptance.md) owns executable examples and final gates.
These clauses extend the existing module contracts; they do not rewrite historical approvals.

**Contract S — one accepted decision, one built assignment.** Keep strategy in the existing
`budget_basis_json.strategy`, with a schema version and input/decision revision. Each proposed
slot has a stable slot ID, role, customer-group ID (or explicit unknown when permitted), selected
offer key, carried-ad ID or new-test intent, evidence references and rationale. Available IDs
come from planner_context, never from display names or invented model identifiers. Evidence
references identify source learning/result rows or known calendar facts, not model citations
to nonexistent documents. The allocation retains role percentages; budget helpers alone produce
whole amounts and capacity. The model explains its proposed allocation qualitatively and does
not claim an algorithm proved an optimal percentage.

Resolve eligible carryover and remaining capacity before a proposal is presented as executable.
The default preserves a carried ad's former role; a different role is permitted only as an explicit
proposed assignment accepted with that revision. No rule automatically promotes every relative
winner. A two-slot plan cannot promise three distinct audiences unless its actual representation
can support them. A missing/deleted/forbidden binding or infeasible capacity returns a structured
reason and revision exit before adoption. No silent fallback may overwrite accepted audience,
offer or role intent. LLM delivery generation may fill creative detail, not change bound slots.

Adoption validates the same version, serializes competing writes and persists groups/ads/retained
creative references in one transaction with idempotent operation identity. A retry returns the
same accepted result; invalid output leaves no partial plan. The delivery result is compared to
the accepted slots before commit. Store slot-to-built IDs in the receipt. Preserve image/copy
versions for carried ads. Subsequent explicit structure edits revise the decision projection and
invalidate stale rationale/approval according to existing rules, not a silent narrative rewrite.
Old strategies remain readable; a new adoption that lacks bindings requires regeneration and
confirmation. Existing approved historical plans remain intact. No migration is assumed necessary.

Serve available, proposed and actual facts as separate states. Candidate customer-group count
is not actual targeting. Actual unique customer groups and number of delivery groups are distinct.
Strategy, structure, brief and handoff consume the same revision and receipt; frontend prints
served counts, names, reasons and amounts. It does not reconstruct semantic bindings.

Wire contract for I01 (additive reads; required for new adoption): `strategy.decision` contains
`schema_version:1`, `revision:string`, `state:proposed|adopted|modified|legacy_unbound`,
`slots:[{id,role,customer_group_id:string|null,offer_key,carry_from_ad_id:string|null,
test_intent:string|null,evidence_refs:[{kind,id}]}]` and
`feasibility:{state:ready|blocked,reasons:[{code,message,slot_ids:string[]}]}`.
Exactly one of carry_from_ad_id and nonempty test_intent is supplied for a slot; legacy_unbound
may have no slots. Existing allocation/rationale fields remain, now referring to these slots.
Evidence kind is learning, result, calendar or brand_fact; identifiers resolve within the prepared
context. A null group is permitted only when that context has no selectable customer groups,
and renders unknown rather than an invented audience. The revision hashes decision-relevant
inputs/assignments/allocation, excluding read timestamps and rendered labels.
The existing POST campaign/plan receives `expected_revision` and `operation_id`; missing revision
on a new adoption returns 409 `strategy_confirmation_required`. A changed revision returns 409
`strategy_changed`; infeasible returns 409 `strategy_infeasible` with the feasibility reasons.
Successful adoption retains the existing campaign envelope and adds
`strategy.decision.receipt:{revision,slots:[{slot_id,group_id,ad_id,carry_from_ad_id}]}`.
Strategy/structure clients and scripted factories change before their UI consumers are dispatched.

**Contract P — every numeric projection names its window.** Keep raw performance history as
history. Campaign period projection selects the campaign window through the last completed
account day, with start/end inclusive; intraday provisional observations are separately labelled.
Totals, daily series, group/ad tables, shares and period grade use the same selected rows and
declared scope. Campaign-detail/list period totals and closeout/learning period inputs use this
projection too. Unknown/null remains unknown. Date-less imported campaigns use an explicit
requested/observed range rather than an invented date. Platform/account currency and attribution
remain part of scope. Monthly account spend, recent windows and comparison periods keep their
own explicit windows. Do not globally clip repository history or erase pre-period rows.

**Contract A — approve the displayed revision.** Retain the existing launch snapshot hash and
idempotent operation semantics. Initialization of effective settings/pixel-derived recommendation
must finish before serving an approvable revision. The displayed settings and hash refer to one
coherent snapshot; reads from different generations cannot create a false first-click conflict.
Detect real edits and require a fresh explicit approval. A cache refresh does not count as human
acceptance. Preserve the central unknown-network-result rule and money/permission checks.
The precise false-conflict cause remains a hypothesis until I07 captures the hash difference.

**Contract V — a new-ad action is checked by its handoff owner.** `new_ad.target_id` identifies
a placement; it is not an external entity. Single and aggregate change-item checks dispatch
new_ad to its approved handoff item(s), reusing handoff_check, its bindings, revision validation,
locks and attempt guards. Other action kinds retain their existing readback paths. The aggregate
serves successful observed time, attempted time and scoped settings/material proof explicitly.
Missing timestamp stays missing; a successful read is not stamped by the browser. Material
unknown/self-confirmed and independently read matching fields remain distinct. No settings
receipt asserts actual delivery or sales causality. Tenant/campaign checks remain mandatory.

**Contract R — user retry includes the failed scope.** Scheduled default sync keeps its current
window. An explicit user refresh/retry at the existing UI entry includes the same account's retained
failed monthly tasks as well as its requested current scope. Each monthly task keeps its original
range and generation/cursor resume rules; restart_required creates a safe fresh generation.
Queue processing remains bounded/page-based, and concurrent clicks deduplicate pending tasks.
Retain last good rows and coverage while retrying. Only actual scoped success clears a failure;
do not drop October merely because November succeeded. This does not expand routine monitoring
to ended/closed campaigns or trigger platform writes. Existing central error/outcome projection
reports remaining failure honestly. I11 updates user entry wiring, not background default meaning.

**Contract L — lifecycle is not delivery.** Keep lifecycle storage/transitions unchanged, but
serve current-period lifecycle wording separately from delivery counts/state/freshness and a
capability-aware next action. Known paused is different from unread/unknown; live alone cannot
claim an active ad. Reuse adapter vocabulary and canonical route builders. No automatic activation
or requirement to spend money. On sync completion, workspace/performance/row detail consume the
latest generation; a late response may not overwrite newer state or another campaign. Keep folds
and independent errors intact. Existing reload callbacks must be investigated before adding more.


### 6.55 Supervised first-release evidence contract (F53, planned 2026-10-07)

Status: implemented through the approved F53 queue and narrowly reviewed acceptance-tool
calibration (2026-10-08). This is the authoritative implemented evidence contract; actual
technical/human/release dispositions remain in the first-release packet and ignored G8 sidecar.
Scope is supervised own-brand use: defensible proposals, faithful accepted assignments and
traceable next-period adaptation. F48-F52 remain open; F52's unchanged nine-dimension drill
is paused and is not replaced by this release gate. No publication, push, paid call or platform
write is included.

#### Ownership and persistence

Keep the existing learning ledger and public brand-intelligence facade unchanged. All ads
writers still enter through `ads_learnings.write`. Use its existing `applicability_scope` text
for an additive, versioned evidence trailer: the exact existing base scope, followed by
`\n@evidence-v1:` and one canonical JSON object. JSON is serialized on one line (embedded
newlines escaped). No second ledger, new table, migration or direct cross-owner SQL is planned.

A narrow pure helper in `app/workbench/learning_evidence.py` owns trailer decoding/encoding,
normalized meaning and qualification for its creative consumers. Export only
`encode_learning_scope(base_scope, evidence)`,
`base_learning_scope(scope)`, and
`qualify_learning_evidence(rows, current, *, min_result_events, max_age_days)`
through `app.workbench`. It performs no SQL, model call, clock lookup or write. Ads already
depends on workbench; workbench must never import ads. Ads owns source extraction, numeric
rules/thresholds, current conditions and the call to that pure helper. Workbench supplies the
same current-condition shape from its own public brand reads. Reuse existing public facade
reads; no new legacy capability. Decode malformed/unsupported trailers conservatively,
retain original history and expose unknown qualification. All existing scope parsers and
comparisons first consume `base_learning_scope`; preserve coordinate v=2 and visual scope
semantics. Round-trip, delimiter/Unicode/malformed and old-row fixtures are mandatory.

Trailer shape (all listed members emitted; unknown scalar values are null, never invented):
- `schema_version:1`, `source_kind:campaign|pause|ab|settle|coordinate|visual`,
  `source_ref:{campaign_id,ad_id,action_id,entity_id,trial_id}`, `source_version:string|null`;
- `provenance:platform_observation|user_report|operation_readback|simulation|unknown`;
- `period:{start:string|null,end:string|null}` (inclusive org-calendar dates);
- `scope:{product_id:string|null,audience_key:string|null,customer_group_id:string|null,
  claim_key:string|null,claim_family:performance|brand_fact|operation,
  objective_family:string|null,result_kind:string|null,currency:string|null,
  attribution:string|null}`;
- `conditions:{price_version:string|null,offer_key:string|null,offer_version:string|null,
  material_version:string|null,target_version:string|null,valid_until:string|null}`;
- `sample:{result_events:number|null,sufficient:boolean|null}`,
  `direction:support|contrary|inconclusive`, `limits:string[]`.

The helper current input is explicit: {org_id,brand_id,product_id,org_day,audience_keys:[],
customer_group_ids:[],result_kind,currency,attribution,conditions:{price_version,
offers:[{key,version,valid_until}],materials:[{ad_id,version}],target_version},
mode:real|isolated_simulation}. Unknown scalars are null and unknown menus are empty with an
explicit conditions_unknown limit. Caller-provided labels are presentation only. The helper
returns {items:LearningEvidence[],revision,eligible_count}; callers wrap scope label/id/omitted
into evidence_context. Caller source extractors hash sorted canonical relevant source facts
and immutable creative/price/offer/target snapshots to obtain versions; no hash from a name,
job success or read timestamp. Sampling sufficiency is recomputed from known event count and
the caller's unchanged threshold, never trusted merely because stored confidence says validated.

Sources are qualified from actual observation/source records, not internal campaign origin,
a successful job, a manually entered sentence or a front-end label. A pause receipt is
operation_readback. A/B's associated market comparison is a separate qualified observation,
not established by the pause. User-provided month angles identify a message, not provenance.
Simulation remains simulation structurally across all tracks, including coordinate and visual.
Unknown legacy provenance is historical; recover only facts proved by retained source records.
Do not bulk rewrite old ledger rows or certify origin from text matching.

#### Support and applicability

The compatibility cohort is tenant + brand + product + audience/claim meaning + result kind +
currency/attribution + relevant condition versions + observation provenance. An unknown
product is not a product-wide permission. Explicit confirmed brand facts may support multiple
products as facts, never as product-specific performance. Exact text is not cohort identity.
Preserve existing `triage.MIN_RESULT_EVENTS=10` and the separate original rank/sample rules;
do not change grades, budget arithmetic or low-sample verdict acceptance.

Count independent qualified trials, not rows. Replay/action recheck is idempotent. Campaign,
coordinate, visual, settle and A/B derivatives of the same source trial count once for the
same claim; overlapping measurement windows do not add independent support. Stable sorting
uses source period then source ID, never accidental SQL order. Keep independent_count and
same_direction_count distinct. A new contrary comparable trial resets same-direction support
to the new observation; older contrary/supporting observations remain inspectable history.
Inconclusive, unknown, operation, simulation and thin samples cannot promote market support.
Compatibility transport levels remain observed (one), likely (two), validated (three or more)
for sufficient independent same-direction market observations. These levels describe scoped
association; UI/prompt wording never says causality is established or promises promotion after
one additional repeat. Pause wording names the action and unknown performance cause. Settle
wording says within/above the declared cost cap for that period, not universally effective.

Compute current eligibility on read from the requested product, org day and relevant known
price/offer/material/target/measurement conditions. A relevant changed or ended condition is
revalidation; another product is excluded; expired/superseded/unknown-source results are history.
Performance older than the existing 180-day visual-result horizon needs revalidation; adopt
that horizon for ads performance only. Brand facts have no blanket age expiry. Unknown
decision-critical conditions cannot certify current applicability. Preserve newest-current-
campaign-verdict behavior; history still includes previous verdicts and original ranks.

`use_state` is usable|history|revalidation|excluded. A usable thin observation can justify
a labelled test or retained control, not promotion, proven effectiveness or automatic scaling.
`allowed_uses` is a subset of test|retain_control|market_support|brand_fact|operation.
An operation receipt allows operation only. Simulation is excluded from real-brand market
support/proposals; isolated acceptance may exercise the same paths with explicit simulation
labels. Existing accepted/carry bindings stay readable and recoverable; historical original
creative can remain a declared control without being falsely promoted to present effectiveness.
No available eligible evidence is a valid cold start, not a failure or fabricated history.

#### Additive read map and revision identity

Use one normalized `LearningEvidence` projection (required on new server responses):
`{schema_version:1,id,meaning_revision,display_text,support_label,provenance,
sources:[{kind,id,version,period:{start,end},label}],
scope:{product_id,product_label,audience_key,customer_group_id,claim_key,claim_family,
objective_family,result_kind,currency,attribution},
conditions,sample,independent_count,same_direction_count,contrary_count,
use_state,reason_codes:string[],reason_labels:string[],allowed_uses:string[],limits:string[]}`.
All unspecified source/scalar values are null; counts are backend-owned. meaning_revision
hashes actual learning_text, normalized evidence, support and eligibility; read timestamp,
rendered labels and row order are excluded. Source/condition changes must invalidate meaning
even when the learning ID stays constant. Reason codes include scope_required, other_product,
unknown_source, conditions_unknown, condition_changed, offer_ended, measurement_stale,
superseded, insufficient_sample, simulated, operation_only and contradictory_result.

| Existing response / owner | Implemented additive projection |
|---|---|
| Campaign budget_basis_json.basis.learnings / strategy + planner_context | Each StrategyBasisLearning gains required evidence; basis gains evidence_context snapshot |
| GET /api/ads/brands/{brand_id}/learnings / ads_learnings + learning_routes | Each AdsLearning gains evidence; optional sell_way_id query qualifies current use without hiding history |
| GET .../coordinate-learnings / learning_view + learning_routes | Existing campaigns/groups/next unchanged; each LearningRow gains evidence; top-level evidence_context contains all capped ads/coordinate/visual items and eligible reasons for the same selected scope |
| Change-set item.learning / ads_learnings.view_for_item + change_control_data | Existing recorded/confidence/count retained; evidence is required and null only when no learning was recorded |
| Internal review evidence/model_input / review_evidence + review_rounds | Add capped learning_context with the same evidence_context shape; existing evidence hash covers qualification/revision, preventing stale review generation |

`evidence_context:{schema_version:1,revision,scope_product_id:string|null,
scope_label:string|null,eligible_count:number,items:LearningEvidence[],omitted:number}`
uses the supplied sell_way_id, else the existing latest next.sell_way_id. Unknown/deleted
scope produces scope_required and no product-specific eligible count. Strategy always uses
its selected campaign product. No front-end scope/count inference. Keep campaign/row/nav
counts separate. Product filtering must also apply to coordinate prompt input and all brief,
copy, review and visual consumers; their historical data must not silently become current
performance evidence. Library's original ranks and money remain served as before.

I01 settles these additive shapes and every affected typed factory before UI dispatch.
Strategy/plan/copy use the same normalized snapshot. decision_context hashes it, not the
nonexistent ledger `text` key. A stale proposal is blocked on read and rejected on adoption
with existing strategy_changed conflict semantics. Preserve input on refresh/failure, atomic
receipts, accepted slots, ordinary same-scope retry and exact original carried copy/images.
Display snapshots remain historical snapshots; do not silently update their accepted revision.
Contract S's explicit offer=none remains legal even when offers exist, with a reasoned choice.
Align the existing department prompt, validator and evidence references; no hard-coded split,
extra scoring agent or new model arithmetic.

#### Current inventory and dispatch coverage

Static inventory on product HEAD 2375e161 (2026-10-07):
- Campaign closeout: closeout -> learning.write_learning; separate coordinate and visual
  writers run through ads_learnings.write. Source cycle is campaign or campaign:ad.
- Pause/A-B: change_control_verify.check -> record_for_item / record_for_ab_item after the
  committed setting receipt; runtime rechecks the same action. Cycle is action ID.
- Month settle: settle.confirm -> ads_learnings.write; cycle is settle:month:entity.
- Main readers: ads_learnings.list_for_brand/view_for_item; learning_routes;
  learning_view; coordinate_learning.prompt_view/ranked_section/gate_pairs/keep_ads;
  planner_context.ads_learnings/prepare/creative_basis/creative_projection;
  strategy decision_context/generation/served/adoption and plan.
- Downstream: assets/asset_suggestions/asset_suggestion_policy -> workbench creative context;
  workbench.prompts.creative_text, jobs image generation and looks.visual_learnings;
  review_evidence/review_jobs/review_rounds and month_summary/closeout use the same served outcomes. No other direct
  ledger learning writer was found outside the public facade and ads_learnings.write.
  context_compiler documents its retired ledger prompt path; do not reactivate it.
- Backend factories: test_ads_closeout, learning_ledger, learning_flow, learnings_api,
  coordinate_learning, learning_rank, learning_view, visual_learning, live_creative,
  settle, planner_context, strategy, strategy_decision, plan, plan_scripted_reply,
  one_ruler, assets, asset_suggestions, review_cycle/month_summary and workbench
  looks/image_round/brief/copy/claims suites. Test fixtures use real response shapes.
- Frontend factories: StrategyTab, PerformanceTab, detail/CampaignDetailPage, LibraryPage,
  learnings/learnings, ChangeControl, flow/{VerifyPage,AbFlow,CleanupVerifyRows,ConfirmPage,
  HandoffPage}, review/CopyPage and settle/{SettlePage,SettleResult}. Preserve other screens'
  behavior; no unrelated redesign. E2E consumers include ads-cold-start, ads-target,
  guided-advanced and width-overflow. I01 owns shared shapes; UI issues own their screen tests.

Frozen counterexamples: C03/E01 cross-product promotion; C04 simulation promotion;
R02 400-day-old result; R04 revalidation flag without exclusion; D02 same-ID meaning edit;
D03 contradictory offer prompt. Additional fixed boundaries: null/zero/unknown source and
scope, mixed currency/attribution/result families/tenants, overlapping/replayed observations,
new contrary trial, invalid trailer, expired offer, changed price/material/target, removed
audience, deterministic ordering, org midnight, thin sample, duplicate action check and
unchanged accepted carry/none-offer. Probe counts are diagnostic, not a completion percentage.

#### Fixed first-release gates and stopping rule

Expectations are frozen here before code changes. I07 implements one isolated acceptance
runner using existing drill/F13-F15 helpers; it must not rewrite original drill evidence.
One controlled brand, product A plus incompatible product B, groups A1/A2, cost cap 300
in one currency/attribution; periods 2026-07-01..07-31, 08-01..08-31, 09-01..09-30.
Market-shaped fixtures use an injected platform reader to exercise the platform_observation
branch; the entire receipt is labelled synthetic, never real market proof. Separate simulation
fixtures persist provenance=simulation and must remain excluded from real-market support. Preparation freezes observation IDs, context and expected
transitions; alternative reasoned model allocations are allowed.

G1: July starts from confirmed brand facts, no history, adopts an explicit none-offer test.
Close with 2 result events and cost-per-result 200: retain original rank/low-sample labels,
do not promote confidence. August may propose a labelled test/control with uncertainty.
G2: August contains one sufficient disjoint trial (10 events, cost-per-result 200); inject
same-trial derivative/replay rows and product-B matches. Only independent product-A support
counts. September proposal cites actual evidence and changes audience/offer/carry/test intent,
or states a justified retained choice; rhetorical rewrites alone fail adaptation.
G3: September has a sufficient contrary trial (10 events, cost-per-result 400). Current
support cannot monotonically rise. Preserve history and lower support/new hypothesis.
Before next adoption, change an offer/price/material/target and mutate same-ID learning meaning
in separate fixtures: each blocks the displayed stale revision, keeps input and allows explicit
refresh/reconfirmation. Adoption receipt and actual audience/offer/carry/test assignments match.
G4: Exercise pause/A-B/month/coordinate/visual source qualification, provenance, overlapping
windows, 400-day history, unknown legacy scope and cold start at source and reader boundaries.
Preserve money rules and original rankings; no invented fact, causal conclusion or silent input loss.
G5: Three UI screens match this exact HTML prototype and states at 1024/1920. Reference/build
pairs, keyboard/focus, loading/empty/error/retry/stale/input-retention and the design five
questions are separate from function pass. Sample percentages/names never become defaults.
G6: Diagnose the recorded 60-second provider timeout from retained logs, executable/model/auth
availability and subprocess behavior before one new bounded real-provider sample through
the existing gateway. Default call cap stays 60 seconds, tools disabled, synthetic context,
no direct paid API. Freeze inputs/semantic checklist first; no generation-until-pass or blind
timeout extension/model switch. Output must respect facts, uncertainty, explicit no-offer
and bindable slots; no optimal-strategy or profit claim. A fresh failed call stays unverified.
A different model/provider, timeout policy or external cost is an unresolved change, not
implicitly authorized by the queue.
G7: On the selected private release environment, prove genuine login/session-expiry and
ordinary recovery without forged tokens, plus Postgres backup restore into a separate
disposable target and schema/row/tenant/asset-reference checks, including restoration and
byte-hash equality of sample Storage objects into an isolated owned destination. Do not overwrite shared public,
delete another task's data or expose backup secrets. Existing provider availability is checked.
No new backup service/framework or public deployment is planned. The user selected this Windows host for local/private use during carve. If its required
capabilities are unavailable, record G7 unverified and do not call the release eligible.
G8: On the final code tree, restart the matching backend, run the fixed cycle once and assemble
source-matched G1-G7 receipts. Commit the tracked packet and scoped documentation closeout
before one clean Harness feature integration. The tracked packet contains only a pending G8
pointer to the lead-owned ignored `.harness/scratch/F53/final/` sidecar, never a predicted
integration HEAD, signature or pass. Its receipt-only verify uses --pre-integration and does
not demand its own pending integration receipt. After integration succeeds, preserve its actual
CLI result/exit and `.harness/runtime/integrations/F53.json` receipt with hashes and timestamps
in that ignored sidecar. The final checker reads those receipts and seals an ignored combined
packet without changing tracked files, Feature/Issue bytes or HEAD. It recomputes the installed
Harness integration signature, checks the same successful run/required steps, relevant product
and runtime/config fingerprints, source evidence and cleanup. Never invoke integrate as a read
check. Seal before human close; a subsequent close changes HEAD and removes queue inputs, so
the archived seal then represents its explicitly captured pre-close version. Human acceptance
remains separate. No cycle/model/auth/restore rerun is performed during sealing. The combined
packet includes model limits and fixed/remaining/unverified disposition. Manifest suites
run once through integrate; affected failures may be corrected/rechecked within approved scope.
Do not begin another full drill/repair campaign after the agreed report boundary. F52 remains
open and its unrun original acceptance is explicitly recorded.

Release eligibility requires all blocking gates and genuine human UI acceptance. Copy/image
polish and simulated profit are not gates. Completed issues, historical green checks, a model
sample or fixture counts do not certify readiness, live delivery, causality or revenue.
