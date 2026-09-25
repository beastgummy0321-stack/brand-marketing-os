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
6. **The wizard writes the facts it collects.** Measured 2026-09-14 on the drill data: the only
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
