---
id: 0049
decision: The schedule module owns migrations; every migration file takes the prefix of the module that owns the table it creates.
applies-to: [supabase/migrations/, app/schedule/, app/tests/test_migration_ownership.py]
supersedes: none
status: in-force
---

# The schedule module owns its migrations

2026-09-01, settled before T1b is written. Module-boundary decision (constitution rule 2), so it
is an ADR and not a ticket line.

## The wall

`app/tests/test_migration_ownership.py:16` holds the registry:

```python
MODULES = ("core", "brand_intelligence", "intake", "ads", "orders", "identity", "background", "meta")
```

`schedule` is not in it. The first ad-loop migration named `<ts>_schedule_creative.sql` fails
`test_every_file_names_a_known_module` on the filename alone, before a single table is created.
T1b cannot be written until this is answered, and the answer is not the ticket's to give.

## The ruling

1. **`schedule` becomes a migration-owning module.** `MODULES` gains the string. The tables the
   ad loop creates — the ones ADR 0050 lists as new — are created by `<ts>_schedule_*.sql` files
   and belong to this module.
2. **A migration file's prefix names the module that owns the table, never the ticket that wanted
   the change.** T1b adds columns to `official_asset`, which `brand_intelligence` owns; that goes
   in `<ts>_brand_intelligence_*.sql`, in the same ticket, as a separate file. One ticket, several
   files, each under its owner's name.
3. **The write path stays with the owner too.** A new column on another module's table is written
   through that module's repository function, not by reaching into its table from
   `app/schedule/`. Container contract rule 2.

Rule 2 is the part the ownership gate cannot see: `test_migration_ownership.py` only inspects
`CREATE TABLE`, so an `ALTER TABLE` on somebody else's table under the wrong prefix passes the
machine and still breaks the boundary. The precedent is already in the repo —
`20260901000001_meta_spend_history_restrict.sql` alters a `meta` table under the `meta` prefix and
says so in its header.

## Considered and rejected

- **Put the ad-loop tables under the `ads` prefix** (free since `app/ads/` was deleted, ADR 0030).
  Rejected: the code lives in `app/schedule/`, so the table prefix and the module directory would
  disagree from day one, and every future reader has to learn the mapping.
- **Hang `brand_coordinate` and the `creative_*` tables off `brand_intelligence`.** Rejected: it
  is true of `brand_coordinate` alone. The campaign-period, channel and candidate tables have no
  home there, and splitting one data model across two owners is the boundary fault this ADR
  exists to avoid.
- **Widen the gate instead** — make `_module_of` accept unknown prefixes. Rejected outright: that
  is turning a gate green by loosening what it applies to.

## What we looked at

No external search. This adds one row to a registry the repo already has and already enforces;
it is a naming convention, not a capability, so reuse-first §2 has nothing to compare against.

## Consequences

- `MODULES` gains `"schedule"` in the ticket that writes the first schedule migration (T1b).
  Changing that tuple is the visible part of this decision, and it is the only code change here.
- The `ads` prefix stays retired. Nothing new is created under it.
