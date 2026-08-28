# Handoff — replace `app/ads/` with a prompt shell

Date: 2026-08-28. Produced by a `/grill-with-docs` session. Supersedes
`HANDOFF-shell-os.md` (which planned a separate new repo — that plan is dead, see §5).

Branch base: `saas`. Everything below happens on a branch cut from `saas`, not `master`.

**Read `docs/adr/0028` and `docs/adr/0029` before touching code.** The new vocabulary is
appended to `CONTEXT.md` under "外殼與代理". The binding constraint is the user's global
`~/.claude/CLAUDE.md` section **"Build only what has hurt"**.

---

## 1. What is being replaced, and why

`app/ads/` is 21,595 lines that encode guessed thresholds as constants — "可信門檻 = 50
conversions", "規則有效期 = 6 期", the 預熱/高潮/衝刺 day-and-budget curve, echo-chamber,
fingerprints, the learning ledger. **None of them was ever validated against a real campaign.**

The disease is not that the code is rigid. It is that a judgement written into Python becomes
unarguable: changing `50` to `30` means editing code, running tests, and waiting for review, so
nobody changes it, so the guess becomes the specification. The cure is not "replace code with
AI" — it is **move the constants out of the code into a file the user can edit** (`rules.md`),
and keep in code only what must be identical on identical input.

The split, which every ticket below obeys:

| Nature of the thing | Who does it |
| --- | --- |
| Same input must give same output (arithmetic, gates, sorting) | Code — the only thing code is irreplaceable at |
| A judgement you can write as a formula | Code, but the parameter lives in `rules.md` |
| A judgement you cannot write as a formula | The agent |

## 2. Measured cost of the amputation

| | Lines |
| --- | --- |
| `app/ads/` | 21,595 |
| Its tests (81 of 175 test files — **55% of the suite**) | 23,154 |
| **Total deleted** | **44,749** |
| Import sites to rewire | **31, across 5 modules** — dashboard 17, orders 6, creative 4, brand_web 2, brand_intelligence 2 |

All 31 are module-level (`from app.ads import X as ads_X`) across 16 submodules; the heaviest
is `performance` (5x). Shallow, not entangled.

**Frontend:** 21 routes, of which **10 depend on ads** (campaigns x3, workbench x2, ads-claims,
learnings, report, tracking x2, data-onboarding). The other 11 — `/`, `/inbox`, `/settings`,
`/intake/new`, `/brands/:id`, `/intake`, `/library`, `/products` x2, `/orders` — survive the
deletion untouched. On `master` those 11 were confirmed working by hand on 2026-08-28.

**SaaS work lost with ads is about 2,547 lines** (`supabase/migrations/...ads_baseline.sql` 853,
`app/ads/migrations/0001_tables.sql` 571, `ads/repository.py` 467, `auto_sync` 202,
`performance` 191). The rest of the `saas` branch's 463-file, +15,365/-13,856 diff —
identity/orgs/auth, Supabase migrations, the psycopg rewrite of `core/db.py`, `core/vocab.py`,
uv/pyproject — **does not live in ads and survives.** This is why the base is `saas`: choosing
`master` would mean redoing roughly 26,000 lines of already-finished SaaS work.

## 3. Settled decisions

Numbers and rejected alternatives are recorded deliberately — a later summary that softens
these into prose has lost the decision.

1. **v1 scope**: plan → creatives → **the human posts to Meta by hand**. Review, CSV import,
   and cycle N+1 are explicitly out. Rejected: stopping at the plan (can't post, never gets
   real numbers, repeats the original failure); including review (needs 2 weeks of real data
   that does not exist yet, so any review built now is guessed).
2. **A department is a folder of task `.md` files, not a Python package** (ADR 0028).
   Adding a department = adding a folder. Price paid: **a department cannot have its own
   screen.** "Department" is deliberately not "module" — CLAUDE.md #7 and ADR 0024 already
   own that word for Python packages.
3. **The shell cats files into the prompt but never parses them** (ADR 0029). Precedent:
   `app/llm/methodology.py` already composed methodology files verbatim.
4. **Money numbers are computed by code, never by the agent.** The agent returns *ratios and
   choices* (`budget_share: 0.4`), the shell multiplies. Keeps ADR 0016/0022/0023's
   "numbers by code, words by LLM". CPA/ROAS/spend come from the imported Meta CSV and never
   pass through a model at all.
5. **Two new tables only**: `run` (id, brand, department, task, cli, model, status, started_at,
   ended_at, exit_code, error, out_path) and `approval` (id, brand, department, cycle,
   artifact_path, budget, approved_at). `run` exists because "what is running / why did that
   fail" is the only cross-brand cross-department question. `approval` exists because it is the
   money audit trail and must not be erasable by deleting a file. Brands stay folders — no
   second source of truth. All ads tables are dropped.
6. **UI is button-driven, not a chat room.** A work-order feed of cards with stable ids, plus
   a free-text field that is *appended* to the fixed prompt and re-runs it. Rejected: a real
   chat box — it destroys the prompt-library discipline and gives the approval gate nothing
   stable to attach to.
7. **The 10 dead routes collapse to 2**: the work-order feed and a dashboard. The other 8 are
   deleted, not redirected. Which 2 pages exactly is deferred to its own grill (§4).
