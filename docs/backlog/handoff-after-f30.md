# Handoff after F30 (2026-09-26)

Start here in the next session. This is a board, not an implementation authorization: pick one line, `/dig` or fix it directly, and re-verify every claim first (causes written here have been wrong before).

## State
- F30 is closed and merged to `master` (`8f1dfd71`). No open feature; the queue is empty. The user pushes manually.
- Rules: `docs/architecture/ads.md` §6.34 (F30) on top of §6.32 (F28) and §6.33 (F29). UI spec: `docs/design/ads/prototype-v10-ads-center.html` + `prototype-v10-ai-blocked.html`. Every v10 screen is now built.
- The user accepted the F30 side-by-side as is (pill tab bar, the extra 「打開」 on verified change rows, and the missing 「第 V 版有改」 chip included).

## Priority board (user ruling 2026-09-26)
Order: bugs and everything the ad closed loop needs first; the rest is archived below for a later session.
Each open-file claim was re-verified against `1fd9a187` on 2026-09-26 (file:line in the issue files may be stale).

### P1 — bugs (one feature batch)
Ad loop:
1. Wizard: offerings step does not advance, forgets 「廣告帶來的是什麼」, order flips (`issue-offerings-step-does-not-advance-and-forgets-choice.md`).
2. Wizard: start-step draft lost on navigation (`issue-intake-draft-not-saved.md`).
3. Intake research: a failed queued job with no `llm_task` row reads `done` (`research.py` `_idle_job`); pipe-table format has no retry (`issue-intake-research-first-run-format-fail-and-silent-worker.md`).
4. Meta token rejection shows raw Graph text, no missing-scope hint (`issue-meta-token-rejection-shows-raw-graph-text.md`).
5. Meta parent-id guard is fail-open for ads-center bindings — the second caller now exists (`adapters/manual.py` name matches; `issue-meta-unknown-parent-id-fail-open.md`).
6. Coordinates edited after dispatch: **ruling — editing stays allowed; learning reads a coordinates snapshot taken at dispatch** (`issue-ad-coordinates-edited-after-dispatch.md`).
7. Image selection: no one-per-ad cap; the creative that ran is not recorded (`issue-image-selection-one-per-ad.md`).
8. Failed image validation does not gate or warn at selection (`issue-image-validation-does-not-gate-selection.md`; prose-drift check stays undecided).
9. Brand-home 「判讀」 (cockpit diagnosis) has three bugs (`issue-adopt-button-visible-while-a-new-round-starts.md`, `issue-adopt-has-no-echo.md`, `issue-diagnosis-hides-full-coverage.md`). **Ruling (2026-09-26): keep it and fix the three bugs** — an overlap map found four capabilities the Ads Center lacks (brand-level grouping by the 7 coordinate dimensions, breakeven against coordinates, the cross-campaign 3-lens diagnosis, 「採用」 → an experiment brand rule read by every generation prompt via `context_compiler`).
10. Connections: a day after the latest order without orders reads as missing.
11. Bind message hides partial success (`issue-bind-message-hides-partial-success.md`) — the ads-center bind endpoint has no frontend caller: fix the message or delete the dead path.
12. Loop wording (`issue-drill-wording-gaps.md` items 3, 4, 5, 7a): 「尚未成功拉取」 beside real numbers, newly matched campaign waits for the next pull, attribution window on the cockpit ROAS tile, fixed vs unit cost help.

Other bugs:
13. Brand delete misses 10 brand_id tables; 3 have FKs so delete fails (`ads_runtime_event`, `campaign_period`, `channel_entity_map`); `llm_task` is kept on purpose; the coverage test `cleanup.py` cites does not exist (`issue-brand-delete-misses-nine-tables.md`). Drop the 4 dead tables in the same pass (`issue-five-live-tables-zero-code.md`).
14. Post-processing failure after a successful AI call reads as done (`issue-post-processing-failure-reads-as-done.md`).
15. Research/report status reads done while queued (`issue-research-status-reads-done-while-queued.md`).
16. Non-loop wording (`issue-drill-wording-gaps.md` items 1, 7c, 7d): internal ticket notes on rule cards, US$ cost with no 「不是廣告費」, EasyStore-only empty state.
17. Flaky under load: `test_ads_external_sync.py` cursor test; DB connection exhaustion at `pytest -n 4` on 54322.
18. `TreeRows` squeezes long names at 1024; `DayGrid` truncates long account names.

### P2 — ad-loop features, one /dig each, in this order
1. **Platform writes** (the system creates ads, changes budgets and pauses on Meta after approval) — next /dig (§6.4 ruling needed).
2. In-app image generation — pick a provider first.
3. Notification channels beyond the inbox: a per-user 「通知」 section in `/settings`, then LINE OA and email.
4. Past-month suggestion history in the month review (not stored today).
5. Reserved objectives 互動, App 推廣, 來店 (§6.34).

### Archived — later session
- Two parallel performance-reading systems (brand-home 判讀 vs Ads Center review/learnings): discuss moving the four unique capabilities into the Ads Center, then retire the old panel (`app/schedule/diagnosis.py` helpers `breakeven_roas` etc. must stay).
- 「第 V 版有改」 chip (accepted missing); objective catalog keys keyed by id (`channels.py`); F29 review evidence page vs v10 (three columns, no 「在活動裡的位置」); kit pieces for the workspace four-number strip and publish summary tiles.
- `issue-no-export-anywhere.md` (remaining scope), free-job reference image and scene field (need a product decision).
- Before deploy / charging: `issue-07-2-*`, `issue-07-4-*`, `issue-delete-seed-debug-account.md`, `issue-ai-cost-reconciliation.md`, `issue-key-source-switch.md`, `issue-intake-error-shape-diverges.md`, `issue-intake-pending-photos-dict.md`, `issue-u1-banned-words-gate.md`.
- Not planned / decided-deferred: `issue-variant-level-learning.md`, `issue-organic-post-visual-learning.md`, `issue-intake-scan-per-photo-progress.md`.
- Discussion material: `discovery-*.md`, `roadmap-autonomous-marketing-major-updates.md`, `issue-drill-4-root-causes-pending-rulings.md` (all eight ruled). `engineering-existing-campaigns-user-assets.md` is superseded by ads.md §6.9 except the unverified-platform list and the pending usability sign-off: fold those into §6.9, repoint `CLAUDE.md`, `ads.md` and the roadmap link, then delete.
- Resolved and deleted 2026-09-26: `candidate-multiplatform-campaign-assets.md` (redirect stub), `issue-test-schema-ddl-deadlock.md` (bounded retry in `app/tests/conftest.py` `_ddl`).

## Workflow lessons from F30
- While any worker is active the lead edits only `.work/` and `.harness/`; a main-tree code edit is blamed on the running worker and violates its lease (recovery: release → claim → apply the saved patch).
- Merges and rescopes wait for in-flight worker calls; a small retry loop (`harness merge <id>` every 15 s while "still in flight") avoided polling by hand.
- Carve-time gap checks per screen (one read-only agent each) found the missing backend fields up front; the remaining misses were cross-issue rules (one readiness rule, one freeze rule), which the lead turned into a follow-up issue instead of copies.
