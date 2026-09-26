# Handoff after F30 (2026-09-26)

Start here in the next session. This is a board, not an implementation authorization: pick one line, `/dig` or fix it directly, and re-verify every claim first (causes written here have been wrong before).

## State
- F30 is closed and merged to `master` (`8f1dfd71`). No open feature; the queue is empty. The user pushes manually.
- Rules: `docs/architecture/ads.md` §6.34 (F30) on top of §6.32 (F28) and §6.33 (F29). UI spec: `docs/design/ads/prototype-v10-ads-center.html` + `prototype-v10-ai-blocked.html`. Every v10 screen is now built.
- The user accepted the F30 side-by-side as is (pill tab bar, the extra 「打開」 on verified change rows, and the missing 「第 V 版有改」 chip included).

## Priority board (user ruling 2026-09-26)
Order: bugs and everything the ad closed loop needs first; the rest is archived below for a later session.
Each open-file claim was re-verified against `1fd9a187` on 2026-09-26 (file:line in the issue files may be stale).

### P1 — bugs: done in F31 (2026-09-26)
All 18 items fixed at their causes (rules in `docs/architecture/ads.md` §6.35 and `docs/architecture/intake.md` "F31"); the absorbed backlog files were deleted. Follow-ups F31 surfaced, not fixed:
1. `WorkspaceHead` 打平線 pill squeezes to one character per line beside a long campaign name at 1024 (same class as the TreeRows fix).
2. Brand-home 判讀: a failed round reads 「這一輪判讀沒有給出建議」, not as a failure (the diagnosis response has no failure message).
3. `GET …/campaigns/{c}` returns the internal `live_creative_json` on each ad (payload only; frontend ignores it).
4. `test_workbench.py::VideoScriptRoundTripTest::test_short_reply_stays_red_after_a_fix_round_that_does_not_add_one` fails under xdist without `--dist loadfile` (order/queue dependence).
5. The two cross-org lookup functions are callable by any signed-in user through PostgREST RPC as a yes/no oracle on a platform id; wait page `missing_days` only cover the connections window (this month or last 28 days).
6. `issue-image-validation-does-not-gate-selection.md`: the prose-drift check is still undecided.

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
