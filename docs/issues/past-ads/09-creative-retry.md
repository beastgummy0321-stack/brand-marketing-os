# 09 — a creative Meta failed to return is asked for again: after 24 hours, or when the owner presses 「重新抓素材」

Route B (behaviour inside `app/schedule` + one button; no schema, no new table, no money, no permission
path — the new route is brand-scoped like its siblings). Rule: ADR 0067 §1.9 as amended 2026-09-08.
Graduated from `issue-creative-none-is-cached-forever.md`. **No LLM call anywhere.**

## What

### 1. `app/schedule/history.py`

- `_needs_creative_fetch(existing_by_id, external_id, now)` is true when the row is missing, when
  `creative_fetched_at IS NULL`, **or** when both `creative_body` and `creative_image_url` are NULL and
  `creative_fetched_at < now - 24h`. The 24 h is the ADR's number; state it once as a module constant
  with the ADR reference, never in the route.
- `clear_creative_cache(conn, org_id, brand_id, external_ids) -> int`: sets `creative_fetched_at = NULL`
  (and the three `creative_*` columns to NULL) on this brand's `imported_ad` rows whose `external_id` is in
  the list, `WHERE org_id = %s AND brand_id = %s`; returns the row count. SQL lives in
  `app/schedule/repository.py` (`reset_imported_ad_creatives`), the function here only calls it.
- The fetch cap stays 15 per GET (the cards themselves are ≤15 per currency).

### 2. `app/schedule/routes.py`

`POST /api/schedule/brands/{brand_id}/history/creatives/refetch`, body `{"external_ids": ["…"]}`
(1–30 ids; more → `web.ApiError(400, "too_many_ids", …)`) → `require_actor`, `require_brand`,
`clear_creative_cache(...)` → reply `{"cleared": <int>}`. The screen then re-reads the history GET,
which fetches again. Parses, calls, wraps (container contract §7).

### 3. `frontend/src/components/intake/HistoryPage.tsx` + `frontend/src/lib/scheduleApi.ts`

`refetchHistoryCreatives(brandId, externalIds)` client. Under the line 「這些是 Meta 現在還回得出的廣告…」,
when at least one visible card has `creative === null`, an outline `Button` 「重新抓素材」 → POST with the
ids of the cards whose `creative` is null → then `fetchHistory` again; while running, the button reads
「重新抓取中…」 (the kit's convention, `BudgetPanel.tsx:69`). Wording per §8.

Literal example:

```json
{"request": "POST /api/schedule/brands/brd_bughunt/history/creatives/refetch",
 "body": {"external_ids": ["120234301113370671", "120234301113370672"]},
 "reply": {"cleared": 2}}
```

## How we know it's done

Tests in `app/tests/test_past_ads_history.py` (`CreativeCacheTest` already swaps the Graph client):

1. **24-hour retry**: a row with `creative_fetched_at` 25 h ago and both creative columns NULL → the next
   GET calls `fetch_ad_creatives` with that id; the same row at 1 h ago → no call; a row with a body and
   `creative_fetched_at` 25 h ago → no call (a good answer is never refetched).
2. **The button's route**: POST with two ids of this brand → `{"cleared": 2}`, the rows' `creative_fetched_at`
   are NULL, and the next GET fetches exactly those two; POST with an id of another brand in the same org →
   `cleared: 0` and that brand's row untouched; org B's actor on org A's brand → 404; 31 ids → 400.
3. **Frontend**: `npm test` gains no test (a button and a request; screen behaviour is the walk's).
4. **Machine gate**: `unset BRAND_OS_LLM_PROVIDER; uv run ruff check app; uv run pyright;
   uv run pytest app/tests/test_past_ads_history.py app/tests/test_architecture_boundaries.py -q` ·
   `cd frontend && npm run build && npm run lint && npm run depcruise && npm test` · `cd frontend && npm run e2e`.
   Ratchets (`KNOWN_MODULE_SIZES["app/schedule"]`, `TEST_LINES_CEILING`) by measured amounts.
5. **Walk** (with ticket 07's, stand-in backend): on `/app/brands/brd_bughunt/intake/history` with the
   stand-in (which never returns creatives) the button 「重新抓素材」 is visible; press it → 「重新抓取中…」,
   then the cards re-render still saying 「Meta 現在回不出這則的素材」 (the stand-in cannot do better —
   the walk proves the round trip, the DB check proves the reset: `creative_fetched_at` was NULL between
   the POST and the GET; read it with SQL right after the POST if the timing allows, else assert it in
   test 2 only). Screenshot before and after.
6. **No LLM**: `grep -n "gateway\|llm_task" app/schedule/history.py` prints nothing.

## Shared files touched

Searched 2026-09-08, whole repo, unscoped:

```
grep -rn clear_creative_cache .          → (no hits)
grep -rn reset_imported_ad_creatives .   → (no hits)
grep -rn "creatives/refetch" .           → (no hits)
grep -rn refetchHistoryCreatives .       → (no hits)
grep -rn "重新抓素材" .                    → docs/adr/0067-*.md (the amendment), this folder
```

Files this ticket edits:

```
app/schedule/history.py            (_needs_creative_fetch, constant, clear_creative_cache)
app/schedule/repository.py         (reset_imported_ad_creatives)
app/schedule/routes.py             (one route + request model)
frontend/src/lib/scheduleApi.ts    (one client)
frontend/src/components/intake/HistoryPage.tsx
docs/contracts/schedule.md         (the route; the 24 h decision as a module-local line)
app/tests/test_past_ads_history.py
app/tests/test_architecture_boundaries.py   (ratchets)
```

## Contradiction check

- **Done-check 1 (a good answer is never refetched) vs done-check 2 (the button resets any listed id).**
  Consistent: the button clears the columns first, so the row *becomes* "no answer"; input that shows the
  boundary — press the button on a card that has a body: it is refetched once and comes back (the
  frontend sends only null-creative ids, but the route does not refuse others; say so in the report).
- **Cheapest wrong implementation that leaves every check green**: the 24 h rule keyed on
  `creative_fetched_at` alone (refetching good answers daily) — check 1's third case catches it.
