---
id: 0050
decision: The ad-loop data model of record is this ADR's table list, not a board row and not the published diagram.
applies-to: [supabase/migrations/, app/schedule/]
supersedes: none
status: in-force
---

# The ad-loop data model is one table list, and it lives here

2026-09-01. Gate A for the ads & scheduling module was signed the same day
(`CONSTITUTION.md`), and its "how" was published as a diagram:
<https://claude.ai/code/artifact/534811bd-7078-424c-b839-7493b2c73b25>, §4 (the table list)
and §10 (the doors). **The diagram is a picture, outside the repo, and cannot be read by an
agent working here.** Until today the table shapes existed only in `BOARD.md` ticket rows —
and the board's own rule is that a row is deleted when its ticket is done, which would have
deleted the decisions with it.

This ADR is the record. The diagram stays as the readable overview; where the two differ, this
file wins.

## What changed against the diagram (verified in the repo on 2026-09-01)

The diagram's §9 list of "broken right now" was checked line by line. Four entries do not
survive; they are corrected here so nobody builds on them.

| Diagram §9 says | Verified |
|---|---|
| `app/meta` never registered a cleanup function, so deleting a brand bound to Meta fails today | **False.** `app/meta/repository.py:526` calls `cleanup.register(` |
| `meta_entity_spend`'s FK is `ON DELETE CASCADE`, so unbinding an ad account destroys all spend history | **Already fixed**, `supabase/migrations/20260901000001_meta_spend_history_restrict.sql` — now `ON DELETE RESTRICT` |
| Uploads have no size limit | **False.** `app/brand_web/routes_library.py:57` caps at 50 MB and checks it twice (`:79`, `:273`). What is missing is only the bucket-side `file_size_limit` in `20260830000002_core_storage_assets_bucket.sql` — a second line of defence, not the first |
| Deleting a product photo is a naked DELETE with no FK, so it 500s and breaks finished creatives | **Not found.** There is no `product_photo` table; `delete_official_asset` (`app/brand_intelligence/repository.py:1151`) goes through the shared `_delete_entity`. The "breaks finished creatives" case needs the creative tables, which do not exist yet |

One more is a future door, not a present bug: `_tree_signature`
(`app/schedule/routes.py:213-224`) does fold `daily_amount` into the approval hash, but nothing
in the repo changes `daily_amount` on its own, so no approval can be invalidated today. It bites
when automated budget changes ship — see the open questions below.

## The table list

`module` is the prefix its migration file must carry (ADR 0049 rule 2) — not the ticket that
wants it. `ticket` is the board row that lands it.

### New tables

