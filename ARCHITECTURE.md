---
{
  "harness": 1,
  "stack": "python",
  "app_shell": [
    "frontend/src/App.tsx",
    "frontend/src/main.tsx",
    "frontend/src/components/layout/**",
    "frontend/src/lib/**",
    "frontend/src/config/**",
    "frontend/src/styles/**",
    "frontend/e2e/**"
  ],
  "modules": {
    "workbench": {
      "root": "app/workbench",
      "public": "app/workbench/__init__.py",
      "may_depend_on": [],
      "owns": [
        "app/workbench/**",
        "app/departments/workbench/**",
        "app/tests/test_workbench*.py",
        "app/tests/fixtures/workbench/**",
        "frontend/src/components/workbench/**",
        "frontend/src/lib/workbenchApi.ts",
        "supabase/migrations/*_workbench_*.sql"
      ]
    },
    "ads": {
      "root": "app/ads",
      "public": "app/ads/__init__.py",
      "may_depend_on": [
        "workbench"
      ],
      "owns": [
        "app/ads/**",
        "app/departments/ads/**",
        "app/tests/test_ads*.py",
        "frontend/src/components/ads/**",
        "frontend/src/lib/adsApi.ts",
        "frontend/src/lib/adsLaunchApi.ts",
        "supabase/migrations/*_ads_*.sql"
      ]
    },
    "schedule": {
      "root": "app/schedule",
      "public": "app/schedule/__init__.py",
      "may_depend_on": [
        "workbench"
      ],
      "owns": [
        "app/schedule/**",
        "app/tests/test_schedule*.py",
        "app/tests/test_approval.py",
        "app/tests/test_imported_ad_schema.py",
        "app/tests/test_meta_daily_spend.py",
        "app/tests/test_past_ads_history.py",
        "frontend/src/components/schedule/**",
        "frontend/src/lib/scheduleApi.ts",
        "supabase/migrations/*_schedule_*.sql"
      ]
    },
    "intake": {
      "root": "app/intake",
      "public": "app/intake/__init__.py",
      "may_depend_on": [
        "ads"
      ],
      "owns": [
        "app/intake/**",
        "app/tests/test_intake*.py",
        "frontend/src/components/intake/**",
        "frontend/src/lib/intakeApi.ts",
        "frontend/src/lib/intakeT2Api.ts",
        "supabase/migrations/*_intake_*.sql"
      ]
    }
  },
  "resources": {
    "workbench_pack": {
      "owner": "workbench",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_workbench_*.sql"
      ],
      "symbol": "workbench_pack"
    },
    "workbench_brief": {
      "owner": "workbench",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_workbench_*.sql"
      ],
      "symbol": "workbench_brief"
    },
    "workbench_output": {
      "owner": "workbench",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_workbench_*.sql"
      ],
      "symbol": "workbench_output"
    },
    "workbench_visual_identity": {
      "owner": "workbench",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_workbench_*.sql"
      ],
      "symbol": "workbench_visual_identity"
    },
    "ads_campaign": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_ads_*.sql"
      ],
      "symbol": "ads_campaign"
    },
    "ads_delivery_group": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_ads_*.sql"
      ],
      "symbol": "ads_delivery_group"
    },
    "ads_ad": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_ads_*.sql"
      ],
      "symbol": "ads_ad"
    },
    "ads_action": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_ads_*.sql"
      ],
      "symbol": "ads_action"
    },
    "ads_outcome_daily": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_ads_*.sql"
      ],
      "symbol": "ads_outcome_daily"
    },
    "campaign_period": {
      "owner": "schedule",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_schedule_*.sql"
      ],
      "symbol": "campaign_period"
    },
    "channel_entity_map": {
      "owner": "schedule",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_schedule_*.sql"
      ],
      "symbol": "channel_entity_map"
    },
    "period_node_result": {
      "owner": "schedule",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_schedule_*.sql"
      ],
      "symbol": "period_node_result"
    },
    "imported_ad": {
      "owner": "schedule",
      "kind": "sql-table",
      "definition": [
        "supabase/migrations/*_schedule_*.sql"
      ],
      "symbol": "imported_ad"
    }
  },
  "legacy": [
    "app/__init__.py",
    "app/main.py",
    "app/worker.py",
    "app/background/**",
    "app/brand_intelligence/**",
    "app/brand_web/**",
    "app/core/**",
    "app/dashboard/**",
    "app/identity/**",
    "app/llm/**",
    "app/meta/**",
    "app/orders/**",
    "app/shared/**",
    "app/storage/**",
    "app/tools/**",
    "app/tests/conftest.py",
    "app/tests/identity_test_helpers.py",
    "app/tests/test_schedule.py",
    "app/tests/test_workbench.py",
    "app/tests/test_workbench_api.py",
    "app/tests/test_approval.py",
    "app/tests/test_imported_ad_schema.py",
    "app/tests/test_meta_daily_spend.py",
    "app/tests/test_past_ads_history.py",
    "app/tests/test_schedule_diagnosis.py",
    "app/tests/test_schedule_performance.py",
    "app/tests/test_schedule_period.py",
    "app/tests/test_org_isolation_all_tables.py",
    "app/tests/test_brand_isolation_all_tables.py",
    "scripts/**",
    "archive/**",
    ".scratch/**",
    ".worktrees/**",
    "app/tests/test_brand_delete.py",
    "app/tests/test_dashboard_guide_card_links.py"
  ],
  "legacy_facades": [
    "app/__init__.py",
    "app/main.py",
    "app/worker.py",
    "app/background/__init__.py",
    "app/brand_intelligence/__init__.py",
    "app/brand_intelligence/repository.py",
    "app/brand_intelligence/personas.py",
    "app/brand_intelligence/benchmarks.py",
    "app/core/__init__.py",
    "app/core/db.py",
    "app/core/config.py",
    "app/core/settings.py",
    "app/core/rule_cards.py",
    "app/core/approval.py",
    "app/core/audit.py",
    "app/core/interrupts.py",
    "app/core/cleanup.py",
    "app/core/vocab.py",
    "app/identity/__init__.py",
    "app/identity/repository.py",
    "app/llm/__init__.py",
    "app/llm/gateway.py",
    "app/llm/context_compiler.py",
    "app/llm/methodology.py",
    "app/llm/providers.py",
    "app/meta/__init__.py",
    "app/meta/repository.py",
    "app/meta/daily_pull.py",
    "app/meta/graph.py",
    "app/orders/__init__.py",
    "app/orders/repository.py",
    "app/shared/__init__.py",
    "app/shared/web.py",
    "app/shared/logging.py",
    "app/storage/__init__.py",
    "app/tests/conftest.py",
    "app/tests/identity_test_helpers.py",
    "app/core/net.py",
    "app/brand_intelligence/background_job.py",
    "app/brand_intelligence/customer_voice.py",
    "app/llm/pricing.py"
  ],
  "verify": {
    "test": "uv run python -m pytest app/tests -q -n 8 --dist loadfile",
    "typecheck": "uv run ruff check app && uv run python -m pyright && cd frontend && npx tsc -b --noEmit && npm run depcruise && npx vitest run src/architectureBoundaries.test.ts",
    "build": "cd frontend && npm run build",
    "smoke": "cd frontend && npm run e2e"
  },
  "checker": {
    "command": "uv run python tools/check_architecture.py"
  }
}
---

# Brand Marketing OS — how the system works now

Traditional-Chinese vocabulary for every business term is in `CONTEXT.md`; front-end rules are in
`docs/design-system.md`. This file is the only place where module boundaries, data ownership and
settled decisions live. Previous versions are in git.

## 0. What this system is for, and what failure looks like

MarketingOS owns one thing: the brand's decision flow —
goal → context → decision → strategy → artifact → action → outcome → learning → next goal.
Success is whether that chain closes for one brand, not how many modules exist.

Before cutting any issue the planner answers five questions:
1. Which link of the chain does this serve? No answer = an isolated feature.
2. Where does its input come from? Existing brand / product / campaign / history rows — never re-asking the user.
3. Where does its output go? Into the next link as structured data, not a screen the user copies from.
4. What trace does it leave? Why, what, which data, who approved, what happened.
5. If removed, does the OS still hold? Yes = pluggable module. No = core.

Golden path (prove this before any new module): brand → offering → goal (the brief) → strategy →
delivery plan → pack → artifacts → publish (manual or simulated) + bind → outcome → verdict against
the campaign's success criterion → learning → the next campaign's strategy reads the learning.

Stop signals — any one means stop adding features and re-check the architecture:
- a module keeps its own copy of brand data · one product fact lives in two places
- the user copies between screens · a step cannot see what the previous step did
- an outcome cannot find its campaign · a learning cannot show its evidence · a suggestion cannot say why
- one feature touches many modules · every feature adds system prompt · the user must know module
  names to finish a simple job · features grow but the full job still does not complete

Autonomy is earned: observe → recommend → act with approval → bounded autonomy. Today: recommend,
manual or simulated execution, zero writes to a live platform. Learning keeps its uncertainty:
「看不出」 is a valid verdict and a correlation is never reported as a cause.

**「不預設」 (settled 2026-09-14, F05).** The core loop carries no branch on platform, customer
type, user role or outcome source. Those are **keys on rows** — `ads_delivery_group.channel_key`,
`brand.conversion_goal` (`purchase`／`lead`／`booking`／`awareness`), a `product_economics` row's own
numbers. Platform differences live in `app/ads/adapters/**` and in `app/ads/channels.py`, the one
registry allowed to know a platform's name; anywhere else in `app/ads` a platform name in a string
literal is a bug, machine-checked by `app/tests/test_ads_no_platform_literal.py`. It has exactly
three exemptions — `channels.py`, the whole of `outcome.py`, and the whole `adapters/` directory;
`outcome.py` only until the 閉環 feature's RC-D removes the `source = 'meta'` rule, the other two for good. The
test and this sentence must name the same three.
Nouns on screen come from the data's own labels — the channel's `label`, the conversion goal's label
— shipped as text by the side that owns the rule (§5.3) and never re-spelled in the browser. There
is no platform abstraction layer, no role system and no second data model: 「使用者」 is an identity
(老闆／行銷／代理商), not a role, and the copy says 你.

Every feature close answers one sentence: did this make the OS better at understanding, deciding,
executing, learning and handing over — or did it add a feature?

## 1. Shape

