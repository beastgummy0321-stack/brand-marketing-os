# Next UI batch: handoff (2026-09-25)

Start here in the next session. This is discovery, not an implementation authorization: `/dig` the open question below, then `/carve`.

## State (verified 2026-09-25)
- F28 and F29 are closed, merged and **pushed**. `origin/master` = `master` = `1c39f585`. No open feature; the harness queue is empty.
- The rules live in `docs/architecture/ads.md`: §6.32 (F28: one cap, grades) and §6.33 (F29: settle learnings, A/B, one ruler, rejection memory, v10 vocabulary, known gaps).
- The UI spec is the approved prototype `docs/design/ads/prototype-v10-ads-center.html` (v9 plus the F29 changes). The HTML itself is the layout spec (CLAUDE.md, design-system §1.7).

## Scope: remaining screens not yet rebuilt to v9/v10
| Screen | Prototype hash (v10 file) | Current app route |
|---|---|---|
| New-campaign wizard | `#/new/1`, `#/new/2` | `/brands/:b/ads/new`, `/ads/new/:c` |
| Workspace lifecycle rail + tabs (overview, strategy, structure, assets, perf, changes) | `#/camp/<id>/overview`, `…/strategy`, `…/assets`, `…/changes` | `/brands/:b/ads/campaigns/:c` (tabs via `?tab=`) |
| Assets tab, incl. the v10 素材需求 card (「換掉這一則」 requests, F29-I06 API) | `#/camp/<id>/assets` | the assets tab of the workspace |
| Full publish page (F29 rebuilt only its three settings blocks) | `#/pub/fall/list`, `…/platform`, `…/verify` | the launch handoff in `ManualHandoffPanel` / `PublishPage` |
| Connections | `#/connections` | `/brands/:b/ads/connections` |

Already rebuilt (do not redo): home, settle, campaign detail/perf, cleanup/A/B/stop flows, month review, strategy cap block, jobs panel.

## Open question: decide before carving (original drill-5 item 4)
- **Symptom (Vivian, drill 5):** the 變差 (worse) review flow says 「請人工判讀」 when the fact check rejects the model output. It then locks choosing a direction and editing the copy, and offers no retry.
- **Where:** `app/ads/review_policy.py:72` raises `模型包含未允許的數字或因果斷言；請依原始證據人工判讀。`, called from `app/ads/review_jobs.py:74`. The frontend steps are `frontend/src/components/ads/review/` (the prototype's `#/d/<id>/dir` and `#/d/<id>/copy`).
- **Proposal from the backlog (not ruled):** open a manual copy path plus a retry when the fact check blocks.
- **Unverified:** whether the lock comes from the frontend state or from the review round's status. Probe that before choosing a fix.

## Confirmed constraints (keep)
- Graphics-first, linear flows, no text walls, default simple with advanced folded on the same page (§1.7, F12).
- Every UI change is prototyped first and checked by a cold-novice persona on screenshots before the user sees it.
- The user reviews ONE side-by-side page after the batch merges. Make it self-contained with embedded images: a file card cannot resolve relative image paths.
- One cap per campaign, cost per result. Words on screen: 上限; grades 划算/偏貴/太貴/沒賣出; money tag 有賺/剛好打平/在虧 against break-even.
- No platform writes (§6.4). Never ask the user to run real Meta ads.

## Still deferred (not this batch unless the user pulls them in)
- In-app image generation: pick a provider first.
- Notification channels beyond the inbox: a per-user 「通知」 section in `/settings`, then LINE OA and email.
- Past-month suggestion history in the month review: not stored today.
- Platform writes: needs its own ruling.

## Lessons from F29 to apply when carving (each cost a rescope)
- An issue that adds a required field to a shared frontend type must list **every** test fixture that builds that type (3 misses in F29). Grep the type name across `frontend/src/**/*.test.tsx` at carve time.
- Never put a wildcard in `do_not_touch` over a sibling of a touch file, and re-check with fnmatch whenever touch is widened later (harness 3.0.8 evaluates do_not_touch first).
- Workers must write logs outside the worktree (`%TEMP%/claude/`); a stray file locks the lease. After a lease recycle the lead must not `attach`, or worker dispatch is refused.
- Issue verify does not run the whole suite; `test_ads_no_platform_literal` and e2e only run at merge/integrate. Worker prompts should run the full `app/tests/test_ads*.py` before reporting.

## Environment
- Start: `啟動行銷系統.bat` (8710; it brings up Docker and Supabase itself). Restart the backend and worker before live acceptance.
- Prototype preview server: `.claude/launch.json` config `prototype`, port **8741** (8799 is reserved by Windows). It serves `.harness/scratch/prototype/`.
- Test login `123@example.com` (see CLAUDE.md). The agent cannot type the password; ask the user to sign in in the browser pane, or probe the API with a self-signed HS256 JWT.
- Apply a migration to the dev DB as `supabase_admin`: `docker exec -i supabase_db_marketing psql -U supabase_admin …`.

## Recommended first step
Run `/dig` on the open question (item 4), with a cheap probe of where the lock comes from. Then `/carve` the five screens: one issue per screen, plus a small backend issue first for any field the prototype shows that the API lacks.