| table | module | ticket | the columns that are the decision |
|---|---|---|---|
| `brand_coordinate` | schedule | T1b | `dimension` seven values in one CHECK · stable `key` (the 35 seeds use a global key) · `label` / `category` / `parent_id` · `canonical_key` · `disabled_at` · `unique(brand_id, dimension, key)` |
| `creative_slot` | schedule | T1b | the seven dimensions as "what this slot wants now" · `status` including `exhausted` |
| `creative_candidate` | schedule | T1b | **the seven dimensions frozen again here at generation time** · `generation_round` · `selected_at` · `reject_reason` · `published_ad_external_id` · `provider` / `provider_job_id` / `provider_status` · `llm_task_id` |
| `creative_candidate_item` | schedule | T1b | carousel: `candidate_id` · `position` · `fields_json` (array values from day one) · exactly one row in v1 |
| `feedback` | schedule | T1b | `scope` CHECK `('coordinate','candidate','period')` — all three values defined now, only the first two written in v1 · `reason_code` · `note` · `lifted_at` · all three owner columns nullable |
| `campaign_period` | schedule | T2 | `version` (optimistic lock) · `status` four values (planning／running／awaiting_data／settled) · `force_settled_at` / `reason` · **`settled_spend` / `settled_revenue` / `settled_at` snapshot** · `cpa_basis` · `currency` · `recurrence_rule` / `source_period_id` |
| `campaign_period_budget_version` | schedule | T2 | shaped like `sku_cost_version` · `change_type` including `auto_decrease` · `actor_kind` (human／system) · `reverted_from_id` |
| `ad_set_period_membership` | schedule | T2 | `from_date` / `to_date` · `allocation_weight` DEFAULT 1.0 · **never add `unique(ad_set_id)`** |
| `product_economics_version` | brand_intelligence | T2 | append-only · **half-open interval** (`< effective_to`) · EXCLUDE constraint against overlap |
| `holiday` | schedule | T2 | `source` / `source_key` / `holiday_date` · `campaign_skip` (core) repoints at it, its `year` column becomes a date |
| `channel_entity_map` | schedule | T3 | path-style `node_key` · `external_id` · **`external_status` stores the platform's own words** plus a separate `local_state` · `learning_reset_at` · `unique(org_id, brand_id, node_key)` is the idempotency key |
| `ad_channel` | schedule | T4 | five capability flags each with its own CHECK · `last_data_at` / `data_lag_days` · `spec jsonb` (level count, platform minimum daily budget) |
| `ad_channel_format_spec` | schedule | T4 | keyed on **(channel, format)**, not channel · `field` / `max_chars` / `aspect_ratio` |
| `channel_credential` | schedule | T4 | replaces `meta_credential` (whose PRIMARY KEY is `org_id` — one token per organisation) · `unique(org_id, channel_id, account_scope)` · `expires_at` · `last_error_code` · `scopes` · Vault logic carries over unchanged |

### Existing tables that change

