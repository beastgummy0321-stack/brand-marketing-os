# 投放中心：Campaign、策略、投放與結案

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
