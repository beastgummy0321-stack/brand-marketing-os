---
id: 0067
decision: An ad the platform already ran enters coordinates as an imported_ad row its owner tags; no model infers why it worked.
applies-to: [supabase/migrations/, app/schedule/, app/meta/, app/brand_intelligence/, app/brand_web/, app/dashboard/, frontend/src/components/intake/]
supersedes: none
status: in-force
---

# An imported ad is tagged by its owner, never read by the model

2026-09-08, slice past-ads station ①. Amends **ADR 0057 §1** ("no new table" was said of the join for
*generated* creatives; this ADR adds a second entrance beside it) and closes **ADR 0057 §9**'s "legacy
ads get coordinates later". Does not touch ADR 0066: an imported ad is never scored by a period,
because it belongs to no period.

## 0. What was measured and what was paid, before this was decided

- Three rounds of "let the model read 37 months of Meta history and say why the ads worked" ran between
  2026-08-30 and 2026-09-01 (user's account, 2026-09-08): one prompt with everything (≈US$20), 37 subagents
  → 127 plans (≈US$20), 37 subagents plus one merger → 12 "decisions" (≈US$25). The inference leaned on ad
  names. Every one of the 12 was a guess; every one could have been obtained by asking the owner. That
  record is the reason for rule 1 and is not to be re-run.
- What the pipeline already does, measured 2026-09-08 on the local database: `meta_entity_spend` holds
  ad/adset/campaign rows whose three levels sum identically (15,746.00 TWD over 2026-08-31..09-08 for the
  bound account), `daily_pull.backfill()` accepts any `--since` inside Meta's 37-month retention, and
  `creative_candidate` carries seven nullable `*_key` columns plus `coordinates_status`.
- The join path of ADR 0057 (`creative_candidate → creative_slot → channel_entity_map depth 3 →
  meta_entity_spend`) has no entrance for an ad that did not come out of a tree: `creative_candidate.slot_id`
  is `NOT NULL`, a slot needs a tree, a binding needs a node.

## 1. Rulings

1. **Numbers come in by program; reasons come from the owner.** Spend, impressions, clicks, ROAS are pulled
   and ranked by arithmetic. Which audience, angle, offer an old ad carried — and why it won or lost — is
   asked of the owner, who picks from the brand's own coordinate vocabulary and writes one line. No LLM call
   reads history, proposes tags, or summarises. A future ticket that wants "AI-suggested tags from the
   creative text" is proposing the same guess with a different input and is rejected here in advance.
2. **`imported_ad` is the row, and it is channel-shaped from day one.** Owned by `schedule`
   (its migration carries that prefix, ADR 0049). Columns that are the decision: `ad_channel_id` with the
   composite FK `(ad_channel_id, org_id) → ad_channel(id, org_id)`; `external_id`; `external_name`;
   `first_seen_date` / `last_seen_date` (from the spend rows, so the screen can say when it ran);
   `creative_body` / `creative_title` / `creative_image_url` / `creative_fetched_at` (a cache of what the
   platform returned, nullable — "the platform no longer returns this one" is a state, never a blank filled
   in); the seven `*_key` columns nullable, `coordinates_status` with the same CHECK as
   `creative_candidate`; `owner_note` (the verbatim line); `tagged_at` / `tagged_by`;
   `unique(org_id, brand_id, ad_channel_id, external_id)`. The row is a fact about one ad on one channel; it
   is not versioned — an owner retagging their own memory overwrites it, and `audit_log` keeps the before.
   Performance rows stay in the channel's own table (`meta_entity_spend` today; a second channel gets its
   own, ADR 0055 §8). Opening Google/TikTok/Shopee imports later is a new spend table plus a CSV screen —
   `imported_ad` itself needs no change (constitution rule 3).
3. **The coordinate view gets a second entrance, and the bucket invariant does not move.** For an ad-level
   spend row, the coordinates are those of the depth-3 binding live on that date (ADR 0057 §1, ADR 0064)
   **or else** those of the `imported_ad` row with the same `(ad_channel, external_id)` and
   `coordinates_status = 'tagged'`. A binding wins when both exist. Tagged + 未標座標 still equals the
   brand's total ad-level spend per currency (ADR 0057 §5).
4. **Not a candidate, not a slot, not a binding.** `creative_candidate` means "the system generated this";
   a `creative_slot` is a position on a tree; a `channel_entity_map` row ties a tree node to an entity.
   An old ad is none of these, and lending it any of those rows would make a name change meaning.
