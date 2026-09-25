# Handoff after F30 (2026-09-26)

Start here in the next session. This is a board, not an implementation authorization: pick one line, `/dig` or fix it directly, and re-verify every claim first (causes written here have been wrong before).

## State
- F30 is closed and merged to `master` (`8f1dfd71`). No open feature; the queue is empty. The user pushes manually.
- Rules: `docs/architecture/ads.md` §6.34 (F30) on top of §6.32 (F28) and §6.33 (F29). UI spec: `docs/design/ads/prototype-v10-ads-center.html` + `prototype-v10-ai-blocked.html`. Every v10 screen is now built.
- The user accepted the F30 side-by-side as is (pill tab bar, the extra 「打開」 on verified change rows, and the missing 「第 V 版有改」 chip included).

## Found during F30, still open (most useful first)
2026-09-26 session fixed and removed: skipped e2e specs (cold-start self-seeds, five retired — `docs/verification.md`), stuck `partial` sync, superseded review round + notice, readiness copies + deferred ads in the manual list, workspace settle grading, one daily-budget rule (ads.md §6.34), frontend test env, material confirm-by-eye evidence, last-group delete guard (ads.md §6.34). Resolved backlog files were deleted; `issue-no-export-anywhere.md` trimmed to its open scope.

1. **「第 V 版有改」 chip** on the publish page: launch items carry no "changed in this version" field (`launch_view.py`).
2. **Objective catalog platform keys** come positionally from `channels.CHANNELS` (a test pins them). Cleaner: per-platform objective names in `channels.py`, keyed by id.
3. **Connections:** a day after the latest order without orders reads as missing (spend days read zero-as-ok); `/settings?tab={platform}` only exists for meta.
4. **Flaky under load:** `test_ads_external_sync.py` cursor test ("did not terminate" in 12 rounds) and DB connection exhaustion when several workers run `pytest -n 4` on the shared 54322 DB (workers used `-n 2`).
5. **Kit gaps used by composition:** the workspace four-number strip (`.kv`) and the publish summary tiles have no kit piece; `TreeRows` squeezes long names at 1024; `DayGrid` truncates long account names.
6. The F29 review evidence page still differs from v10 (three columns, no 「在活動裡的位置」 ruler); F30 only changed its rejected state.

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
