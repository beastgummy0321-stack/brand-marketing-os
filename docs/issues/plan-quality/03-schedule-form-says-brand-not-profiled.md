# 03 — The schedule form says which brand-profile categories are empty before a plan is generated

Route B: behaviour change; no schema, no module boundary, no money path, no permission path.
Staffing (user, 2026-09-08): Sonnet implements; main chat (Fable) reviews the diff; Opus reviewed the ticket list once
before dispatch. Board row: 方案品質 (`docs/issues/plan-quality/spec.md`, cause 一).

Why: the plan prompt drops every empty context category silently (`app/llm/context_compiler.py:129-154`, each
section is `if <list>: sections.append(...)`), and nothing on the schedule screen or in `_run_plan()`
(`app/schedule/routes.py:234-269`) tells the user the brand has no profile. Measured 2026-09-08 on the local DB:
`brd_bughunt` (product Beast Gummy) has `brand_fact` 0 / `persona` 0 / `claim` 0 / `product_fact` 5; the brand
`brd_01M1Y3SJSGWDCJSGV6R27PR09C` that completed the intake wizard has 12 / 4 / 2 / 6, and its one plan cites
brand-specific facts. The gap is data, not code; this ticket makes the gap visible where the plan is started.

## What

### 1. Backend — `app/schedule/state.py` `_brand_response()` (`:156-199`) gains one key

```
"knowledge_gaps": list[str]
```

The list holds the display names of the brand-level categories that are empty, in this fixed order, using the same
reads `context_compiler.compile()` uses so the notice never disagrees with the prompt:

| name | empty when |
|---|---|
| `"品牌事實"` | `bi_repo.list_brand_facts(conn, brand_id, status="confirmed")` is `[]` (`context_compiler.py:107`) |
| `"典型客人"` | `personas.list_personas(conn, brand_id)` is `[]` (`context_compiler.py:109`, `app/brand_intelligence/personas.py:19`) |
| `"宣稱"` | `bi_repo.list_claims_for_brand(conn, brand_id)` is `[]` (`app/brand_intelligence/repository.py:1081`) |

All three present → `[]`. Product facts are not in the list: they are per product and the form already handles a
brand with no product (`ScheduleSetup.tsx:51`). Literal response fragment for `brd_bughunt` today:

```json
{"daily_budget": 2000.0, "plan_count_min": 1, "plan_count_max": 5,
 "knowledge_gaps": ["品牌事實", "典型客人", "宣稱"],
 "plan": null, "tree": null, "creative": null, "period": null, "next_period_suggestion": null}
```

`app.brand_intelligence.repository` and `app.brand_intelligence.personas` are already allowed imports for this
module (`docs/contracts/schedule.md` "Allowed dependencies"; `personas` is the module `context_compiler` reads for
the same list). Read-only; no write, no new query function in either module.

### 2. Frontend — `frontend/src/lib/scheduleApi.ts` `ScheduleState` (`:227`) gains `knowledge_gaps: string[]`;
`frontend/src/components/schedule/ScheduleSetup.tsx` shows one line when the list is non-empty

Placed inside the first `surface` (the product picker, above the product grid at `ScheduleSetup.tsx:49-51`), the
same muted panel style as the "no products" state on `:51`:

```
這個品牌還沒有{knowledge_gaps.join("、")}，出來的方案會比較空泛。   [前往建檔]
```

`[前往建檔]` is a `Button variant="outline" asChild` wrapping `<Link to={`/brands/${brandId}/intake`}>` — the same
component pair as `:51`'s 前往產品頁. `docs/design-system.md` §8 governs the wording: noun-phrase button label,
no first person, no question. Empty list → nothing rendered, no wrapper element.

Not this ticket: any change to the prompt text; a placeholder line in `context_compiler` for empty categories;
the intake wizard itself (ticket 04).

## How we know it's done

1. `uv run pytest app/tests/test_schedule.py -q -k knowledge_gaps` — two new tests in `test_schedule.py`'s
   `_ScheduleApiTestBase` family: (a) the test brand as `setUp` leaves it (no facts, personas or claims) → GET
   `/api/schedule/brands/{id}` body `knowledge_gaps == ["品牌事實", "典型客人", "宣稱"]`; (b) after
   `bi_repo.create_brand_fact(..., status="confirmed")` (the call `test_schedule.py:1763-1766` already makes) the
   list no longer contains `"品牌事實"` and still contains the other two, in order. Red proof: returning `[]`
   unconditionally fails (a); returning the three names unconditionally fails (b).
