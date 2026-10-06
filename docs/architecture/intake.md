# 建檔：品牌事實、商品經濟與研究

本頁是此領域的現行決策；只在任務涉及此領域時讀取。邊界與所有權見 [架構入口](../../ARCHITECTURE.md)。
保留原 §8 編號供既有票引用；其他 § 編號由架構入口定位。舊 Feature 編號是來源標記，不是必讀文件。

## 8. 品牌地基與可投放檢查表 — settled decisions (2026-09-14, F05)

These are decided. A worker implements them; it does not re-open them.

1. **One product, many 賣法; knowledge on the parent, money on the child.** `product` gains a
   nullable self-referencing `parent_id` (same org/brand, `ON DELETE CASCADE`, `CHECK (parent_id IS
   NULL OR parent_id <> id)`). **One level only** — a child may not have children, enforced in
   `brand_intelligence.repository.create_product`, because a CHECK cannot see another row. A child is
   a 賣法 (單瓶／3 入組／5 入組／隨身包) and its `name` stores the full display string
   「<母產品名> · <賣法>」, so every screen that prints a product name keeps working untouched.
   **Knowledge lives on the parent** (`product_fact`, claims, 商品照, coordinates); **money lives on
   the child** (`product_economics`, one row per 賣法). One reader resolves it —
   `brand_intelligence.repository.knowledge_product_id(conn, brand_id, product_id)` =
   `COALESCE(parent_id, id)` — and the three existing readers call it: `app/llm/context_compiler.py`
   (facts into every prompt), `app/workbench/jobs.py::_product_line` (the 商品照 lookup) and
   `app/ads/strategy.py::_products_section` (one fact block per 母產品, one line per 賣法, capped
   like every other prompt list, §1). Budget uses the campaign's chosen `product_id`; when that id is
   a parent, `budget._economics_for` falls to its **first child** (the wizard writes「單品」first).
   結案與學習 aggregate at the parent — F05 records the rule and builds no screen for it.
   **Not built:** a variant table, a pack-size column, bundle auto-arithmetic (a 3 入組's cost is a
   number the user types, never one the program multiplies).
2. **One conversion value, one formula.** 「一次轉換值多少錢」 = `(售價 − 單位變動成本 − 運費) ×
   成交率`, 成交率 being the new nullable `product_economics.close_rate` (NULL = 一次轉換就是一次
   成交, so a goods row computes exactly as it did before F05). `app/ads/budget.py::breakeven_cpa`
   is the one place that multiplication happens. 服務 declares 成交率 and 每單毛利; 運費 is 0, never
   NULL, because「沒有運費」and「不知道運費」are different facts. There is **no brand-level 業務類型
   column**: 商品／服務／兩者 and 廣告帶來的是什麼（直接下單／先詢問再成交／留資料）are controls on
   the wizard's step 3 — the first decides which block is shown, the second decides whether 成交率 is
   asked at all — and the durable answer is the offering rows themselves (`brand.industry` was
   dropped in 2026-08-29 for having no reader; this would have had one).
3. **An assumed number stays labelled for the rest of its life.** When the user says 不知道 the
   program fills a benchmark and records which fields were filled that way in the new nullable
   `product_economics.assumptions_json` (`["cost","shipping","close_rate"]`; same column on
   `product_economics_version`); editing the field clears its flag. The benchmarks live in **code
   with their sources** — `app/brand_intelligence/benchmarks.py`, one module-level table, each entry
   carrying label, value, source name, source URL and fetch date (evidence:
   the historical onboarding probe (not a required input)). **No model ever supplies one of these numbers**, and
   the screen always prints where it came from (「美國 2025 基準，起點用 · 來源：…」). There is no
   Taiwan primary source for any of them — that is said on screen, not hidden. They are replaced by
   the brand's own closed-campaign numbers (the 閉環 feature), not by a better blog post. `cpa_roas_basis` was
   **not** reused for this: that column was dropped in `20260903000004`, and its name says something
   else.
4. **成效來源 is `brand.conversion_goal`**, which already exists (`purchase`／`lead`／`booking`／
   `awareness`) and already maps to platform events in one place
   (`app.meta.repository._CONVERSION_ACTION_PRIORITY`). The wizard's step 4 sets it; nothing else
   asks. `ads_outcome_daily.purchases` therefore means 「這個品牌的成效目標被達成幾次」 — the column
   keeps its name (its migration is applied), and every screen label for it comes from the brand's
   conversion goal, so a 名單 brand reads 每筆名單成本 where a 購買 brand reads 每次購買成本. A new
   `success_metric` value for leads would have been the same arithmetic under a second name, so
   there is none: the metric stays `cpa`／`roas`／`purchases` and only its **label** varies (§0
   「不預設」).