Python 3.12 + FastAPI backend (`app/`), Postgres through Supabase (Postgres / Auth / Storage /
Vault), raw SQL only — no ORM. Background work runs on procrastinate in a separate worker process
(`app/worker.py`). The front end is React + Vite in `frontend/`, built and mounted at `/app`; the
backend serves JSON under `/api` only. Every table carries `org_id` (and `brand_id` where the row
belongs to a brand); RLS is the second line, `require_brand` plus tenant-scoped queries are the
first. LLM calls go through `app/llm/gateway.py`; prompts are assembled by the shell from
department task files (`app/departments/<department>/*.md`) plus methodology files
(`app/methodology/*.md`) — those `.md` files are program parts that cost tokens, not documentation.

Branches: `saas` is the developed line; `master` is the retired single-machine SQLite build.

**What an external model is allowed to cost** (2026-09-13, F04). The model is asked for judgment
only: arithmetic, fixed text and label mapping are the program's job, and no prompt ships bulk rows
or a long parameter list. Three rules hold everywhere, not per call site:
1. **Every list that goes into a prompt has a cap in one place.** `app/llm/context_compiler.py`
   caps rules, claims and brand facts against the same `rule_cards` 「rule_prompt_cap」 value —
   one guard for every caller rather than one per department. A caller that assembles its own
   list (learnings, products, coordinate vocabulary) caps it where it builds it and says in the
   prompt how many were left out; a truncated list is never silently truncated.