5. **The owner's reason travels with the ad, not as a rule.** `imported_ad.owner_note` holds the line
   verbatim; the 【投放史】 section (§1.10) carries it into the plan prompt beside that ad's numbers and
   coordinates. Nothing is written to `rule`. Settled at plan review, 2026-09-08, and confirmed by the
   user: a rule per interviewed ad would take up to 15 of the 20 soft-rule slots (ADR 0012,
   `app/llm/context_compiler.py:49-56`), evicting older rules with no screen left to show the eviction
   (`list_overflow_rules` and its page are gone), and it would put the same sentence into the prompt twice.
6. **The fork is a brand fact.** `brand.advertising_history` (`brand_intelligence` migration), CHECK
   `('has_history','none')`, nullable = not yet answered. Asked once, in a two-button `ui/dialog`, the moment
   the wizard's first step is submitted (user ruling 2026-09-08); changeable from the brand page; the
   cockpit guide card reminds a `has_history` brand with zero `imported_ad` rows to bring its ads in.
   The design system's "no modal forms" (§6) is read as: a form is fields; this is a choice with two
   buttons and no dismiss, the closest existing pattern being the Confirm dialog.
7. **Which ads are asked.** Over every pulled day: the 5 highest by spend, the 5 highest by conservative
   ROAS among ads with tracked revenue, the 5 lowest by optimistic ROAS among ads with spend — deduplicated,
   at most 15, each skippable (user ruling 2026-09-08). Win/lose uses `diagnosis.breakeven_roas()`; with no
   break-even the lists still rank and the screen says no line was drawn. No sample-size constant
   (`ab-testing.md:73`).
8. **Backfill is a background task, 37 months, one per organisation.** `background.meta_backfill` in
   `app/meta`, lock `meta_backfill:{org_id}`, started by the owner's press, reusing `daily_pull.backfill()`
   unchanged. Progress is `background.is_active(lock)` plus the earliest `spend_date` on record — no new
   table. Whether Meta's insights include deleted or archived ads is not stated in the official reference
   (checked 2026-09-08, developers.facebook.com/docs/marketing-api/reference/ad-account/insights/); the
   screen says "the ads Meta still returns", never "everything you ever ran".
9. **Creative text and image are fetched only for the ads being asked about**, at most 15, via
   `GET /{ad-id}?fields=creative{body,title,image_url,thumbnail_url,object_story_spec}` (Ad node `creative`
   field, developers.facebook.com/docs/marketing-api/reference/adgroup/; AdCreative fields
   developers.facebook.com/docs/marketing-api/reference/ad-creative/; nested expansion is Graph API field
   expansion). Cached on the `imported_ad` row. An ad whose creative is not returned shows "Meta 現在回不出
   這則的素材".
10. **The plan prompt gains one program-built section, 【投放史】**: the tagged imported ads with their
    coordinates and numbers, placed after 【上一期】 and before the role text, because position decides
    whether a section is read (`docs/contracts/schedule.md`, "Position in the prompt decides").

## 2. Considered and rejected

- **The model reads the history** (all three shapes in §0). Rejected by the user, 2026-09-08, with the bill.
- **AI-suggested tags from creative body + image + targeting, owner confirms.** Same guess, new input; the
  owner picks seven dropdowns in less time than reading a suggestion. Rejected 2026-09-08.
- **Interview only, no numbers.** Cheapest (one wizard question); rejected because without the real ranking
  the owner recalls what they liked, not what earned, and old ads never reach the coordinate chart.
- **Numbers + interview, but stored only as rules.** Rejected: the coordinate chart and the diagnosis would
  still show every old ad as 未標座標.
- **Store the owner's line as a soft rule as well as on the row.** Rejected at plan review (§1.5).
- **Tagging through `creative_candidate` with a synthetic slot.** Rejected, §1.4.
- **CSV import for Google/TikTok/Shopee in this round.** Deferred, not closed: `imported_ad.ad_channel_id`
  and `ad_channel` (`google`/`tiktok` already in the catalogue) are the seat; the spend table and the upload
  screen are the switch. A non-Meta advertiser this round gets the interview without numbers.

## 3. What we looked at (reuse-first §2)

The repo's own retired draft `.scratch/adloop/S2-DESIGN.md` — the reading-conclusions ledger, rejected
above. The market search recorded in ADR 0055 §12 was not repeated; no external tool was evaluated for
this decision, and none is installed. Commercial creative-analytics products that auto-tag ads with a model
were not examined, because rule 1 rules that approach out regardless of vendor.