5. **可投放檢查表 belongs to `ads`, and it has three colours.** `app/ads/readiness.py`, exported as
   `app.ads.launch_readiness(conn, org_id, brand_id)` from the module's public entry and served at
   `GET /api/ads/brands/{brand_id}/readiness`. `ads` is the owner because it is the module that
   answers「能不能投」 and it already reads all three inputs through declared facades
   (`brand_intelligence` for offerings and economics, `channels.py` for the bound ad account,
   `brand` for the conversion goal); the reverse — the wizard owning it — would need `ads` to import
   `app.intake`, which LAYER_ORDER forbids. Three rows (至少一項要賣的東西且填了數字 · 廣告目標已設定
   · 廣告帳戶已接上並指定給這個品牌), each **綠／黃／紅**: 黃 means the row works but stands on an
   assumed number or on data still arriving — at least one economics row carries `assumptions_json`,
   or the ad account is bound but the 37-month backfill has not finished. Every row prints **why** it
   is the colour it is, and a 黃 row carries a「去改」deep link into the wizard step that owns it. The
   primary button follows the worst colour: 紅「先補齊地基」／黃「進入投放中心（有假設值）」／
   綠「進入投放中心」, and「還是要先建立」appears only on 紅. Every line's text and its link ship from
   the backend and are rendered verbatim (§5.3). Two consumers: the wizard's completion screen and
   投放中心's 建立 Campaign entry. **It never refuses.** No「N 條 confirmed 事實」threshold: facts
   affect copy quality, not whether money can be spent. Whatever is assumed here is named again in the
   strategy's basis text ——「用的是假設成交率 20%」—— so a number never loses its label downstream.
6. **(Superseded by F42 below.) The wizard writes the facts it collects.** Measured 2026-09-14 on the drill data: the only
   caller of `repository.create_items` is `state.py:284`, fed by the paste step — so **the external
   AI paste is the single writer of `brand_fact`／`product_fact`**, and a user who stops before it
   ends with zero knowledge however many questions they answered (常春健康: paste done → 11 items,
   4 brand_fact + 3 product_fact confirmed, 0 `product_economics`; MOVE Daily: stopped at step 3,
   0 items, 0 facts, economics only because the user found the product page herself). F05 closes
   this by having the system run the research itself and feed the reply to **the same parser**
   (`state.apply_paste` → `paste_parse` → `create_items`), with the external-AI handoff kept as a
   collapsed advanced option. No second parser, no new fact writer. The in-system run gets its
   **own** prompt, assembled in `app/intake/research.py` the way `ai.run_scan` already does:
   `script.build_prompt` is written for a web-enabled external AI (it demands sourced URLs and
   verbatim customer quotes) and this path has **no web search** — `gateway.TaskOptions.tools`
   defaults to `None` and no production call site enables `providers.WEB_SEARCH_TOOL` (ADR 0048
   deferred it; it bills per search). The program fetches the user's own URLs through
   `app.core.net.fetch_url` and hands the text over; the prompt forbids inventing a source, and
   顧客原話 stays an honest 累積中 unless the user takes the advanced paste path. Opening web search
   is a user ruling, not a worker's.
7. **沒有迴圈歷史時，預算讀廣告帳戶的歷史.** `ads.repository.budget_history` returns
   `{"source": "ads_loop"|"meta_account", ...}`: when no closed ads-loop campaign has settled spend,
   it falls back to the brand's own connected ad account (近 30 天每日花費 + CPA, read through
   `channels.py` → `app.meta.repository.spend_summary` with the brand's `conversion_goal`). The
   caption names which one it used. Nothing tracked → honest cold start, unchanged. **No model reads
   ad history** (ADR 0067): every number here is program-computed and the model only phrases it.

### F31 (2026-09-26): offerings choice, start-step draft, one job-status rule
- The offerings step's two choices (賣什麼, 廣告帶來的是什麼) are stored on the draft (`intake_draft.offerings_choice_json`);
  `close_rate` cannot tell 先詢問 from 留資料. Saving advances the draft to step 4. Sell-ways come back in creation order
  where "first 賣法" matters (offerings, `ads.budget._economics_for`); `list_products` keeps name order.
