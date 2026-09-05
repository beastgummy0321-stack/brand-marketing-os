# 04 — `_row_hash()` normalises numbers before hashing

Route C (money flow). Graduated from `issue-row-hash-numeric-normalisation.md` (2026-09-05).

## What

`app/orders/channel.py:177-183` `_row_hash()` feeds `revenue` and `quantity` into `json.dumps`
exactly as received. `json.dumps(5000)` is `"5000"` and `json.dumps(5000.0)` is `"5000.0"`, so
the same logical row hashes two different ways depending on the caller's Python type. The hash
is the dedupe key for hand-entered channel revenue (`channel_revenue.source_row_hash`, partial
unique index `idx_channel_revenue_brand_channel_row_hash`), so a type mismatch silently inserts a
second row and doubles that day's revenue.

The contract after this ticket: **`_row_hash()` is stable across `int`/`float`/`Decimal` inputs
that represent the same number, and `None` stays `None`.** Normalise inside `_row_hash()`, not at
its caller — the caller-side guarantee is exactly what this ticket exists to remove.

Literal example — all three of these must return the same hexdigest, and the fourth must differ:

```json
[
  {"channel": "pharmacy", "entry_date": "2026-09-05", "revenue": 5000,     "quantity": 3,    "note": null},
  {"channel": "pharmacy", "entry_date": "2026-09-05", "revenue": 5000.0,   "quantity": 3.0,  "note": null},
  {"channel": "pharmacy", "entry_date": "2026-09-05", "revenue": "5000.0", "quantity": "3",  "note": null},
  {"channel": "pharmacy", "entry_date": "2026-09-05", "revenue": null,     "quantity": null, "note": null}
]
```

`None` must not become `0.0` — a row with no revenue is not a row with zero revenue, and
`float(None)` raises. Do not touch `record_channel_entry()`'s signature, the SQL, the index, or
the two automatic paths (`save_shopee_rows` / `_sync_website_channel_revenue`), which deliberately
leave `source_row_hash` NULL and dedupe on `external_id` instead (migration
`20260904000001_orders_channel_revenue_dedupe.sql:12-14`).

Existing stored hashes are not a migration concern: today's only production caller is the HTTP
form, which passes everything through `parse_number()` (`app/shared/web.py:291-298`, always
`float | None`), so every hash already on disk is the float spelling — which is the spelling this
ticket standardises on. **Normalise to `float`, not to `int` or to a string**, for that reason.

## How we know it's done

1. `uv run ruff check app` — clean.
2. `uv run pyright` — 0 errors.
3. One new test in `app/tests/test_orders_channel.py` calling `_row_hash` directly asserts the
   four rows above: rows 1–3 produce one identical digest, row 4 produces a different one.
   Proven red once before it counts: revert the `float()` normalisation, see this test fail,
   restore. Run with `uv run pytest app/tests/test_orders_channel.py -q`.
4. A second assertion in the same test, on the real write path: call
   `record_channel_entry(..., revenue=5000, quantity=3)` then
   `record_channel_entry(..., revenue=5000.0, quantity=3.0)` with the same brand/channel/date and
   assert `SELECT count(*) FROM channel_revenue` is 1, not 2. This is the money bug itself; the
   digest assertion alone would pass on a hash change that broke the SQL.
5. `uv run pytest app/tests/test_orders_channel.py app/tests/test_architecture_boundaries.py -q`
   — green (the boundaries file carries the line ledger for this module).
6. `cd frontend && npm run e2e` — green (backend ticket still runs the one smoke; `supabase start`
   must be up first).

No migration, no schema change, no new column: `## Shared files touched` below must match
`git diff --name-only` exactly.

## Shared files touched

Unscoped repo-wide search for `_row_hash` (the name that changes meaning), excluding
`.git/node_modules/dist/.scratch/backups/__pycache__`:

```
./app/orders/channel.py:177:def _row_hash(channel: str, entry_date: str, revenue, quantity, note: str | None) -> str:
./app/orders/channel.py:202:    row_hash = _row_hash(channel, entry_date, revenue, quantity, note)
./app/orders/channel.py:206:    # external_id 可用，用 (brand_id, channel, source_row_hash) 對齊新的 partial unique
./app/orders/channel.py:211:        " AND source_row_hash = %s",
./app/orders/channel.py:226:            " quantity, note, source, source_row_hash, created_at, updated_at)"
./app/tests/test_architecture_boundaries.py:1220 (comment, ledger)
./app/tests/test_orders_channel.py:99,102,104 (asserts the Shopee path leaves it NULL)
./docs/adr/0050-the-ad-loop-data-model-is-one-table-list.md:89
./docs/adr/0057-performance-meets-the-coordinate-at-the-depth-three-binding.md:181
./supabase/migrations/20260904000001_orders_channel_revenue_dedupe.sql:12,21,23,24,25
```

Only `app/orders/channel.py` and `app/tests/test_orders_channel.py` may appear in the diff. The
migration file is already applied and must not be edited (constitution: applied migrations are
never edited). The two ADR lines describe the column, not the hash recipe, and stay as they are.

Non-HTTP caller that already exists and already passes Python `int`:
`app/tests/test_orders_channel.py:188-190,198,201-203`.

## Contradiction check

Done-check 3 (digest stability) and done-check 4 (one row in the DB) can contradict each other:
a change that makes `_row_hash` return a constant passes 3 and 4 both, while destroying dedupe
between genuinely different rows. The input that shows it: two entries on the same date and
channel differing only in `note` — they must still land as **two** rows (`channel.py:172-174`
says this is deliberate: two pharmacy deliveries on one day). Add that as the third assertion in
the same test, so a constant hash cannot pass.