2. **The same bytes are never sent twice by accident.** `gateway.run_task` does not resend a large
   prompt on retry (above the threshold in `gateway.py` a failed attempt is final, because a
   16k-token resend costs more than the failure); a call site that deliberately sends the same
   prefix several times in a row (`performance_reading`'s three lenses) marks that prefix with
   Anthropic `cache_control`, which the dev-only codex route flattens away harmlessly.
3. **The cost column is the billing truth.** `llm_task.cost` is `numeric(14,6)`; the monthly cap
   sums it, so a sub-cent call must not round to `0.00`.
4. **Effort is explicit and an external agent gets only the tools the task needs** (2026-09-15,
   F07). The per-task thinking table in `app/llm/providers.py` reaches every provider: the dev-only
   `CodexCliProvider` passes it as `-c model_reasoning_effort=<level>` (`max` → `xhigh`) — before
   F07 `--ignore-user-config` silently dropped it — and always runs with
   `--disable shell_tool --disable browser_use --disable computer_use --disable apps
   --disable image_generation --disable in_app_browser`; `-c tools.web_search=true` is still added
   when the caller asked for web search. Measured on the image-prompt probe: with the shell tool on,
   3 of 10 runs executed a command mid-task and re-sent the whole prompt (17.5k → 40k input
   tokens); tools off cut input to 14.3k. No event or turn counting is stored. Probe v4 still saw
   one generation at 32.2k input with tools off (5 others at ~13.4k), so extra turns are not only
   shell use — but the probe never recorded what the extra turn was, a counter of an unknown event
   would be a guess, and `usage_json.input_tokens` already flags the run. Add a count when a
   recorded codex event stream shows which event marks the extra turn.
The coordinate vocabulary keeps its `label` column in prompts — `key` is an English slug and the
label is its meaning; dropping it would save tokens by making the model guess. `app/schedule`'s
`schedule_plan`／`schedule_tree` prompts are **not** capped: no screen has reached them since
檔期規劃 retired (F03), so their uncapped tables cost nothing and capping dead code buys nothing.

## 2. Managed modules and the legacy surface

Managed modules today are `workbench`, `schedule`, `ads` and `intake`. They follow the container rules: one
root, one public entry (`app/<module>/__init__.py`), declared dependencies, no cycles, no import of
the app shell. The machine check is `tools/check_architecture.py`, driven by the manifest above.

`ads` (投放中心) is the module added 2026-09-12 for the Ads V2 loop (§6). It depends on `workbench`
only; everything else it needs it reaches through legacy facades — `app/meta/repository.py` (bound
accounts, exact-name entity lookup, `daily_entity_spend`), `app/brand_intelligence/repository.py`
(brand facts, product economics, the learning ledger), `app/core/*`, `app/llm/*`, `app/shared/web.py`,
`app/background/__init__.py`. It never imports `app.schedule` and never names another module's table
in a string literal.

`intake` (品牌建檔精靈) is promoted out of legacy on 2026-09-14 (F05) for one reason: it owns the
**first link of the golden path**, so「legacy may shrink but never grow」would have forbidden the
foundation work the product actually needs. The promotion was measured before it was made — with
`intake` declared, `tools/check_architecture.py` reported seven violations, all of them imports that
already existed and were simply undeclared: `app/core/net.py`, `app/brand_intelligence/background_job.py`,
`app/brand_intelligence/customer_voice.py` and `app/llm/pricing.py` are now named legacy facades, and
`test_brand_delete.py`／`test_dashboard_guide_card_links.py` join the individually-listed legacy tests
(they reach into intake internals to seed rows). No code moved. Declaring those four facades records
what was already true; it is not permission for `ads`／`workbench`／`schedule` to start reaching for
them. `intake` reaches `ads` (`may_depend_on`) for one thing only — the 可投放檢查表 (§8) — and today
that call is made by the browser, not by a Python import.

Everything else under `app/` (core, shared, llm, identity, meta, brand_intelligence, brand_web,
orders, dashboard, storage, background, tools) plus `scripts/` is **legacy**: it works, it
is not governed by the container checker, and it may shrink but never grow. A managed module
reaches legacy code only through a file listed in `legacy_facades` (in practice: the package entry
or the module's `repository.py` / `gateway.py`). `may_depend_on` governs **managed modules only**:
importing a legacy facade is not an entry there and never needs one — `ads`' `may_depend_on:
["workbench"]` does not forbid `app/ads/repository.py` importing `app.brand_intelligence.repository`
(it is a declared facade; F03-I19 review). New capability never lands in legacy (one test-only exception: the e2e seam in §7); moving a
caller out of legacy is a `legacy_migration: true` issue with `review: planner`. There is no
clean-up-first round and no tolerance ledger.

`app/main.py` (the FastAPI composition root), `app/worker.py` and `app/__init__.py` are declared
legacy facades rather than app shell: a module's own tests must import them to build a `TestClient`,
and the checker forbids a module reaching the app shell at all. The invariant they would have
carried — no production module imports `app.main` — is already machine-checked by
`app/tests/test_no_branch_imports_app_main.py`, so nothing is lost. The `app_shell` globs therefore
name the front-end shell only, which the Python checker never scans (its boundary is
dependency-cruiser).

Tests: a test file that exercises one managed module is listed in that module's `owns` and obeys the
same import rules as production code — this is where new tests go. Thirteen existing test files are
listed individually in `legacy` instead, and the checker skips them: the seam tests
(`test_schedule.py`, `test_workbench.py`, `test_workbench_api.py`) drive both sides of the
schedule↔workbench boundary and seed each other's tables, the enumeration tests
(`test_org_isolation_all_tables.py`, `test_brand_isolation_all_tables.py`) name every table in the
database by design, and the rest reach into legacy internals. Rewriting them to public entries would
be a clean-up round that buys nothing the layer scans in
`app/tests/test_architecture_boundaries.py` do not already cover for production code. An issue that
touches one of those files carries `legacy_migration: true` and `review: planner`; the legacy list
shrinks when a seam stops needing both sides.

`app/methodology/**` is a shared prompt corpus read by every department task; it has no single
module owner. Amending a methodology file changes model behaviour for every task that reads it, so
those edits carry `review: planner`.

The front end is not a separate harness module: `frontend/src/components/<feature>/` folders are
owned by the backend module of the same capability (see `owns` above) and their import boundary is
enforced by `frontend/.dependency-cruiser.cjs` (feature folders talk to each other only through
`index.ts`; `layout/` is the shared kit), which runs inside the `verify.typecheck` command together
with the 800-line file cap `frontend/src/architectureBoundaries.test.ts`.
`frontend/src/lib/**` is app shell except the per-module API clients (`workbenchApi.ts`,
`scheduleApi.ts`, `adsApi.ts`, `adsLaunchApi.ts`, `intakeApi.ts`, `intakeT2Api.ts`), which each
module owns — `adsLaunchApi.ts` is `ads`' second client (F05-I05 split it out when `adsApi.ts`
passed the 800-line convention; a module may own more than one client, and `intake` reads it
because `intake.may_depend_on = ["ads"]`);
`frontend/e2e/**` is acceptance code that belongs to whichever ticket changes it.

## 3. Data ownership

`workbench_pack`, `workbench_brief`, `workbench_output` and `workbench_visual_identity` (the
derived brand visual identity cache, one row per brand knowledge version, §5.9 — a cache of what
the brand facts imply, not a second brand data model) belong to `workbench`; the
campaign/period tables belong to `schedule`; `ads_campaign`, `ads_delivery_group`, `ads_ad`,
`ads_action` and `ads_outcome_daily` belong to `ads`. Physical definitions live in the shared `supabase/migrations/` directory, one file
per module prefix (`<timestamp>_<module>_<desc>.sql`); an applied migration is never edited, a
correction is a new file.
**A table name is never reused as another identifier** (2026-09-15, F07-I02 block). The checker's
`sql-table` analyzer is textual: an owned table's name inside any string literal outside its owner
counts as access. A task type, job kind, prompt id or dict key therefore never equals a declared
table's name — the identity derivation's task type is `workbench_derive_identity`, not the table
`workbench_visual_identity`. Rename the new identifier; never narrow the analyzer to make a name pass.

`product_economics` (and its `product_economics_version` history) stays in `brand_intelligence` and
is the **one home of「一次轉換值多少錢」** for every kind of offering (§8). `intake` and `brand_web`
both write it through `app.brand_intelligence.repository.save_product_economics`, never with their
own SQL, and `ads` reads it through `get_product_economics`. No second table for services and no
per-offering-type table: the kind of thing being sold is a row's numbers, not a schema.

`learning_ledger` stays where it is — in `brand_intelligence`, which is legacy. It is brand
knowledge shown in 品牌智庫, not ads bookkeeping, so `ads` does not own it and does not write it
with SQL: `app/brand_intelligence/repository.py` (already a legacy facade, already registered for
brand/product deletion) gains `record_learning` / `list_learnings` and `ads` calls those. The
capability — when a learning is written, at what level, when it needs revalidation — lives in
`ads`; the facade only stores and reads rows of the table its own package already owns.
**Two tracks, one ledger** (2026-09-15, F07): the existing `learning_ledger.source_track` column
(`NOT NULL DEFAULT 'ads'`) separates campaign verdicts (`ads`, read by the strategy prompt) from
visual learnings (`visual`, written at 結案 by §6.3 and read by the image-prompt call).
`record_learning(..., source_track="ads")` and `list_learnings(..., source_track=None)` carry it;
`None` means every track. No second table, no migration. `expire_learning(conn, brand_id,
learning_id, *, actor)` sets the existing `expired` flag (audited) — the one write §6.3 item 19
needs to downgrade a visual winner that later loses; the rule of when lives in `ads`. The four
other dead tables (`decision`, `strategy_hypothesis`, `campaign_period_budget_version`,
`brand_dismissed_calendar_category`) stay in `docs/backlog/issue-five-live-tables-zero-code.md`;
dropping them is not part of building the loop.

Two cross-module raw-SQL reads exist and are deliberate, pre-dating the manifest:
`app/workbench/repository.py::list_coordinate_vocabulary` reads `brand_coordinate`/`feedback`
(schedule's tables) read-only rather than importing `app.schedule`, which would reverse the
dependency direction. They are recorded here rather than declared as owned resources; the layer
scan in `app/tests/test_architecture_boundaries.py` remains the tripwire for new ones.

A third one is granted, 2026-09-12, for the same reason, and shipped in F03-I06 as
`app/ads/repository.py::coordinate_vocabulary` (`SELECT dimension, key, label FROM
brand_coordinate WHERE org_id/brand_id AND disabled_at IS NULL`) — the one copy inside `ads`:
`ads` reads `brand_coordinate` read-only for the seven-coordinate vocabulary and its labels, and
every later ads issue that needs the vocabulary calls that function instead of writing its own
query. `brand_coordinate` is brand vocabulary that
outlives the module that happens to hold it today — when `schedule` retires (§4) the table moves to
`ads`, and until then importing `app.schedule` from `ads` would build a dependency we are about to
delete. `ads` writes nothing there and reads nothing else of schedule's. Do not add a fourth
without a planner decision.
**Coordinate labels are everyday words** (2026-09-15, F07, user ruling). `brand_coordinate` keys are
permanent (performance groups by them). Labels and situations are the words a shop owner reads —
互動過・沒買、已購・回購、太貴、怕買錯、免運、保證退換、買家視角 — and are never replaced by an abstract or
jargon term to make them "neutral" or "simpler" (an F07 draft did that on a main-conversation call and
was retired: 「不要把已經很簡單的詞彙再嘗試換種說法讓他更簡單」). Fitting an industry is the prompt's job:
on-image copy uses the words that industry's customers say (a coach's copy says 選錯, not 買錯), at
the level of the probe outputs the user accepted, and only classification jargon is kept off the
image (§5.8). The seeds live in a schedule migration plus the lazy seeder
`app/schedule/repository.py::_SEED_COORDINATES`／`_SEED_ANGLES`, kept in sync by hand. Meta has no
彈性 option any more: the `format`
value `flexible` is disabled for every brand and no longer seeded (「若排程仍然說這期要排彈性圖片，
則視為BUG」); a stored `flexible` reads as 單圖.

## 4. The loop, end to end

品牌建檔精靈 (`intake`) fills 品牌智庫 (`brand_intelligence`) — five steps since F05 (2026-09-14):
1 起始輸入 · 2 初步印象 · 3 賣什麼與數字 · 4 接工具 · 5 品牌知識, ending on the 可投放檢查表 (§8) →
the user describes one goal in one
sentence in 投放中心 (`ads`), which derives a draft Campaign carrying 為什麼做 (`goal_text`), 目標
(`objective`) and 成功條件 (`success_criterion`) plus the ids of the brand and product rows it used
→ one recommended 策略 (新客／再行銷／探索 split, budget scenarios) → 採用策略 writes the delivery
plan as real rows, Campaign → 通路 → 投放組 → 廣告, each deepest row carrying the seven coordinates
(audience · pain · angle · hook · proof · offer · format) → the plan dispatches one 任務包 into
素材工作檯 (`workbench`), one 素材組 per 廣告 (§5.4) → the workbench generates copy and image
prompts; the user 選定 one version per required 產物 and 核准整包 → 投放中心 reads readiness back
through the workbench's public entry, or the user ticks 「素材已就位」 → 發布 goes through a channel
adapter (`manual` 手動清單＋配對, `simulated` 演練用, auto-Meta reserved and 未接上) which binds the
rows to platform entities → daily outcome rows are attributed by the bound entity → 結案 judges the
outcome against the campaign's own 成功條件 → a learning row goes into `learning_ledger` → the next
campaign's strategy prompt reads it. Every change meant to reach a platform is an `ads_action` row
(what, before, after, who approved, sync state, reversible).

The dependency is one-way: `ads` and `schedule` import `workbench`'s public entry, never the
reverse. The workbench knows no tree — it stores `source_kind` + `source_ref` and compares them,
never interprets them, and the 來源 line it shows is a string the upstream handed it.

`schedule` (檔期規劃) is what 投放中心 replaces. Its four-stage page, its route and its sidebar entry
retire with the Ads V2 loop; its package stays because 經營概況 still reads its 判讀 surfaces
(creative-performance, diagnosis, coordinates, 舊廣告 history) and those are entangled with
`plan.py`／`state.py`. The package retires when those readers move — not before, and no new work
lands in it.

## 5. 素材工作檯 — settled decisions (2026-09-12 reset)

These are decided. A worker implements them; it does not re-open them. This revision replaces the
2026-09-10 list where they conflict — the IA (old 1–4), the copy contract (old 5) and the reserved
image seat (old 10) are rewritten below. §5.7–§5.10 (image prompts) and the image parts of §5.2,
§5.11–§5.13 were rewritten on 2026-09-15 by F07; the 2026-09-09 【】 8-module template they
replaced is in git. The visual source of truth is the four reference images listed
in `.work/features/F02.md`; where a prototype and an image differ, the image wins.

1. **任務包 → 素材組 → 產物 → 版本.** One 任務包 (pack) holds one or more 素材組 (sets); a set
   holds one 產物 (product) per required content type (文案／圖片／腳本, extensible); a product
   holds 版本 (versions). Display vocabulary only — code and DB names do not change
   (`workbench_brief` is a set, `workbench_output` is a version, `part` is a product type,
   `generation_round` is which round a version came from). The physical pack is one new table,
   `workbench_pack`; every brief carries `pack_id`. 產物類型 are generation parameters, never
   navigation: adding a type must not change the IA and must not add a page.
2. **Rounds are history, never navigation.** A product shows its versions newest round first;
   there is no round switcher and no 建議組合 pool. A version is one selectable artifact and one
   `workbench_output` row (`version_index` inside its round): a copy round writes 5 rows, an
   image-prompt round writes 10 rows (one per prompt; a 輪播 round writes 2 rows, one per concept of
   5 cards — §5.7), a script round writes one row per script.
3. **States are derived, never stored twice.** product: 未生成 (no version) ／待選定 (versions
   exist, fewer selected than required) ／已選定 (selected count ≥ required). set: 待開始 (no
   product has a version) ／等待決定 ／已完成 (every required product 已選定). pack: 待處理 (no
   set started) ／進行中 ／待核准 (every set 已完成, not yet approved) ／已完成 (approved). The
   only stored pack state is `approved_at` plus the completion ticks. A set-table cell reads
   `已選定／需要` (e.g. 2／5), reads 未生成 when no version exists, and reads 「—」 when the set
   does not require that type — one rule, no other spellings. That rule lives in the repository
   derivation and the cell text ships with the API (`cells[].text`); the browser renders the string
   it is given and never re-spells it. Same for the reserved-seat line (§5.11).
4. **The upstream handoff contract.** An upstream module hands over one pack in one call,
   `submit_pack(conn, org_id, brand_id, pack)`; the workbench never learns how the upstream works
   and still only stores and compares `source_ref`, never interprets it. `pack` carries: `source`
   (`source_kind` ＋ opaque `source_ref`), `name`, `context` (brand／product／campaign ids, plus
   the two optional display strings `origin_label` and `origin_href` — 2026-09-12: the upstream
   supplies the origin line and the in-app path back to itself, both stored verbatim in the
   existing `context_json` and returned verbatim by `pack_detail`／`set_detail`; the workbench
   renders them and never parses them, so removing the upstream just removes the line.
   `origin_href` is a router path *without* the `/app` basename, e.g.
   `/brands/<brand>/ads/campaigns/<id>?tab=assets`, and both values must be plain strings),
   `summary` (the 摘要 shown read-only on the pack page: 情境／角度／風格／目標受眾／重點訊息／
   參考連結), `sets` (each: name, opaque `source_ref`, coordinates, product_id,
   `required_outputs` = `{產物類型: 需要選定的版本數}`, and the per-type generation counts — since
   F07 a set's `style_key` and `request.image_prompt_count` are accepted and ignored — an image
   round is always §5.7's fixed shape and its looks come from §5.9 — and `request.variant_count`
   (integer 0–9) is how many ② 變體 the upstream plan wants for that set: the workbench renders that
   count and never computes it, missing or invalid reads 0), and
   `constraints` (e.g. `copy_length`, `promotion_note`). 完成條件 is not sent by the upstream: it
   is §5.5's fixed three-item checklist. 檔期規劃 dispatches one pack per expanded tree, one set
   per deepest node, with `required_outputs = {"copy": 1, "image_prompt": 1}` — one node is one
   ad, so it needs one selected copy and one selected image prompt. `submit_brief` stops being a
   public entry: a set only exists inside a pack.
   `required_outputs[type]` (how many versions must be 選定 before the product is 已完成) and the
   per-type generation count (how many versions one round writes) are **two different fields**;
   neither defaults to the other. 自由創作 fills both from its parse (§5.12): the count the user
   asked for, 1 per requested type when they said none.
   `free` is **not** a valid `required_outputs` key — it is a legacy part name
   (`repository._PART_NAMES`, `app/departments/workbench/free.md`) whose rows predate packs and are
   unreachable from the new screens; the pack's own origin is `source_kind = "free_job"`, so the
   two words never collide. New packs ask only for `copy`／`image_prompt`／`video_script`, and the
   API owns the one label map (文案／圖片／腳本).
5. **核准整包 never blocks anyone.** 完成條件 is three checks: 「完成所有素材組的必要文案與圖片」
   (computed from §5.3), 「確認內容符合品牌規範」 and 「可核准整包並回報上游」 (human ticks). The
   computed check may be overridden by a person; the override warns, and the warning is skippable.
   Approving sets the pack to 已完成 and locks its selections. The upstream reads the approval as
   state — `pack_for_source(conn, org_id, brand_id, source_kind, source_ref)` — never as a
   callback, so the dependency stays one-way. 檔期規劃 shows 「素材製作完，可以開始追蹤成效」 when
   the pack is approved, and may still run its own next step without it behind a small skippable
   warning 「還沒製作素材」.
6. **One copy round = 5 complete sets.** A 文案 round returns `sets`: exactly 5 objects of
   `{body, headline, description}` — 主文 in the band `copy_length` names (短 100–150 ／中 300–500
   ／長 800–1000 中文字元), 標題 ≤27 字, 說明 ≤30 字 — and each object is one selectable version.
   The 2026-09-09 copy decisions are void: no per-length body counts (5／3／2), no separate
   `headlines`／`descriptions` pools, no 建議組合. `copy_length` still comes from the node
   (`short` fallback) and still decides the band only.
   The 5 is written once, as `validate.COPY_SET_COUNT`; `validate.BODY_BANDS` carries the band
   `(lo, hi)` only and no count, and every other reader (the copy prompt's 長度 line, the fix
   round's shape hint, a round's version rows) reads the constant.
   `app/departments/workbench/copy.md` and
   `validate.check_copy` carry the shape; `schedule/state.py::_copy_summary` keeps its flat
   `bodies`／`headlines`／`descriptions` lists, now index-aligned from `sets`, so the 素材準備
   stage does not change.
7. **Image prompts: one round = one GPT paste of up to 10 images** (settled 2026-09-15, F07;
   re-planned the same day after probes v3/v4). The bar, in the user's words: 「若系統真的能看行業/風格
   等自適應產出這個Prompt，那真的十分完美。但前提是，系統真得能自己生，而不是靠使用者調適、選風格、下指令。」
   The image engine is GPT (「統一GPT。已經不會變動」). One round is **one model call that writes
   exactly 10 complete natural-language prompts** — GPT chat's per-message image cap. No mode, no
   style pick, no count input: `style_key` and `image_prompt_count` are accepted and ignored, the
   圖片 tab's 「再生成一輪（10 張）」 always asks for one more round, and a new round receives the
   previous round's titles. The shape follows the set's `format` coordinate (key or label, §5.8):
   - **單圖** (`single_image`; a stored `flexible` — Meta has no 彈性 option any more, §3 — reads as
     單圖; also a free pack or no format): 10 independent prompts, one version row each.
   - **輪播** (`carousel`): 2 concepts × 5 cards in the same paste; a concept shares one device,
     layout, look and person; card 1 carries the hook, card 5 the offer/CTA; one version row per
     concept. No variants.
   - **影片** (`video`): no image prompts (「影片廣告不用出圖」). 投放中心 asks a video ad for copy +
     video script (§6.3 item 21). A video set that runs 圖片 anyway gets the 單圖 shape.
   The ratio sentence comes from one table in `app/workbench/visual.py`, copied from
   `app/methodology/meta-format-specs.md`: 單圖 「4:5 直式單圖廣告，1080×1350」 · 輪播 「1:1 輪播卡片，
   1080×1080」.

   **One craft grammar for every industry and style** — `app/departments/workbench/image_prompt.md`,
   built from `.harness/scratch/probes/image-prompt-v4/task_v4.md` (the v2 file's aespa-surface
   examples do not come back): visual device → first sentence names ratio and use → a real layout
   and its typesetting language → at least two concrete details flavoured by the slot's look →
   the subject from the offering's reference → designed typography (every on-image string in 「」,
   tiers, share of frame, one or two colours, position) → a closing sentence of intent from the
   image task. Classification jargon (full audience labels, angle and hook names, task names) never
   goes on the image, and an everyday word is never rewritten into a more abstract one; on-image
   copy uses that industry's customers' own words. A prompt holds only picture and on-image text,
   never a worksheet instruction.

   **What each image must achieve is decided by the system, not by a button**
   (「我需要的是系統自己決定這張圖主訴是什麼自己去給圖，而不是做成按鈕」). The image-task table lives
   once, in `visual.py`. The set's audience key picks the row; `brand.conversion_goal` fills
   `{close}` (purchase 下單 · booking 預約 · lead 留下資料或報名 · awareness 進一步了解 · null 下單);
   only that row is sent:

   | audience | task key · label | 畫面怎麼做 | `subject_role` allowed |
   |---|---|---|---|
   | `cold_unaware` | `stop_relate` 讓人停下來、有共鳴 | 情境反差、比喻、生活觀察，不推銷 | absent, incidental |
   | `cold_problem_aware` | `believe_solution` 讓人相信有解法 | 使用情境、前後對照、把效果或服務現場畫出來（不畫效果數字） | clear, hero |
   | `warm_engaged` | `convert` 讓猶豫的人{close} | 主角主視覺、誘因與截止、打消疑慮 | clear, hero |
   | `customer_repeat` | `come_again` 讓用過的人再{close}一次 | 補齊、時間感、成套 | clear, hero |
   | `lapsed` | `win_back` 讓很久沒回來的人想起來 | 給回來的理由、有什麼不一樣了 | clear |

   `persuasion` allowed = `none` ∪ offer-derived ∪ proof-derived, except `stop_relate` → `none`
   only. Offer: `discount` → offer_headline, price_breakdown · `limited_time` → offer_headline,
   countdown · `bundle`／`trial_sample`／`guarantee`／`free_shipping` → offer_headline · `none` or a
   brand-made key → nothing. Proof: `customer_review` → testimonial, before_after ·
   `founder_voice` → testimonial · `expert_endorsement`／`lab_report`／`media_coverage` → credential
   · `sales_numbers` → data_proof · `none` or a brand-made key → nothing. A set with no audience
   (自由創作) — or with an audience value the table does not know (a brand-made key, or a label
   that matches no vocabulary row) — gets the whole table and returns
   one top-level `image_task`; every item is checked against that row, no visual learnings are read
   for it, and `round.audience_key` stores the value as given. The table changes only by a planner-reviewed code edit.

   **Visual fingerprint.** Every item returns `title` (≤10 characters, for people), `headline` (1–2
   strings, each ≤14 characters, each quoted verbatim in the prompt), `device` (`contrast` 對照／
   `metaphor` 誇張比喻／`borrowed_format` 借用格式／`frozen_moment` 定格瞬間／`demonstration` 直接示範／
   `testimony` 人物證言／`data_visual` 數據具象), `layout` (`candid_scene` 情境畫面／`portrait_focus`
   人物特寫／`subject_focus` 主角特寫／`split_compare` 分割對照／`flat_lay` 俯拍陳列／`magazine_cover`
   雜誌封面／`newspaper_editorial` 報紙編輯／`zine_collage` 拼貼／`infographic` 資訊圖表／
   `social_screenshot` 社群截圖／`screen_mockup` 畫面示意／`type_poster` 大字海報), `look` (the slot's,
   §5.9), `subject_role` (`absent` 不出現／`incidental` 順手帶到／`clear` 清楚出現／`hero` 主角),
   `persuasion` (`none` 無／`offer_headline` 優惠大字／`price_breakdown` 價格拆解／`countdown` 倒數／
   `testimonial` 顧客證言／`credential` 資格背書／`data_proof` 數據證明／`before_after` 前後對比) and
   `prompt`. The fingerprint is image_task + device + layout + look + subject_role + persuasion +
   slot (`exploit` 主力／`explore` 探索). It is stored, shown small, read by 結案 (§6.3), and never
   pasted to GPT.

   **The offering's reference, whatever is sold.** No new asset kinds (「KOL要賣自己，則自己=商品參考。
   講師要賣課，則課的截圖、畫面、教材等=商品參考，牙醫診所要賣預約，則牙醫診所本身照片、案例=商品」):
   `official_asset.asset_kind = 'product_photo'` is labelled 商品參考照 (key unchanged) and its
   `title` is the description. The 商品參考 line lists up to 3 descriptions of the set's knowledge
   product's 商品參考照, else the brand-level ones (`product_id IS NULL`); a missing title reads as
   the product name, else 參考照. The prompt then writes 「主角外型依附上的參考照：<說明>」. No
   reference → the line says so, and the prompt describes only visible traits, never an invented
   package, logo or face.

   **② 變體 — 單圖 only, count from the plan** (「變體只是作主體不變、圖片其他部分些許改變」;
   「依照排程決定，不一定每期每組每個素材都要10張變體」). Rendered at read time from the selected
   version, no model call. `N` = the set's `request.variant_count` (§5.4); missing, invalid or 0 →
   no ②. It keeps subject, person, ratio, text tiers and **every 「」 string of that item verbatim**,
   then lists the first N of nine fixed changes: 1 背景色調 · 2 取景遠近 · 3 文字位置 · 4 強調色 ·
   5 姿勢或表情 · 6 光線時段 · 7 景深 · 8 背景色調＋強調色 · 9 取景遠近＋文字位置. Variants are not
   learned (Meta groups near-identical creatives into one entity; small deltas are noise).
8. **The model writes the prompts; the program plans, appends and checks.** Prompt, in order:
   `image_prompt.md` · the 工作單 — 用途 and ratio; 商品參考; 品牌視覺規範 (the identity text, §5.9);
   每則風格分配, one line per slot 「第 N 則：<look key>（<look label>）」; audience／pain／angle／hook／
   proof／offer as `label（situation）`; 這張圖的任務 with the allowed subject_role and persuasion;
   這一輪手法清單順序, the seven devices shuffled by the program every round (probe v3: an unshuffled
   list put `contrast` first in 6 of 6 brands); 可用字句; 題材 from the pack summary's 情境／重點訊息;
   自由指示; the previous round's titles; 已知的視覺學習 (§5.9) — · the compiled brand context
   (`context_compiler.compile`, as-is). No `app/methodology/**` file is fed. **Coordinate lookup
   matches key or label**: 投放中心 hands keys, 檔期規劃 handed labels; before F07 every
   ads-dispatched prompt carried raw English keys and no ratio.
   The reply shape is requested by one `input_schema` tool in `gateway.TaskOptions.tools` (the
   `app/intake/ai.py` pattern) at thinking `medium`, with per-set enums (`look` = the plan's looks,
   `subject_role`／`persuasion` = the derived row). The schema is a request, not a guarantee —
   Anthropic tool use is not strict and the fix round sends no tools — so every schema rule is also
   a program check, run on the first reply and again on fix-round replacements.
   Program checks, no tokens, per item (輪播: item fields on the concept, text rules per card):
   - `look` equals its slot's look; `device`／`layout` in their lists; `subject_role` and
     `persuasion` inside the derived row;
   - the ratio token in the first sentence; no `【`; no English code
     (`(?<![A-Za-z])[a-z]+_[a-z_]+`);
   - `headline`: 1–2 strings, each ≤14 characters, each verbatim as a 「」 string in the prompt;
   - every 「」 string ≤22 characters and holds no nested 「; ≤6 「」 strings;
   - **no jargon leak**: no 「」 string contains the set's full audience label (the whole `A・B`
     string, never a half), its angle or hook name, 無證明 (the proof label when proof is `none`), or
     the task label. Everyday words are never flagged — pain and offer labels and halves of audience
     labels (太貴、怕買錯、回購、免運、陌生…) — and a term that occurs in the quotable text is exempt
     (滿799免運). Probe v4's 「還在怕選錯理財方法？」 is customer wording and passes.
   - every **fact number** inside a 「」 string occurs verbatim in the quotable text (the set's
     promotion note, the pack's 重點訊息, the compiled brand context); numbers outside 「」, clock
     times and dates are not checked; efficacy numbers never go on the image;
   - at most one negative phrase (the pattern never matches 要不要).
   Per round: more than 10 trimmed, fewer ❌; `headline[0]`'s first 3 characters at most twice;
   ≥5 layouts; ≥4 devices; the 2 輪播 concepts use different layouts. A failing item is re-asked
   once, as a whole item, in the existing fix round; a round-level failure shows ❌. The recorded
   probe outputs are the fixtures (`app/tests/fixtures/workbench/`); CI never calls a model.
   **Each version row stores its own item** — `body_json` = `{title, headline, prompt, text,
   fingerprint, cards, round, validation, warnings}`:
   - `text` = prompt + blank line + `品牌視覺規範：<identity text>` + newline + `風格規範：<look
     texture>`. A carousel concept's `text` is its 5 card texts, each with that tail, joined by a
     blank line;
   - `fingerprint` = `{image_task, device, layout, look, subject_role, persuasion, slot}`, each
     `{key, label}`;
   - `cards` = `null`, or for 輪播 5 × `{headline, prompt, text}`;
   - `round` = `{format, audience_key, image_task, identity_id, identity_text, plan: [{look, slot}],
     look_order: {exploit, explore}, recommended_index, recommended_slot, learning_ids}` — `plan`
     is in slot (shuffled) order; `look_order` keeps the 主力 looks in pool order and the 探索 looks in
     exploration order; `audience_key` is the resolved key, or the value as given when it has no task
     row.
   This is the contract `ads` reads through `adopted_output` (§6.3), using only `fingerprint` and
   `text` — no second export.
9. **The system derives the brand's look, a program allocates it, learnings steer, nothing is
   excluded by a guess.** Reverses the earlier "one look per brand, no style library" call: probe
   v3 proved looks make industries read differently, probe v4 proved the system can derive them
   from facts alone — and that a derived exclusion list is harmful.
   - **Look catalogue** (code, `app/workbench/looks.py`): twelve texture-only families, key →
     (label, texture), texture text from `.harness/scratch/probes/image-prompt-v4/run_v4.py::LOOKS`:
     `phone_raw` 手機原生抓拍 · `flash_snapshot` 直閃快照 · `documentary` 紀實自然光 ·
     `soft_lifestyle` 柔光生活 · `clean_bright` 明亮乾淨 · `studio_hero` 棚拍主視覺 · `dark_luxury`
     暗調精品 · `cinematic` 電影感 · `bold_graphic` 平面大字 · `ui_render` 介面畫面 · `illustration`
     插畫 · `editorial_portrait` 人物專訪. A texture names light, camera and rendering only — never
     who, which colours or which words.
   - **Brand visual identity** (derived and cached; nobody fills anything). One model call,
     task type `workbench_derive_identity` (`app/departments/workbench/visual_identity.md`, thinking
     `medium`), reads the compiled brand-level context and the catalogue and returns `identity`
     (80–150 characters: casting, palette, type personality, mood — no light, camera or bans),
     `fit_looks` (3–5 catalogue keys, ranked) and `excluded_looks` (0–3 × `{look, fact}`). The
     program keeps an exclusion only when its `fact` occurs verbatim in the context it sent: a look
     is excluded only when brand facts say so. (Probe v4 derived 手機原生抓拍 as never-use for Beast
     Gummy from 中高價＋力量感 — the style the user had proven.) The result is one
     `workbench_visual_identity` row per (brand, `brand.knowledge_version`); a fact edit bumps the
     version and the next round re-derives. Two cold rounds in parallel may both call; the first
     insert wins (`ON CONFLICT DO NOTHING`) and both read the stored row, so a pack never mixes
     identities.
   - **Brand-provided look.** Confirmed `visual_base` facts, values joined by a newline, become the
     look `brand_spec` 品牌規範 — ranked first, never excluded, texture = that text verbatim. No
     `visual_base` is a normal state, not a warning. More than 2 negative phrases in it → one
     warning in 品牌智庫 → 品牌事實, shipped as text by
     `GET /api/workbench/brands/{brand_id}/visual-spec` → `{warnings: [{text, href}]}`, which the
     browser calls (no Python import from legacy).
   - **Slot plan** (program, `looks.allocate`, no model). Per round of 10, 7 主力 slots cycle
     through the learned winners — `visual` rows at likely/validated, same audience, scope
     `look=<key>`, not expired, learned within 180 days — or, with none, through the fit ranking
     (`brand_spec` first). 3 探索 slots take the least-tried non-excluded looks outside the 主力
     pool, ordered by adopted items with that look (brand + audience), then items offered with that
     look, then fit rank, then catalogue order. Slots are shuffled for the prompt only (`round.look_order` keeps display order). 輪播: concept 1 = the first 主力
     look, concept 2 = the first 探索 look. The derived ranking is a starting guess; every
     non-excluded look stays reachable (「假設系統今天丟了5個風格，回收回來的前3名被放到品牌成功區，而
     系統之後只會走快樂路徑，不去找其他可能，永遠都在這三個風格繞」).
   - **Exploration reaches the test.** The user picks the hero, so an exploration look is tested
     only if picked. Each round recommends one item (「建議選這張」): a 探索 item when
     `explore_recommendations_so_far + 1 ≤ 0.3 × (brand_image_rounds_so_far + 1)`, else the first
     主力 item; the 探索 pick is the first item holding the least-tried 探索 look. About 3 in 10
     sets therefore recommend exploration whatever the pack size. The pack page warns when fewer
     than 30% of its sets' adopted image rows are 探索. Never a gate — §5.5's 核准整包 never blocks.
   - **Learnings read.** The worksheet carries ≤5 `learning_text` lines of this audience's
     non-expired `visual` rows at likely/validated, not 看不出, within 180 days, newest first, plus
     「另有 N 條沒列出」 (§1 rule 1). Look winners act through the slot plan, not through the model. No
     audience, or an audience value the table does not know → no learnings and the cold-start plan.
   - **Negatives are tiny.** A model-written prompt carries at most one negative sentence naming a
     specific visual thing (「除此之外不放其他文字」); never a legal line, a brand red line or a broad
     ban (「可以有negative prompt，但不能長篇大論或是為了法規限制、品牌紅線等限制創作力」). Red lines stay
     text-side: 絕對不能講 in the brand context and the fact-number check. The appended identity and
     look texture are exempt.
10. **The old style library retires; the look catalogue is code.** `app/workbench/image_styles.json`,
    `repository.STYLES`／`get_style`, `GET /api/workbench/styles`, 自由創作's style dropdown and
    style mapping, the 【】 template `app/methodology/image-prompt-template.md`,
    `prompts.render_hero_prompt`／`render_variant_prompt`／`render_exploration_prompt`, and the
    neutral default spec with its warning retire. `workbench_brief.style_key` stays (applied
    migration), unread. Nobody picks a look; the catalogue changes only by a planner-reviewed code
    edit.
11. **In-site image generation is a reserved port, not a feature.** `app/workbench/image_port.py`
    is one module with one stub: no provider, no key, no cost, no billing, no automation. It
    reports 未接上 and the API repeats that, so the 圖片 tab defaults to the prompt view.
    「顯示提示詞」 is a permanent toggle, not a fallback: the same version cards render as
    plain-text prompt cards with a copy button each plus 「複製全部」. Since F07 each image version
    ships `prompt_cards` = `[{label: "NN｜<title>", text: body.text}]` plus, on a **selected**
    單圖-shape version of a set whose `variant_count` > 0, `{label: "② 變體", text}` (§5.7); a
    `fingerprint_text` line (look · layout · device · persuasion labels); and `badges` (「主力」 or
    「探索」, then 「建議選這張」 on the round's recommended item);
    「複製全部」 copies `SetDetail.products.image_prompt.copy_all_text`, the latest round's paste
    block built once by the backend (a lead line, then `第 N 張` + each text). When a provider is
    connected the image view is the same component fed by the port. 席位保留 is never
    phrased as a refusal, and nothing in the product asks the user to run live ads to see a result.
12. **Four screens, one IA.** 素材工作檯 (入口: search ＋ status pills ＋ pack cards ＋ 最近使用 ＋
    快速開始) → 任務包 (pack-local left rail 總覽＋sets, 完成進度, 素材組進度 table, 摘要, 完成條件,
    核准整包) → 素材組 (studio: tabs = that set's required product types in dispatch order, version
    cards, 生成設定, 查看 Prompt, 完成此素材組) → 自由創作 (natural-language front door, two clicks:
    解析 then 建立). 自由創作 creates a pack named 自由工作 #n through the same contract an upstream
    uses, with 品牌 and 商品 both allowed to be 不指定. The 「AI 解析結果」 is **one real model
    call** on the first click (never while typing): `POST /api/workbench/brands/{b}/parse` →
    `free_parse.py` → `gateway.run_task` with an empty context and the department task file
    `app/departments/workbench/free_parse.md` (no `app/methodology/**` change). It returns the spec
    fields 專案主題／需要產出（含張數）／投放平台／尺寸／目標受眾／主要訴求 (風格設定 retired with the
    style library, §5.10 — the reply's `style_hint` key is kept and is always `null`), and the
    second click submits them as `required_outputs`. A failed, timed-out or unparseable call is
    never a dead end: it returns the caller's defaults with `parsed: false` and the user continues. Rails inside the workbench are pack-local or
    set-local; the OS sidebar is untouched. The old `.workspace-split` workbench page (開始生成／
    派工任務／工單 rail) is retired with this revision.
13. **The 生成設定 table is shipped as text, like `cells[].text`.** `SetDetail.generation_settings`
    is a backend-derived **ordered list of `{label, text}`** — since F07: 品牌／商品, 平台, 尺寸,
    品牌視覺, 這張圖的任務, 風格分配, 視覺學習, 主要訊息 — and the 圖片 tab's right column renders it verbatim, row by row, with no
    per-label branch in the browser (§5.3's rule: text the user reads is produced once, by the side
    that owns the rule). Every row is always present; a row with nothing to say reads 「—」, and the
    商品 half of row 1 reads 「不指定」 when the set has no `product_id`. Sources: brand and product
    names from `brand`／`product` via the set's `product_id`; 平台／尺寸 are the same values as
    `chips` (`chips.style` is `null` since F07 — nobody picks a style); 品牌視覺 is the latest image
    round's `round.identity_text`; 這張圖的任務 is that round's `image_task` label; 風格分配 reads
    「主力：<look labels>；探索：<look labels>」 from `round.look_order` (主力 in pool order, so a
    brand-provided look comes first; 探索 in exploration order); 視覺學習 is 「N 條」 from `round.learning_ids` or 「無」 (no round → 「—」 for these four); 主要訊息 is the pack summary's 重點訊息. It is
    a **read-only mirror of what produced the current prompts**, never an input form and never a
    second endpoint fetch. `SetDetail.products[<part>].generation_settings` is a different field
    with a different shape (the per-product run parameters `copy_length`／`count`) and keeps its
    meaning; the table is the top-level one.

## 6. 投放中心 (Ads V2) — settled decisions (2026-09-12)

These are decided. A worker implements them; it does not re-open them. The user's rulings are in
`.harness/scratch/ads-v2-summary.md` (23 items) and are quoted in `.work/features/F03.md`; the
visual reference for all three Ads V2 features is the prototype
`.harness/scratch/prototype/ads-v2/index.html`.

1. **New module, not a reshape.** The thing being replaced is the model itself — today's plan and
   tree live as JSON inside `llm_task` rows and 93 tests in `test_schedule.py` are coupled to those
   shapes. `ads` therefore starts clean with real rows; `schedule` is not patched. What is reused is
   reached through legacy facades (`app/meta/repository.py` for exact-name binding and daily spend,
   `app/brand_intelligence/repository.py` for facts, product economics and learnings), not by
   importing `app.schedule`.
2. **Four levels, three tables.** Campaign → 通路 → 投放組 → 廣告 is the model; the 通路 level is a
   column on the 投放組, not a table — it has no state of its own. Nothing is platform-specific:
   a channel is a key with a label (Meta, Google Ads, TikTok, 蝦皮, momo…); only Meta is connected,
   the rest read 未接上, and no platform name is baked into a column name or a CHECK.
3. **Budget lives in 投放中心.** Money is allocated at the 投放組 level only; the 廣告 level shows
   observed spend share. Breakeven CPA = 售價 − 單位成本 − 運費 (`product_economics`), target CPA =
   breakeven × 0.7. No spend history → 日預算 = target CPA × 每天想要的購買數 (最低 2 ／推薦 5 ／
   積極 10), labelled 冷啟動估算; with history → 近 30 天 CPA 中位數, scenarios ×0.6 ／×1 ／×1.6.
   Every number is editable; the AI only prefills. The 設定 page's 檔期日預算 card goes away.
   After 採用策略 the **group daily budgets are the single source of truth**; the campaign row keeps
   the adopted scenario amount as `budget_planned` for the record, and the total on screen is
   `sum(daily) × days`, derived in one place.
4. **Channel adapters, one interface.** `manual` (checklist with copy buttons → the user builds on
   the platform → 配對 by exact name, the existing algorithm) and `simulated` (publishing binds fake
   entities **and** writes the daily outcome rows for the days already elapsed, so a walkthrough
   reaches 成效 in the browser with no command line) ship now; the auto-Meta adapter is a reserved
   third that reports 未接上. Binding columns live on all three levels (campaign, group, ad) because
   the platform's name lookups are hierarchical, and the campaign node is bound first. Nothing in
   the product ever asks the user to run live ads to see a result.
5. **Every platform-bound change is an `ads_action` row** — what changed, before, after, who
   approved, sync state (`pending_manual` / `confirmed_manual` / `auto_synced`), platform ref,
   reversible by a reverse action. It replaces `campaign_period_budget_version`. Budget raises still
   pass through `app/core/approval.py` (`max_daily_amount` stays the brake).
6. **Outcome attribution is by bound entity.** One `ads_outcome_daily` row per (entity, day), fed
   either by the Meta ingest (read `meta_entity_spend` through `app.meta.repository`) or by the
   simulated adapter. 重疊分帳 (ADR 0053's day-splitting between overlapping 檔期) does not come
   along; a campaign owns the entities bound to it.
7. **Learning is inference, never a brand fact.** Written at 結案 (and at 採用建議, from F04) into
   `learning_ledger` through the brand_intelligence facade; level by fixed rule — 1 campaign =
   已觀察, ≥2 same-direction = 可能成立, 已驗證 needs a same-period comparison or ≥3 campaigns (a
   human tick also counts); `needs_revalidation` when older than 180 days or the source offering's
   price changed. Adopting a suggestion never writes a `rule` row — only the user's own typed
   feedback does.
8. **Confidence is a sample bucket (低／中／高), never a percentage**, and no model reads raw ad
   history (ADR 0067): evidence tables are program-computed.

### 6.1 Second round — 基座 (settled 2026-09-13, F04)

The visual source of truth for 投放中心 is now `docs/design/ads/01-home.png` … `10-strategy-advanced.png`
(01 首頁, 02 所有 Campaign, 03 建立投放計畫, 04 理解如下, 05 推薦策略, 06 Campaign 工作區總覽,
07 素材交接 = F05, 08 發布前檢查 = the 閉環 feature — F06 borrows only its warning band, §6.2 —
10 進階設定). `09-performance-overview-not-built.png` is
recorded as **not built**: suggestions live inside 投放中心, not behind a new nav item. Where an
image and the 09-12 prototype differ, the image wins; the prototype is history.

9. **One page, two depths.** Every screen shows the simple face by default — a recommendation, one
   primary button, an honest sentence — and the expert's knobs live in a collapsible *inside that
   same page*, closed until opened. Never a mode switch, never a second page, never a second data
   model (rows are the truth; simple and advanced are two projections of them), and never a layout
   that reads like another Meta/Google console.
10. **The judgment sentences are the program's, not the model's.** 一句整體判斷 (home), the
    per-campaign 一句判斷 (list, 總覽) and every 最近做了什麼 line are composed in
    `app/ads/judgment.py` from status, dates, budget progress and `ads_action` rows, shipped as
    text with the payload, and rendered verbatim by the browser (the §5.3 rule: text the user
    reads is produced once, by the side that owns the rule). No LLM call is made to write them,
    and a correlation is still never reported as a cause (§0).
11. **Two model calls per new Campaign, no third.** 建立投放計畫 parses the sentence
    (`ads_brief_parse`) into 商品／目標/平台／預算／時間／受眾方向 with a 數字優先 rule — a number
    in the sentence becomes that field, `null` only when the sentence has none — and 理解如下 is a
    confirm screen over those six editable field cards, each labelled 你說的 or 系統帶入
    (`context_json.field_sources`). Only 「產生策略建議」 spends the second call (`ads_strategy`).
    Editing a card is a `PATCH`, never a re-parse. Dates are optional input: when the sentence has
    none the system fills today…+30 天 and labels them 系統帶入. Parsed 預算上限 and 平台 live in
    the existing `constraints_json`; no column is added for them.
12. **「這輪想學到什麼」 ships with the strategy.** `strategy.md` returns `learning_goals[]`
    (≤3 sentences) next to `why[]` and `unknowns[]`, stored inside `budget_basis_json.strategy`,
    rendered as the strategy page's third column so F05's 結案 can answer it. 預估購買 =
    採用總額 ÷ 目標 CPA, captioned 推估（CPA 不變的算術）, computed in code, never 預估觸及.
13. **Reserved seats are named, not built.** 「MarketingOS 為你執行中」 (home + 總覽) and
    「進階設定」 (策略頁: 平台結構／受眾／版位／出價／優化事件／歸因／追蹤／UTM) are grey
    placeholder cards reading 「自動執行接上後開放」／「自動發布接上後開放」 — never phrased as a
    refusal. Their future readers are recorded here and created nowhere else: the execution feed
    will read `ads_action` rows with `sync_state = 'auto_synced'`, and the advanced panel will
    write `platform_settings_json` on `ads_delivery_group` — **that column does not exist and is
    not created until an adapter writes it.** 「需要你決定」 has no producer in F04 (suggestions are
    F05) and renders its honest empty 「目前沒有需要你決定的事」.
14. **The strategy page's buttons do what they say.** 照這個方式進行 = adopt the recommended
    scenario if none is chosen, adopt the strategy, land on 投放結構 — one click from a newcomer's
    point of view. 調整建議 = edit the allocation percentages inline before adopting (sum 100, the
    program re-splits the money). 查看完整判斷 = the existing 查看策略依據 panel. The permanently
    disabled 採用 button is gone.

### 6.2 Third round — 工作區的快樂路徑 (settled 2026-09-14, F06)

Measured on a live campaign: after 策略 → 投放結構 the user did not know what to do next. The
next-step rule had one producer, rendered on 總覽 only, and its 「素材已就位」 target pointed at a
tab with no publish affordance; 投放結構 and 素材 ended with no next step, and the header's
發布 Campaign only printed 自動發布未接上 while the working paths hid in a ⋯ menu.

15. **One next-step rule, every tab.** `frontend/src/components/ads/nextStep.tsx::nextStep(campaign)`
    is the only producer of 「下一步」 in the Campaign workspace: 總覽's 下一步 card and 狀態時間軸,
    and the full-width primary button at the end of 策略／投放結構／素材／成效 all read it. Order:
    closed／live／ended → 成效; no strategy or no groups → 策略; groups but not a single ad →
    投放結構 (新增廣告); every ad ready → 發布; no pack yet → 投放結構 (開始做素材); pack dispatched
    but not every ad ready → 素材. A tab whose own step is the answer shows that step's in-place
    action instead, chosen by the step's `id` (策略 照這個方式進行, 投放結構 新增廣告／開始做素材,
    素材 前往素材工作檯). **It is navigation, not a judgment sentence** — decision 10 is unchanged:
    its output is a tab and a button label, its inputs are fields the server already ships
    (`budget_basis_json.strategy`, `groups`, `status`, `asset_readiness`), the tabs exist only in
    the browser, and its sentences name the step without judging the campaign or re-spelling a
    server rule (總覽's old next-step line 「投放已結束，7 天後自動結案…」 is replaced by the rule's
    sentence; 成效's own 結案 card is not a next step and keeps its copy). Whether a pack exists is
    a server fact read **from the pack itself** — `asset_readiness.pack_id` via `assets.pack_id()`,
    the same `pack_for_source` lookup `dispatch_pack` guards with — never derived from readiness
    rows (an ad added after the handoff has no set, so every row can be empty while the pack
    exists), never a second request, never a parsed 400.
16. **投放結構 stays on the newcomer path, in the strategy page's shape** (`05-strategy.png`). The
    default face is a plain summary of what the system built (投放組, 廣告, 每日合計, 投放期間),
    「不用改也可以」 and one full-width 「開始做素材 →」 that dispatches the pack (the existing
    `POST .../campaigns/{id}/pack`) and lands on 素材 — offered only while no pack exists, so the
    handoff never repeats; with no ad at all the button is 「新增廣告 →」 and opens the existing add
    dialog. An ad added after the handoff is not in the pack (adding sets to an existing pack is not
    built): 素材 says so on its row and the 素材已就位 tick makes it ready. The tree, the group／ad panels, add／delete
    and the budget comparison live in 「調整結構（進階）」, closed by default (decision 9). Inside
    it a blank group date reads 「跟活動同期間」 (blank already means the campaign's dates —
    `repository._budget_total`, `adapters/manual.py::_group_field`), 「儲存變更」 appears only
    while a panel has unsaved edits, and binding badges appear only once the campaign is published.
    Dispatching from 素材 is gone: the handoff has one button, on 投放結構; 素材 keeps its
    「查看素材任務包」 link.
17. **Readiness warns, never blocks** (F03's rule kept). The publish screen, for every adapter
    except 模擬發布, shows 「還有 N 則廣告沒有素材」 in the red band of `08-preflight.png` with
    「回到素材」; nothing is disabled. 模擬發布 is a drill and carries no warning. The band is
    composed inline on the publish screen; it becomes a shared pattern only when a second screen
    needs it.
18. **The auto-publish screen is not a dead sentence.** While auto publish is not connected it
    prints the adapter's own message verbatim and offers 手動發布 and 模擬發布（演練） as buttons
    (decision 1: "not connected", never a refusal). The header's ⋯ menu is gone — the publish
    screen is the one place the path is chosen.

### 6.3 Fourth round — image work and visual learning (settled 2026-09-15, F07)

Prompts do not rewrite themselves. What evolves is (a) the visual learnings the image-prompt call
reads — the slot plan and ≤5 lines (§5.9) — and (b) the image-task table, only by a
planner-reviewed edit once a learning is 已驗證. The traces that cannot be retrofitted ship with
F07: the fingerprint on every item (§5.7) and which item became the hero (the 選定 on its row).

19. **Visual learning is written at 結案, by fingerprint, inside one audience.** After the campaign
    learning, `closeout.close` groups the campaign's ads by `audience_key`. Only ads whose image set
    has an adopted row count — `workbench.adopted_output(...)["is_adopted"]` must be true, because
    that entry falls back to the latest round when nothing is selected, and a fallback is not a
    hero. Within one audience, for each of `look`, `device`, `layout`, `subject_role` and
    `persuasion` that has ≥2 distinct values, the ads are grouped by value. Each group's ad-level
    outcome rows go through `outcome._bucket`, the campaign's own success metric is applied (ROAS =
    the conservative value, §6 item 8), and `outcome.sample_bucket(purchases, days)` labels the
    sample. A group at 低 or with the metric untracked is listed, not compared.
    - Two or more comparable groups with a strict best → one row, scope
      `visual；audience=<audience_key>；<dimension>=<value_key>`.
    - Anything else → one row, scope `visual；audience=<audience_key>；<dimension>=看不出`, at
      `observed`.
    Confidence reuses §6 item 7's count: prior non-expired `visual` rows with the identical scope
    from other campaigns, plus this one — 1 `observed`, 2 `likely`, ≥3 `validated`; 看不出 is always
    `observed`. `needs_revalidation` follows the campaign learning's rule; readers also ignore rows
    learned more than 180 days ago.
    **A winner that later loses is downgraded.** When this campaign has a strict best B in one
    audience and dimension, every other compared value A that has non-expired prior rows with scope
    `…；<dimension>=A` loses its newest such row (`bi_repo.expire_learning`). Confidence is the
    stored value of the newest surviving row, so each contradicting campaign lowers A one step
    (validated → likely → observed, and below likely the image prompt stops reading it).
    The sentence is built by the program from labels — audience labels from
    `ads.repository.coordinate_vocabulary`, value labels from the fingerprint's own `{key, label}`.
    It names the numbers, counts and sample buckets, and says the result is a correlation, not a
    cause (§0). No model call. It is written through `record_learning(..., source_track="visual")`.
20. **Why inside one audience.** The image task is derived from the audience (§5.7). Comparing
    fingerprints across audiences would learn audience effects as look or layout effects, so the
    audience is the stratum and never a compared dimension.
    Not learned:
    - variants (one entity to Meta; small deltas are noise);
    - 自由創作 organic posts — no post-insights source exists, and PRODUCT.md forbids fabricated
      sources. Both are backlog entries.
    Early samples are mostly 低, so early rows are mostly 看不出. That is honest and is what the
    image prompt then does not read; the slot plan keeps exploring regardless.
21. **The dispatch decides the image work, the workbench renders it.** `app/ads/assets.py::_ad_set`
    sends, per ad, by `format_key`:
    - `single_image` (and a stored `flexible`): `required_outputs = {copy: 1, image_prompt: 1}` and
      `request.variant_count` = run days ≤7 → 3, 8–21 → 6, >21 → 9; +3 when the group's `role` is
      `retarget`; capped at 9. Run days come from the group's dates, else the campaign's
      (`plan._days`); no dates → 6.
    - `carousel`: `{copy: 1, image_prompt: 1}`, `variant_count` 0.
    - `video`: `{copy: 1, video_script: 1}` with `request.video_script_count` 3
      (`meta-format-specs.md` §3: 3 scripts per angle), no `image_prompt`. Script generation itself
      is unchanged (「影片廣告要產投放時需要的影片本體的腳本與資訊欄位的主要文案、說明、標題欄位(Meta來說)，
      和圖片廣告是一樣的邏輯」).
    No `style_key`, no `image_prompt_count`. The manual checklist's 圖片提示詞 is the adopted row's
    `body_json.text`, only when `is_adopted`.

## 7. Verification

`verify.typecheck` runs ruff, pyright, the frontend type build, dependency-cruiser and the frontend
800-line file cap (`src/architectureBoundaries.test.ts`, ~2 s). The cap sits here, not in an issue's
own verify, because harness runs `verify.typecheck` at every issue finish while the whole `npm test`
runs only at feature integration (2026-09-14: F06-I02 grew `DeliveryTab.tsx` to 931 lines unseen until
integrate). Structural gates belong in `verify.typecheck`; behaviour tests stay targeted per issue. `verify.test`
is the full pytest suite with `-n 8 --dist loadfile` (`-n auto` exhausts Postgres connections, see
`CONTEXT.md`); `verify.smoke` is the Playwright end-to-end suite, which starts its own backend on
8720 — the reason acceptance must never be judged on the long-running 8710 process. A schema or
migration change additionally runs the tenant-isolation and boundary trio named in `CLAUDE.md`.
Real-browser acceptance happens on a restarted backend at 1024 and 1920 in empty, normal and heavy
states (`docs/design-system.md` §9/§10).

**e2e never calls a model and never hands a job to another process** (2026-09-14, F06).
`verify.smoke`'s backend runs with `BRAND_OS_LLM_PROVIDER=scripted` and `BRAND_OS_JOB_QUEUE=memory`, both set
in `frontend/playwright.config.ts`'s `webServer.env`. Both values are refused outside `BRAND_OS_ENV=local`.
- **`scripted`** makes `app/llm/providers.select_provider` answer from `SCRIPTED_REPLIES`, keyed by
  `task_type`.
  - A task type with no reply raises `LookupError` at selection, before `gateway.run_task` writes its `running`
    row. The gateway does not catch it.
  - So a request-path model call without a reply fails loudly, instead of sliding into a caller's parse-failed
    fallback.
- **`memory`** makes `app/background.enqueue()` write no queue at all. It only remembers the queueing lock in
  process memory, and `is_active()` reads that set.
  - The dev database's `public__queue` is shared with the long-running `python -m app.worker`.
  - Without this, that worker would run e2e jobs with its own provider and its own, possibly old, code.
  - Limit: no background job runs under e2e. A spec step that needs a job's result is not possible under this
    seam; it would time out with no `LookupError`. Such a step needs a planner decision first.
- **The replies live in legacy `app/llm/providers.py`** because the switch point does. This is the one sanctioned
  growth of legacy for test infrastructure: a local-only verification seam, not product capability, cut as a
  `legacy_migration: true` issue under planner review (F06-I05). The seam grew four legacy files and no others:
  `app/llm/providers.py` (the replies), `app/llm/gateway.py` (selection before the `running` row),
  `app/background/__init__.py` (the `memory` queue) and `app/core/config.py` (the local-only refusal).
  - Each reply's shape is pinned by a test in the module that owns the shape (`test_ads_brief.py`,
    `test_ads_strategy.py`, `test_workbench_free_parse.py`).
  - An e2e path that needs a new model call adds its reply there, under that issue's plan.
- **Consequence:** a red e2e is a real failure. An upstream model outage can no longer turn it red.

A UI issue additionally carries a **visual gate** (2026-09-13, F04): it names its reference image
under `docs/design/ads/`, the worker invokes `impeccable:impeccable` with that image before writing
the screen, and the issue is not done until a screenshot of the built screen has been compared
against that image side by side. The shared patterns those screens compose — 頁首判斷帶, 決定卡,
Campaign 卡, 數字條, 時間軸, 佔位卡, 步驟指示, 摘要欄位卡 — are specified in
`docs/design-system.md` §5.3 and implemented once in `frontend/src/components/ads/patterns/`;
a page issue composes them and does not re-invent one.

**How the visual gate is performed** (2026-09-14, after F06-I01 blocked on a helper script written into
`frontend/`). The worker captures; the planner compares. Nobody writes a helper file, anywhere.
- **Tool:** the global `playwright-cli` (needs no repo file and no `node_modules`). Its session folder
  `.playwright-cli/` is gitignored, so the scope diff never sees it.
- **Code under test:** the worktree's own code, served on the port the issue names (8731 and up; never 8710,
  never e2e's 8720). From the worktree run `cd frontend && npm run build`. Then, from the worktree root and
  in the background, run `BRAND_OS_LLM_PROVIDER=scripted BRAND_OS_JOB_QUEUE=memory uv run python -m uvicorn app.main:app --port <port>`.
- **Sign-in:** the `/app/login` form with the seed account `123@example.com` / `123456` (brand `brd_bughunt`).
  No forged token, no saved storage-state file.
- **Commands:**
  1. `mkdir -p C:/Users/User/AppData/Local/Temp/harness-shots/<issue>`
  2. `playwright-cli -s=<issue> open http://localhost:<port>/app/login`
  3. `playwright-cli -s=<issue> resize <w> <h>` (1024 800, then 1920 1080)
  4. `snapshot`, then `fill` Email and 密碼, then `click` the 登入 button
  5. `goto` the screen
  6. `screenshot --full-page --filename C:/Users/User/AppData/Local/Temp/harness-shots/<issue>/<name>-<w>.png`
  7. `close`
  8. Stop the server: `netstat -ano | grep ":<port> .*LISTENING"`, then `taskkill //PID <pid> //F`.
- **Output:** images live outside the repo, in that `harness-shots/<issue>/` folder. The finish note lists each
  image's absolute path, the worktree path and the port.
- **Screen state:** reach whatever state the screen needs through that server's UI; dev data is test data.
- **If capture fails:** do not work around it with a file. Say so in the finish note.
- **Comparison:** happens at `review: planner`. The planner reads each PNG beside its reference image and takes
  any missing shot the same way. Approval is the gate.

## 8. 品牌地基與可投放檢查表 — settled decisions (2026-09-14, F05)

These are decided. A worker implements them; it does not re-open them.

1. **One product, many 賣法; knowledge on the parent, money on the child.** `product` gains a
   nullable self-referencing `parent_id` (same org/brand, `ON DELETE CASCADE`, `CHECK (parent_id IS
   NULL OR parent_id <> id)`). **One level only** — a child may not have children, enforced in
   `brand_intelligence.repository.create_product`, because a CHECK cannot see another row. A child is
   a 賣法 (單瓶／3 入組／5 入組／隨身包) and its `name` stores the full display string
   「<母產品名> · <賣法>」, so every screen that prints a product name keeps working untouched.
   **Knowledge lives on the parent** (`product_fact`, claims, 商品照, coordinates); **money lives on
   the child** (`product_economics`, one row per 賣法). One reader resolves it —
   `brand_intelligence.repository.knowledge_product_id(conn, brand_id, product_id)` =
   `COALESCE(parent_id, id)` — and the three existing readers call it: `app/llm/context_compiler.py`
   (facts into every prompt), `app/workbench/jobs.py::_product_line` (the 商品照 lookup) and
   `app/ads/strategy.py::_products_section` (one fact block per 母產品, one line per 賣法, capped
   like every other prompt list, §1). Budget uses the campaign's chosen `product_id`; when that id is
   a parent, `budget._economics_for` falls to its **first child** (the wizard writes「單品」first).
   結案與學習 aggregate at the parent — F05 records the rule and builds no screen for it.
   **Not built:** a variant table, a pack-size column, bundle auto-arithmetic (a 3 入組's cost is a
   number the user types, never one the program multiplies).
2. **One conversion value, one formula.** 「一次轉換值多少錢」 = `(售價 − 單位變動成本 − 運費) ×
   成交率`, 成交率 being the new nullable `product_economics.close_rate` (NULL = 一次轉換就是一次
   成交, so a goods row computes exactly as it did before F05). `app/ads/budget.py::breakeven_cpa`
   is the one place that multiplication happens. 服務 declares 成交率 and 每單毛利; 運費 is 0, never
   NULL, because「沒有運費」and「不知道運費」are different facts. There is **no brand-level 業務類型
   column**: 商品／服務／兩者 and 廣告帶來的是什麼（直接下單／先詢問再成交／留資料）are controls on
   the wizard's step 3 — the first decides which block is shown, the second decides whether 成交率 is
   asked at all — and the durable answer is the offering rows themselves (`brand.industry` was
   dropped in 2026-08-29 for having no reader; this would have had one).
3. **An assumed number stays labelled for the rest of its life.** When the user says 不知道 the
   program fills a benchmark and records which fields were filled that way in the new nullable
   `product_economics.assumptions_json` (`["cost","shipping","close_rate"]`; same column on
   `product_economics_version`); editing the field clears its flag. The benchmarks live in **code
   with their sources** — `app/brand_intelligence/benchmarks.py`, one module-level table, each entry
   carrying label, value, source name, source URL and fetch date (evidence:
   `.harness/scratch/research-onboarding.md`). **No model ever supplies one of these numbers**, and
   the screen always prints where it came from (「美國 2025 基準，起點用 · 來源：…」). There is no
   Taiwan primary source for any of them — that is said on screen, not hidden. They are replaced by
   the brand's own closed-campaign numbers (the 閉環 feature), not by a better blog post. `cpa_roas_basis` was
   **not** reused for this: that column was dropped in `20260903000004`, and its name says something
   else.
4. **成效來源 is `brand.conversion_goal`**, which already exists (`purchase`／`lead`／`booking`／
   `awareness`) and already maps to platform events in one place
   (`app.meta.repository._CONVERSION_ACTION_PRIORITY`). The wizard's step 4 sets it; nothing else
   asks. `ads_outcome_daily.purchases` therefore means 「這個品牌的成效目標被達成幾次」 — the column
   keeps its name (its migration is applied), and every screen label for it comes from the brand's
   conversion goal, so a 名單 brand reads 每筆名單成本 where a 購買 brand reads 每次購買成本. A new
   `success_metric` value for leads would have been the same arithmetic under a second name, so
   there is none: the metric stays `cpa`／`roas`／`purchases` and only its **label** varies (§0
   「不預設」).
5. **可投放檢查表 belongs to `ads`, and it has three colours.** `app/ads/readiness.py`, exported as
   `app.ads.launch_readiness(conn, org_id, brand_id)` from the module's public entry and served at
   `GET /api/ads/brands/{brand_id}/readiness`. `ads` is the owner because it is the module that
   answers「能不能投」 and it already reads all three inputs through declared facades
   (`brand_intelligence` for offerings and economics, `channels.py` for the bound ad account,
   `brand` for the conversion goal); the reverse — the wizard owning it — would need `ads` to import
   `app.intake`, which LAYER_ORDER forbids. Three rows (至少一項要賣的東西且填了數字 · 廣告目標已設定
   · 廣告帳戶已接上並指定給這個品牌), each **綠／黃／紅**: 黃 means the row works but stands on an
   assumed number or on data still arriving — at least one economics row carries `assumptions_json`,
   or the ad account is bound but the 37-month backfill has not finished. Every row prints **why** it
   is the colour it is, and a 黃 row carries a「去改」deep link into the wizard step that owns it. The
   primary button follows the worst colour: 紅「先補齊地基」／黃「進入投放中心（有假設值）」／
   綠「進入投放中心」, and「還是要先建立」appears only on 紅. Every line's text and its link ship from
   the backend and are rendered verbatim (§5.3). Two consumers: the wizard's completion screen and
   投放中心's 建立 Campaign entry. **It never refuses.** No「N 條 confirmed 事實」threshold: facts
   affect copy quality, not whether money can be spent. Whatever is assumed here is named again in the
   strategy's basis text ——「用的是假設成交率 20%」—— so a number never loses its label downstream.
6. **The wizard writes the facts it collects.** Measured 2026-09-14 on the drill data: the only
   caller of `repository.create_items` is `state.py:284`, fed by the paste step — so **the external
   AI paste is the single writer of `brand_fact`／`product_fact`**, and a user who stops before it
   ends with zero knowledge however many questions they answered (常春健康: paste done → 11 items,
   4 brand_fact + 3 product_fact confirmed, 0 `product_economics`; MOVE Daily: stopped at step 3,
   0 items, 0 facts, economics only because the user found the product page herself). F05 closes
   this by having the system run the research itself and feed the reply to **the same parser**
   (`state.apply_paste` → `paste_parse` → `create_items`), with the external-AI handoff kept as a
   collapsed advanced option. No second parser, no new fact writer. The in-system run gets its
   **own** prompt, assembled in `app/intake/research.py` the way `ai.run_scan` already does:
   `script.build_prompt` is written for a web-enabled external AI (it demands sourced URLs and
   verbatim customer quotes) and this path has **no web search** — `gateway.TaskOptions.tools`
   defaults to `None` and no production call site enables `providers.WEB_SEARCH_TOOL` (ADR 0048
   deferred it; it bills per search). The program fetches the user's own URLs through
   `app.core.net.fetch_url` and hands the text over; the prompt forbids inventing a source, and
   顧客原話 stays an honest 累積中 unless the user takes the advanced paste path. Opening web search
   is a user ruling, not a worker's.
7. **沒有迴圈歷史時，預算讀廣告帳戶的歷史.** `ads.repository.budget_history` returns
   `{"source": "ads_loop"|"meta_account", ...}`: when no closed ads-loop campaign has settled spend,
   it falls back to the brand's own connected ad account (近 30 天每日花費 + CPA, read through
   `channels.py` → `app.meta.repository.spend_summary` with the brand's `conversion_goal`). The
   caption names which one it used. Nothing tracked → honest cold start, unchanged. **No model reads
   ad history** (ADR 0067): every number here is program-computed and the model only phrases it.
