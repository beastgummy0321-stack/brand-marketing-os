# Discovery — creative lifecycle, program triage and monthly review (2026-09-20)

Status: discussion draft with user rulings. Not an implementation authorization. No product code changed.
Origin: the preview-vs-frontend audit (`discovery-preview-vs-frontend-audit.md`) exposed that F15 built an honest
single-ad repair loop but nothing decides WHICH ad needs it, WHEN a creative is retired, HOW results reach brand learning,
or how the next period is opened. Code facts below were read, not run.

## 1. Why the feature exists (now written down)

Purpose in the owner's words: 「好的留下繼續投、爛的換掉」, for any brand on any budget (SaaS), without the owner having to
know which of N ads to look at. The platform campaign is a long-lived container — it is not rebuilt when creatives rotate
(rebuilding resets platform learning). What rotates, retires and teaches the brand is the creative.

## 2. Confirmed rulings

1. Keep F15 and repair on top; do not rewind A–D. Redo the front end and the entry logic.
2. **Program triage, no LLM.** Each ad is compared with its own previous window. Classes: 停損 · 變差 · 變好 · 持平 · 資料不足.
   Only 停損/變差/變好 surface as decisions; the rest collapse into one line.
3. **Thresholds are formulas scaled per brand**, reusing `app/methodology/ads-core.md` §3/§5 (today prompt-only, not enforced):
   - judgeable = spend ≥ 3 × target CPA, or ≥ 7 days with enough events; otherwise 資料不足 (never reviewed, no AI cost);
   - window auto-extends 7 → 14 → 28 days for small budgets;
   - stop-loss = spend ≥ 3 × target CPA with zero conversions → propose pause at once, no review round;
   - ad-count cap = daily budget × 7 ÷ (3 × target CPA): checked at planning, shown as a hint on import, listed in monthly review;
   - scale ≈ +20 %, never > 30 %, then wait 3–5 days.
   Numbers must be re-checked against current platform docs before they become code constants.
4. **Target CPA default = break-even CPA** (price × margin, `ads-commerce.md`), user-overridable; if cost is missing use the
   account's trailing-30-day actual CPA, labelled provisional.
5. **Unit of learning = the creative lineage**, written at retirement (loss) or stable win, through the existing fingerprint /
   confidence mechanism (`learning.py`, `visual_learning.py`: observed → likely → validated). Imported campaigns contribute.
6. **Monthly review ("每月回顧")**: internal only, tied to the monthly brand total. Program compiles wins/losses/undecided,
   target attainment, budget use, idle creatives; the model only proposes next month's adjustments. "Next period" = next
   month; the platform campaign is untouched. The unattended close removed in F15-I05 is not restored.
7. **Escalation ladder per lineage** (program counts, model explains): change copy → replace image (B2, `source_review`) →
   retire the angle and record a loss. Stable for two windows → record a win.
8. **Pause and scale proposals both exist, program-originated.** Pause targets one ad. Scale targets the ad set / campaign
   (where the budget lives), only when there is a stable winner, CPA below break-even and room in the monthly total; ≤ 20 %.
   Both are proposals: user approves, acts on the platform by hand, system reads back (existing machinery).
9. **Creative refresh is state-triggered, not calendar-triggered**: fatigue of the main creative over two windows; fewer than
   two judgeable creatives live; a creative with almost no delivery for 14 days (cleanup candidate).
10. Per-ad repair loop keeps the model rules already fixed: one review = one ad; review-linked change set = copy only;
    `deviated` vs `stale`; "持續觀察" = deferred + revisit time. UI per `docs/design-system.md` §1.7.
11. Campaign end conditions (system proposes, user approves): end date reached (time-limited); objective or product changed;
    two consecutive months under target after N lineages were rotated (strategy problem, not creative problem).

## 3. Operating flow (agency view → system)

| Level | Clock | Judged by | Actions |
|---|---|---|---|
| Creative (ad) | 3–7 days, extended by sample gate | program triage; model only inside a repair round | keep · change copy · replace image · pause/retire |
| Ad set / audience | 1–2 weeks | program | scale ±, (later) audience change |
| Campaign | monthly review | program + model proposal | continue · adjust · end |
| Brand | monthly / quarterly | learning ledger | feeds strategy, brief, workbench look allocation |

