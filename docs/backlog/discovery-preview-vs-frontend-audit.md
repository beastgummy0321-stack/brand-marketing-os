# Discovery — preview images vs. actual frontend (audit 2026-09-20)

Status: audit + proposal only. No product code changed. Not an implementation authorization.
Scope actually walked: ads flow on `http://localhost:8710/app` (served build; whether it contains the
uncommitted working-tree edits was NOT verified), test account, Chrome at ~1440 px layout width.

Evidence legend: **[T]** clicked in the running app · **[C]** code read only (file:line) · **[N]** not checked.
Screenshots could not be written to disk by the browser tool; every [T] row lists the URL/state to reproduce.
Brand/campaign used: `brd_bughunt` / `adc_01M2T370NSGZDS0YXWTATKCN3T` (no reviews) and
`brd_01M2G0TYS8Q25PX90XNKS99HM3` / `adc_01M2X1RSV0GHR696DCFNFRY576` (5 review rounds in DB).

## 1. What is explicitly required vs. inferred

Explicit (user words / signed docs):
- Novice default page, advanced folded on the same page, "only press next", not another Meta back office — `docs/design-system.md:47-66`.
- Previews 01–22 are the reference; 07–08, 13–14, 15–16 use the later corrected sheets — `預覽圖/readme.txt`.
- Five tabs are not a hard constraint — `HANDOFF.md:36`. Main screen = current state, required decision, next step; evidence folded.
- Approve ≠ publish; user report ≠ platform verified; unknown ≠ 0; monthly total includes festivals and is not a platform cap — `docs/architecture/ads.md` §6.9.6–6.9.9.

Inferred from the images only (NOT requirements until confirmed):
- One task = one full page with breadcrumb `投放中心 › 廣告檢討 › 第1次檢討 › …` and a single primary button bottom-right.
- Every ad shown as a card with thumbnail; product hero image on onboarding pages.
- Flat 7-item sidebar (品牌總覽/收件匣/經營概況/投放中心/素材工作檯/商品/設定).
- Review/change pages sometimes sit under 經營概況 in the breadcrumb (15–18) and sometimes under 投放中心 (07, 13–14): the previews are inconsistent; treat as undecided.
- Google Ads "尚未支援" card, 商城資料 card, step counter "步驟 1/3".

## 2. Difference table

