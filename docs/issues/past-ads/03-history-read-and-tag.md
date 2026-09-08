# 03 — schedule: rank the old ads, let the owner tag them; brand: record 投放過／沒投過

Route C (first writer of `imported_ad`; a new exported shape on `app/schedule/__init__.py`; a new door in
`app/brand_intelligence`). Rulings: ADR 0067 §1.1–1.5, §1.7, §1.9. Goal picture: `spec.md`. Requires
tickets 01 (table, column) and 02 (`daily_pull.backfill_status`, `daily_pull.backfill_lock`,
`graph.fetch_ad_creatives`) shipped. **No LLM call anywhere in this ticket** — `grep -n gateway app/schedule/history.py`
must print nothing.

## What

### 1. `app/schedule/history.py` (new, private) — the work

`history_cards(conn, org_id, brand_id) -> dict`:

1. `account_ids = meta_repo.bound_account_ids_for_brand(...)`; none → `{"connected": false, "backfill": null, "breakeven": null, "currencies": [], "coordinates": [...]}` (coordinates still returned, see 5).
2. `backfill = daily_pull.backfill_status(conn, org_id, account_ids)` plus `running = background.is_active(daily_pull.backfill_lock(org_id))`. No ad rows yet → `currencies: []`.
3. Window = `[earliest_spend_date, latest_spend_date + 1 day)`; `rows = meta_repo.daily_entity_spend(..., level="ad")`,
   names and `cpa` from `meta_repo.spend_summary(..., level="ad", conversion_goal=brand.conversion_goal)` — the
   same two reads `performance.ad_performance()` makes (`app/schedule/performance.py:242-299`), same window shape.
4. Per currency (never across, ADR 0057 §4): group rows by `entity_id`, aggregate each ad with
   `performance._bucket(rows)` (reuse, do not reimplement), add `first_seen_date`/`last_seen_date` (min/max
   `spend_date` of that ad). Three lists: `top_spend` = 5 highest `spend`; `top_roas` = 5 highest
   `roas_conservative` among ads with `revenue` not None; `bottom_roas` = 5 lowest `roas` (optimistic) among
   ads with `revenue` not None. Union in that order, deduplicated by `entity_id`, each card carrying
   `why: ["top_spend", …]` for every list it made. At most 15 per currency.
5. `breakeven = diagnosis_mod.breakeven_roas(conn, org_id, brand_id)` (the existing tuple); verdict per card
   with ADR 0066 rule 4's arithmetic: `win` if `roas_conservative >= breakeven`, `lose` if `roas < breakeven`,
   else `unclear` (also when breakeven or revenue is None).
6. Creative cache: for cards whose `imported_ad` row is missing or has `creative_fetched_at IS NULL`, one
   `graph.fetch_ad_creatives(token, ids)` call (token via `meta_repo.get_token`); each answer is upserted into
   `imported_ad` with `coordinates_status='pending'`, `external_name` = the card's name, first/last seen dates,
   `creative_fetched_at = now()` — **also when the answer is `None`** (that is the "Meta 現在回不出這則的素材"
   state; a `None` is never refetched). A `GraphError` here does not fail the page: cards render with
   `creative: null` and `creative_error: "<the GraphError message>"`, nothing is upserted.
7. Coordinates for the dropdowns: `schedule_repo.list_coordinates(...)`, filtered to `disabled_at IS NULL`,
   in the shape `GET /coordinates` already returns.

`tag_imported_ad(conn, org_id, brand_id, external_id, *, keys: dict, owner_note: str | None, actor) -> dict`:
`keys` has the seven dimension names, each a `brand_coordinate.key` or `None`. Every non-None key must exist
in `list_coordinates()` for **this brand and that dimension** and not be disabled → otherwise
`ValueError("coordinate_unknown:<dimension>")`. The row must already exist (the GET created it) → otherwise
`ValueError("imported_ad_unknown")`. Writes the seven `*_key` columns, `owner_note` (verbatim, `None` when
blank), `coordinates_status = 'tagged' if any key else 'pending'`, `tagged_at = now()`, `tagged_by = actor`,
`updated_at`; `write_audit(entity_type="imported_ad", action="tag", before=<old row>, after=<new row>)`.