- The start step's text fields are kept in browser storage per user, org and brand until a successful submit; photos are not.
- **One job-status rule** (also used by `app/brand_web` and `app/schedule`): a status reader first asks
  `app.background.job_outcome(lock)` about the newest queued job — active → running; failed → failed, quoting the
  `llm_task` error when that job wrote one, else `JOB_FAILED_MESSAGE`; otherwise the `llm_task` row rule. A handler whose
  save fails after a successful AI call sends its notice and re-raises, so the job ends failed. Research re-asks once when
  the reply's table cannot be read.

### F38 (2026-09-29): 「證據」 brand facts
- `brand_fact.fact_type='proof'` carries a required `fact_key` ∈ {customer_review, expert_endorsement, lab_report, sales_numbers,
  media_coverage, founder_voice} (CHECK-constrained; other types keep NULL). Labels = the `proof` coordinate seed labels
  (`app/core/vocab.py::PROOF_KINDS`, copied). Entry points: brand onboarding step 4 and the library FactPanel (「哪一種證據？」 select) — F42.
- `available_proof_keys(conn, brand_id)` (facade) = confirmed proof facts' keys ∪ {customer_review} when an active customer-voice
  row exists. Readers: `app/ads/plan.py`, `app/workbench/jobs.py` (ads.md §6.42). Evidence text reaches the copy prompt through
  `workbench/claims.prompt_sources` (proof facts always listed, regardless of the RISK regex).

### F42 (2026-09-30): brand onboarding — one interview, AI-prefilled, confirmed step by step
Supersedes rule 6 above and the F38 「truth cards do not propose 證據」 line. Products are not asked here (F43 product onboarding).
- **Seven steps** (`app/intake/state.py::WIZARD_STEPS`; routes `…/onboarding/*` in `app/intake/routes_onboarding_api.py`, logic in
  `app/intake/onboarding.py`): 1 基本 (name, websites ≤5, brand photos by kind logo/store/team/brand_image/other, 投放地區, 適用法規,
  投過廣告嗎) · 2 AI 讀網站 (skipped when there are no URLs and no photos) · 3 品牌是誰 · 4 證據與政策 · 5 素材 · 6 接工具 · 7 完成
  (the 可投放檢查表, five rows, ads.md §6.46). A completed brand re-enters at step 7; `?step=N` reopens a step. The low-key entry is
  the 「品牌資料（建檔時填的）」 link on 經營概況.
- **One writer per fact, every fact has a field.** The research → paste → truth-card stage, the AI Q&A, the old scan and the old
  step 3 「賣什麼與數字」 are deleted. Where each fact lives: positioning / tone (`params_json.tones`, 1–2) / visual →
  `brand_fact` `positioning`/`tone`/`visual_base`; brand proof → `brand_fact` `proof` + `fact_key`; store policy → `brand_fact`
  `policy` (`fact_key` = registry key or `custom`, `params_json`, `value` = the program-composed sentence; written only by
  `save_brand_policies`); 7-day cooling-off exemption → policy key `cooling_off_exempt` + disclosure (no row = the law applies);
  forbidden phrases → `rule` `forbidden_word`; media → `brand.media_capability` ∈ {photo, photo_video} (NULL = never asked);
  brand photos → `official_asset` with `product_id` NULL.
- **Store policy registry** = `app/core/vocab.py::POLICY_TYPES` (26 types from SHOPLINE／CYBERBIZ／Shopify／蝦皮／TW supplement
  shops; 8 `common`; each with params, an offer key or `none`, a threshold param where it has one, and a sentence template). The
  API ships it to the screen; the frontend keeps no copy. 7 天猶豫期 (消保法 §19) is shown fixed; 「不適用」 only for a statutory
  exception with its web disclosure text (≥10 chars).
- **AI prefill** (`app/intake/ai.py::run_prefill`, task `intake_prefill`, job `background.intake_scan(prefill=True)`): one gateway
  call reads ≤5 fetched pages + ≤5 brand photos, no web search, no user description; each entry is contract-checked on its own
  (unknown keys dropped, a source note naming something not read is dropped) and stored in `intake_draft.prefill_json`. A prefill
  is a proposal shown with a source tag (「✦ about 頁」); it is confirmed only by the step's 下一步.
