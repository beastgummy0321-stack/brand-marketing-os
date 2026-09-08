# 03 — workbench routes (`/api/workbench/*`) and the frontend API module

route=C: module entry point — the HTTP surface of `app/workbench/` named in
`docs/contracts/workbench.md` "Routes"; no schema change, no money, tenant checks at every route.
Serves the board row 素材工作檯 (spec.md in this folder). Ticket 02 landed the tables, repository
and jobs; this ticket makes them reachable. No screen yet (ticket 04); the frontend part of this
ticket is the typed API module only.

## What

### 1. `app/workbench/routes.py` (new, private; `__init__.register()` includes its router)

Shape rule (container contract §7): every handler = `require_actor` → `require_brand` → one
repository/job function → wrap. No business branch in the routes file; anything that decides
lives in `repository.py`. Read `app/meta/routes.py` and `app/schedule/routes.py:487-500` for the
error style (`web.ApiError(status, code, message)`, Chinese message).

Router prefix `/api/workbench`. Every route below except `/styles` takes `brand_id` and calls
`web.require_brand(brand_id, actor)` first (another organisation's brand → 404, existing helper);
a brief that does not belong to `(actor.org_id, brand_id)` → 404 `brief_unknown`.

| method + path | body | reply | errors |
|---|---|---|---|
| `GET /styles` | — | `{"styles": [<image_styles.json entries verbatim>]}` | — |
| `GET /brands/{brand_id}/briefs?status=active` | `status` ∈ `active`(default: not closed) / `closed` / `all` | `{"briefs": [BriefSummary]}` newest first | `status_unknown` 400 |
| `POST /brands/{brand_id}/briefs` | `NewBrief` (below) | 201 `{"brief": BriefDetail}` | `kind_unknown` 400 (`ad_creative` is schedule's, not creatable here), `style_unknown` 400, `product_unknown` 404, `count_out_of_range` 400, `on_image_texts_required` 400 |
| `GET /brands/{brand_id}/briefs/{id}` | — | `{"brief": BriefDetail}` | `brief_unknown` 404 |
| `POST …/briefs/{id}/parts/{part}/run` | `{"count": int}` required for `image_prompt`, `{}` otherwise | `{"brief": BriefDetail}` (status `queued`) | `part_unknown` 400 (part not allowed for the brief's kind — table below), `count_out_of_range` 400 (1–30), `brief_closed` 409, `round_running` 409 (brief `status` is `queued` or `running`), `on_image_texts_required` 409 (image_prompt run with neither a `copy` output nor `request.on_image_texts`) |
| `POST …/briefs/{id}/outputs/{output_id}/adopt` | — | `{"brief": BriefDetail}` | `output_unknown` 404, `brief_closed` 409 |
| `POST …/briefs/{id}/close`, `POST …/briefs/{id}/reopen` | — | `{"brief": BriefDetail}` | `brief_unknown` 404 |
| `DELETE …/briefs/{id}` | — | 204 | `brief_unknown` 404 |

Parts allowed per kind: `ad_creative` → `copy`, `image_prompt`; `copy` → `copy`; `image_prompt` →
`image_prompt`; `video_script` → `video_script`; `free` → `free`.

Literal shapes:

```json
NewBrief = {
  "kind": "copy",
  "product_id": "prd_…" | null,
  "coordinates": {"audience": "…", "pain": "…", "angle": "…", "hook": "…", "proof": "…", "offer": "…", "format": "…"} | null,
  "visual_tone": "暗調強對比" | "暖調生活" | null,
  "visual_concept": "…" | null,
  "style_key": "ugc",
  "request": {"use_brand_knowledge": true, "free_text": "…" | null,
              "image_prompt_count": 6 | null, "on_image_texts": ["…≤27 字…"] | null}
}
BriefSummary = {
  "id": "wbb_…", "kind": "copy", "source_kind": "manual", "source_ref": {}, "product_id": null,
  "product_name": null, "style_key": "ugc", "status": "done", "last_error": null,
  "closed_at": null, "created_at": "2026-09-09T12:00:00+00:00",
  "parts": {"copy": {"latest_round": 2, "adopted_round": 1, "running": false}}
}
BriefDetail = BriefSummary + {
  "coordinates": {…seven keys…}, "visual_tone": null, "visual_concept": null, "request": {…},
  "outputs": [{"id": "wbo_…", "part": "copy", "generation_round": 1, "adopted_at": "…" | null,
               "body_json": {…the validated reply + "validation" + "rendered"…},
               "coordinates_json": {…} | null, "llm_task_id": "llm_…", "created_at": "…"}]
}
```

### 2. `app/workbench/repository.py` additions (private)

`list_briefs(conn, org_id, brand_id, status)`, `brief_detail(conn, org_id, brand_id, brief_id)`
(summary + outputs, or `None`), `run_part(conn, org_id, brand_id, brief_id, part, *, count)` —
the enqueue half of `submit_brief` extracted so both call it (one place decides the lock string
`workbench:{brief_id}:{part}` and the `queued` status write); raises `ValueError("part_unknown")`,
`ValueError("brief_closed")`, `ValueError("round_running")`, `ValueError("count_out_of_range")`,
`ValueError("on_image_texts_required")` — routes map each to the table above.
`close_brief` (sets `closed_at`, `status='closed'`) / `reopen_brief` (clears `closed_at`; the
pre-close status is stored nowhere, so **reopen sets `status='done'` when the brief has any output,
else `'failed'` with `last_error` untouched** — ticket decision, reversible), `delete_brief`
(outputs cascade).
`submit_brief` validates `style_key` (already), `product_id` belongs to the brand
(`brand_intelligence.repository` read), `image_prompt_count` 1–30 when given, and for
`kind='image_prompt'` requires `request.on_image_texts` (1–5 strings, each ≤27 字) — the 「」
text must come from somewhere the user wrote (`creative-matrix.md` §3.1).

### 3. `app/workbench/jobs.py` — one change

`_run()` for `image_prompt`: headlines = the adopted/latest `copy` output's `headlines`
(existing, `jobs.py:138-139`) **or, when there is none, `request_json.on_image_texts`**; when
both are empty the job marks the brief `failed` with `last_error`
「沒有圖上文字可用：先產文案，或在工單填圖上文字。」 and makes **no LLM call** (no money spent on a
prompt the rules forbid the model to complete).

### 4. `frontend/src/lib/workbenchApi.ts` (new)

Types mirroring §1 verbatim (`NewBrief`, `BriefSummary`, `BriefDetail`, `WorkbenchOutput`,
`ImageStyle`) and functions `fetchStyles()`, `fetchBriefs(brandId, status)`, `createBrief(brandId,
input)`, `fetchBrief(brandId, id)`, `runPart(brandId, id, part, count?)`, `adoptOutput(brandId,
id, outputId)`, `closeBrief`, `reopenBrief`, `deleteBrief` — all through `apiFetch` from
`./http`, errors through `errorMessageFrom` exactly as `frontend/src/lib/scheduleApi.ts:307-340`
does. Also export the three fixed length hints as one constant, because two feature folders
(workbench in ticket 04, schedule in ticket 05) show them and may not import each other:
`export const LENGTH_HINTS = { short: "折疊前一口氣講完，適合再行銷、已認識品牌的人", medium: "痛點→證明→優惠，適合第一次看到你的人", long: "說故事，適合高單價、需要被說服的商品" } as const;`
plus `LENGTH_LABELS = { short: "短版", medium: "中版", long: "長版" } as const`. No component
imports the module yet (ticket 04); dependency-cruiser stays green because `lib/` is not a feature
folder.

### 5. `app/tests/test_workbench_api.py` (new)

Fixture shape from `app/tests/test_schedule.py:626-680` (`TestClient(main.app)`, `_headers(token,
org_id)`, test `background.app()` + `register_tasks()` for schedule **and** workbench). Cases:

1. `POST briefs` (`kind=copy`) → 201, `status=queued`, one row; `GET briefs` lists it; `GET briefs?status=closed` does not.
2. `POST briefs` with `style_key="studio"` → 400 `style_unknown`; with `kind="ad_creative"` → 400 `kind_unknown`; `kind="image_prompt"` without `on_image_texts` → 400 `on_image_texts_required`.
3. `run image_prompt` with `{"count": 0}` → 400 `count_out_of_range`; with `{"count": 31}` → 400; on a closed brief → 409 `brief_closed`; while `status='running'` → 409 `round_running`.
4. FakeProvider round-trip through the worker: `run copy` → output row → `adopt` → `GET brief` shows `adopted_round=1`; a second run → round 2, adopt stays on 1.
5. Cross-tenant: org B's brief id via org A's token and brand → 404 `brief_unknown` on GET, run, adopt, close, DELETE (five calls, one assertion each).
6. `DELETE` → 204; the outputs are gone (`SELECT count(*) FROM workbench_output WHERE brief_id=…` = 0).

### 6. Bookkeeping

- `docs/contracts/workbench.md` "Routes" paragraph and "Error shapes": add `GET /styles`,
  `status_unknown`, `kind_unknown`, `style_unknown`, `product_unknown`, `output_unknown`,
  `on_image_texts_required`; exported shapes unchanged.
- `KNOWN_MODULE_SIZES["app/workbench"]` rises to the measured value (new `routes.py` +
  repository additions), reason line `ticket workbench/03: routes.py`; `TEST_LINES_CEILING`
  rises by exactly the line count of `app/tests/test_workbench_api.py` plus that one reason
  comment — measured, written in the existing comment style. No other module row moves;
  `app/llm`, `app` untouched.

## How we know it's done

1. `uv run ruff check app` and `uv run pyright` clean.
2. `uv run pytest app/tests/test_workbench_api.py app/tests/test_workbench.py -q` green; case 5 proven red once by commenting out the `org_id = %s` predicate in `repository.get_brief` (paste the red line), then restored.
3. `uv run pytest app/tests/test_architecture_boundaries.py app/tests/test_migration_ownership.py app/tests/test_rls_tenant_policy.py -q` green.
4. `cd frontend && npm run build && npm run lint && npm test` green (the new `lib/workbenchApi.ts` compiles; `npx depcruise` runs inside lint/build per `frontend/package.json` — verify which script runs it and name it).
5. `cd frontend && npm run e2e` green.
6. With the backend running (`uv run uvicorn app.main:app --port 8720` or the e2e's own boot) and a self-signed HS256 JWT (`IDENTITY_ALLOW_HS256=1`, CLAUDE.md 指令): `curl -s -H "Authorization: Bearer $TOKEN" -H "X-Org-Id: org_bughunt" http://localhost:8720/api/workbench/styles` returns the `ugc` entry — paste the reply.
7. `git diff --name-only` ⊆ Shared files touched + the three new files.

## Shared files touched

Searched 2026-09-09 with `git grep -n -F <name>` (tracked) plus `grep -rn` over `app/workbench`
and `app/tests/test_workbench.py` (untracked, ticket 02's files). Names that change meaning:

`submit_brief` (its enqueue half moves into `run_part`; signature and contract unchanged):
```
docs/contracts/workbench.md:22, :39
app/workbench/__init__.py:10, :20, :59, :64
app/workbench/repository.py:53
app/tests/test_workbench.py:118, :321
```

`image_prompt_count` (gains the 1–30 check at submit; meaning unchanged):
```
app/workbench/repository.py:37, :44, :82
app/tests/test_workbench.py:188, :250, :314
```

`headlines` inside `app/workbench/jobs.py` (gains the `on_image_texts` fallback):
```
app/workbench/jobs.py:138, :139, :141
app/workbench/prompts.py:52, :56, :59
app/tests/test_workbench.py:128
```

`on_image_texts`: no hits anywhere (new name).

`workbench_generate` (unchanged; listed because `run_part` becomes its only enqueuer):
```
app/workbench/jobs.py:195, :197, :213, :215
app/workbench/repository.py:56, :84
app/workbench/__init__.py:8, :53
app/tests/test_workbench.py:266
```

`KNOWN_MODULE_SIZES` / `TEST_LINES_CEILING`: `app/tests/test_architecture_boundaries.py` (the
`app/workbench` row and `:1320`).

Files edited: `app/workbench/__init__.py` (register includes the router), `app/workbench/repository.py`,
`app/workbench/jobs.py`, `app/tests/test_architecture_boundaries.py`, `docs/contracts/workbench.md`.
Files created: `app/workbench/routes.py`, `frontend/src/lib/workbenchApi.ts`,
`app/tests/test_workbench_api.py`.

## Contradiction check

- Done-check 2 case 3 (`round_running` 409 while `status='running'`) vs case 4 (a second run
  writes round 2): the input that shows the tension is a brief whose job crashed before writing
  `failed` — `status` stays `running` forever and no run is ever accepted again. Ticket 02's
  `jobs.py` marks `failed` in its exception path; this ticket does not add a timeout. Named so the
  reviewer checks that path, not so it is built here.
- Done-check 2 case 2 (`on_image_texts_required` at submit for `kind=image_prompt`) vs §3 (the job
  also fails without texts): both fire on the same input by design — submit catches the manual
  case, the job catches the `ad_creative` case where copy has not been produced yet. An
  implementation that only checks at submit leaves case 2 green and the §3 rule unbuilt; the
  reviewer runs `run image_prompt` on an `ad_creative` brief with no copy output.
- Cheapest wrong implementation that leaves every check green: `get_brief` filtering by
  `brand_id` only (case 5 uses a different brand per org, so it stays green) — case 5 must use
  **the same `brand_id` string** for both orgs' briefs is impossible (brand belongs to one org), so
  instead the reviewer reads the SQL: every workbench query carries `org_id = %s AND brand_id = %s`.
  Second: `list_briefs` default reading `status != 'closed'` vs `closed_at IS NULL` — differ when
  a closed brief is reopened by a code path that clears `closed_at` but leaves `status`; `reopen`
  must set both, and the list filter uses `closed_at IS NULL`.
