# 06 — an existing brand can say 「投放過廣告」 from the brand profile panel

Route B (frontend only; the backend route `PUT /api/library/brands/{id}/advertising-history` already exists
from ticket 03 and is reused unchanged). Ruling: ADR 0067 §1.6 — the fork is a brand fact, "changeable from
the brand page". The dialog's own copy promises it (「選了之後可以在品牌頁改」) and ticket 04 shipped no such
control, so a brand created before 2026-09-08 (Beast Prime, `brd_bughunt`) has no screen path to the
「把過去的廣告帶進來」 page. **No LLM call anywhere.**

## What

`frontend/src/components/library/panels/BrandProfilePanel.tsx` (the 「編輯品牌資料」 side panel, `LibraryPage.tsx:145`):

1. A fourth `select` after 廣告目標, label 「以前投放過廣告嗎？」, options 「尚未回答」 (`""`),
   「投放過廣告」 (`has_history`), 「完全沒投放過」 (`none`), initial value from `profile.advertising_history`
   (`libraryApi.ts:105`). Same markup as the three existing selects (`:169-215`).
2. On save (`useFormSubmit`, `:74-83`): after the existing `editBrandProfile(...)` resolves, if the select's
   value differs from `profile.advertising_history` and is not `""`, call `setAdvertisingHistory(brandId, value)`
   (`libraryApi.ts:447-453`). 「尚未回答」 never writes (there is no way back to NULL; the CHECK allows only the
   two values). A failure of the second call surfaces as the form's error line and keeps the panel open.
3. Under the select, when the *saved* value is `has_history`: a `Link` 「把過去的廣告帶進來 →」 to
   `/brands/<id>/intake/history`, wording per `docs/design-system.md` §8.

Literal example of what the panel sends when the owner picks 投放過廣告 on an existing brand:

```json
{"first": {"request": "POST /api/library/brands/brd_bughunt/edit", "body": {"name": "Beast Prime 野獸至尊", "client_name": "", "status": "active", "persona": "", "market_region": "TW", "conversion_goal": "purchase"}},
 "then":  {"request": "PUT /api/library/brands/brd_bughunt/advertising-history", "body": {"value": "has_history"}},
 "overview_card_afterwards": {"title": "你說這個品牌投放過廣告——把過去的廣告帶進來，方案才用得上", "action_url": "/app/brands/brd_bughunt/intake/history"}}
```

No backend change, no new API client, no schema.

## How we know it's done

1. **Machine gate**: `cd frontend && npm run build && npm run lint && npm run depcruise && npm test` ·
   `cd frontend && npm run e2e` (own 8720 backend, `supabase start` first, shut it down after).
2. **Walk (WALK subagent, playwright-cli, stand-in backend `uv run python -m scripts.drill.serve --port 8720`, account `123@example.com`/`123456`)**:
   1. Open `/app/brands/brd_bughunt/library`, press 「編輯品牌資料」 → the side panel shows the new select
      with 「尚未回答」 selected (Beast Prime was never asked). Screenshot.
   2. Pick 「投放過廣告」, 「儲存」 → the panel closes or shows saved; reopen it → 「投放過廣告」 selected and the
      「把過去的廣告帶進來 →」 link is under it. Screenshot.
   3. Open `/app` → the Beast Prime card's `next_step` is now 「你說這個品牌投放過廣告——把過去的廣告帶進來，方案才用得上」
      **only if** the brand has zero `imported_ad` rows; the seeded walk brand has tagged rows, so instead
      confirm on a brand with none (create one with the wizard choosing 「完全沒投放過」, then flip it to
      「投放過廣告」 in its panel) → its overview card carries the link. Screenshot.
   4. Click the panel link → `/app/brands/<id>/intake/history` opens. Screenshot.
   5. Pick 「完全沒投放過」 on that brand, save, reload → the select shows 「完全沒投放過」 and the overview card
      no longer carries the past-ads link. Screenshot.
   6. Console: no errors on the library page.

## Shared files touched

Searched 2026-09-08, whole repo, unscoped (same exclusions as the earlier past-ads tickets):

```
grep -rn "以前投放過廣告嗎" .   → (no hits)
grep -rn setAdvertisingHistory . → frontend/src/lib/libraryApi.ts:446 (definition), frontend/src/components/intake/AdvertisingHistoryDialog.tsx (the dialog) — both stay as they are
```

Files this ticket edits:

```
frontend/src/components/library/panels/BrandProfilePanel.tsx   (the select, the second call, the link)
```

If `LibraryPage.tsx` must re-read the profile after the second call to show the saved value (its `onSaved`
already re-fetches after `editBrandProfile` — check `:145-160` before assuming), that file is the one
allowed extra, named in the report.

## Contradiction check

- **Done-check 2 step 2 (reopen shows the saved value) vs the two-request save.** If the profile edit
  succeeds and the history PUT fails, the panel shows an error and stays open while the profile is
  already saved — the owner presses 儲存 again, which re-sends both; the profile edit is idempotent and the
  PUT then succeeds. Input that shows it: a 400 on the PUT (value `"maybe"` cannot be produced by the
  select, so the realistic input is a network failure on the second call).
- **Cheapest wrong implementation that leaves every check green**: writing `advertising_history` on every
  save even when unchanged — harmless to the checks but produces an audit row per save; step 5's reload
  check does not catch it. Send the PUT only when the value changed; say so in the report.
