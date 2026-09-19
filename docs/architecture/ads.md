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
6. **Outcome attribution is by bound entity.** One `ads_outcome_daily` row per (entity, day), fed
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
