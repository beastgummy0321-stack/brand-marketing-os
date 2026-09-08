# 02 — The diagnosis coordinate guard keys off this round's table, not the brand's whole coordinate library

Route B: behaviour change; no schema, no module boundary, no money path, no permission path.
Staffing (user, 2026-09-08): Sonnet implements; main chat (Fable) reviews the diff; Opus reviewed the ticket list once
before dispatch. Board row: 方案品質 (`docs/issues/plan-quality/spec.md`).

Graduated from `issue-coordinate-guard-only-blocks-unknown-labels.md` (2026-09-06 review note). Scout re-verified
2026-09-08: the claim holds, the line numbers drifted — current ones below.

## What

Today `jobs.schedule_diagnosis()` builds the label→key map from every coordinate the brand has ever registered
(`app/schedule/jobs.py:572-573`, `repository.list_coordinates()`; `brd_bughunt` seeds 35 `angle` labels alone) and
hands it to `diagnosis._valid_suggestions()` (`app/schedule/diagnosis.py:327`). An agent that cites a real coordinate
with **zero spend this round** therefore passes the structural guard and only prompt wording
(`diagnosis.py:312`, `:315`) stands in its way — the same module's contract page records that wording alone does
not hold (`docs/contracts/schedule.md` "Position in the prompt decides…").

Change: the map is built from the coordinate values that actually appear in this round's compressed table.

1. `app/schedule/diagnosis.py` — new pure function, next to `compress()`:

```
label_map_from_performance(performance: dict) -> dict[tuple[str, str], str]
```

`performance` is the exact dict `performance_mod.brand_creative_performance()` returns
(`app/schedule/performance.py:196`; shape assembled by `_currency_view()` at `:159-186`). The map is
`{(dimension, label): key}` over every `currencies[*].dimensions[*].values[*]` entry — the same `values` list
`compress()` prints. Precisely: `_currency_view()` (`performance.py:169-186`) buckets every `meta_entity_spend`
row in the window, **whatever its amount** — plan review 2026-09-08 found one row of 78 with spend 0 in the
local DB — so the map is "coordinates that have a spend row this round", not "coordinates with spend > 0". A
coordinate with no row at all (the 65 of `brd_bughunt`'s 68 registered coordinates that no ad in the window
carries) is absent by construction; that is the guard this ticket buys. Do not add an amount filter — the table
the agent reads is the same `values` list, and the guard must match what it was shown. `untagged` buckets are
not coordinates and are skipped. Literal example — input:

```json
{"currencies": [{"currency": "TWD", "total_spend": 300.0, "untagged": {"spend": 0.0},
  "dimensions": [
    {"dimension": "angle", "untagged": {"spend": 0.0},
     "values": [{"key": "angle_value", "label": "價值感", "spend": 300.0}]},
    {"dimension": "hook", "untagged": {"spend": 300.0}, "values": []}
  ]}]}
```

output:

```json
{"angle|價值感": "angle_value"}
```

(the JSON above spells the tuple key `("angle", "價值感")` as `angle|價值感` only because JSON has no tuple keys;
the Python value is the tuple.) Two currencies naming the same `(dimension, label)` map to the same key — last one
wins, they are identical.

2. `app/schedule/jobs.py:572-573` — replace the two lines with
`label_to_key = diagnosis_mod.label_map_from_performance(performance)`. `repository.list_coordinates()` is no longer
called in `schedule_diagnosis()`; its other callers (`jobs.py:530`, `performance.py:107`, `routes.py:579`) are
untouched.

3. `_valid_suggestions()` and its docstring (`diagnosis.py:327-330`) keep their signature; the docstring line that
says the map comes from `list_coordinates()` is corrected to say it comes from this round's table.

Not this ticket: the prompt wording at `diagnosis.py:312-315` (stays as is); anything in `compress()`.

## How we know it's done

1. `uv run pytest app/tests/test_schedule_diagnosis.py -q` — new test in that file: build a `performance` dict with
   one dimension `angle` holding one value `{"key": "angle_value", "label": "價值感"}`; call
   `_valid_suggestions()` with two raw suggestions, one citing `("angle", "價值感")` and one citing
   `("angle", "CP值")` where `CP值` is a label the map does **not** contain; assert exactly one suggestion survives
   and its `coordinate_key == "angle_value"`. Red proof: the same test against a map built from
   `list_coordinates()`-style data that contains both labels would keep both.
2. Same file: `label_map_from_performance()` on the literal input above returns `{("angle", "價值感"): "angle_value"}`
   and an `untagged`-only dimension contributes nothing.
3. `git grep -n "list_coordinates" -- app/schedule/jobs.py` prints exactly one hit, at the `schedule_tree` path
   (today `jobs.py:530`), and none inside `schedule_diagnosis()`.
4. Machine gate: `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule_diagnosis.py app/tests/test_schedule_performance.py -q`
   green; `cd frontend && npm run e2e` green (start the backend on 8720 yourself, stop it after; `supabase start`
   first) — no frontend file changes, the smoke proves the server still boots with the changed job module imported.

## Shared files touched

`git grep -n "label_to_key" -- . ':!graphify-out'` (2026-09-08):

```
app/schedule/diagnosis.py:327:def _valid_suggestions(raw: list, label_to_key: dict[tuple[str, str], str]) -> list[dict]:
app/schedule/diagnosis.py:343:        key = label_to_key.get((dimension, label))
app/schedule/jobs.py:573:        label_to_key = {(c["dimension"], c["label"]): c["key"] for c in coordinates}
app/schedule/jobs.py:602:                raw if isinstance(raw, list) else [], label_to_key
```

`git grep -n "list_coordinates" -- . ':!graphify-out'`:

```
app/schedule/diagnosis.py:330:    （`schedule_repo.list_coordinates()` 現有資料）把它解回真正的 key——跟
app/schedule/jobs.py:530:            repository.list_coordinates(conn, org_id, brand_id)
app/schedule/jobs.py:572:        coordinates = repository.list_coordinates(conn, org_id, brand_id)
app/schedule/performance.py:104:    `list_coordinates()`（跟品牌智庫「創意座標」分頁同一支既有讀取，不另開一條）。"""
app/schedule/performance.py:107:        for c in schedule_repo.list_coordinates(conn, org_id, brand_id)
app/schedule/repository.py:225:def list_coordinates(conn: _AnyConn, org_id: str, brand_id: str) -> list[dict]:
app/schedule/repository.py:336:    # 分頁，落地前自己確保一次（跟 list_coordinates() 同一支冪等函式，讀第二次不動作）。
app/schedule/routes.py:579:    return {"coordinates": schedule_repo.list_coordinates(web.conn, actor.org_id, brand_id)}
```

Files this ticket edits: `app/schedule/diagnosis.py`, `app/schedule/jobs.py`, `app/tests/test_schedule_diagnosis.py`.

## Contradiction check

- Done-checks 1 and 3 could contradict if `compress()` printed labels that `brand_creative_performance()` does not
  carry in `values[]` (then a cited label from the table would be dropped as unknown). Input that would show it: a
  dimension whose only spend is `untagged` — `compress()` prints the untagged bucket; an agent citing 「未標座標」 as
  a coordinate is dropped. That is the intended reading: untagged is not a coordinate (contract page, diagnosis
  frozen shape).
- Cheapest wrong implementation that leaves every check green: build the map from `list_coordinates()` and then
  filter it by the labels in `performance` — same result, one extra query. It is wrong only by cost, so check 3
  (no `list_coordinates` call inside `schedule_diagnosis()`) is what rules it out.
