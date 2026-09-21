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

- (Resolved by F16, re-read 2026-09-21: Meta purchases now reach close-out; see §5a.)
- Imported campaigns cannot produce learning (`external_models.py:9-29`, `ads.md:291-293`).
- No lineage counter: `ads_review_round.previous_id` and `source_review` exist but nothing counts interventions.
- (Resolved by F16: the three stale "automatic close" texts now say manual close.)

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
- RULED 2026-09-21 (user, option 1 — conditional tracked zero): an absent platform action may be read as a tracked zero
  ONLY when all three hold: (1) the entity delivered that day (spend or impressions present); (2) the same account reported
  that same action type within the recent observation window (the account demonstrably tracks it); (3) that day was fully
  synced. Otherwise it stays unknown. A derived zero is stored/marked as "derived by rule", distinguishable from a
  platform-reported number, and shown as such. F16 closed and merged to master on 2026-09-21 after human acceptance on real
  synced data (daily budget 1,900; 29-day cost per purchase ≈ 452).
- Background of that ruling: an absent platform action was stored as unknown, never zero (F15 rule). With all-or-nothing
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

## 5b. Tooling check and Phase 2 batch 1 (2026-09-21)

Harness 3.0.4 verified live with F17 (one issue, closed and merged to master): the worker ran in
`.harness/worktrees/F17-I01`; finish, merge smoke and the full `integrate` were green with the manifest's
`verify.env_files` / `env_exclude` / `timeouts` and no external env wrapper. Two plugin defects were found and fixed in harness 3.0.5 on 2026-09-21 (plugin source
`D:/0UserProfile/Desktop/Default/Planner`; needs a new session to load; the Codex install is not updated):
- a worker Bash call that fails never fires PostToolUse, so its baseline is left behind, blocks `merge`, and
  `baselines --reconcile` refuses it while the lease lives (30 min TTL). 3.0.5: failed calls clear their own baseline (PostToolUseFailure); for interrupted calls use
  `harness baselines --reconcile --ended <issue>` after the worker's completion notice.
- the write gate hard-denies Edit/Write on `ARCHITECTURE.md` regardless of `touch`, while a Bash write to the same file is
  judged by `touch` only — two rules for one file. 3.0.5: one rule everywhere — `touch` must name `ARCHITECTURE.md` literally.

Phase 2 batch 1 is carved as F18 (`.work/features/F18.md`; contract and rulings live there): conditional tracked zero →
program triage → brand queue summary. User-confirmed defaults 2026-09-21: enough events = 10 per window; tracking
observation window = 28 days; flat band = ±20 %. The derived zero is marked in `ads_external_daily.availability`, so the
`ads_outcome_daily` attribution migration noted in §5a is NOT needed for this batch. Later batches: pause/scale proposals
with suppression, then the v7 front end.

F18 closed and merged to master 2026-09-21 after human acceptance on real synced data (Beast Prime, target cost 450: 69 derived-zero ad-days marked, 20 ads classified, queue empty). Settled in review and now
documented in `docs/architecture/ads.md` §6.16–6.18: the derived-zero cutoff and the triage window end use the AD ACCOUNT's
timezone (unknown timezone ⇒ no derivation / org-today − 2 days); a window not fully inside the recorded sync coverage is
`needs_resync`, never a zero; refresh supersedes stale open triage interrupts through `interrupts.resolve(actor="system")`.
Known limits for the next batch:
- Sync coverage records only the LAST synced range (≤ 31 days), so the 28-day step can never see its previous window and
  always ends in `no_previous_window`; fixing it means cumulative coverage in the sync layer.
- A user-resolved queue item is raised again when the window moves (daily) while the ad is still 停損/變差; suppression
  belongs to the pause/scale-proposal batch.
- `frontend/src/lib/adsReviewApi.ts` `ReviewResultView` lacks `derived_zero_days`; the v7 front end must label derived
  zeros 規則推定 (acceptance item of that batch).
- Observed at acceptance: an ad at 2.4 × target cost classifies `flat` because triage compares only with its own previous window; a persistently over-target ad never reaches the queue. Candidate class for the next batch (needs a user ruling).
- Read-only preview on the local real data (2026-09-21): both imported campaigns classify every ad as
  `no_target / target_unresolved` (`missing: product` plus `needs_resync` / `result_unknown_days`) — acceptance needs a
  re-sync (which derives zeros) and a target cost set through `PUT …/target` first.