Home = decision queue (4 kinds: 停損, 變差, 加預算, 補素材) + one health strip for all ads + budget. Finishing one item
advances to the next. 停損/加預算 use a 3-step light flow (confirm → platform → verify); 變差 uses the 6-step repair loop.

## 4. Prerequisites (existing debts that block the loop)

- Meta purchases are zeroed at close-out (`outcome.py:142,170`; ruled 2026-09-14, unimplemented) → every real verdict is 看不出.
- Imported campaigns cannot produce learning (`external_models.py:9-29`, `ads.md:291-293`).
- No lineage counter: `ads_review_round.previous_id` and `source_review` exist but nothing counts interventions.
- Three stale texts still promise an automatic close (`routes.py:819`, `judgment.py:109-112`, `PerformanceTab.tsx:295`).

## 4a. Wiring probe of prototype v4 + multi-objective check (code-read 2026-09-20)

Several campaigns with different objectives can already be stored, synced, budgeted and change-controlled
(`ads_external_entity.objective`, brand-wide month budget, cross-campaign `change-control-summary`). They cannot be JUDGED:
- Result metrics are purchase-only: `ads_external_daily` has spend/impressions/clicks/purchases/revenue; Insights `actions`
  are fetched but everything except the first purchase synonym is discarded (`graph.py:169-174,556-558`, `meta_read.py:168-171`);
  `aggregate` hard-codes CPA/ROAS (`review_evidence.py:44-49`); `success_metric` enum is cpa|roas|purchases.
  Non-sales ads read as unknown (not zero), but incidental purchases could trigger a false 變差/stop-loss → triage must be
  objective-aware: persist a per-row result count keyed by objective, widen the metric to "cost per result", and judge only
  where a result definition AND a target exist; otherwise show 尚未設定目標 / 資料不足.
- Meta `budget_amount` is never resolved (`meta_read.py:68-84`, "unverified_currency_denominator"): budget proposals are
  accepted at create but blocked at approve, budget read-back stays `unknown`, the ad-count cap has no input for imported
  campaigns, and month `available` is None for real accounts. Until fixed the UI must say 預算待核實 and not propose scale.
- Imported ads have no angle/coordinates (only `ads_ad` has them) → the learning sentence has no subject. Ruling-consistent
  fix: ask the user to tag what the creative was about at retirement (reasons come from the user, not the model).
- Confidence promotion is campaign-verdict based (`learning.py:70-88`), not lineage based; `record_learning` itself needs no
  fingerprint and works for imported ads. No learning list route exists.
- Fits today: pure `aggregate()` for triage from one grouped SQL; `budget.breakeven_cpa()/target_cpa()` + `product_economics`;
  pause on one ad without a review link; ads-per-adset count via `parent_native_id`; lineage count from `ads_action` +
  `source_review`; pause read-back via `effective_status`; deterministic `operation_id` for proposal idempotency;
  `interrupts.enqueue` (dedupe per brand/key) is the inbox to reuse for queue reminders. Missing: `origin` marker on change
  sets, suppression of rejected proposals, "spend stopped" follow-up check, monthly compilation, preferred-series rule.

## 5. Construction plan (three features, carved one at a time; approved prototype = v7)

Each later phase is carved only after the previous one closes, so its issues are written against real code, not this draft.

- **Phase 1 — F16 投放判斷地基 (carved, `.work/features/F16.md`)**: real purchases into verdicts + stale close texts (I01);
  Meta budget amounts (I02); objective-aware result metric (I03); target resolver + API (I04). Backend only, no LLM, no new UI.
- **Phase 2 — 分流、待決定佇列與新版投放中心**: program triage endpoint (own previous window, sample gate, window
  auto-extend, 3×target stop-loss, preferred-series rule); brand-level queue/progress summary reusing `interrupts`;
  program-originated pause / scale proposals (`origin` marker, deterministic `operation_id`, suppression after
  reject/defer, "spend stopped" follow-up check); then the front end rebuilt from v7: home queue + campaign cards, 3-step
  light flow, 6-step repair loop (copy branch), set-target page, campaign page with classes + cleanup proposal + door to the
  legacy tabs, D3 connection hub (read-only, links to existing entries), D5 states (data-short page, unreadable card,
  recovery banner that locks decisions). Contract first, then backend and frontend issues in parallel.
