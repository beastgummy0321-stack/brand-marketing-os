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
    "test": "uv run pytest app/tests -q -n 8 --dist loadfile",
    "typecheck": "uv run ruff check app && uv run pyright && cd frontend && npx tsc -b --noEmit && npm run depcruise",
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

`workbench_brief` and `workbench_output` belong to `workbench`; the campaign/period tables belong
to `schedule`. Physical definitions live in the shared `supabase/migrations/` directory, one file
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
the seven coordinates (audience · pain · angle · hook · proof · offer · format) → each deepest node
dispatches one brief into 素材工作檯 (`workbench`) → the workbench generates copy, image prompts and
video scripts; the user adopts one round → the schedule page reads the adopted output back for the
投放包 → Meta binding, spend pull (`meta`), diagnosis and settlement close the period.

The dependency is one-way: `schedule` imports `workbench`'s public entry, never the reverse. The
workbench knows no tree — it stores `source_kind` + `source_ref` and compares them, never
interprets them.

## 5. 素材工作檯 — settled decisions (2026-09-10)

These are decided. A worker implements them; it does not re-open them.

1. **The workbench is a multi-upstream hub with a standalone front door.** Upstream modules
   dispatch briefs (檔期 today; 網站 and 品牌內容 later). Anyone who needs brand or product content
   also starts here without an upstream. Adding an upstream = a new `source_kind` value plus the
   shape of its `source_ref`; it never restructures the page.
2. **Source is a facet, not a page.** One brief list, filtered by `source_kind`. 派工任務 are
   grouped by source (檔期／網站／品牌內容) and are always visible, never an inbox that collapses;
   the empty state reads 「尚無任務」.
3. **Layout C (creation-first).** The page is the existing `.workspace-split` pattern
   (`docs/design-system.md` §5): a left rail with three groups — 開始生成 (文案／圖片提示詞／影片
   腳本／自由生成), 派工任務 by source, 工單 (全部／已採用) — and the work area on the right. 工單／全部 is
   every brief of the brand whatever its state (queued and failed included), with closed briefs in a
   collapsed 「已關閉」 section so closing and re-opening stay reachable; 已採用 is the briefs with at
   least one adopted round. Three groups, no fourth. No new layout pattern is introduced;
   `docs/design-system.md` §5.2's 素材工作檯 row is rewritten to this and §5.1's 素材準備 row loses the
   短／中／長 tabs.
4. **One brief, several parts.** `request_json.parts` (a list of `copy` / `image_prompt` /
   `video_script` / `free`) is the authority for what a brief **asks for**, and it is never rewritten
   afterwards; what a brief actually **produced** is recorded by `workbench_output.part`.
   `workbench_brief.kind` stays as a display label derived at submit time (`ad_creative` when more
   than one part is requested, otherwise the single part name) — nothing branches on `kind` any more,
   and no migration is needed. A manual brief is product (optional) + parts (multi-select) + free
   text; the seven coordinates arrive only from a schedule node. Which cards the work area shows is
   decided by source, not by `kind` or by what already exists: a dispatched brief always offers 文案
   and 圖片提示詞 (the schedule asks for copy, the user adds the image prompt with its own count when
   they want it), a manual brief offers exactly the parts it requested. The `on_image_texts` key is
   retired with this round — no writer, no reader.
5. **One copy length, chosen by the tree.** The plan-expansion AI decides a copy length per deepest
   node and writes `copy_length` (`short` / `medium` / `long`) on the node; the schedule hands it to
   the workbench inside `submit_brief`'s `request`; the workbench generates that length only. The
   length vocabulary is unchanged (短 100–150 / 中 300–500 / 長 800–1000 characters) and so are the
   per-length body counts (短 5 / 中 3 / 長 2). Generating all three lengths at once is retired:
   `validate.BODY_BANDS` keeps the bands but is applied to one band per brief, `jobs.py` asks for one
   band, `schedule/state.py::_copy_summary` returns one list, and the 素材準備 stage shows one
   length with its hint instead of three tabs. A node with no usable `copy_length` falls back to
   `short`.
