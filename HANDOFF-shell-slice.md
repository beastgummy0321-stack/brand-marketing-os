# Handoff — amputate `app/ads/`, then gate what let it grow

**First sentence for the next session:** "Read `HANDOFF-shell-slice.md` and execute tickets 1
through 7. Do not redesign anything — the design is settled; §3 is the constraint list, not
a menu. Anything in §6 comes back to the architecture session, not to you."

Date: 2026-08-28. Produced by a `/grill-with-docs` session. Paperwork committed as `ba63f49`
(pushed by the repo's `post-commit` hook). Supersedes `HANDOFF-shell-os.md`, which planned a
separate new repo — that plan is dead (§5). It does **not** supersede
`.scratch/HANDOFF-2026-08-28-pause.md`; that one still holds for slices ⑤⑥⑦, which resume
after this work (§7).

**Read before touching code:** `docs/adr/0028`, `0029`, `0030`, and `CONTEXT.md` §外殼與代理.

---

## 0. State, verified

- Branch `saas`, HEAD `ba63f49`, pushed. Working tree clean.
- Full suite was **2,374 passed, zero red** at `68a52f9`; `ba63f49` is docs-only.
- **Ticket 0 is done**: `saas` comes up locally under `supabase start` and all 11 non-ads
  routes were clicked through by hand on 2026-08-28. The base decision is final: `saas`,
  not `master`.

## 1. What is being replaced, and why

`app/ads/` is 21,595 lines that encode guessed thresholds as constants — "可信門檻 = 50
conversions", "規則有效期 = 6 期", the 預熱/高潮/衝刺 curve, echo-chamber, fingerprints, the
learning ledger. **None was ever validated against a real campaign.**

The disease is not that the code is rigid. A judgement written into Python becomes unarguable:
changing `50` to `30` means editing code, running tests, waiting for review — so nobody does,
and the guess becomes the specification. The cure is **move the constants out of code into a
file the user edits** (`rules.md`), and keep in code only what must be identical on identical
input:

| Nature of the thing | Who does it |
| --- | --- |
| Same input must give same output (arithmetic, gates, sorting) | Code — the only thing code is irreplaceable at |
| A judgement you can write as a formula | Code, but the parameter lives in `rules.md` |
| A judgement you cannot write as a formula | The agent |

## 2. Measured scope of the cut

| | Count |
| --- | --- |
| `app/ads/` | 21,595 lines |
| `app/core/orchestrator.py` + `app/tests/test_core_orchestrator.py` | 215 lines + its test |
| Ads test files | **81 of 175** files, 23,154 lines — **55% of the suite** |
| **Total deleted** | **~44,960 lines** |
| `app/creative/` | 817 lines, imported by nothing but `app/ads/` |
| `import app.ads` statements to rewire | **35**, in 3 places |

Import distribution — **`app/main.py` is the hard one and was missed in the first count**:

| Location | `import app.ads` statements |
| --- | --- |
| `app/main.py` (766 lines; 31 lines reference `ads_*` symbols) | 12 |
| `app/dashboard` | 17 |
| `app/orders` | 6 |
| `app/creative`, `app/brand_web`, `app/brand_intelligence` | **0** |

An earlier count said 41 across 6 modules. Six of those were comment lines, and what they say
is "不 import app.ads" — the modules were documenting that they deliberately do *not* import it
(`brand_web/routes_library.py:326`, `brand_web/routes_products.py:173`,
`brand_intelligence/background_job.py:9`). The blast radius is three modules, not six. All 35
are module-level (`from app.ads import X as ads_X`); `main.py` and `dashboard` carry 29 of
them.

**Frontend:** 21 routes. **10 depend on ads** — `/brands/:id/campaigns`, `campaigns/new`,
`campaigns/:cycleId`, `workbench`, `workbench/:cycleId`, `ads-claims`, `learnings`, `report`,
`tracking`, `tracking/setup`, `data-onboarding`. The other 11 — `/`, `/inbox`, `/settings`,
`/intake/new`, `/brands/:id`, `/intake`, `/library`, `/products`, `/products/:productId`,
`/orders`, `/accept-invite` — survive and were hand-verified.

## 3. Settled — constraints on the cut, not open questions

Numbers and rejected alternatives are recorded deliberately. A summary that softens these into
prose has lost the decision.

1. **v1 scope**: plan → creatives → **the human posts to Meta by hand**. Review, CSV import and
   cycle N+1 are out. Rejected: stopping at the plan (can't post, never gets real numbers,
   repeats the original failure); including review (needs 2 weeks of real data that does not
   exist, so any review built now is guessed).
2. **A department is a folder of task `.md` files, not a Python package** (ADR 0028). Adding a
   department = adding a folder. Price paid: **a department cannot have its own screen.**
   "Department" is deliberately not "module" — `CLAUDE.md` #7 and ADR 0024 already own that
   word for Python packages. Both terms are now defined in `CONTEXT.md`, pointing at each
   other under `_Avoid_`.
3. **The shell cats files into the prompt but never parses them** (ADR 0029). Precedent:
   `app/llm/methodology.py` already composed methodology files verbatim.
4. **Money numbers are computed by code, never by the agent.** The agent returns *ratios and
   choices* (`budget_share: 0.4`); the shell multiplies. Keeps ADR 0016/0022/0023's "numbers by
   code, words by LLM". CPA/ROAS/spend come from the imported Meta CSV and never touch a model.
5. **Two new tables only**: `run` (id, brand, department, task, cli, model, status, started_at,
   ended_at, exit_code, error, out_path) and `approval` (id, brand, department, cycle,
   artifact_path, budget, approved_at). Brands stay folders — no second source of truth. All
   ads tables are dropped.
6. **UI is button-driven, not a chat room.** A work-order feed of cards with stable ids, plus a
   free-text field *appended* to the fixed prompt that re-runs it. Rejected: a real chat box —
   it destroys the prompt-library discipline and leaves the approval gate nothing stable to
   attach to.
7. **The 10 dead routes collapse to 2** — a work-order feed and a dashboard. The other 8 are
   **deleted, not redirected**; a redirect makes a dead page look alive. Which 2 pages exactly
   is §6.1, and it does **not** block ticket 2.
8. **v1 dashboard shows plan-side numbers only**, computed by code from `plan.json`.
   Performance numbers do not exist until cycle 2.
9. **First buttons: exactly two** — `產生本期方案`, `產生素材`. Rejected: an "auto-fill the
   brand file from the website" button — data entry, not delivery, and it has not hurt yet.
10. **Both CLIs from day one, switchable in settings.** *Not* interchangeable at the call site;
    six verified differences: codex refuses to run outside a git repo without
    `--skip-git-repo-check`; instruction file is `CLAUDE.md` vs `AGENTS.md`; permissions are
    `--permission-mode bypassPermissions` vs `-s danger-full-access`; results arrive on stdout
    vs `-o <FILE>`; **only codex has `--output-schema`**; codex has `--ephemeral`, claude leaves
    session files in the workspace. Both read the prompt from **stdin** (verified 2026-08-28) —
    argv is not viable, the prompt exceeds the ~8191-char Windows limit.
11. **The shell validates `plan.json` itself**, because only one CLI can enforce a schema.
    Pydantic model + one automatic retry with the validation error appended. Not an abstraction
    layer: it is the dashboard's data source and the precondition of the budget gate. Rejected:
    normalising error semantics across the two CLIs — no screen would behave differently.
12. **Waiting is front-end polling** (2s, "執行中… 已 42 秒"). SSE is deferred until staring at
    a spinner has hurt twice.
13. **Cloud cost model, already built on this branch**: `resolve_ai_credentials()` in
    `app/core/settings.py` decides whose key pays (`'platform'` with a monthly cap vs `'own'`).
    A user's Claude Pro/Max subscription **cannot** pay for a third-party SaaS — BYOK with an
    Anthropic API key is the supported path. Local desktop is the only form where the user's own
    subscription pays.
14. **The orchestrator's code goes, its design stays** (ADR 0024, now marked). Its only caller
    was `app/ads/auto_sync.py:212`; 7 of its 8 `status()` providers lived in `app/ads/`. In v1
    two buttons are pressed by a human — there is nothing to orchestrate. Rebuild from ADR 0024
    when automation returns.

## 4. Tickets — execute these

**Read your global `~/.claude/CLAUDE.md` § "Workflow overrides" first.** It was rewritten on
2026-08-28 and it wins over the plugin's `workflow.md` wherever they disagree. The four that
change how you work here: main chat does its own read-only scans (do not dispatch a scout for
a grep); work sequentially, not in parallel worktrees; every ticket's done-checks spell out the
gate command verbatim; a reject must quote the done-check it fails, word for word, or it is a
note and the ticket ships.

### Ticket 1 — branch

`git checkout -b shell` from `saas`. **Short-lived**: merge back the moment ticket 5's gate is
green, then delete it. A 45,000-line deletion that diverges for a week is unmergeable.

### Ticket 2 — the amputation (route B: no schema, no money, no permission path)

**Delete:**
- `app/ads/` entirely
- `app/core/orchestrator.py` and `app/tests/test_core_orchestrator.py`
- the 81 ads test files under `app/tests/`
- `AdsMustNotImportOrdersTest` from `app/tests/test_architecture_boundaries.py` (its subject
  is gone)
- the 8 dead frontend routes and their page components (§2). **Keep `/brands/:id`** — it
  becomes the shell dashboard later, so strip it to a brand header plus a "本期還沒有方案"
  empty state rather than deleting it.

**Rewire:** the 41 import statements. `app/main.py` (13 imports, 31 referencing lines) and
`app/dashboard` (17) are 30 of them and are the real work. Where a call site only rendered ads
data, delete the call site; do not stub it.

**`app/creative/` goes too, but extract one file first.** It is imported by nothing except
`app/ads/` (7 sites, all inside ads) and imports nothing from ads, so the deletion leaves it
with zero callers — the orchestrator situation again. Its 15 `workbench/*.tsx` components go
with the two dead `/workbench` routes.

- `theme_engine.py` (477) and `theme_engine_video.py` (231): delete. This logic becomes the
  creative department's task `.md`.
- **`format_specs.py` (108): copy its contents into the ad department's task material before
  deleting it.** It is Meta's real format table — flexible ads cap at 10, single image is 1,
  narrative carousel gives each card its own beat. Those numbers have a genuine source (Meta's
  spec), unlike the thresholds this slice exists to remove, so the preamble rule keeps them.
  Delete without extracting and someone re-invents Meta's limits from memory later.

**Tolerance lists:** entries in `KNOWN_OVERSIZED_FILES`, `KNOWN_LAYER_VIOLATIONS`,
`KNOWN_IMPORT_CYCLES` that name deleted files (e.g. `app/ads/repository.py`, 856 lines) **must
be removed** — that makes a gate stricter and is always allowed. **Adding or widening an entry
to turn a red gate green is forbidden.** If the cut turns a gate red, fix the code.

**Done-checks (run exactly these):**
- `git grep -l "app\.ads" -- app/ frontend/src/` prints nothing
- `test ! -d app/ads && test ! -f app/core/orchestrator.py`
- `uv run python -m pytest app/tests -q` — zero red. The count drops well below 2,374; that is
  the point, not a regression.
- `cd frontend && npm run build && npm run lint`

### Ticket 3 — drop the ads tables (route C: migration)

Split from ticket 2 deliberately. Ticket 2 is route B and needs no independent review; **this
one is a migration, so it is the only part of the cut that earns one.** Do not let a 45,000-line
deletion get dragged through route C because one migration was bundled into it.

New file under `supabase/migrations/`. Done-check: `supabase db reset` applies clean, then the
suite from ticket 2 stays green.

### Ticket 4 — one e2e smoke, and delete the screen scans it replaces

**This is the gate that proves the cut did not break the 11 surviving screens.** It runs before
the merge, not after.

**Add** one Playwright spec: log in → land on 跨品牌總覽 → open a brand → 建檔精靈 → products →
orders. One file, one path, no fixtures, no page objects.

**Delete** from `app/tests/test_architecture_boundaries.py`:
- `ClipboardHonestyScanTest` (lines ~512–553)
- `ReviewStepSettleRefetchWiringTest` (lines ~555–623)

Together ~111 lines. Both assert **screen behaviour** — one scans copy buttons, the other
asserts a React prop is passed down — and the rules say screen behaviour gets one e2e smoke,
not unit tests. They exist only because this project has no smoke: the cheap broad check was
never built, so its absence was paid for with expensive brittle narrow ones. This ticket pays
the debt properly. It pulls board item **07-1's** Playwright line forward; delete that half of
07-1 in ticket 7.

Ten boundary classes become seven, and the screens end up better protected than before.

**Done-checks:** the smoke passes against the freshly-cut branch; `pytest` still zero red;
`grep -c "ClipboardHonestyScanTest\|ReviewStepSettleRefetchWiringTest" app/tests/test_architecture_boundaries.py`
returns 0.

### Ticket 5 — merge and delete the branch

Merge `shell` into `saas`, run the **full** suite on `saas` (this is the only place it runs in
full), delete `shell`.

### Ticket 6 — gate what let it grow

The three existing gates **could not have caught this**, and that is the finding that matters:

- `FileLineCapTest` caps a **file** at 800 lines. `app/ads/`'s 21,595 lines were spread over
  dozens of files each under 800. Every one passed.
- `LayerDirectionTest` / `ImportCycleScanTest` catch coupling, not volume. Ads' coupling was
  clean — all 41 imports are module-level.

Measured 2026-08-28: production 38,491 lines, tests 42,166 → **ratio 1.10×**. **After the cut
it is 1.13× — it gets worse.** The test bloat is not concentrated in ads.

Add to `test_architecture_boundaries.py`, **frozen at the post-cut numbers**:

1. `TestRatioTest` — one frozen number, **may only go down**.
2. `ModuleSizeRatchetTest` — a frozen `{module: lines}` dict. Raising an entry is allowed but
   appears in the diff where a reviewer sees it. Same shape as `KNOWN_OVERSIZED_FILES`, and the
   global rule against widening tolerance lists already guards it. Ads would have hit this at
   ~2,000 lines instead of 21,595.

Optional third, and the most direct attack on the remaining 19,012 test lines: require every
test file to open with `# protects: money | tenant-isolation | api-contract | data-correctness`.
That turns an existing prose rule into a gate.

Once `TestRatioTest` exists, write "test lines ≈ 0.7× production lines" back into the workflow
rules — until then it stays deleted, because a number with no gate behind it is forbidden.

**Honest limit, state it in the ticket:** no gate catches the actual cause — writing 21,595
lines of guessed thresholds for a system nobody had run. "Do it by hand first; code it after it
has hurt twice" is the right rule and is **not machine-checkable**. These gates buy a 10×
earlier warning, not a cure. The rule that would have caught it is now in the global
`CLAUDE.md`: **a numeric threshold must name its source, and "industry benchmark" is not one.**

### Ticket 7 — rewrite the board

`BOARD.md`'s milestone reads "用真品牌跑一期廣告閉環". **That closed loop was `app/ads/`** — as
written it is unreachable. Rewrite it as "two buttons → plan → creatives → the human posts by
hand". Under 「里程碑之後」, V1-02, M1-01, M1-02, M1-03 and P1 die with ads; U1 (術語大掃除)
survives. Delete **04-0b** entirely (§5) and the Playwright half of **07-1** (done in ticket 4).
Mechanical work, no grill needed.

## 5. Voided by the grill session

- The separate "Shell OS" repo. Its purpose was keeping old code out of an agent's grep range;
  deleting ~45,000 lines achieves that more completely. `HANDOFF-shell-os.md`'s copy list is
  void — nothing is copied in, the direction is deletion out. `app/methodology/`'s 8 content
  files stay put and become task-file material; `methodology/README.md`'s lookup table is
  superseded by each task file naming its own inputs.
- "Rebuild the frontend from scratch" — the 11 surviving routes are inherited instead.
- The claim that `app/brand_web/` or `app/intake/` holds a reusable form schema. **It does
  not** — intake is a state machine. The real field list is in `流程心智圖.md` §A1–A5.
- "SaaS comes later." SaaS is the destination; local is the test phase.
- Ticket **04-0b** (org_id leak in `app/ads/sync.py:457-459`). It fixes a security hole in a
  file being deleted. **Do not do it.** Delete the line from `BOARD.md` in ticket 5.

## 6. Not yours — bring these back to the architecture session

1. **Which 2 pages, concretely.** A grill is queued. Does not block ticket 2.
2. **`claude -p` loads the user's global `~/.claude/CLAUDE.md`** — verified: a bare probe came
   back prefixed `Beast，`. Every brand prompt is contaminated by the developer's personal agent
   rules. Unsolved. Candidates: `--settings` with a clean config, or a scoped
   `CLAUDE_CONFIG_DIR` (which also loses auth — needs testing).
3. **Workspace directory layout under many departments** is undesigned.
4. **`run_task`'s two shapes** — spawn a local CLI vs call an API. The single SaaS seam;
   decision 3 is what makes the swap cheap. Note that **slice ⑤'s 05-1 (procrastinate
   `enqueue／status／cancel` + worker) is exactly the contract `run_task` needs** — its
   contract survives even though its payload (`_auto_sync_loop`, the weekly engine) dies with
   ads. Same for **06-1**: "每組織一 bucket" *is* the cloud workspace; "素材檔掛主題" dies.
