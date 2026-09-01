---
id: 0035
decision: A sales channel is a row plus an importer, not a table, a pair of endpoints and a screen of its own.
applies-to: [app/orders/]
supersedes: none
status: in-force
---

# Channels are data, and there is one offline channel

A sales channel is a row, not a module. Adding a channel adds an importer; it does not add a
table, a set of functions, a pair of endpoints and a screen section.

The repo currently does the opposite. Each channel grew its own everything:

| Channel | Table | Code |
| --- | --- | --- |
| Own site (EasyStore) | `order_record`, `order_item`, `customer` | `app/orders/importer.py` |
| Shopee | `shopee_report_row` | `app/orders/channel.py` |
| Pharmacy | `pharmacy_batch` | `channel.py:164-239`, `routes_api.py:148`, plus a screen block |

`pharmacy_batch` is the clearest case: one table, four functions, two endpoints and a UI
section, existing for one kind of business selling through pharmacies. MOMO cannot be added
because there is nowhere to put it — not because its API is missing.

**The user's ruling, 2026-08-29: "no more pharmacy channel, car-dealer channel, wholesale
channel. Call it offline and be done."** MarketingOS does not serve one industry.

## The shape

One channel-revenue table carrying `org_id`, `brand_id`, **`channel`**, date, external order
id, revenue, quantity, source and import batch. The `channel` value comes from the existing
`CHANNEL_TYPES` list in `app/core/vocab.py` — `website`, `marketplace`, `physical_store` —
rather than a second spelling of the same idea invented here.

- `website` — own site. EasyStore importer, already validated against the user's real export.
- `marketplace` — Shopee, MOMO, any platform. One importer per platform; the table does not
  change.
- `physical_store` — **one category for every offline channel.** Pharmacies, car dealers,
  wholesalers, anything. Recorded by hand.

Ad spend arrives the same way, keyed by platform rather than channel, and the dashboard joins
the two. That join is the product: one page showing what was spent and what came back across
every channel, which is the second failure named in ADR 0034.

## What this costs

**The pharmacy record loses its bespoke shape.** `pharmacy_batch` holds `batch_date`,
`quantity` and `note` — a *shipment*, not a sale, with no revenue figure. The signal it was
built for (restocking intervals shortening) went with `app/ads/`, so what remains is a date, a
count and a note. Those fit the generic row with revenue left null. Anything more specific than
that is gone, and if it turns out to matter it comes back as a channel-specific importer, not
as a channel-specific table.

**Shopee's column mapping is still unverified.** `app/orders/channel.py` says so in its own
docstring: the alias table was written from plausible Seller Centre column names and has never
been run against a real export. Moving it to a new table does not fix that; calibrating it
against a real file is a separate ticket and comes first.

## Consequences

- **`cycle_shopee_code` is deleted.** No production code reads or writes it and its foreign key
  points at `campaign_cycle`, which was dropped with the ads tables.
- **Adding a channel is one importer plus a row in the vocabulary list.** No migration, no new
  endpoint, no new screen.
- **This is a schema change** and therefore route C: ticket, Sonnet implementer, a different
  Sonnet reviewer.