2. Frontend: `cd frontend && npm run build && npm run lint && npm test` green.
3. `cd frontend && npm run e2e` green (start the backend on 8720 yourself, stop it after; `supabase start` first).
4. Acceptance walk (`WALK:` post, playwright-cli, login `123@example.com` / `123456`): open
   `/app/brands/brd_bughunt/schedule` → the product picker shows the line
   「這個品牌還沒有品牌事實、典型客人、宣稱，出來的方案會比較空泛。」 and a 前往建檔 button; click it → URL is
   `/app/brands/brd_bughunt/intake`. Screenshot each step.

## Shared files touched

`git grep -n "_brand_response" -- . ':!graphify-out'` (2026-09-08) — the function whose return shape changes:

```
app/schedule/period.py:261:    """`routes._brand_response()` 的 `period` 鍵——這個品牌目前顯示的那一個檔期
app/schedule/repository.py:326:    `routes._brand_response()`，每次 GET 成功的 creative 都會呼叫一次，跟 35 個座
app/schedule/routes.py:40:`_brand_response()`——跟 GET 回的形狀一模一樣，`plan`／`tree`／`creative` 在剛排進去
app/schedule/routes.py:202:    return state._brand_response(conn, brand_id, org_id)
app/schedule/routes.py:231:    return state._brand_response(conn, brand_id, org_id)
app/schedule/routes.py:273:    return state._brand_response(conn, brand_id, org_id)
app/schedule/routes.py:353:    response = state._brand_response(conn, brand_id, org_id)
app/schedule/routes.py:385:    return state._brand_response(conn, brand_id, org_id)
app/schedule/routes.py:397:    return state._brand_response(conn, brand_id, org_id)
app/schedule/routes.py:416:    return state._brand_response(conn, brand_id, org_id)
app/schedule/routes.py:423:    return state._brand_response(web.conn, brand_id, actor.org_id)
app/schedule/state.py:7:`_brand_response()` 把核准那一塊交給 `tree_approval._fill_approval()`——本檔不算任何錢
app/schedule/state.py:156:def _brand_response(conn, brand_id: str, org_id: str) -> dict:
app/tests/test_architecture_boundaries.py:1707:                  # in `state.py`'s `_brand_response()`. 4516->4622, measured
app/tests/test_architecture_boundaries.py:2021:                           # _leaf_ad_node_names()／_creative_ad_node_names()、_b
```

`git grep -n "ScheduleState" -- . ':!graphify-out'` — the frontend type that gains a field (readers, all of which
compile unchanged because the field is additive):

```
frontend/src/components/schedule/PlanComparison.tsx:8, :18
frontend/src/components/schedule/SchedulePage.tsx:14, :22
frontend/src/components/schedule/ScheduleSetup.tsx:8, :22
frontend/src/lib/scheduleApi.ts:227, :299, :306, :330, :334, :336, :352, :356, :358, :374, :380, :396, :400, :415, :419, :421, :437, :441, :442, :457, :461, :465, :487, :611
```

`git grep -n "knowledge_gaps" -- . ':!graphify-out'` — no hits (name is new).

Files this ticket edits: `app/schedule/state.py`, `app/tests/test_schedule.py`, `frontend/src/lib/scheduleApi.ts`,
`frontend/src/components/schedule/ScheduleSetup.tsx`. `wc -l` 2026-09-08: `app/schedule/state.py` 199;
`routes.py` 608 and `jobs.py` 642 of the 800 cap are not touched here.

## Contradiction check

- Done-check 1(a) and the prompt could disagree if `context_compiler` counted claims per product while the notice
  counts them per brand: a brand with one product-scoped claim and no brand-scoped claim would show no gap while a
  brand-only `compile()` call (no `product_id`) prints no claims. `schedule_plan()` always compiles per selected
  product (`jobs.py:71`), so the per-product read is the one that matters and the brand-wide count is the
  looser, never-false-negative reading. Accepted.
- Cheapest wrong implementation that leaves every check green: count `brand_fact` rows of any status (unconfirmed
  ones too). Check 1(b) creates a `confirmed` fact, so it passes; only the `status="confirmed"` argument in the
  spec table rules it out — the reviewer reads the call, not the test.