- **自訂** (`app/intake/custom.py`, task `intake_custom`): one small call turns a plain-language sentence into a field value or a new
  option for that block (positioning, tone, visual, brand_proof, policy, forbidden), contract-checked (digits must appear in the
  user's sentence); it returns a proposal only, shown once where it lives, marked 「你自訂」; 下一步 saves it.
- **Connectors** = `app/intake/connector_catalogue.json` (what each connector reads; Meta live, csv → orders import, the rest seats:
  Google/TikTok, GA4, Search Console, shop platforms, MCP, custom API). Binding a second Meta account adds it (「再接一個帳戶」);
  unbinding stays in 設定 → Meta. The conversion goal saves on a completed brand too.

### F43 (2026-10-01): product onboarding, sell-ways and bundles
Supersedes rule 1's 「one level only」 / 「not built: bundle auto-arithmetic」 limits; the parent/child 賣法 rows of F05 still read.
- **Product = knowledge, sell-way = what a campaign sells.** A knowledge product (`product`, `parent_id` NULL, new `page_url`,
  `onboarding_step` 1–5 while unfinished — such products and their sell-ways are not pickable) carries facts (`core_info` /
  `mechanism` / `differentiation`), product photos (`official_asset`), 1–3 customer groups (`product_customer_group`: who, 1–2 of the
  six `pain` keys, quote, when used, source), product proof (`product_fact` `proof` + `fact_key`) and claims (`claim`
  approved／forbidden; 食安法 hits forced 不能講 via `workbench.validate_claims`). A sell-way is a `product` row with component rows
  (`product_component`: product × qty; a cross-product bundle has several, `parent_id` NULL) and its own `product_economics`
  (+ `list_price`, `cap_per_sale`, `landing_url`). Both new tables live in `brand_intelligence`, written only through its facade.
- **One resolver each**: `knowledge_product_ids(conn, brand, product_id)` (components in order; F05 rows fall back to `parent_id`);
  `get_product_economics` returns effective values — NULL list price = Σ component single prices, NULL cost = Σ component costs,
  named in `derived_fields`; `raw=True` for read-then-write callers. Offers from the price itself: list price > price →
  `bundle` (more than one unit) or `discount`, sentence 「〈name〉優惠價 NT$x（原價 NT$y）」, added to `offer_sources`.
- **Five steps** (`app/intake/product_onboarding.py`, routes `app/intake/routes_product_api.py`, screens `frontend/src/components/intake/product/`):
  是什麼 → 誰會買 → 證據與說法 → 賣法與價格 → 完成; routes `/brands/:b/products/new`, `/brands/:b/products/:p/onboarding?step=N`.
  The product page (`/brands/:b/products`) lists 商品, 組合 and brand-scan suggestions; 經營概況 shows 「你的商品」 on top.
  Bundles: `/brands/:b/products/bundles/new|:id`; `POST …/bundles/preview` returns the saved-bundle shape without writing (the create
  path in a rolled-back transaction). Break-even and offers always come from the server.
- **Product prefill** (`app/intake/product_prefill.py`, task `intake_product_prefill`, job `background.intake_product_prefill`): one
  call on the product page text + ≤3 product photos, per-entry contract checks, a customer quote must appear in the page text; stored
  in `intake_product_prefill` (intake-owned) as a proposal. Cost cap = the brand's shared cap (products are usually built after the
  brand draft is closed). Product 自訂 blocks: difference, group, pain, product_proof, claim (`CustomEscape` takes a `propose`).

### F45 (ruled 2026-10-02; built in F45): base and composed sell-ways
Supersedes F43's 「sell-way = product × qty」 storage and its 「earliest qty-1 sell-way of the product」 derivation (drill 10 B1/M1/O1,
drill 9 #9: quantity had no unit, so a ×N sell-way priced its cost from whichever one-unit sell-way came first).
- **Two shapes.** A *base* sell-way binds exactly one knowledge product and has no quantity — it is the unit (單盒, 體驗包): a
  `product` row with `parent_id` = that product and no `product_component` rows (F05 child rows read as base). A *composed* sell-way
  is a list of base sell-way × qty (12 盒 = 單盒 × 12; 5 盒＋2 包 = 單盒 × 5 + 體驗包 × 2): `product_component.base_sell_way_id`
  (renamed from `product_id`) → an active base sell-way of the same brand, `qty` > 0, each base once, Σqty ≥ 2. Its `parent_id` is
  the knowledge product when every base belongs to one product (listed and named under it, 「〈商品〉 · 〈名稱〉」), else NULL (a
  cross-product bundle). A component is never a composed sell-way or a knowledge product. Changing a sell-way's shape is refused.
  `product.free_shipping` (bool, default false) = 「這個賣法免運」.
