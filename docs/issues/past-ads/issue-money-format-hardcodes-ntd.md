# `formatCurrency` hardcodes `NT$`, so a USD ad account's money reads as NT$

Status: open (found at ticket 04 review, 2026-09-08; not fixed there — the ticket prescribed the helper).

Cause: `frontend/src/lib/format.ts:6` prefixes every amount with `NT$ ` regardless of the row's
currency. The backend buckets by `row["currency"]` (`app/schedule/history.py:213-236`, ADR 0057 §4),
so the history screen prints a `USD` section header over `NT$ 500` cards (`frontend/src/components/intake/HistoryPage.tsx:163,245,249`).
The same pattern already ships on Meta money at `frontend/src/components/cockpit/DiagnosisPanel.tsx:201`;
the sibling that does it right is `PerformanceDetails.tsx:322` (`${value.toLocaleString("zh-TW")} ${currency}`).

Impact: any tenant whose Meta account bills in a currency other than TWD sees the wrong symbol on
every money figure the helper formats. No arithmetic is wrong; the label is.

Fix shape: give `formatCurrency` a `currency` argument (or a sibling `formatMoney(value, currency)`)
and change every call site that has a currency in hand — a shared-helper change across features, so
its own ticket, with `docs/design-system.md` §7 amended to say money carries its currency.
