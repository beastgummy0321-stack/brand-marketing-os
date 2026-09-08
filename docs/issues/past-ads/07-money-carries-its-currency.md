# 07 — money that came from a platform row carries that row's currency

Route B (frontend only; one new helper, three screens re-pointed). Rule: `docs/design-system.md` §7 as
amended 2026-09-08 (ADR 0065 makes that file the only frontend rule); ADR 0057 §4 (one brand may bind
accounts in two currencies; never add across them). Graduated from `issue-money-format-hardcodes-ntd.md`.
**No backend change, no LLM call.**

## What

1. `frontend/src/lib/format.ts`: add `formatMoney(value: number | null, currency: string): string` —
   `null` → 「累積中」 (same rule as `formatCurrency`, the file's header comment); otherwise
   `${Math.round(value).toLocaleString("zh-TW")} ${currency}` (the shape `PerformanceDetails.tsx:322`
   already uses by hand). `formatCurrency` stays for the system's own TWD figures and is not changed.
2. Re-point every `formatCurrency(` call whose screen has the row's currency in hand:
   - `frontend/src/components/intake/HistoryPage.tsx` — spend, revenue and CPA on each card use the
     section's `currency.currency` (the per-currency section at `:161-163`).
   - `frontend/src/components/cockpit/PerformanceDetails.tsx` — its three `formatCurrency(` sites and the
     hand-rolled `${value.toLocaleString("zh-TW")} ${currency}` at `:322` all become `formatMoney` with the
     `currency` the component already carries (14 references).
   - `frontend/src/components/cockpit/DiagnosisPanel.tsx:201` — the suggestion's own `currency` field
     (the ticket 04 review found it there; read the type in `scheduleApi.ts` before assuming the name).
   Screens whose money is the system's own TWD (schedule budgets in `CampaignTree`, `PeriodPanel`,
   `ScheduleSetup`, `PlanComparison`; own-site orders in `OrdersPage`; `BrandCard`) keep `formatCurrency`.
3. One vitest case in `frontend/src/lib/format.test.ts` (create it beside `http.test.ts` if absent):
   `formatMoney(28860.4, "TWD") === "28,860 TWD"`, `formatMoney(1250, "USD") === "1,250 USD"`,
   `formatMoney(null, "USD") === "累積中"`.

Literal example — the same card rendered for a TWD and a USD account:

```json
{"TWD": {"spend": "16,110 TWD", "revenue": "11,277 TWD", "cpa": "累積中"},
 "USD": {"spend": "1,250 USD", "revenue": "累積中", "cpa": "累積中"}}
```

## How we know it's done

1. **Machine gate**: `cd frontend && npm run build && npm run lint && npm run depcruise && npm test`
   (the new test included; `designTokens.test.ts` still green) · `cd frontend && npm run e2e` (own 8720
   backend, `supabase start` first, shut it down after).
2. **No `NT$` under a non-TWD header**: `grep -n "formatCurrency(" frontend/src/components/intake/HistoryPage.tsx frontend/src/components/cockpit/PerformanceDetails.tsx frontend/src/components/cockpit/DiagnosisPanel.tsx`
   prints nothing; `grep -n 'toLocaleString("zh-TW")} \${' frontend/src/components/cockpit/PerformanceDetails.tsx`
   prints nothing (the hand-rolled shape is gone).
3. **Walk** (WALK subagent, playwright-cli, stand-in backend `uv run python -m scripts.drill.serve --port 8720`,
   account `123@example.com`/`123456`; done together with ticket 09's walk): on
   `/app/brands/brd_bughunt/intake/history` every money figure on a card under the `TWD` header reads
   `… TWD`, none reads `NT$`; on the cockpit's performance details the spend figures read `… TWD`.
   Screenshot each.

## Shared files touched

Searched 2026-09-08, whole repo, unscoped (same exclusions as the earlier past-ads tickets):

```
grep -rn formatMoney .          → (no hits)
grep -rln "formatCurrency(" frontend/src → 9 component files + format.ts (only the three named above change)
```

Files this ticket edits:

```
frontend/src/lib/format.ts
frontend/src/lib/format.test.ts                          (new)
frontend/src/components/intake/HistoryPage.tsx
frontend/src/components/cockpit/PerformanceDetails.tsx
frontend/src/components/cockpit/DiagnosisPanel.tsx
```

## Contradiction check

- **Done-check 2 (no `formatCurrency` left in the three files) vs §7 (`NT$` stays for the system's own
  TWD figures).** They collide only if one of the three files also prints a system-own figure; input:
  `DiagnosisPanel` printing a rule-card budget beside the suggestion's spend — read the file; if such a
  figure exists it keeps `formatCurrency` and done-check 2's grep is narrowed to that line, named in the
  report.
- **Cheapest wrong implementation that leaves every check green**: `formatMoney` ignoring `currency` and
  printing `TWD` always — the vitest `USD` case is what catches it; keep it.

## Blocked

2026-09-08, implementer round 1: `PerformanceDetails.tsx`'s `MonthMoneySection` (`:80,85,101`) prints
`revenue`/`margin` (own-site orders, `BrandMonthMoney` has no `currency` — §7's own carve-out) and one
Meta `spend` total the endpoint returns without a currency (a backend change this ticket forbids). Ruling
(main chat): those three lines keep `formatCurrency`; done-check 2's grep on that file is narrowed to
"nothing but lines 80/85/101". The per-currency spend total on the cockpit is a separate wish, not opened.