## 5c. v7 front end batch 1 — F19 (2026-09-21)

Built (seven issues, feature `F19`, branch `feature/ads-center-v7-home`): v7 home (brand-level decision queue with
to-target meters, per-campaign filter, month budget card, campaign cards with target + five-class strip) and the
target page (`/brands/:brandId/ads/campaigns/:campaignId/target`). Small backend additions that followed the screens:
queue items carry their `triage` item; `app/ads/result_kinds.py` (`result_label`, `result_kinds`, PUT validation);
`campaign_name` on triage items. Rules are in `docs/design-system.md` §5.1–5.3 and `docs/architecture/ads.md` §6.17–6.19.

Known gaps, not built (each needs its own screen or a backend field; none is faked):
- 「看證據」 lands on the campaign's performance tab, not on the ad: the workspace keeps the selected ad in local state,
  there is no query-string selection. Belongs to the campaign-detail batch.
- Target page shows a number only for the basis in force; per-basis preview numbers (v7 shows three) need a backend
  "candidates" field. The v7 actual-vs-target gauge is omitted for the same reason.
- Cost / target numbers print without a currency symbol: triage and target responses carry no currency and
  `formatCurrency` hard-codes NT$. Add `currency` to those responses before printing a symbol.
- Zero-ad campaigns (drafts) show no target and no entry to the target page on their card (reach it through the workspace).
- Revision conflict on the target page reloads server values; local edits are not merged.
- Placeholders 「接上後開放」: pause proposal, 可加預算, 補素材, 每月回顧. Not built: campaign detail, data-connection page,
  six-step repair restyle, "系統暫停補資料" banner, "資料不足先不判斷" card state (no backend state).
- One `getTriage` request per campaign card; add a brand-level summary endpoint when a brand has > 10 campaigns.
- Queue meter clamps at 1.5 ×, so 1.5 × and 4 × over look equally full; the numbers carry the difference.

## 5d. v7 front end batch 2 — F20 campaign detail page, measured trial of harness 3.0.6 (2026-09-22)

Built (two issues, branch `feature/ads-center-v7-detail`, base `feature/ads-center-v7-home`): triage items carry
`thumbnail_url` (from `creative.fields`); new queue rows' `action_url` lands on `/brands/:b/ads/campaigns/:c/detail?ad=<entity>`;
the detail page itself (groups by class, 停損／變差 open — else the first non-empty group, rows with thumbnail / spend / cost,
去處理 for queued ads → workspace `?tab=performance` until the six-step flow is rebuilt, capacity card as one grey placeholder).
Omitted, no backend: ladder, 「14 天幾乎沒投」, 「平台設定」 chip, the 3× amount in the 資料不足 hint. Closes §5c gap 1.
Noted, not fixed: every detail-page open calls `getQueue`, which re-classifies the whole brand.

Measured (`.harness/runtime/metrics.jsonl` + agent durations), authorize 00:48 → second merge 02:23 = 95 min:
- Environment, 21 min: Docker would not start (undeletable `.sock` files after a Windows update; workaround = rename two folders).
- I01 (backend, 40 lines + tests), 14 min: worker 6 min + 3 min; finish 69 s; merge 66 s. ~8 min of it was lead error:
  wrong test path in `touch` (carve typo), build broke on three test factories outside `touch`, and a skipped `attach`
  after a re-claim blocked the issue. No code was returned by review.
- I02 (screen, 415 + 334 lines), 59 min: worker 34 min first pass; lead screenshot compare returned it once (content
  max-width, summary hints, all-folded page) 9 min; finish 28 s; Opus adversarial review 5 min returned it once with three
  real defects (去處理 looped to the same page — caused by the I01 plan, queue failure killed the page, `?ad=` scroll
  replayed) 6 min; finish 25 s; merge 44 s.
- Documents a worker was told to read: the issue, the feature file, design-system §1.7, the prototype function. No long .md.
- Takeaways: each touch-list correction costs a save-patch → release → edit → claim → apply → attach round (~2–3 min and
  easy to get wrong) — this is the missing `rescope`; carve must `ls` every path it writes into `touch`/`verify`; a type
  field added to a shared API type needs its test factories in `touch`; a link changed in one issue must be traced to
  every consumer planned in the next.