- **Phase 3 — 素材生命週期、學習與每月回顧**: lineage counter + ladder position; learning written at retirement / stable
  win with a user-tagged angle, lineage-based confidence, learning list route; monthly review compilation + one proposal
  call; ad-count cap checked in planning.
- Deferred, each needs its own prototype before carving: image / existing-asset branches (user previews 09, 11, 12);
  create-plan + import flows together with the D2 intake wizard; non-Meta adapters.

**UIUX baseline for anything the prototype does not cover** (condensed from the user's words; full rule `docs/design-system.md` §1.7):
not the simplest and not the richest — a first-time, non-technical user must tell from the screen alone where they are, what
this step does, and where next / back / accept / reject / exit are; the judgement stays with the user (no mindless
next-next-next); never solve confusion with tutorial screens or stacked explanatory text — fix hierarchy and layout instead;
passing functional tests is not UI acceptance; an uncovered screen gets a prototype or a side-by-side screenshot review
against the nearest approved v7 page before merge, and a material new screen goes back to the user first.

## 5a. Phase 1 result — F16 integrated 2026-09-21 (not closed: human acceptance pending)

Branch `feature/ads-judgement-foundation`; `harness integrate feature F16` green: backend 1832 passed (`-n 4`), frontend
311 tests, build, Playwright 5 passed / 6 skipped. Five issues (I05 added mid-run). Migrations 20260920000001–06, applied and
registered on the local dev DB only. No platform writes; one bounded read-only Meta read (budget cross-check).

Implemented: `ads_outcome_daily.purchases/revenue` nullable + legacy Meta zeros normalised to NULL; real Meta purchases and
purchase value reach close-out through the meta facade (one synonym definition, disagreement ⇒ unknown); Meta budgets
resolved by the official currency offset table (TWD offset 1 proven: doc + read-back 1,900 vs daily spend 1,639–2,383),
untabled currency ⇒ None with reason; per-row `result_kind/result_count/result_action/result_attribution` and an untorn
`result_views` per (scope, currency) with `mixed_result_definition` / `result_unknown_days`; target cost in its OWN columns
(`target_cost`, `target_basis`, `result_kind`, `target_revision`) with `GET/PUT …/target`, never touching `success_*`;
sync fills `ads_campaign.result_kind` only when NULL.

Phase 2 must know / decide:
- PRODUCT RULING NEEDED: an absent platform action is stored as unknown, never zero (F15 rule). With all-or-nothing
  windows many real ads resolve to unknown and a "spend with zero results" stop-loss can never fire. May "delivery present +
  action absent + account demonstrably tracks that action" count as a tracked zero?
- Attribution window / counted synonym are not persisted on `ads_outcome_daily` (needs a migration).
- Objective→result table is verified against real data only for OUTCOME_SALES; AWARENESS/REACH are unmapped on purpose.
- Already-imported non-sales campaigns need a normal re-sync before results exist (no new permission).
- The frontend target client was deferred: add `frontend/src/lib/adsTargetApi.ts` + manifest `owns` with the set-target page
  (`adsApi.ts` is at the 800-line cap).
- User remembered NT$2,000/day for Beast Prime; the platform reads NT$1,900 — confirm at acceptance.
- Workflow defects to fix before the next crank: host-isolated workers must `attach` (binding the lease to a disposable agent
  worktree, leaving unsignable baselines and a dead lease); `finish` takes base_sha at attach time; worktrees have no `.env`
  / `frontend/.env` / node_modules; e2e exceeds the 120 s command default; workers cannot message the lead; background
  agents die with the session. Until fixed: merge/integrate run from the main session with env loaded and a raised timeout.
- Time-bomb test fixed in passing: `test_orders_api.py` used a literal date against a trailing 30-day window.

## 6. Still open

Exact numeric defaults (event count for "enough", fatigue definition, "almost no delivery"), wording of learning sentences,
how scale proposals behave under CBO vs ad-set budgets, what the monthly review shows for brands with several platforms.
