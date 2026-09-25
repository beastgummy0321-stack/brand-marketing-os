# Handoff after F30 (2026-09-26)

Start here in the next session. This is a board, not an implementation authorization: pick one line, `/dig` or fix it directly, and re-verify every claim first (causes written here have been wrong before).

## State
- F30 is closed and merged to `master` (`8f1dfd71`), **not pushed** (the user pushes manually). No open feature; the queue is empty.
- Rules: `docs/architecture/ads.md` §6.34 (F30) on top of §6.32 (F28) and §6.33 (F29). UI spec: `docs/design/ads/prototype-v10-ads-center.html` + `prototype-v10-ai-blocked.html`. Every v10 screen is now built.
- The user accepted the F30 side-by-side as is (pill tab bar, the extra 「打開」 on verified change rows, and the missing 「第 V 版有改」 chip included).

## Found during F30, not fixed (most useful first)
1. **Five e2e specs never run.** `ads-cold-start`, `existing-campaigns-assets`, `ads-material-cycle`, `ads-runtime-cycle`, `ads-change-control` skip without their `F15_*_E2E_CONTEXT` fixtures; F30 changed their selectors (folds, renamed tabs) blind. Integrate showed 6 passed / 6 skipped. Either make the context reproducible or retire the specs.
2. **Stuck `partial` sync state** (a background-task chip was offered). A failed single-campaign pull task in `ads_external_sync_job` keeps its own date range, is never re-run or cleared, so the job stays `partial` and its overall last-success stops updating (`external_sync.request_sync` × `_update_task`). The connections read avoids these fields; anything else reading them is stuck.
3. **Superseded review round stays open.** After 「再請 AI 看一次」 the old rejected/failed round stays `ready`/undecided and its 「檢討已備妥」 notice stays (`runtime.py:260`). Triage and the monitor already follow the new round.
4. **「第 V 版有改」 chip** on the publish page: launch items carry no "changed in this version" field (`launch_view.py`).
5. **Readiness copies left:** `adapters/manual.py:77` (素材需重新指派) and `change_control_launch._material_label` still spell the `confirmed` condition instead of calling `ready_material()`; the old manual publish list still lists deferred ads.
6. **Workspace read cost:** `GET …/workspace` runs `triage.get_queue(items=…)`, which also grades the brand's previous month for the settle row and throws it away; `/structure` classifies a second time.
7. **Two daily-budget rules:** workspace/capacity (owners of active ads) vs the home row (all live owners) can differ; never shown side by side today.
8. **Objective catalog platform keys** come positionally from `channels.CHANNELS` (a test pins them). Cleaner: per-platform objective names in `channels.py`, keyed by id.
9. **Connections:** a day after the latest order without orders reads as missing (spend days read zero-as-ok); `/settings?tab={platform}` only exists for meta.
10. **Frontend tests need Supabase env:** `publish/publish.test.tsx` fails with 「supabaseUrl is required」 without `VITE_SUPABASE_*` (see also `issue-ci-frontend-tests-missing-supabase-url.md`).
11. **Flaky under load:** `test_ads_external_sync.py` cursor test ("did not terminate" in 12 rounds) and DB connection exhaustion when several workers run `pytest -n 4` on the shared 54322 DB (workers used `-n 2`).
12. **Kit gaps used by composition:** the workspace four-number strip (`.kv`) and the publish summary tiles have no kit piece; `TreeRows` squeezes long names at 1024; `DayGrid` truncates long account names.
13. **Material confirm by eye** (`unread("material")` on launch items) does not upgrade the material binding's evidence level.
14. The F29 review evidence page still differs from v10 (three columns, no 「在活動裡的位置」 ruler); F30 only changed its rejected state.

## Backlog board: check first whether F29/F30 already made these obsolete
`handoff-v7-remaining-screens.md` (all v10 screens are built now), `issue-assets-table-shows-raw-user-id-and-iso-time.md` (assets tab rebuilt), `issue-structure-dead-end-after-all-groups-deleted.md` (structure tab rebuilt), `issue-strategy-kpi-strip-cramped-at-1024.md`, `issue-no-export-anywhere.md` (F29 added CSV), `issue-period-page-has-no-history.md`, `drill5-open-items.md` (items 1–10 done in F28/F29/F30; keep only its capability gaps if still open). Delete or merge what is resolved; keep unique evidence.

## Still deferred (need a ruling before any work)
- In-app image generation: pick a provider first.
- Notification channels beyond the inbox: a per-user 「通知」 section in `/settings`, then LINE OA and email.
- Past-month suggestion history in the month review: not stored today.
- Platform writes: needs its own ruling (§6.4).
- Reserved objectives 互動, App 推廣, 來店 (§6.34).

## Workflow lessons from F30
- While any worker is active the lead edits only `.work/` and `.harness/`; a main-tree code edit is blamed on the running worker and violates its lease (recovery: release → claim → apply the saved patch).
- Merges and rescopes wait for in-flight worker calls; a small retry loop (`harness merge <id>` every 15 s while "still in flight") avoided polling by hand.
- Carve-time gap checks per screen (one read-only agent each) found the missing backend fields up front; the remaining misses were cross-issue rules (one readiness rule, one freeze rule), which the lead turned into a follow-up issue instead of copies.