- **Facade** (`app/brand_intelligence/repository.py`): `save_sell_way(…, product_id=None, components=None, economics, landing_url,
  free_shipping, actor)` — exactly one of `product_id` (base) or `components` `[{sell_way_id, qty}]` (composed). Base needs a price
  > 0; a composed price may be empty. Refused: a component that is not an active base of this brand, has no confirmed price, or
  is in another currency than the sell-way; a currency change of a base that an active composed sell-way uses.
  `composed_using(conn, brand_id, base_id)` = the active composed sell-ways that list a base (archive guard). `list_sell_ways`
  items add `shape` (`base` | `composed`), `free_shipping`, and components `{sell_way_id, qty, name, product_id, product_name, price,
  cost, currency}` (the base's display name, its knowledge product, its own effective price / cost); `kind` (`single` | `bundle`)
  keeps meaning 「listed under a product」 vs 「cross-product」.
- **Derived numbers, on read** (`get_product_economics`): a base derives nothing. A composed sell-way's empty `selling_price` /
  `list_price` = Σ qty × each base's confirmed effective selling price; empty `unit_variable_cost` = Σ qty × each base's cost. A part
  that is unknown or in another currency leaves the field empty (not derived). `derived_fields` names what was filled; every screen
  that prints a derived number or a break-even computed from one labels it 推算. `product_economics(.version).selling_price` is
  nullable for composed rows only.
- **Knowledge** (`knowledge_product_ids`): a composed sell-way → each base's product in component order, each once; a base → its
  product. Customer groups, proof, claims, photos and the bundle page's 「廣告會用到的」 read through it.
- **Own offers**: effective list price above effective price → `discount` for a base, `bundle` for a composed sell-way, sentence
  「優惠價 NT$X（原價 NT$Y）」 (no product name). `free_shipping` → `free_shipping`, sentence 「免運」 (base) / 「這組免運」 (composed).
  Both join `offer_sources` / `available_offer_keys` after the brand policies. When the flag is ticked and a store-wide
  free-shipping policy also applies to the sell-way, the list carries one `free_shipping` sentence — the sell-way's own.
- **Step 4 API** (`GET|PUT …/products/{p}/onboarding/sell-ways`): rows `{id, name, shape, components [{sell_way_id, name, qty, price,
  cost}], price, price_derived, price_note, list_price, list_price_derived, list_price_note, cost, cost_derived, cost_note,
  cost_estimate, cost_missing [{sell_way_id, name}], shipping, free_shipping, break_even, break_even_derived, cap_per_sale,
  cap_is_default, landing_url, landing_is_default, offer_sentences, offer_labels, offer_notes, assumptions, used_by, source, note
  (+close_rate)}`. Notes read 「推算：單盒 180 × 5 ＋ 體驗包 100 × 2」 (prices for price / list price, costs for cost);
  `cost_estimate` = the Σ when every base cost is known (shown as 「照內容推算是 X」 beside a typed cost); `cost_missing` = bases
  without a cost; `offer_sentences` = this sell-way's own offer sentences; `used_by` = names of active composed sell-ways using a
  base. PUT rows `{id?, name, components?: [{base: "<name of a base row in this body>", qty}], price?, list_price?, cost?, shipping?,
  free_shipping?, close_rate?, cap_per_sale?, landing_url?, assumptions?}`: no `components` = base; a `qty` key is refused; a row left
  out is archived unless an active composed sell-way not left out uses it (「「〈base〉」還在「〈組合〉」裡，先從組合拿掉。」). AI
  proposals: qty 1 → base; qty N > 1 → composed of the first qty-1 proposal × N, else a base.
- **Bundles** (`…/bundles`, preview): components `[{sell_way_id, qty}]` = base sell-ways of finished products, at least two different
  knowledge products (one product's combinations live on its step 4); GET components `{sell_way_id, name, product_id, product_name,
  qty, thumbnail_url, unit_price, unit_cost}` (that base's own effective numbers); money fields as step 4. Products page sell-way
  briefs add `shape`; bundle card components add `sell_way_id`, `product_name`.
- Migration (`20261004000010_brand_intelligence_sell_way_base.sql`): rename, the flag, nullable price. Existing rows: a single
  qty-1 component row is dropped (that sell-way is a base); every other sell-way with component rows is archived and its rows
  deleted. No backfill: test data is rebuilt (CLAUDE.md 資料狀態).
- The new-campaign picker's options carry `derived_fields` (ads §6.49).

### F47 (built 2026-10-02): reads keep their input and failures; inputs checked where stored
- **Store-time input rules** (`app/core/input_rules.py`, docstring = the rule list): every intake / brand-intelligence store keeps
  exactly what was sent or refuses with one sentence naming the field — selling price > 0, cost and shipping ≥ 0 on every path
  (the economics form's negative-shipping hint is gone), channel revenue ≥ 0 (0 stored as 0), rule-card number bounds, min ≤ max.
  Uploads are sniffed by content (a real PNG named `.jpg` is stored as PNG). The frontend sends what was typed and shows the
  server's sentence per field.
- **A read keeps what it read and what failed (Contract F).** The brand prefill stores `urls_read` and
  `pages_failed [{url, reason}]` (reasons from `app/core/net.read_url`: status code, timeout, unknown domain, certificate, empty
  page); `GET …/onboarding/scan` returns them; a saved URL list that differs from `urls_read` makes the old result stale and the
  scan startable again. 「讀完你的網站了」 only when ≥ 1 page was read; the scan step lists unread URLs with reasons and an exit.
  The product page read uses the URL sent with the retry (`product_prefill.start_scan(page_url=…)`, stored, then read).
- **Product suggestion cards (Q8)**: hidden when a product has the same name (casefold) or page URL; 「不用了」
  (`POST …/products/suggestions/dismiss`) adds the name to `prefill_json.dismissed`, which survives a new read. No migration.
- **Meta token connect** reads the one classifier (`app/meta/graph.py`): an outage is 502 「Meta 暫時讀不到…」, not a rejected token; a
  token that lists no ad account is not stored (400) and the input stays on screen; a stored token offers 「換一把權杖」.
- **Unsaved step edits** survive 上一步, the step bar and a reload: one helper `frontend/src/components/intake/shared/stepDraft.ts`
  (sessionStorage per brand / product and step, dropped once 下一步 saves); brand step 3 and product steps 1–3 use it.

### F48 (2026-10-04): a 食安法 hit is a reminder, never the verdict
Supersedes F43's 「食安法 hits forced 不能講」 (decision 13). `product_onboarding.get_evidence`／`_check_claims` and `custom.py` keep
the user's 可以講／不能講 and attach `statutory` as a flag; the product claims step shows the reminder on the row and both buttons
stay usable. The reminder has no regulation link yet (no URL field is served).

### F50 (2026-10-05): one input-rule table, one readiness, archived lists
Intake stores validate through `app/core/input_rules.py` and send keyed `field_errors`; percentages are 0–100; enums go through
`vocab.require`. The product scan uses the vocab types `core_info`／`audience` only (語調／法規風險 are brand facts). Readiness has
one owner (`brand_intelligence.product_readiness`／`sellable_products`／`knowledge_products`): zero customer groups is not ready,
`status()` serves `ready`, `checklist` and `missing`; knowledge products hold no money; every root product is born through
onboarding; the done page's title follows `ready` and 「繼續建檔 →」 opens the first missing step. Archived products and brands are
listed and restored on the products page and the brand overview. The library read lists queued customer-voice jobs. Details:
`ads.md` §6.52.


### F51 (built 2026-10-06): wizard location and drafts (Contract W)
The brand wizard uses `/brands/{brand}/intake?step=N`. Creating a brand replaces `/intake/new`; subsequent step changes push
history so browser Back walks the steps. Without a query, drafts open their stored reachable step and completed brands open
step 7; unreachable query steps are clamped. The former `intake-view:` and `intake-start:` stores are removed.
`shared/stepDraft.ts` owns `brandDraftKey` and `productDraftKey`: session drafts are scoped by user, brand/product and step,
restored on reload, Back and step-bar navigation, and dropped after a successful save. Files and upload tokens are not drafts.
Enter in an inline evidence editor saves only that edit, without submitting the whole step. Errors, buttons and derived
figures follow `ads.md` section 6.53 and `design-system.md` sections 6-7. Draft/history behavior has targeted component tests;
full drill and human acceptance are separate checks.

F51-I15 preserves the served signed `break_even` in sell-way summaries, shared price editors and save feedback. A negative
value states loss before advertising; zero states no advertising room. Explicit `cap_per_sale` stays unchanged, including the
above-break-even warning. Default cap display reads the served cap; the browser never clamps break-even to zero. Component
regressions and the frontend figure guard cover this drill-12 money-stop repair; persona rerun is recorded separately.
