# Time may be bucketed. Nodes may not.

Ticket S2b, 2026-08-31. **Approved by the user 2026-08-31**; B1 landed that day and one condition
below was amended after measurement (marked inline). **This overturns a decision frozen in the
ad-loop spec on 2026-08-30**, in the style ADR 0044 used for the `learning_ledger` reversal.

## The sentence being overturned

`.scratch/adloop/SPEC.md:251-254`, repeated verbatim into the S2 ticket at
`.scratch/adloop/issues/S2-onboarding-read.md:55`:

> Numbers reach the model as CSV rows, not Chinese prose (~3x cheaper for identical facts), and
> DB-only columns (`id`, `org_id`, `ad_account_id`, `pulled_at`) are dropped. **That changes the
> shape, never the content. Summarising nodes away stays forbidden** — it is the judgement the
> shell is not allowed to make.

The clause that moves is **the daily grain**. Per-day rows for every entity were the concrete
form that "never the content" took. They are no longer required.

## The scope of the overturn, stated narrowly on purpose

- **Allowed now:** bucketing the *time* axis — several days may share one row.
- **Still forbidden, not one word relaxed:** summarising a *node* away. No entity — campaign,
  ad set, or ad — may disappear because it looks unimportant. Selecting which entities the model
  is allowed to see is judgement, and the shell does not make it.

The existing selection rule is untouched and is the boundary: S2 filters on **"did this campaign
have any row in the window"** — presence is a fact, size is a judgement. Nothing in this ADR
authorises a sample-size, spend, or importance filter on entities.

## The premise that moved

The daily grain was frozen before anyone had measured it. The first real-account run of S2
(account `368741390835357`, window 2025-09-05 → 2026-08-31, 361 days) measured it:

| item | measured |
| --- | --- |
| campaigns with numbers in the window | 24 |
| prompt per campaign | ~370 KB |
| └ daily CSV | **236,696 chars (64%)** |
| daily rows, largest campaign | 722 |
| ad-level sparsity | 81% of (entity, day) pairs have no row; of 560 ad-days with spend, only 191 carry ROAS |

One campaign exceeded the local codex CLI's 1,048,576-character input limit. The account total
was ~8.9 MB.

Three reviewers who had never seen this project were then given the problem and the numbers, and
nothing else. They converged independently. Their shared finding is the premise change: they
walked the six high-quality behaviours observed in S2's real run one at a time, and **not one of
them rested on a single day.** The unfair-A/B refusal came from the budget mode (a structural
fact). The refusal to call an 11× ROAS a winner came from 9 purchases (a window total). The
"sample too thin" reading came against the cheat-sheet. Blank-is-not-zero came from coverage.

What the daily CSV was genuinely doing beyond that is a second job: **letting the model count for
itself which days had no data.** ADR-level principle already in force — the shell does arithmetic,
the LLM does judgement (decision ④, `.scratch/adloop/GRILL.md`) — says that job belongs to the
shell. So it moves: one computed coverage line per entity states it outright, which is both
cheaper and more honest than hoping the model counts 722 rows correctly. That is the same fix
already applied once, when the hand-run's only error was arithmetic (`view_content` 344 vs 342
across eight daily values, `.scratch/adloop/SPEC.md:425-429`).

## What a bucket must carry, or it is a lie

A bucket that drops missing days launders absence into silence, which is the exact failure the
overturned sentence existed to prevent. So the permission is conditional:

- **Every bucket states how many days it covers and how many of those had data.** Without both
  numbers, bucketing is forbidden.
- **A bucket with no data is named, and its ROAS is `None`, not `0`.** *Amended 2026-08-31, on
  implementation day; original wording was "stays in the table".* Measured: 83% of 195 entities ×
  24 buckets are empty, and a row each takes the CSV from 3,531 to 5,702 rows — fatter than the
  grain it replaces, killing the reason B1 exists. So no CSV row; `coverage_text()` names it per
  entity, by bucket name, with a denominator. **Naming is not silence**, and laundering absence
  into silence stays forbidden (`EmptyBucketIsNamedNotSilentlyDroppedTest`).
- **Bucket sums equal the daily sums they replace.** Spend, impressions and clicks per bucket must
  equal the per-day figures added up. Bucketing may change shape; it may not change a total.

## Natural weeks are forbidden as a bucket boundary

The single most valuable conclusion this system has produced is *"the delivery-discount ads cost
about 40% less per click at weekends than on weekdays."* A plain weekly bucket averages that away
— it destroys the class of finding the whole loop exists to produce.

**Every bucketing scheme must keep weekday and weekend separate.** The rule lives in one place in
code with this reason written beside it. Which coarser axis pairs with it (month, week index) is
an implementation choice the ticket settles and the golden-sample diff may revise; the
weekday/weekend split is not that kind of choice.

## What this does not authorise

- **No entity filter of any kind.** Presence is a fact, size is a judgement — unchanged.
- **No statistical threshold in Python.** `app/methodology/ab-testing.md:73` states 「不用自訂常數」
  and GRILL decision ④ refused a rule card for thresholds. If a bucketing scheme needs a number to
  decide *what to show*, that is a surfacing rule and must be named as one, kept out of the
  significance path, and given a source. A number with no source does not go into code.
- **No summarising of the shell-computed window totals** (spend / impressions / clicks / CTR /
  CPC / CPM / ROAS / CPA / per-action totals). Their encoding may change; their content may not.
- **No summarising of the frozen-facts section** — the window actually read, the attribution
  window, days never pulled, campaigns skipped and why. Under 1 KB, and the only mechanism by
  which this system can state what it did not read.
- **No rewriting of ad copy.** Creative text reaches the model verbatim, always. Conclusions quote
  it, and a summarised quote is not a quote.

## How we will know if this was wrong

S2's first real-account run is kept as a golden sample. The same campaigns are re-read under the
new encoding and the conclusions are diffed one by one. **Any conclusion only the old encoding
could produce is escalated to a human**, who decides whether to loosen the scheme or withdraw it.
That diff is the acceptance condition of the ticket, not a follow-up.

## Consequences

- **Measured 2026-08-31; the "~60 KB per campaign" predicted above was wrong.** Account daily CSV
  1,080,281 → 405,658 chars (−62%), empty-bucket naming costs 48,585 back, net −626,038 (−57%);
  largest campaign 223,455 → 58,435, whole prompt ≈156 KB — under the CLI's 1,048,576 ceiling,
  over S2b's 80 KB done-check, which no A-series or B1 lever can reach.
- Counting gaps moved from the model to the shell, where decision ④ always put it. The four-segment
  prompt order (`SPEC.md:242-247`) is untouched and stays the precondition for prompt caching on a
  billed API. The overturned sentence survives here, quoted — `.scratch/` is disposable under
  CLAUDE.md's 資料狀態 section, so this file, not the spec, is its record.