## 5e. Handoff — cut UI-worker time and review bounces (open, written 2026-09-22)

Goal (user-chosen, before the remaining v7 screens): make a UI issue cheaper. In F20 the screen issue took 59 of 95 min:
worker first pass 34 min, two bounces 20 min (lead screenshot compare 9, Opus review 5 + repair 6). Tooling fixes
(harness 3.0.8: `rescope`, unattached finish refused, leftovers moved aside, new-directory note) save ~12 min and do not
touch this. Gates are not the cost: finish ≤ 69 s, merge ≤ 66 s.

Measured, I02 worker (Sonnet), whole life incl. both repairs: 240 tool calls, ~513k tokens. 70 Reads over 48 distinct
files (its own page 10×, 18 image reads of its own screenshots), 34 Edits, ~125 shell calls (13 playwright, 16 node
helper scripts, 13 git, 8 npm test, 4 builds, 3 sleeps, ~57 uncategorised). First pass alone: 174 calls, 367k tokens.
I01 worker (backend, 40 lines): 49 + 27 calls, 6 + 3 min. Opus review: 29 calls, 5 min, three real defects.
Raw transcripts (git-ignored, do not read whole — tally with a script): `.harness/runtime/logs/F20-transcripts/`
(only `I02-worker.jsonl` survived; the other three copied empty).

What the bounces were, by origin:
- Plan defect (lead): 去處理 looped to the same page because I01 changed `action_url` and I02 was told to use it.
- Spec not reaching the worker: content `max-width:1180px` and the two summary hints are in the prototype HTML/CSS; the
  worker missed them and also expanded the prototype's groups by hand before shooting, hiding the fold mismatch.
- Missing general knowledge: queue failure killing the page, scroll effect replaying — both already solved once on the
  home page (`AdsHomePage.tsx:19-20`), not carried to the next screen.

Hypotheses, none verified — measure before changing anything:
1. A lead-side pre-pass that extracts the prototype screen's facts mechanically (container widths, every text node,
   default open/closed state, each control's target) into the issue would have prevented bounce 1 entirely.
2. A short per-project "screen pitfalls" list fed by past review findings (independent blocks fail independently;
   effects keyed on fresh objects; focus ring clipping; zero vs unknown) would have prevented bounce 2's two generic defects.
3. 48 distinct files read suggests orientation cost; a per-screen context pack (the 5–8 files a new ads screen always
   needs: a sibling page, its test, the API type file, patterns index, tokens) could replace exploration.
4. Evidence capture is expensive (13 playwright + 16 helper scripts + 18 image reads): one reusable side-by-side
   script in the repo, parameterised by prototype hash and app route, instead of each worker writing its own.
5. Model choice is unmeasured: Opus as worker may cost more per minute but fewer bounces. Needs an A/B on one screen.

Rejected / constraints: do not add approval rounds, new reports or mandatory reading (user rule); do not replace design
with explanatory text; the HTML prototype stays the spec; a new gate must be replayed against real history before it is
installed (3.0.7's path check failed that: 17 of 334 false refusals). User instruction in force: if a returned worker
fails again, pause and show the user the cause instead of returning it a third time.

State: F20 closed into `feature/ads-center-v7-home` (main tree is on it, clean). F19 still open (human acceptance
pending). Nothing pushed. harness 3.0.8 installed from Planner `2d5ef0c`; loads in a new session; Codex copy not updated.
Remaining v7 screens (evidence／six-step repair, data connections, three abnormal states, monthly review) wait for this.
Docker on this machine needs the two-folder rename before each start (memory `docker-stale-sockets-block-start`).

Next step: tally `I02-worker.jsonl` by phase (orientation → build → evidence → repair) with timestamps to see which of
hypotheses 1–4 owns the most minutes; then try the cheapest one on the next single screen and compare against 59 min / 2 bounces.

## 6. Still open

Exact numeric defaults (fatigue definition, "almost no delivery"), wording of learning sentences,
how scale proposals behave under CBO vs ad-set budgets, what the monthly review shows for brands with several platforms.
