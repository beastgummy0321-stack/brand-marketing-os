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
        "frontend/src/components/workbench/**",
        "frontend/src/lib/workbenchApi.ts",
        "supabase/migrations/*_workbench_*.sql"
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
        "app/departments/ads/**",
        "app/tests/test_schedule*.py",
        "app/tests/test_approval.py",
        "app/tests/test_imported_ad_schema.py",
        "app/tests/test_meta_daily_spend.py",
        "app/tests/test_past_ads_history.py",
        "frontend/src/components/schedule/**",
        "frontend/src/lib/scheduleApi.ts",
        "supabase/migrations/*_schedule_*.sql"
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
    "app/intake/**",
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
    ".worktrees/**"
  ],
  "legacy_facades": [
    "app/__init__.py",
    "app/main.py",
    "app/worker.py",
    "app/background/__init__.py",
    "app/brand_intelligence/__init__.py",
    "app/brand_intelligence/repository.py",
    "app/brand_intelligence/personas.py",
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
    "app/tests/identity_test_helpers.py"
  ],
  "verify": {
    "test": "uv run python -m pytest app/tests -q -n 8 --dist loadfile",
    "typecheck": "uv run ruff check app && uv run python -m pyright && cd frontend && npx tsc -b --noEmit && npm run depcruise",
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

## 2. Managed modules and the legacy surface

Managed modules today are `workbench` and `schedule` — the two packages this round changes. They
follow the container rules: one root, one public entry (`app/<module>/__init__.py`), declared
dependencies, no cycles, no import of the app shell. The machine check is
`tools/check_architecture.py`, driven by the manifest above.

Everything else under `app/` (core, shared, llm, identity, meta, brand_intelligence, brand_web,
intake, orders, dashboard, storage, background, tools) plus `scripts/` is **legacy**: it works, it
is not governed by the container checker, and it may shrink but never grow. A managed module
reaches legacy code only through a file listed in `legacy_facades` (in practice: the package entry
or the module's `repository.py` / `gateway.py`). New capability never lands in legacy; moving a
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
`index.ts`; `layout/` is the shared kit), which runs inside the `verify.typecheck` command.
`frontend/src/lib/**` is app shell except the per-module API clients (`workbenchApi.ts`,
`scheduleApi.ts`), which each module owns; `frontend/e2e/**` is acceptance code that belongs to
whichever ticket changes it.

## 3. Data ownership

`workbench_pack`, `workbench_brief` and `workbench_output` belong to `workbench`; the
campaign/period tables belong to `schedule`. Physical definitions live in the shared `supabase/migrations/` directory, one file
per module prefix (`<timestamp>_<module>_<desc>.sql`); an applied migration is never edited, a
correction is a new file.

Two cross-module raw-SQL reads exist and are deliberate, pre-dating the manifest:
`app/workbench/repository.py::list_coordinate_vocabulary` reads `brand_coordinate`/`feedback`
(schedule's tables) read-only rather than importing `app.schedule`, which would reverse the
dependency direction. They are recorded here rather than declared as owned resources; the layer
scan in `app/tests/test_architecture_boundaries.py` remains the tripwire for new ones. Do not add
a third one without a planner decision.

## 4. The loop, end to end

品牌建檔精靈 (`intake`) fills 品牌智庫 (`brand_intelligence`) → 檔期規劃 (`schedule`) produces a
plan, then expands the chosen plan into a three-level campaign tree whose deepest nodes each carry
the seven coordinates (audience · pain · angle · hook · proof · offer · format) → the expansion dispatches
one 任務包 into 素材工作檯 (`workbench`), one 素材組 per deepest node (§5.4) → the workbench
generates copy, image prompts and video scripts; the user 選定 one version per required 產物 and
核准整包 → the schedule page reads the selected output back for the 投放包 → Meta binding, spend pull (`meta`), diagnosis and settlement close the period.

The dependency is one-way: `schedule` imports `workbench`'s public entry, never the reverse. The
workbench knows no tree — it stores `source_kind` + `source_ref` and compares them, never
interprets them.

## 5. 素材工作檯 — settled decisions (2026-09-12 reset)

These are decided. A worker implements them; it does not re-open them. This revision replaces the
2026-09-10 list where they conflict — the IA (old 1–4), the copy contract (old 5) and the reserved
image seat (old 10) are rewritten below; the image-prompt decisions are carried over unchanged as
§5.7–§5.10. The old text is in git. The visual source of truth is the four reference images listed
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
   image-prompt round writes 1 row (the ①＋② prompt pair it renders), a script round writes one
   row per script.
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
   (`source_kind` ＋ opaque `source_ref`), `name`, `context` (brand／product／campaign ids),
   `summary` (the 摘要 shown read-only on the pack page: 情境／角度／風格／目標受眾／重點訊息／
   參考連結), `sets` (each: name, opaque `source_ref`, coordinates, product_id, style_key,
   `required_outputs` = `{產物類型: 需要選定的版本數}`, and the per-type generation counts), and
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
7. **Image prompts: hero → approve → N variants.** One image-prompt card, mode taken from the
   brief's `source_kind`:
   - dispatched (`schedule_node`) → **變體模式**: ① 主圖提示詞 (one image, built from the node's
     coordinates) then ② 變體提示詞 (paste with the approved hero attached).
   - manual → **探索模式**: ③ 探索提示詞 (N angles picked from `creative-matrix.md` §1's 35-angle
     matrix, one paste) then ② 變體提示詞.
   Prompt ② is a constant plus slots — no model call. N is the existing `image_prompt_count`
   (1–30), user-entered, prefilled in the UI from the node's `format` coordinate (彈性格式 → 10,
   otherwise 3).
8. **The shell renders, the model returns fields.** The model returns
   `{"hero": {scene, person, subject_position, headline, subhead}}` in 變體模式 and
   `{"angles": [{name, brief, on_image_line}] × N}` in 探索模式; the shell assembles the text.
   Prompt ① is, in order — every line dropped when it has no content:
   `【風格】` (style block) · `【商品】` (見參考商品照：<product>。不重述外觀。 / 無參考商品照，畫面以
   情境與人物為主，不畫商品特寫。) · `【受眾】<audience>；痛點：<pain>` · `【這則的訴求】切角：
   <angle>——<說明>；標題公式：<hook>——<說明>` · `【可用字句（逐字，不得改）】` (the promotion
   note's lines) · `【畫面】` (the model's three sentences) · `【圖上文字】大標：「…」；副標：「…」；
   文字純色填滿，數字獨立成行` · `【輸出】<format label>（<format 說明>），一張`. Coordinate labels
   and their descriptions come from the coordinate vocabulary the workbench already reads; the
   format line's 說明 is that label's own `situation` text, so no platform spec is hard-coded in
   the shell. A selected copy headline is an optional hint, never a constraint, so an image prompt
   can run before any copy is selected.
9. **Positive prompts only.** No prohibition lines anywhere in a generated prompt — no 禁止 line,
   no 保留｜禁止 line, no 「未列出的…」 wording. The surviving guard is positive: 【圖上文字】 lists
   every string that will appear on the image and that list is the whole of it; a number or claim
   may only be a verbatim string from the brief's quotable text — the period's `promotion_note`
   plus the compiled brand knowledge the prompt already carries. When there is none, the 可用字句
   line is absent and no number may appear on the image; the machine check is that every digit run
   in an on-image string occurs in that quotable text.
10. **The style entry is photographic only.** `app/workbench/image_styles.json` holds `key`,
    `label` and one `style_block` — the capture style (iPhone 原生抓拍、未修圖、輕微晃動模糊、雜亂
    背景、不均勻光線、文字純色填滿, plus 東亞日常面孔、非廣告選角). Who appears in the picture is
    derived from the node's `audience` coordinate, never baked into the style. The 商品 line is
    conditional and product-scoped: 見參考商品照 only when the brief has a `product_id` and that
    product has an `official_asset` row of kind `product_photo`.
11. **In-site image generation is a reserved port, not a feature.** `app/workbench/image_port.py`
    is one module with one stub: no provider, no key, no cost, no billing, no automation. It
    reports 未接上 and the API repeats that, so the 圖片 tab defaults to the prompt view.
    「顯示提示詞」 is a permanent toggle, not a fallback: the same version cards render as
    plain-text prompt cards (① 主圖／② 變體) with a copy button each plus 「複製全部」. When a
    provider is connected the image view is the same component fed by the port. 席位保留 is never
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
    fields 專案主題／需要產出（含張數）／風格設定／投放平台／尺寸／目標受眾／主要訴求, and the
    second click submits them as `required_outputs`. A failed, timed-out or unparseable call is
    never a dead end: it returns the caller's defaults with `parsed: false` and the user continues. Rails inside the workbench are pack-local or
    set-local; the OS sidebar is untouched. The old `.workspace-split` workbench page (開始生成／
    派工任務／工單 rail) is retired with this revision.
13. **The 生成設定 table is shipped as text, like `cells[].text`.** `SetDetail.generation_settings`
    is a backend-derived **ordered list of `{label, text}`** — 品牌／商品, 平台, 尺寸, 風格, 人物,
    場景, 主要訊息 — and the 圖片 tab's right column renders it verbatim, row by row, with no
    per-label branch in the browser (§5.3's rule: text the user reads is produced once, by the side
    that owns the rule). Every row is always present; a row with nothing to say reads 「—」, and the
    商品 half of row 1 reads 「不指定」 when the set has no `product_id`. Sources: brand and product
    names from `brand`／`product` via the set's `product_id`; 平台／尺寸／風格 are the same three
    values as `chips`; 人物 and 場景 are the **latest image-prompt round's structured reply**
    `body_json["hero"]["person"]／["scene"]` (the model's fields, §5.8 — not the rendered prompt
    string, and absent in 探索模式, which is a 「—」); 主要訊息 is the pack summary's 重點訊息. It is
    a **read-only mirror of what produced the current prompts**, never an input form and never a
    second endpoint fetch. `SetDetail.products[<part>].generation_settings` is a different field
    with a different shape (the per-product run parameters `copy_length`／`count`) and keeps its
    meaning; the table is the top-level one.

## 6. Verification

`verify.typecheck` runs ruff, pyright, the frontend type build and dependency-cruiser; `verify.test`
is the full pytest suite with `-n 8 --dist loadfile` (`-n auto` exhausts Postgres connections, see
`CONTEXT.md`); `verify.smoke` is the Playwright end-to-end suite, which starts its own backend on
8720 — the reason acceptance must never be judged on the long-running 8710 process. A schema or
migration change additionally runs the tenant-isolation and boundary trio named in `CLAUDE.md`.
Real-browser acceptance happens on a restarted backend at 1024 and 1920 in empty, normal and heavy
states (`docs/design-system.md` §9/§10).