5. **Variance is unmeasured.** A probe sits at
   `D:\0UserProfile\Desktop\MarketingOS Shell\variance-probe\` (stdlib only, `--selftest`
   proven red once then green). It runs one task N times against a real brand and reports how
   often the same products are chosen, the min–max spread of each `budget_share`, **how often
   the shares fail to sum to 1.0**, and angle-name repetition. Needs a real brand filled into
   `workspace/{brand,products,rules}.md`. Until it runs, decision 11's retry budget is a guess.
6. **ADR 0004 is stale and it is not this slice's fault.** Its stated premise is "系統是單機
   單人"; ADR 0027 and `CLAUDE.md` #1 overturned it. `authorized_by` auto-filled with a fixed
   value is an audit gap under multi-tenancy. Marked, unresolved.

## 7. After this work

Slices ⑤⑥⑦ resume from `.scratch/HANDOFF-2026-08-28-pause.md`, with these amendments:
**04-0b is void** (§5); **04-2's K1** (`tracking.py` writes `meta_ad_id`) is void — `/tracking`
is one of the 8 deleted routes. Everything else there still stands, including the six 小債 and
the D4-1…D4-4 rulings in `.scratch/saas/tickets/04-plan.md`.

## 8. Environment (after a reboot)

1. Start Docker Desktop, wait for the engine.
2. `supabase start` (CLI is in `C:\Users\User\scoop\shims`; needs a new terminal for PATH).
3. `uv sync --frozen`.
4. In bash, before any docker/supabase command:
   `export PATH="/c/Users/User/AppData/Local/Programs/DockerDesktop/resources/bin:/c/Users/User/scoop/shims:$PATH"`
5. Backend: `uv run python -m uvicorn app.main:app --port 8710` → http://localhost:8710/app/
   **Frontend changes need `cd frontend && npm run build`** (the backend serves `frontend/dist`);
   **backend changes need uvicorn restarted.** Both were forgotten once each last round.
6. 2,000+ errors at setup means the database is not up, not that the code is broken.

Local demo accounts (test data, deletable): `beast-demo-01@example.com` (owner, org
「野獸行銷有限公司」), `-02`, `-03` (members), password `demo-password-1234`.

## 9. Traps, learned the hard way

- **Tell every subagent "前景執行，不要背景跑，不要等通知".** Four agents stalled last round
  waiting for notifications that never arrived. Single biggest time sink.
- **Frontend tickets must run the backend suite too.** Architecture scans like
  `ClipboardHonestyScanTest` live in `app/tests/`; `npm test` alone misses them.
- **Screen tickets need a human clicking the browser.** Two of slice ③'s four bugs were only
  findable that way.
- **Ask a ticket to scan its neighbours** ("look for the same mistake next door, report only,
  don't fix") — that is how 04-0b was found. Cheap, high yield.
- Route C = ticket (what / done-checks / shared files) + Sonnet implementer + a **different**
  Sonnet reviewer.

## 10. Constraints carried over

- Replies to the user in Traditional Chinese, plain language, one analogy per term, each reply
  starting `Beast，`. Spec files, tickets, ADRs and code comments in English.
- Every money-touching action stays behind a human approve button. `plan.json` budget over the
  `rules.md` cap blocks approval — about 20 lines, the only place the shell refuses.
- New shell code: target under 300 lines of tests total. Pack/unpack round-trip, the budget cap,
  and the runner contract are the three that earn their place.