6. **Image prompts: hero → approve → N variants.** One image-prompt card, mode taken from the
   brief's `source_kind`:
   - dispatched (`schedule_node`) → **變體模式**: ① 主圖提示詞 (one image, built from the node's
     coordinates) then ② 變體提示詞 (paste with the approved hero attached).
   - manual → **探索模式**: ③ 探索提示詞 (N angles picked from `creative-matrix.md` §1's 35-angle
     matrix, one paste) then ② 變體提示詞.
   Prompt ② is a constant plus slots — no model call. N is the existing `image_prompt_count` (1–30),
   user-entered, prefilled in the UI from the node's `format` coordinate (彈性格式 → 10, otherwise 3).
   This round the variants are text only; there is no image provider and no reference image in the
   system, so there is no 「主圖已確認」 state to store.
7. **The shell renders, the model returns fields.** Unchanged architecture, new object. The model
   returns `{"hero": {scene, person, subject_position, headline, subhead}}` in 變體模式 and
   `{"angles": [{name, brief, on_image_line}] × N}` in 探索模式; the shell assembles the text.
   Prompt ① is, in order — every line dropped when it has no content:
   `【風格】` (style block) · `【商品】` (見參考商品照：<product>。不重述外觀。 / 無參考商品照，畫面以情境與
   人物為主，不畫商品特寫。) · `【受眾】<audience>；痛點：<pain>` · `【這則的訴求】切角：<angle>——<說明>；
   標題公式：<hook>——<說明>` · `【可用字句（逐字，不得改）】` (the promotion note's lines) · `【畫面】` (the
   model's three sentences) · `【圖上文字】大標：「…」；副標：「…」；文字純色填滿，數字獨立成行` ·
   `【輸出】<format label>（<format 說明>），一張`. Coordinate labels and their descriptions come from
   the coordinate vocabulary the workbench already reads; the format line's 說明 is that label's own
   `situation` text, so no platform spec is hard-coded in the shell.
   `app/methodology/image-prompt-template.md` is rewritten to the ①②③ shapes and replaces the 9-line
   template, the 200–250 character band, the 固定段／變動段 split and the 「圖上文字逐字取自標題」 rule. An
   adopted copy headline is an optional hint, never a constraint, so an image prompt can run before
   any copy is adopted.
8. **Positive prompts only.** No prohibition lines anywhere in a generated prompt — no 禁止 line, no
   保留｜禁止 line, no 「未列出的…」 wording. `creative-matrix.md` §3 rule 4 is amended accordingly. The
   surviving guard is positive: 【圖上文字】 lists every string that will appear on the image and that
   list is the whole of it; a number or claim may only be a verbatim string from the brief's
   quotable text — the period's `promotion_note`, handed down on the brief, plus the compiled brand
   knowledge the prompt already carries. When there is none, the 可用字句 line is absent and no number
   may appear on the image; the machine check is that every digit run in an on-image string occurs
   in that quotable text. 硬事實 is not a concept in the system and gets no field of its own.
9. **The style entry is photographic only.** `app/workbench/image_styles.json` holds `key`, `label`
   and one `style_block` — the capture style (iPhone 原生抓拍、未修圖、輕微晃動模糊、雜亂背景、不均勻光線、
   文字純色填滿, plus the generic realism rule 東亞日常面孔、非廣告選角). `style_block` replaces
   `capture_line` and `authenticity_hint`, which existed only to fill two lines of the retired 9-line
   template; their read sites (`prompts.brief_text`, the `ImageStyle` type, the test fixture) move
   with them in the same issue. Who appears in the picture is derived from the node's `audience`
   coordinate, never baked into the style. The 商品 line is conditional and product-scoped: it says 見參考商品照 only when the brief has a
   `product_id` and that product has an `official_asset` row of kind `product_photo`; a brand-level
   asset, another asset kind or a brief with no product directs the image to 情境與人物 instead.
10. **Image generation stays a reserved seat.** `workbench_output`'s provider columns remain
    unwritten and the 生成圖片 button ships grey and disabled — 席位保留, never phrased as a refusal.
    No provider, no cost, no automation this round.

## 6. Verification

`verify.typecheck` runs ruff, pyright, the frontend type build and dependency-cruiser; `verify.test`
is the full pytest suite with `-n 8 --dist loadfile` (`-n auto` exhausts Postgres connections, see
`CONTEXT.md`); `verify.smoke` is the Playwright end-to-end suite, which starts its own backend on
8720 — the reason acceptance must never be judged on the long-running 8710 process. A schema or
migration change additionally runs the tenant-isolation and boundary trio named in `CLAUDE.md`.
Real-browser acceptance happens on a restarted backend at 1024 and 1920 in empty, normal and heavy
states (`docs/design-system.md` §9/§10).