8. **v1 dashboard shows plan-side numbers only** (this cycle's total budget, per-product share)
   computed by code from `plan.json`. Performance numbers do not exist until cycle 2.
9. **First buttons: exactly two** — `產生本期方案`, `產生素材`. Rejected: an "auto-fill the
   brand file from the website" button — that is data entry, not delivery, and filling it by
   hand has not hurt yet.
10. **Both CLIs from day one, switchable in settings.** They are *not* interchangeable at the
    call site — six verified differences: codex refuses to run outside a git repo without
    `--skip-git-repo-check`; project instruction file is `CLAUDE.md` vs `AGENTS.md`; permission
    flags are `--permission-mode bypassPermissions` vs `-s danger-full-access`; results arrive
    on stdout vs `-o <FILE>`; **only codex has `--output-schema`**; codex has `--ephemeral`,
    claude leaves session files in the workspace. Both read the prompt from **stdin** (verified
    2026-08-28) — argv is not viable, the prompt exceeds the ~8191-char Windows limit.
11. **The shell validates `plan.json` itself**, because only one CLI can enforce a schema.
    Pydantic model + one automatic retry with the validation error appended. This is not an
    abstraction layer: it is the dashboard's data source and the precondition of the budget
    gate. Rejected: normalising error semantics into three kinds across the two CLIs — no
    screen would behave differently, so it is pure work.
12. **Waiting is handled by front-end polling** (2s, "執行中… 已 42 秒"). SSE streaming is
    deferred until staring at a spinner has hurt twice.
13. **Cloud cost model, already solved on this branch**: `resolve_ai_credentials()` in
    `app/core/settings.py` decides whose key pays (`'platform'` with a monthly cap vs `'own'`).
    A user's Claude Pro/Max subscription **cannot** pay for a third-party SaaS — BYOK with an
    Anthropic API key is the supported path. Local desktop mode is the only form where the
    user's own subscription pays.

## 4. Open — the frontier is not empty

1. **Which 2 pages, concretely.** Deferred by the user to its own grill.
2. **Variance is unmeasured.** A probe exists at
   `D:\0UserProfile\Desktop\MarketingOS Shell\variance-probe\` (stdlib-only, `--selftest`
   proven red once then green). It runs one task N times against a real brand and reports:
   how often the same products are chosen, the min-max spread of each `budget_share`, **how
   often the shares fail to sum to 1.0**, and angle-name repetition. Needs a real brand filled
   into `workspace/{brand,products,rules}.md`. Until it runs, "how much does the plan move
   between runs" is unknown and decision 11's retry budget is a guess.
3. **`claude -p` loads the user's global `~/.claude/CLAUDE.md`** — verified: a bare probe came
   back prefixed `Beast，`. Every brand prompt is therefore contaminated by the developer's
   personal agent rules. Unsolved. Candidates: `--settings` with a clean config, or a scoped
   `CLAUDE_CONFIG_DIR` (which would also lose auth — needs testing).
4. **Workspace directory layout under many modules** is undesigned.
5. **`run_task`'s two shapes** — spawn a local CLI vs call an API — are not specified. This is
   the single SaaS seam; decision 3 is what makes the swap cheap (the prompt is already an
   assembled string, so only the destination changes).
6. **The DB delta SQL** (create `run` + `approval`, drop every ads table) is not written.

## 5. Voided by this session

- The separate "Shell OS" repo. Its reason was keeping old code out of an agent's grep range;
  deleting 44,749 lines achieves that more completely. `HANDOFF-shell-os.md`'s copy list is
  void — nothing is copied in, the direction is deletion out. `app/methodology/`'s 8 content
  files stay where they are and become task-file material; `methodology/README.md`'s lookup
  table is superseded by each task file naming its own inputs.
- "Rebuild the frontend from scratch" — the 11 surviving routes are inherited instead.
- The claim that `app/brand_web/` or `app/intake/` holds a reusable form schema. **It does
  not** — intake is a state machine. The real field list is in `流程心智圖.md` §A1–A5.
- "SaaS comes later." SaaS is the destination; local is the test phase.

## 6. Ticket order

0. **Get `saas` running locally and confirm the 11 non-ads routes work there.** `saas` is
   Supabase-Postgres only (`core/db.py` is psycopg; `DATABASE_URL` defaults to the local
   `supabase start` instance) — there is no SQLite path any more, so this needs Docker. Only
   `master` has been hand-verified. **If `saas` will not come up, the base decision reopens
   and `master` becomes correct.** Nothing below starts until this is green.
1. Run the variance probe against one real brand (§4.2). Its output constrains ticket 4.
2. Delete `app/ads/` and its 81 test files; rewire the 31 import sites; delete the 8 dead
   routes. Machine gate: typecheck + build + the surviving tests.
3. DB delta: create `run` + `approval`, drop the ads tables.
4. `run_task(workspace, task) -> result` for the local CLI, both flavours, stdin-fed.
5. The two pages, once their own grill has settled them.

## 7. Constraints carried over

- Replies to the user in Traditional Chinese, plain language, one analogy per term, each reply
  starting `Beast，`. Spec files, tickets, ADRs and code comments in English.
- Every money-touching action stays behind a human approve button. `plan.json` budget over the
  `rules.md` cap blocks approval — roughly 20 lines, and the only place the shell refuses.
- Tests: target under 300 lines total for the new code. Pack/unpack round-trip, the budget cap,
  and the runner contract are the three that earn their place.
