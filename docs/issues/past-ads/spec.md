# past-ads — a brand that already advertised brings its own ads in

Goal (user's sentence, 2026-09-08): a brand that has already run ads gets a first plan built on its own
past results, instead of accumulating from zero. Rulings: ADR 0067. Vocabulary: `CONTEXT.md` 「舊廣告與投放史」.

## The picture

```
wizard step ① submitted
  └─ dialog, two buttons, no dismiss: 「我投放過廣告」 / 「我完全沒投放過」
       → brand.advertising_history = has_history | none        (changeable later on the brand page)
  └─ wizard continues ②…⑤ exactly as today

「建檔完成」 page, has_history brands: one more primary button 「把過去的廣告帶進來」
brand page (cockpit) guide card, has_history + 0 imported_ad rows: same button
  └─ /brands/:id/intake/history (component under frontend/src/components/intake/)
       1. not connected to Meta → link to /settings Meta section; 「我投的不是 Meta」 → step 3 with no ads
       2. connected → press starts background.meta_backfill (37 months, all three levels);
          progress = running? + earliest spend_date on record
       3. cards: ≤15 ads = top-5 spend ∪ top-5 conservative ROAS ∪ bottom-5 optimistic ROAS, all days;
          left: creative body/title/image (fetched for these ads only) + when it ran + spend + both
          ROAS + coverage + win/lose/unclear against breakeven_roas();
          right: seven dropdowns from the brand's coordinates (each may stay empty) + one line 「這則
          為什麼贏／輸？」; 「略過」 per card
       4. save per card → imported_ad row (tagged, owner_note verbatim); nothing written to `rule`
          (plan review 2026-09-08, ADR 0067 §1.5)
       non-Meta advertiser this round: the screen says 「這一輪只能從 Meta 帶進來；接上 Meta 後隨時可回來」
          with the settings link; nothing stored (an imported_ad row needs an external id)

after that, nothing new is needed: the coordinate chart, the diagnosis and the plan prompt read the
tagged imported ads through the second entrance (ADR 0067 §1.3) and the 【投放史】 section (§1.10).
```

No LLM call anywhere on this path. The only paid thing is Meta Graph reads (free) and the owner's minutes.

## Measured before writing (2026-09-08, local db + repo)

| fact | how |
|---|---|
| `meta_entity_spend`: ad 55 rows / 8 ads, adset 14 / 2, campaign 9 / 1, 2026-08-31..09-08, all three levels sum 15,746.00 TWD; 6 of 8 ads carry a `roas` on ≥1 day | `select level, count(*), count(distinct entity_id), min/max(spend_date), sum(spend), count(roas) … group by level` |
| `daily_pull.backfill(org_id, since, until)` exists, month-chunked, commits per chunk, refuses `since` older than 37 months | `app/meta/daily_pull.py:200-240` |
| `creative_candidate.slot_id` is `NOT NULL`; `coordinates_status` CHECK `('tagged','pending','not_applicable')` | `supabase/migrations/20260901000002_schedule_creative_coordinates.sql` |
| `brand_coordinate` is seeded lazily per brand: 35 angle seeds + 33 across the other six dimensions | `app/schedule/repository.py:7-23` |
| `rule.rule_type` has no DB CHECK; the vocabulary list is `app/core/vocab.py:32` `RULE_TYPES`; `create_rule` sets `status='active'`, `confirmed_at=now` | `app/brand_intelligence/repository.py:882-915` |
| the plan prompt already has program-built sections (`_account_performance_text`, `_last_period_text`, `_continuity_text`) appended in `jobs.schedule_plan()` | `app/schedule/jobs.py:164,252,335,370-467` |
| `performance.brand_creative_performance()` resolves an ad row's coordinates through `_slot_for_spend(bindings_by_entity[...])` → `candidates.get(...)`; a miss falls into 未標座標 | `app/schedule/performance.py:196-241` |
| guide cards are pure functions over a `facts` dict assembled in `app/dashboard/repository.py:130` | `app/dashboard/guide_cards.py` |
| `ui/dialog` exists; design system §6 allows a dialog only for confirming; ADR 0067 §1.6 reads the two-button choice as that pattern | `frontend/src/components/layout/ui/dialog.tsx`, `docs/design-system.md:253-254` |
| Meta: Ad node has `creative`; AdCreative exposes `body`, `title`, `image_url`, `thumbnail_url`, `object_story_spec`; insights `level` ∈ ad/adset/campaign/account; 37-month start-date limit is error 3018; nothing stated about deleted ads in insights | official references fetched 2026-09-08 (URLs in ADR 0067 §1.8–1.9) |
| `app/schedule/*.py` largest files: `repository.py` 625, `routes.py` 613; `app/meta/repository.py` 766 (96% of the 800 cap); `app/intake/routes_api.py` 716 (90%) | `wc -l` |

## Tickets (sequential, one Sonnet implementer each)

1. `01-schema-imported-ad-and-advertising-history.md` — route C, schema frozen and dormant: `imported_ad`
   (schedule migration), `brand.advertising_history` (brand_intelligence migration), isolation tests green.
2. `02-meta-backfill-task-and-creative-read.md` — route C (module `meta`, external API):
   `background.meta_backfill`, `graph.fetch_ad_creatives`, `POST /api/meta/brands/{id}/backfill` + status.
3. `03-history-read-and-tag.md` — route C (first writer of `imported_ad`; `brand.advertising_history`
   written through brand_intelligence): `GET /api/schedule/brands/{id}/history` (ranked cards),
   `PUT …/history/{external_id}` (tags + note → row), `PUT /api/brands/{id}/advertising-history`.
4. `04-fork-dialog-and-history-screen.md` — route B (frontend only, + the guide card rule): the dialog at
   step ①, the button on 「建檔完成」, the guide card, the `/brands/:id/intake/history` screen.
5. `05-second-entrance-and-plan-history-section.md` — route B (schedule internals): `performance.py`
   falls back to `imported_ad`; `jobs.schedule_plan()` appends 【投放史】.

`app/meta/repository.py` at 96% of the cap: ticket 02 puts its new reads in `daily_pull.py`/`graph.py`,
never in `repository.py`; if it must touch it, it stops and reports (workflow.md, boundary escalation).
