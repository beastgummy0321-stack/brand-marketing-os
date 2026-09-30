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
        "app/tests/fixtures/ads_external/**",
        "frontend/src/components/ads/**",
        "frontend/src/lib/adsApi.ts",
        "frontend/src/lib/adsLaunchApi.ts",
        "frontend/src/lib/adsExternalApi.ts",
        "frontend/src/lib/adsUserAssetsApi.ts",
        "frontend/src/lib/adsChangeApi.ts",
        "frontend/src/lib/adsReviewApi.ts",
        "frontend/src/lib/adsRuntimeApi.ts",
        "frontend/src/lib/adsMaterialApi.ts",
        "frontend/src/lib/adsHandoffApi.ts",
        "frontend/src/lib/adsPublishTypes.ts",
        "frontend/src/lib/adsTriageApi.ts",
        "frontend/src/lib/adsHomeApi.ts",
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
        "ads",
        "schedule",
        "workbench"
      ],
      "owns": [
        "app/intake/**",
        "app/tests/test_intake*.py",
        "frontend/src/components/intake/**",
        "frontend/src/lib/intakeApi.ts",
        "frontend/src/lib/intakeT2Api.ts",
        "frontend/src/lib/intakeOnboardingApi.ts",
        "frontend/src/lib/intakeProductApi.ts",
        "supabase/migrations/*_intake_*.sql"
      ]
    }
  },
  "resources": {
    "ads_review_monitor": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_review_monitor"
    },
    "ads_material_task": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_material_task"
    },
    "ads_material_revision": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_material_revision"
    },
    "ads_material_operation": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_material_operation"
    },
    "ads_handoff_item": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_handoff_item"
    },
    "ads_review_round": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_review_round"
    },
    "ads_change_set": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_change_set"
    },
    "ads_month_budget": {
      "owner": "ads", "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"], "symbol": "ads_month_budget"
    },
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
    "ads_external_entity": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_external_entity"
    },
    "ads_external_daily": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_external_daily"
    },
    "ads_external_sync_job": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_external_sync_job"
    },
    "ads_external_listing": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_external_listing"
    },
    "ads_asset_suggestion_batch": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_asset_suggestion_batch"
    },
    "ads_asset_suggestion_reservation": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_asset_suggestion_reservation"
    },
    "ads_asset_binding": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_asset_binding"
    },
    "ads_asset_observation_claim": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_asset_observation_claim"
    },
    "ads_asset_upload_batch": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_asset_upload_batch"
    },
    "ads_user_asset": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_user_asset"
    },
    "ads_asset_upload": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_asset_upload"
    },
    "ads_asset_placement": {
      "owner": "ads",
      "kind": "sql-table",
      "definition": ["supabase/migrations/*_ads_*.sql"],
      "symbol": "ads_asset_placement"
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
    "test": "uv run python -m pytest app/tests -q -n 4 --dist loadfile && cd frontend && npm test",
    "typecheck": "uv run ruff check app && uv run python -m pyright && cd frontend && npm run lint && npm run depcruise && npx vitest run src/architectureBoundaries.test.ts",
    "build": "cd frontend && npm run build",
    "build_outputs": ["frontend/dist"],
    "smoke": "cd frontend && npm run e2e",
    "smoke_after_build": "cd frontend && npx playwright test",
    "typecheck_before_test": "uv run ruff check app && uv run python -m pyright && cd frontend && npm run lint && npm run depcruise",
    "issue_profiles": [
      {
        "only": [
          "app/tests/**",
          "app/methodology/**",
          "app/departments/**"
        ],
        "typecheck": "uv run ruff check app && uv run python -m pyright",
        "build": null
      }
    ],
    "env_files": [".env", "frontend/.env"],
    "env_exclude": ["BRAND_OS_LLM_PROVIDER"],
    "timeouts": {"test": 2400000, "smoke": 2400000}
  },
  "checker": {
    "command": "uv run python tools/check_architecture.py"
  }
}
---

# Brand Marketing OS — how the system works now

Traditional-Chinese vocabulary for every business term is in `CONTEXT.md`; front-end rules are in
`docs/design-system.md`. This file owns module boundaries and data ownership. Domain decisions are linked in §§5, 6, 8;
verification procedure is linked in §7. Read only the relevant section. Previous versions are in git.