| table | module | ticket | change |
|---|---|---|---|
| `official_asset` | brand_intelligence | T1b | `storage_key` (renamed from `file_path` in `20260830000003`) is `TEXT NOT NULL` today → relax to nullable and add `body_text` / `body_json`; add `parent_asset_id` (indexed) / `platform` / `aspect_ratio`, `superseded_by_asset_id`, `usable_until` / `provider` / `no_derivative`, `content_hash`, `unique(id, brand_id)` for composite FKs |
| `interrupt` | core | T2 | `dedupe_key` must include the period id, or two overlapping periods eat each other's warnings |
| `llm_task` | core | T2 / T5 | `campaign_period_id` so LLM cost has an owner (T2); breaking "the newest row is the truth" (`app/schedule/routes.py:133-139`) is a T5 job and is code, not schema |
| `brand_meta_ad_account` | meta | T3 | `allocation_weight` DEFAULT 1.0, **no unique constraint** — the application layer blocks a second brand, the schema does not |
| `meta_ad_account` | meta | T4 | `timezone_name` (Meta returns dates in the ad account's timezone; there is no such column today) · `rate_limited_until` · a soft-disable column |
| `meta_entity_spend` | meta | T5 | `currency` · index on `(adset_id, spend_date)`. The FK is already `RESTRICT` — done, see above |
| `channel_revenue` | orders | T5 | `spend` · `campaign_period_id` · `currency` · `ad_channel_id` · `source_row_hash` and a unique key. Verified today: 13 columns, none of them currency, and the only unique index is `WHERE external_id IS NOT NULL`, so hand-entered rows are not deduplicated at all |
| `learning_ledger` | brand_intelligence | T5 | fill it in while it is still empty: `coordinate_id` · `campaign_period_id` · `last_verified_at` · `status` (active／needs_revalidation／overturned) · `overturned_by_id` · `brand_id` FK. Verified today: the read side was deleted (`app/llm/context_compiler.py:17`) and `create_learning_ledger_entry` has **no production caller** |
| `decision` | core | T6 | add `entity_type` / `entity_id` · `campaign_period_id` · `acted_at` / `acted_by` · `revert_of` · `expires_at`. **Do not open a new table** — verified today: the table exists with `action_json` / `risk_level` / `dedupe_key` / `outcome`, and the codebase has zero references to it |
| `order_record` | orders | T6 | `utm_json jsonb`, stored as imported. Without it real gross margin can never be attached to an ad, and adding it later means re-importing every historical order |

## The doors that are not tables

Constitution rule 3 in three questions, asked of every "not in v1": (1) which table and column
holds it (built now, value may be NULL); (2) is its enum value already in the CHECK; (3) is
turning it on a switch, or a migration. Only "a switch" counts as open.

- **Asset body and its derivatives are one table**, but `parent_asset_id` / `platform` /
  `aspect_ratio` exist from day one (NULL on the body row). Splitting the table later is one SQL
  statement; without the parent key it is guesswork. This model was already built and torn down
  once (`creative_variant` and `final_asset`, both dropped).
- **Draw-again is two levels, not one row**: `creative_slot` (the position) and
  `creative_candidate` (the Nth attempt). v1 writes one candidate per slot; enabling draw-again
  is more rows, zero migration.
- **The seven dimensions are nullable**, plus a `coordinates_status` (tagged／pending／not
  applicable). Back-filling old ads is data entry, not a migration.
- **GA4's three numbers are a long table** `channel_metric(name, value)`, never three columns.
- **Character limits come from `ad_channel_format_spec`, never from a Python constant.** The
  methodology file stays as a prompt part.
- **`asset_kind` carries `copy` / `image` / `video_script` / `video` / `landing_page` now**; v1
  uses the first three. Note the name clash: `vocab.py` already uses `asset_kind` for
  logo／product_photo／packaging／other.
- **`ad_channel` is the name.** `channel` is taken three times over (`owned_channel`,
  `channel_revenue.channel`, `channel_plan.channel`).
- **Deliberately not reserved: the agency client layer** (org, client, brand). A permanently
  NULL `client_id` buys nothing; the real cost is the permission model. Adding it later means one
  column on every brand-scoped table plus a permission rewrite — written down here so the price
  is known rather than guessed.

## Open, and not settled by this ADR

Two decisions were found while writing it. Neither is filled in here.

1. **`approval.max_daily_amount` — what was approved is a ceiling, not the number of the day.**
   That changes the meaning of the money brake (ADR 0040) and touches the money path, so it needs
   the user's approval and its own ADR before T2 writes it. It is also the other half of the
   `_tree_signature` question above.
2. ~~**Rejected angles as a post-generation exclusion list, instead of `rule(severity='hard')`.**~~
   **Settled 2026-09-01 at T1b station (1), by the user.** A rejected angle is a `feedback` row
   with `scope='coordinate'`, and the picker skips it **before the prompt is built** — so a
   rejection costs nothing in prompt budget and lifting it is one column (`lifted_at`), not a
   rewritten rule. `feedback` does not sit beside ADR 0012's path; it replaces it for angles, and
   ADR 0012 keeps brand rules and gains nothing. `app/llm/context_compiler.py` and
   `app/core/rule_cards.py` were not touched by T1b.

   The two coordinate switches are not one mechanism wearing two names:
   `brand_coordinate.disabled_at` is the screen switch ("never this angle for this brand"),
   `feedback` is the loop judgement ("not this one, because …") and is what T5 counts. The picker
   skips a coordinate when either fires.

   Rejected, and recorded so it is not re-proposed: writing each rejection as a
   `rule(severity='hard')`. Hard rules bypass ADR 0012's twenty-rule cap, so every rejection would
   permanently consume prompt space with no ceiling — 35 angles per brand is an unbounded list;
   `rule` belongs to `brand_intelligence`, so `app/schedule/` would be writing another module's
   table (ADR 0049 rule 3); and a sentence of prose cannot be grouped or counted when performance
   comes back in T5. Also rejected: writing both, which makes one decision have two sources of
   truth and keeps the growth problem intact.