| # | User task | Preview | Actual route / state | Evidence | Type | Proposed handling | Needs decision |
|---|---|---|---|---|---|---|---|
| 1 | Create brand | 01: 3-step, 6 plain fields, hero image | `/intake/new`: 5-step AI research wizard (起始輸入→初步印象→責任意與數字→接工具→品牌知識), AI cost meter in USD | [T] | flow deviation + engineering UI (US$ meter, "所屬客戶") | Keep research capability; restyle step 1 to preview 01; move cost meter into a folded "AI 花費" | Yes (D2) |
| 2 | Connect data | 02: one hub, 5 status cards, read-only promise | No hub. Meta in `/settings` → "Meta 廣告連線"; history in `/brands/:id/intake/history`; shop reports under 訂單與顧客 | [T] settings, [C] others | missing frontend entry (backend exists) | Read-only status hub that links to the existing entries | Yes (D3) |
| 3 | Monthly total | 03: step 3 of plan stepper, big number | Panel on ads home + compact copy in 變更與核對; `PUT /monthly-budget` → `ads_month_budget`; row `brd_bughunt 2026-09 TWD 60000 rev 2` survives reload | [T]+DB | visual + placement | Keep panels; also surface as a step in first-plan flow | No |
| 4 | First plan | 04: 4-step stepper; "讓 AI 提出 / 我想先說明"; AI plan card (月額內分配/先觀察 7 天/平台/目標) | `/ads/new`: asset upload list with raw file names FIRST, goal sentence below; then `/ads/new/:id` six field cards; then strategy | [T] step 1, [C] steps 2–3 | flow deviation | Goal first, assets folded; show AI plan summary card before the six fields | No |
| 5 | Import existing ads | 05: full page, thumbnails, status chips, 30-day spend, radio select | Dialog: text rows, `ACTIVE/PAUSED/ARCHIVED`, raw ISO timestamp, `1970-01-01` dates, 20+ archived rows unfiltered, one-click "納入並開啟" | [T] | visual + engineering UI | Chinese status, hide archived by default, format dates; spend/thumbnail need backend fields | Partly (D4) |
| 6 | Confirm takeover scope | 06: 4 summary cards + native tree + chosen ad + "進入活動檢討" | Does not exist; import jumps straight into 6-tab workspace 總覽 | [T] | missing screen | Build as the landing state of an imported campaign (data already in `ads_external_entity`) | No |
| 7 | Round-1 review | 07: A/B cards with image + 花費/購買/成本, one warning, AI suggestion bar with 查看建議/暫緩 | `?tab=performance`: `<select>` of 19 ad names, one ad per review; result page = text table, `7d_click+1d_view:omni_purchase · graph` selector, account/ad IDs, 4+ disclaimers, commerce table, 3 decision buttons | [T] | visual + engineering UI; thumbnails = backend gap | Card picker; one warning line; attribution selector folded; IDs folded | Yes (D4) |
| 8 | Choose what to prepare | 08: 4 option cards as the step after review | Same 4 modes exist but as cards on 素材 tab; "先不改，持續觀察" is a review direction with no button; "新增素材需求" button is a no-op when the chooser is already showing | [T] | flow deviation | Make it the next step after 完成本次檢討; add 持續觀察 as 4th card | No |
| 9 | Use finished asset | 09: upload + title/body + confirm | `MaterialTaskEditor` mode `existing` → `ads_material_task/revision` | [C] | visual | Restyle | No |
| 10 | Copy-only edit | 10: image preview + 舊版/新版 compare + platform mapping chips | 素材 tab editor shows only 任務名稱 / 這次想驗證什麼 / folded 搭配文案; the real old-copy vs new-copy form lives in 變更與核對 → 建立變更清單 (reads back real ad copy) | [T] | flow deviation (one task split over two tabs) | Merge into one page per preview 10, saving both records | No |
| 11–12 | New image via external tool, pick 1 of 10 | 11: source need + reference + P1–P3 prompt + copy button; 12: 10-grid picker | Exists: prompt copy `MaterialTaskEditor.tsx:65`, candidates ≤10 `material_routes.py:61`, `/select` | [C] | visual [N] | Walk through next round | No |
| 13 | Approve change list | 13: budget strip + table + 核准/修改/拒絕暫緩 | `ChangeControl` + `ChangeSetView`, all persisted (`ads_change_set`, `ads_action`); list is hand-built by the user through a form, not pre-filled from the AI suggestion (only copy branch deep-links in) | [T] form, [C] approve | flow deviation | Pre-fill from the review recommendation | No |
| 14 | Do it on the platform | 14: per-item old/new with 複製 + 打開平台 + "我已手動操作，開始核對" | `ManualHandoffPanel`: report + real read-only readback exist; NO copy button, NO platform link | [C] (no data to click) | missing frontend entry | Add copy + Ads Manager link (IDs already stored) | No |
| 15–16 | Partial done / re-approve | 15, 16 | States `pending/reported/confirmed/deviated/unknown/stale`, 需要重審 → 依目前設定另建清單 | [C] | visual [N] | Walk through with drill data | No |
| 17–18 | Round 2 + B2 handoff | 17, 18 | `準備下一次檢討`, `source_review`, new-ad handoff all wired | [C] | visual [N] | — | No |
| 19–20 | Cannot judge / recovering | Full-page state with 3 fact cards, one fix button; 20 shows "worker 恢復" timeline | Small text blocks inside 持續追蹤 and a folded "查看同步、恢復與追蹤設定" | [T] partial | visual; preview 20 itself uses engineering words | Promote to page banner; reword "worker/本機離線" | Yes (D5) |
| 21 | Ads home | 21 | Closest match: 需要你決定的事 + budget + activity card + two entries | [T] | minor visual (card truncates name, "未知", grey helper text) | Polish | No |
| 22 | Verify platform mapping | 22 | Candidate select + readback tiers in `ManualHandoffPanel.tsx:151-170`, `AssetHandoffPanel` | [C] | visual [N] | — | No |
| A | — | none | 策略 / 投放結構 tabs, 結案, experiment plan, simulation recovery, PublishPage | [C] | designed nowhere in 預覽圖 | Keep; reach from "進階／全部資料", not from the novice path | Yes (D1) |
| B | — | none | 收件匣, 經營概況 dashboard, 訂單與顧客, 品牌智庫, 顧問分析報告, workbench pack/set pages | [T] cockpit only | out of preview scope | Untouched this round | No |
| C | — | sidebar 7 flat items, "商品" | 3 groups, 10 items, "產品" | [T] | visual | Leave until D1 settled | No |

Cross-cutting engineering-UI findings [T]: account / ad numeric IDs in page headers; English platform enums; raw ISO timestamps;
attribution-window strings; 3–5 stacked disclaimers per screen ("不代表…", "不等於…"); workspace overview shows a 5-state
"狀態時間軸" that is not a timeline; ultra-wide windows leave the app left-anchored while dialogs centre on the viewport.