## 0. What this system is for, and what failure looks like

MarketingOS owns one thing: the brand's decision flow —
goal → context → decision → strategy → artifact → action → outcome → learning → next goal.
Success is whether that chain closes for one brand, not how many modules exist.

For a new feature or a material boundary change, answer the relevant questions once at feature level;
small fixes inherit the existing answers:
1. Which link of the chain does this serve? No answer = an isolated feature.
2. Where does its input come from? Existing brand / product / campaign / history rows — never re-asking the user.
3. Where does its output go? Into the next link as structured data, not a screen the user copies from.
4. What trace does it leave? Why, what, which data, who approved, what happened.
5. If removed, does the OS still hold? Yes = pluggable module. No = core.

Golden path (verify the affected links when a feature changes this flow): brand → offering → goal (the brief) → strategy →
delivery plan → pack → artifacts → publish (manual or simulated) + bind → outcome → verdict against
the campaign's success criterion → learning → the next campaign's strategy reads the learning.

Signals to inspect the affected boundary (pause dependent work only when correctness or ownership is unresolved):
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

The current checkout uses Postgres. Check Git for branch/merge state when needed; branch names do not define the database architecture.

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
that call is made by the browser, not by a Python import. It reaches `schedule` for one call only
(2026-09-23, drill 5): `app.schedule.seed_brand_vocabulary` right after creating a brand, so the
coordinate vocabulary the ads plan requires exists from the brand's first minute; when
`brand_coordinate` moves to `ads` (§4) this call moves with it.

Everything else under `app/` (core, shared, llm, identity, meta, brand_intelligence, brand_web,
orders, dashboard, storage, background, tools) plus `scripts/` is **legacy**: it works, it
is not governed by the container checker. New product behavior belongs in managed modules;
minimal owned-table facade extensions (§3) and local-only test seams (§7) remain allowed under
`legacy_migration: true` and planner review. A managed module
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
campaign/period tables belong to `schedule`; `ads_campaign`, `ads_delivery_group`, `ads_ad`
and `ads_action` belong to `ads`. Physical definitions live in the shared `supabase/migrations/` directory, one file
per module prefix (`<timestamp>_<module>_<desc>.sql`); an applied migration is never edited, a
correction is a new file.
**Avoid table-name collisions in the textual checker** (2026-09-15, F07-I02 block). The checker's
`sql-table` analyzer is textual: an owned table's name inside any string literal outside its owner
counts as access. Prefer task types, job kinds, prompt ids and dict keys distinct from a declared
table's name — the identity derivation's task type is `workbench_derive_identity`, not the table
`workbench_visual_identity`. Prefer an unambiguous identifier. If this is a proven false positive, improve the analyzer with regression coverage for both the false positive and real ownership violations; do not remove the ownership check.

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
`brand_dismissed_calendar_category`) were dropped in F31-I09 (2026-09-26).

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

品牌建檔 (`intake`) fills 品牌智庫 (`brand_intelligence`) — seven steps since F42 (2026-09-30), each AI-prefilled and
confirmed: 1 基本 · 2 AI 讀網站 · 3 品牌是誰 · 4 證據與政策 · 5 素材 · 6 接工具 · 7 完成 (the 可投放檢查表, intake.md) →
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

只在涉及素材工作檯：生成、素材組、圖片與視覺學習時讀 [領域決策](docs/architecture/workbench.md)。原 §5 子節保留於該頁；本頁不重複全文。

## 6. 投放中心 (Ads V2) — settled decisions (2026-09-12)

只在涉及投放中心：Campaign、策略、投放與結案時讀 [領域決策](docs/architecture/ads.md)。原 §6 子節保留於該頁；本頁不重複全文。

## 7. Verification

命令定義在本檔 frontmatter；執行時機、測試環境與 UI 驗證見 [驗證規則](docs/verification.md)。
只載入本次變更所需小節。

## 8. 品牌地基與可投放檢查表 — settled decisions (2026-09-14, F05)

只在涉及建檔：品牌事實、商品經濟與研究時讀 [領域決策](docs/architecture/intake.md)。原 §8 子節保留於該頁；本頁不重複全文。