`imported_ad_count(conn, org_id, brand_id) -> int` — for ticket 04's guide card.

### 2. `app/schedule/repository.py` — the SQL only

`imported_ads_for_brand(conn, org_id, brand_id) -> dict[external_id, row]`,
`upsert_imported_ad(conn, *, org_id, brand_id, ad_channel_id, external_id, **columns) -> dict`
(`INSERT … ON CONFLICT (org_id, brand_id, ad_channel_id, external_id) DO UPDATE`, id via `new_id("iad")`),
`update_imported_ad_tags(conn, org_id, brand_id, external_id, *, keys, owner_note, status, actor) -> dict`,
`count_imported_ads(conn, org_id, brand_id) -> int`. `ad_channel_id` comes from the existing
`ensure_meta_channel(conn, org_id)` (`repository.py:443`). Every statement filters `org_id AND brand_id`.

### 3. `app/schedule/__init__.py` — one new exported shape

```
imported_ad_count(conn, org_id: str, brand_id: str) -> int   # for app.dashboard's guide card (ticket 04)
```

Lazy import inside the function, like `register()`. Recorded on `docs/contracts/schedule.md` under Exported
shapes with its caller named as "`app.dashboard` (ticket 04)".

### 4. `app/schedule/routes.py` — two routes

- `GET /api/schedule/brands/{brand_id}/history` → `require_actor`, `require_brand`, `history_cards(...)`.
- `PUT /api/schedule/brands/{brand_id}/history/{external_id}` body
  `{"coordinates": {"audience": "new_parents", "pain": null, "angle": "convenience", "hook": null, "proof": null, "offer": "first_order_discount", "format": "carousel"}, "owner_note": "媽媽群組轉貼最多，週末單量翻倍"}`
  → `tag_imported_ad(...)`; `ValueError("coordinate_unknown:…")` → `web.ApiError(400, "coordinate_unknown", "…")`,
  `ValueError("imported_ad_unknown")` → `web.ApiError(404, "imported_ad_unknown", "…")`. Reply: the updated card
  fields `{"external_id", "coordinates", "coordinates_status", "owner_note", "tagged_at"}`.

Literal reply of the GET:

```json
{
  "connected": true,
  "backfill": {"running": false, "earliest_spend_date": "2023-08-08", "latest_spend_date": "2026-09-08", "ad_rows": 55},
  "breakeven": {"roas": 1.4286, "source": "rule card gross_margin 0.70"},
  "currencies": [{
    "currency": "TWD",
    "cards": [{
      "external_id": "120212345678901234", "name": "BP｜夏季｜輪播A", "why": ["top_spend", "top_roas"],
      "first_seen_date": "2026-05-03", "last_seen_date": "2026-08-31",
      "spend": 3570.0, "impressions": 41200, "clicks": 610, "revenue": 2737.8,
      "roas": 1.029, "roas_conservative": 0.767, "roas_coverage": 0.75, "cpa": 178.5, "verdict": "unclear",
      "creative": {"body": "…", "title": null, "image_url": "https://…"}, "creative_error": null,
      "coordinates": {"audience": null, "pain": null, "angle": null, "hook": null, "proof": null, "offer": null, "format": null},
      "coordinates_status": "pending", "owner_note": null
    }]
  }],
  "coordinates": [{"id": "bco_…", "dimension": "angle", "key": "convenience", "label": "省時方便", "category": null, "canonical_key": null, "attributes": {}, "disabled_at": null, "rejected": false}]
}
```

`spend 3570 / revenue 2737.8 / 0.767 / 1.029 / 0.75` are the contract page's own measured numbers
(`docs/contracts/schedule.md`, "One coordinate has two ROAS values"); `breakeven.roas` = 1 ÷ 0.70 (the default
`gross_margin` rule card, `docs/contracts/schedule.md` Diagnosis table row 1).