Record inconsistency to resolve: `HANDOFF.md` says no review was started on a real account, but the Hermosa real-account
campaign holds 5 `ads_review_round` rows (2 completed, 2 ready, 1 waiting) with suggestion text. Origin not investigated.

## 3. Not verified this round

ConfirmBrief + strategy generation, 策略/投放結構 tabs, approve → handoff → readback with live rows (no rows exist in dev DB),
round-2 screens, states 19/20 with real failures, workbench pages, inbox, orders, library, report, widths below 1440,
keyboard/focus behaviour, whether the served build equals the working tree.

## 4. Paths

Current (imported ad, change copy): 投放中心 → 加入既有活動 (dialog) → workspace 總覽 → 成效 tab → pick ad in dropdown → 開始本次檢討 →
read tables → 完成本次檢討 → go to 素材 tab → 只準備新文案 → save → go to 變更與核對 tab → 建立變更清單 → re-pick the ad → type copy →
保存 → 核准 → scroll to 人工交接 → report → readback. Three tabs, the ad is chosen three times.

Proposed: 投放中心 (今天要決定的事) → 第 N 次檢討 (ad cards, one suggestion) → 這次要準備什麼 (4 cards) → 改文案 (old/new) →
確認本次變更 → 到平台完成 (copy / open / 我已操作) → 核對結果. One linear page sequence, ad chosen once, same APIs.
The six tabs stay as "活動全部資料" for advanced users.

## 5. Split

Pure UI (existing APIs suffice): rows 3, 4, 6, 8, 10, 13, 14, 19–21, all engineering-text cleanup, linear step shell.
Needs backend: ad thumbnails and 30-day spend in import/review lists (row 5, 7); connection hub summary endpoint (row 2, could
be composed client-side first); "持續觀察" as a recorded branch if it must leave a trace (row 8).

## 6. Pilot scope proposed

Imported ad → round-1 review → copy-only change → approve → manual handoff → verify (previews 21 → 07 → 08 → 10 → 13 → 14 → 15).
Reason: backend fully wired and tested, it is the daily loop, and it exercises every pattern (cards, step shell, folded evidence,
honest unknowns) the other screens will reuse.

## 7. Decisions pending (user)

D1 step pages vs. tabs · D2 brand wizard shape · D3 connection hub · D4 thumbnails/side-by-side ads · D5 wording of recovery states.

## 8. Rulings after the audit (2026-09-20, user-confirmed in conversation)

Confirmed:
- D1 step-per-page flow, tabs demoted to "all campaign data"; D4 ad cards with thumbnails, no winner labels.
- A brand-level progress summary endpoint may be added (home "resume where you left off").
- Model conflicts resolved WITHOUT backend change: one review = one ad; review-linked change set = copy items only;
  `deviated` (platform differs) and `stale` (premise changed → new review round) are two states with two exits;
  "持續觀察" is stored as `deferred` + revisit time.
- UIUX acceptance goal recorded in `docs/design-system.md` §1.7 (layout carries guidance; no explanatory text as a fix).
- Prototype v3 (`.harness/scratch/prototype/review-loop-steps/v3.html`) accepted as direction for the per-ad repair loop.
- Triage rule: program-side, each ad compared with its own previous 7 days; must be paired with a minimum-sample gate and a
  spend-without-purchase stop-loss (thresholds undecided).
- Keep F15 and repair on top of it; do NOT rewind A–D. The front end and the entry logic ("user picks one ad") are what get redone.

Findings that drive the next discussion (code-read, not run):
- No program-side screening exists; a review is triggered only by a manual pick or a 7-day timer on an already-reviewed ad.
- Recommendation kinds are retain / observe / adjust / new_test only; no pause or scale; review results feed no learning store.
- F15-I05 (`d6fe45e9`) removed the unattended close (end_date + 7 days → verdict + learning) from `app/ads/jobs.py`;
  three texts still promise it (`routes.py:819`, `judgment.py:109-112`, `PerformanceTab.tsx:295`). Not an explicit user ruling.
- Pre-existing debts: Meta purchases zeroed at close-out (`outcome.py:142,170`, ruled 2026-09-14, unimplemented) so real
  campaigns always close as 看不出; imported campaigns cannot close or feed learning; no campaign series / "next period" action.

Lifecycle, triage, learning unit, pause/scale, refresh cadence and the monthly review were ruled later the same day and
live in `discovery-creative-lifecycle-and-triage.md` (single home; not repeated here).