### 5. `app/brand_intelligence/advertising_history.py` (new door) + `app/brand_web`

`app/brand_intelligence/repository.py` is 1398 lines, frozen in `KNOWN_OVERSIZED_FILES` at 1667
(`app/tests/test_architecture_boundaries.py:618-619`); `CLAUDE.md`: an over-cap file gets no new feature.
So the write lives in a new small file of the owning module, the way `personas.py` and
`repository_channels.py` do:

```
set_advertising_history(conn, brand_id: str, value: str, *, actor: str) -> dict
```

`value` ∈ `('has_history', 'none')` else `ValueError`; `UPDATE brand SET advertising_history = %s, updated_at = %s WHERE id = %s`;
`write_audit(entity_type="brand", action="advertising_history", before, after)`; returns `get_brand()`.

Route in `app/brand_web/routes_library_write.py`, beside the brand profile PUT:
`PUT /api/library/brands/{brand_id}/advertising-history` body `{"value": "has_history"}` → `require_actor`,
`require_brand`, the function above; `ValueError` → `JSONResponse({"errors": {"value": "…"}}, 400)` (that
file's own error shape, `routes_library_write.py:388`). Reply `{"data": {"advertising_history": "has_history"}}`.
`_brand_profile_shape` (`app/brand_web/routes_library.py:210-218`) gains `advertising_history` so the brand
page can read it; `frontend/src/lib/libraryApi.ts:100-106`'s brand shape gains the same field.

### 6. Frontend clients only (no component)

`frontend/src/lib/scheduleApi.ts`: `fetchHistory(brandId)`, `tagHistoryAd(brandId, externalId, body)` with
the types above. `frontend/src/lib/libraryApi.ts`: `setAdvertisingHistory(brandId, value)`.

### 7. Contract pages

`docs/contracts/schedule.md`: `history.py` in the private-file list; the exported shape; the two routes; the
module-local decision "GET history writes the creative cache rows (pending) — a read that seeds its own
cache, ADR 0067 §1.9". `docs/contracts/brand_intelligence.md`: the new door in the file table and
`brand.advertising_history` as written by it.

## How we know it's done

Backend tests in a new `app/tests/test_past_ads_history.py`, on the pattern of
`app/tests/test_meta_daily_spend.py` (swap `graph.fetch_page`, own `background.app()`, real HTTP routes via
the test client the other route tests use — grep `TestClient` in `app/tests/` and copy the nearest).

1. **Ranking is the three lists, deduplicated, ≤15, in order.** Fixture: 12 ads in TWD with spends 1200…100 and
   ROAS such that the sets overlap on two ids → the card list has the expected ids in the expected order,
   each with the right `why`, and no id twice. A fixture of 20 ads with disjoint sets → exactly 15 cards.
2. **Money arithmetic is `_bucket`'s.** One ad with the contract page's four days (3,570 / 2,737.8, 3 of 4
   days tracked) → `roas_conservative` 0.767, `roas` 1.029, `roas_coverage` 0.75 (rounded as the page states).
3. **Two currencies never mix.** Two accounts, TWD and USD, bound to one brand → two `currencies` entries,
   each ranked on its own; no card carries the other currency.
4. **The GET seeds the cache once.** First GET: `fetch_ad_creatives` is called with exactly the card ids;
   rows exist with `creative_fetched_at` set, including the id Meta answered `None` (body NULL). Second GET:
   zero creative calls. A `GraphError` on the first GET: 200, every card `creative: null`,
   `creative_error` set, zero rows written.
5. **Tagging validates against this brand's vocabulary.** PUT with a key that exists for another brand →
   400 `coordinate_unknown`; a key under the wrong dimension → 400; a valid set → 200, row `tagged`, audit row
   present; PUT again with different keys → still one row (`count(*)` on the unique key), new values; PUT
   with all seven `null` and a note → `coordinates_status = 'pending'`, note stored; PUT on an `external_id`
   the GET never seeded → 404 `imported_ad_unknown`.
6. **Tenant boundary.** Org B's actor on org A's brand → 404 on GET and PUT and the brand-history PUT;
   `imported_ads_for_brand(org A, brand A)` never returns a row of brand B in the same org (two brands, one
   tagged each); the `ad_channel_id` written is org A's channel (composite FK holds).
7. **`advertising_history` PUT**: `"none"` and `"has_history"` stored and read back through the brand
   profile GET; `"maybe"` → 400 with `errors.value`; audit row.
8. **No LLM, no rule.** `grep -n "gateway\|create_rule\|llm_task" app/schedule/history.py` prints nothing;
   the tests assert `count(*) FROM rule` unchanged across a full GET+PUT sequence.
9. **Boundary gates**: `uv run pytest app/tests/test_architecture_boundaries.py app/tests/test_brand_isolation_all_tables.py app/tests/test_org_isolation_all_tables.py -q`
   green with the new export; `KNOWN_MODULE_SIZES["app/schedule"]`, `["app/brand_intelligence"]`,
   `["app/brand_web"]` and `TEST_LINES_CEILING` rise by measured amounts with reasons.
10. **Machine gate**: `unset BRAND_OS_LLM_PROVIDER`; `uv run ruff check app` · `uv run pyright` ·
    `uv run pytest app/tests/test_past_ads_history.py app/tests/test_brand_delete.py -q` ·
    `cd frontend && npm run typecheck && npm run build` · `cd frontend && npm run e2e` (own 8720 backend).

## Shared files touched

Searched 2026-09-08 across the whole repo, unscoped (same exclusions as tickets 01/02; ADR 0067 and this
folder excluded):

```
grep -rn history_cards .            → (no hits)
grep -rn tag_imported_ad .          → (no hits)
grep -rn imported_ad_count .        → (no hits)
grep -rn set_advertising_history .  → (no hits)
grep -rn "brands/{brand_id}/history" . → (no hits)
grep -rn advertising-history .      → (no hits)
grep -rn coordinate_unknown .       → (no hits)
grep -rn imported_ad_unknown .      → (no hits)
```

Files this ticket edits:

```
app/schedule/history.py                              (new)
app/schedule/repository.py                           (four SQL functions; 625 lines before ticket 01)
app/schedule/__init__.py                             (imported_ad_count)
app/schedule/routes.py:487-613                       (two routes + request/response models; 613 lines)
app/brand_intelligence/advertising_history.py        (new)
app/brand_intelligence/__init__.py                   (only if the module's import convention needs it — read it first)
app/brand_web/routes_library_write.py:370-400        (one route)
app/brand_web/routes_library.py:210-218              (_brand_profile_shape)
frontend/src/lib/scheduleApi.ts, frontend/src/lib/libraryApi.ts
docs/contracts/schedule.md, docs/contracts/brand_intelligence.md
app/tests/test_past_ads_history.py                   (new)
app/tests/test_architecture_boundaries.py            (ratchets)
```

## Contradiction check

- **Done-check 4 (a GET writes rows) vs done-check 8 (nothing but `imported_ad` is written).** They agree
  only while the GET's writes are the cache upsert and nothing else; the input that would show a conflict is
  a GET that also wrote `tagged_at` or a rule — the `count(*) FROM rule` assertion and the `coordinates_status
  = 'pending'` assertion on seeded rows are the two witnesses.
- **Done-check 1 (`bottom_roas` uses optimistic ROAS) vs done-check 2 (verdict `lose` uses optimistic
  ROAS < breakeven).** Consistent by construction (ADR 0066 rule 4). The reading that could drift: an ad with
  spend and **no** tracked revenue — it is excluded from `top_roas`/`bottom_roas` (revenue None) and its
  verdict is `unclear`, never `lose`; the fixture in check 1 must contain one such ad to pin this.
- **Cheapest wrong implementation that leaves every check green:** validating a key against the brand's
  coordinate *keys* without the *dimension* (a key string reused across dimensions passes). Check 5's
  "key under the wrong dimension → 400" exists for that; the fixture must reuse one key string across two
  dimensions.
