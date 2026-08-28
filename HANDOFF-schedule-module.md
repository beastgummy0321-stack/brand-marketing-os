# Handoff — the scheduling module, and the deletions it depends on

Produced by the architecture session, 2026-08-29, from a grill with the user. Settles the
scheduling module's design and four ADRs. **Read `docs/adr/0034`–`0037` before touching code.**

This does not supersede `HANDOFF-shell-slice.md`; tickets 5, 6 and 7 there are still open and
belong to whoever holds the `shell` branch.

**Nothing here is committed.** The architecture session does not commit on `shell` — two
sessions on one branch is a race that bit twice already. Carry these files in your next commit.

---

## 0. What changed since `HANDOFF-shell-slice.md`

The user overturned four of its settled decisions, each with a stated reason:

| Was | Now | Why |
| --- | --- | --- |
| §3.7 the 10 dead routes become 2 pages | Scheduling is **one page**; the dashboard is separate and cross-channel | A v1 dashboard fed only by `plan.json` shows nothing the newest work-order card does not |
| §3.9 first buttons: exactly two | **A form, then one action.** Platform, product(s), daily budget, objective — confirm — schedule | One button cannot supply a budget, and money is never the agent's to invent |
| §3.8 v1 dashboard shows plan-side numbers only | **Real numbers from day one** | The user has a live Meta API and real spend history; see §2 |
| §3.11 the shell validates a full `plan.json` schema | **The JSON carries the money split only**; everything else renders as Markdown | Everything else is prose the shell must not parse (ADR 0029) |

And one new rule outranks all of them: **ADR 0034** — a feature must remove work, not relocate
it. Every ticket below states, in one line, what the user no longer does.

## 1. The scheduling module

Produces **how this period's advertising should run, and why**. It does not produce creative;
that is the creative module's job, reached one ad at a time from an approved plan.

**Input form**, confirmed in place on the same page — a summary appears below it with 修改 and
開始排程; no second route, no back-step state machine:

| Field | Source | Note |
| --- | --- | --- |
| Platform | data file | Meta only; Google and TikTok listed and disabled |
| What to run this period | `product` table, multi-select | No products selected = brand-level. Multi-select *is* the bundle; there is no "combination" concept |
| Promotion / focus | free text | |
| Daily budget | rule card | Set once in settings, not per run |
| Objective | data file, filtered by platform | Meta's six ODAX values; each entry names its source URL |

**Output**: N plans, default 3, selectable 1–5 from a dropdown whose bounds live in a rule card
(the program enforces them, so the program owns the number). Each plan is a **summary plus its
reasoning**, roughly 200 words — *not* a full tree. The user picks one, and only then does it
expand into the campaign tree. Producing five trees to throw four away is four times the output
tokens for a comparison the user cannot make on screen anyway.

**The tree is generic and three levels deep.** The shell knows only `{level, label, fields,
children}`; the words 行銷活動 / 廣告組合 / 廣告 are labels the agent returns, never constants in
shell code. This is less code than hardcoding Meta's vocabulary, not more, and it keeps the
shell's business vocabulary at the three words `CONTEXT.md` allows. Verified platform shapes:

| | Level 1 | Level 2 | Level 3 | Budget sits at |
| --- | --- | --- | --- | --- |
| Meta | Campaign (objective only) | Ad set | Ad | **Level 2** (Level 1 with CBO) |
| Google | Campaign | Ad group | Ads / keywords | **Level 1** |
| Google PMax | Campaign | **Asset group** (no keywords) | Assets | Level 1 |
| TikTok | Campaign | Ad group | Ad | Level 1 or 2 |

**Non-default settings are marked.** Where a plan departs from a platform default — "Facebook
only, no Instagram" — the node carries a warning marker, collapsed by default, expanded on
click. This is half of why manual publishing passes ADR 0034.

**Publishing has two modes.** Manual: the buyer builds it by hand from the tree, typing the
node names the tree specifies. Automatic: the shell builds the structure through the API in
`PAUSED` state and the user confirms and starts it — nothing spends before that press.
Automatic is greyed out until manual has run for real.

**Name-matching binds a hand-built campaign back to its plan**, once. The shell pulls the
account's campaigns, and a unique name match stores the platform id; from then on only the id
is used, so renaming in Ads Manager does not break the link. No match shows
**「配對失敗，請檢查名稱是否完全相符」** and nothing else — no picker, no repair flow.

**Money is computed by code.** The agent returns ratios (`{"驗證組": 0.7, "測試組": 0.3}`); the
shell multiplies by the rule-card budget, rounds, and checks the shares sum to 1.0. About 20
lines, and the only place the shell refuses.

**Feedback** is ADR 0037 in full: + to add one entry at a time, red line or preference, a
category when it is a preference, 100 characters, at least one entry before a re-run.

## 2. Meta data — tested live, 2026-08-29

Pulled through this session's Meta connector with no code written. The user has **4 ad
accounts** (TWD); two are readable through that connector and two are not
(`is_ads_mcp_enabled: false`, "Ads MCP is gradually being rolled out").

| Account | Campaigns | Spend | Notable |
| --- | --- | --- | --- |
| BP AD | 3 | NT$172,081 | ROAS 3.22 and 2.21 on the two sales campaigns |
| 上等生技廣告帳號 | 4 | NT$22,256 | All daily budgets NT$500; ROAS 0.54, three untracked |

`objective` came back as `OUTCOME_SALES` / `OUTCOME_TRAFFIC` / `OUTCOME_LEADS`, matching the
researched enum. So the budget suggestion has a real basis and the 6× ROAS spread across
accounts is exactly what "increase / hold / decrease" should key on.

**Two findings that decide the integration:**

1. **The connector returns money as formatted strings** — `"NT$4,971\u00a0TWD"`, not a number.
   Parsing that back is the shell reading prose to compute money, which is the disease this
   whole slice exists to treat. The Graph API `insights` endpoint returns `spend` as a number.
   **The connector is for hand-testing; the product uses the Graph API.**
2. **The connector cannot see two of the four accounts.** The user's own token can. Second
   reason the connector is not the product's foundation.

**ROAS is null on three of seven campaigns.** Null must render as 未追蹤, never as 0.

## 3. Tickets

**The tickets are published at `.scratch/schedule-module/issues/01`–`12` and those files are
authoritative.** This section is the reasoning behind the split, kept for why-questions; where
it and a ticket disagree, the ticket wins. The S-numbers below map to them in order, except
that S-1 split into 02 and 03, and S-8 split into 07, 08 and 09.

**Meta first** (user's ruling, 2026-08-29). Route C = schema, module boundary, money, or
permission path; everything else is route B. Each ticket names its ADR 0034 saving.

| # | Ticket | Route | Depends on |
| --- | --- | --- | --- |
| 1 | S-0 install procrastinate | C | — |
| 2 | S-4 Meta credentials in Vault | C | — |
| 3 | S-5 daily Meta pull | C | S-0, S-4 |
| 4 | S-1 delete hardcoded domain knowledge | B (+C for the column) | — (runs in parallel) |
| 5 | S-8 the scheduling page | B | S-1 |
| 6 | S-7 feedback entries | B | S-8 |
| 7 | S-9 name matching | B | S-5, S-8 |
| 8 | S-6 dashboard v1 | B | S-5 |
| 9 | S-2 generic channel table | C | — (deferred, see below) |
| — | ~~S-3 Shopee calibration~~ | — | **shelved** |

**S-2 moved to last.** With S-3 shelved no new revenue channel is arriving, and dashboard v1
needs only Meta spend plus EasyStore revenue — both already validated against real data. The
generic channel table exists to make *future* channels cheap; that has not hurt yet. ADR 0035
still stands as the decision, and the pharmacy hardcoding still goes, just not first. Cost of
deferring: S-6's revenue query is written against `order_record` and gets rewritten once when
S-2 lands. One query.

### S-0 — install procrastinate (route C: it creates its own tables)

Already the board's choice (ticket 05-1); not a fresh package decision. Verified 2026-08-29:
**procrastinate 3.9.0**, released 2026-06-20, MIT, requires Python >=3.10, depends on
`psycopg[pool]` — the same psycopg 3 line this repo already pins (`>=3.3,<4`). Pin it exactly
in `pyproject.toml`; `uv sync --frozen`, never pip.

Its schema is plain SQL shipped in the package (`procrastinate schema --migrations-path` prints
where), and every table is `procrastinate_` prefixed, so it satisfies the constitution's rule
that a migration may only create its own module's tables. **Vendor the baseline SQL into
`supabase/migrations/<timestamp>_procrastinate_baseline.sql`** rather than letting the library
apply it — migrations are centralised there.

State the ongoing cost in the ticket: upgrading procrastinate later means copying its new
version-numbered migration files in as new files of our own. That is the price of centralised
migrations, and it is worth paying.

*Saving: none directly — S-5's daily pull cannot be background without it.*
**Done-check:** `supabase db reset` applies clean; a worker starts and runs one trivial job;
`uv run pyright` clean.

### S-1 — delete hardcoded domain knowledge (route B, but large)

ADR 0036. Delete `compliance_wordlist.py`, `campaign_calendar.py` + its JSON,
`calendar_dismiss.py`, `campaign_skip.py`, `CalendarSection.tsx`, the `INDUSTRIES` tuple, the
three test files, `app/methodology/ads-health.md`, the legal paragraphs in `copywriting.md`,
the seeded food rule at `app/intake/script.py:399`, and every call site in `guide_cards.py`,
`dashboard/repository.py`, `routes_brand_settings.py`, `routes_library.py`. Drop
`brand.industry` (this half is route C — it is a migration).
*Saving: none directly — it removes maintenance and unblocks S-2.*
**Done-checks:** `git grep -l "campaign_calendar\|compliance_wordlist\|calendar_dismiss\|campaign_skip\|INDUSTRIES"` over `app/` and `frontend/src/` prints nothing; `uv run python -m pytest app/tests -q` zero red; `cd frontend && npm run build && npm run lint`.
**Tolerance lists:** remove entries naming deleted files. Never add one to turn a gate green.

### S-2 — the generic channel table (route C: migration)

ADR 0035. One channel-revenue table; migrate `shopee_report_row` and `pharmacy_batch` into it;
delete `cycle_shopee_code`. `channel` takes `website` / `marketplace` / `physical_store` from
`CHANNEL_TYPES`. EasyStore importer only; Shopee reuses its existing parser against the new
table; offline is entered by hand.
*Saving: the user no longer has a pharmacy-shaped hole where MOMO should go.*
**Done-check:** `supabase db reset` applies clean; suite stays green.

### S-3 — calibrate the Shopee column mapping — **SHELVED**

Shelved 2026-08-29: Meta first. `app/orders/channel.py`'s alias table has never met a real
export; its docstring says so, and it stays saying so. When this resumes, the user provides a
real file and the aliases are corrected against it — **no code before the real file exists.**
Until then Shopee revenue is not trustworthy and the dashboard must not show it as if it were.

### S-4 — Meta credentials in Supabase Vault (route C: permission path)

The user chose Vault over an env var: do it once, properly. This is ticket 04-2's Vault work,
pulled forward. `app_setting` is plaintext and must not hold a token.
*Saving: the user stops pasting a token anywhere it can leak.*

### S-5 — daily Meta pull (route C: money path)

Graph API `insights`, not the connector. Numeric `spend`. Background and daily, on S-0's
procrastinate. A brand-to-ad-account mapping table: one brand may bind several accounts, and
the user picks which — a beginner has one, and anyone with several already knows why.
*Saving: the user no longer opens Ads Manager to read numbers into a spreadsheet.*

### S-6 — dashboard v1 (route B)

Spend from S-5, revenue from `order_record` (EasyStore — the one importer validated against the
user's real export), cost from `sku_cost`. One page: this month's spend, revenue, impressions,
ROAS. Null ROAS renders 未追蹤, never 0.

**v1 covers one revenue channel and says so on the page.** Shopee is shelved with S-3 and
offline has no data; showing an incomplete total as if it were complete is the failure this
dashboard exists to fix, inverted. Label it 官網, not 全通路, until S-2 lands.
*Saving: the second failure in ADR 0034 — no more flipping between dashboards to compute ROAS.*

### S-7 — feedback entries (route B)

ADR 0037. Four new `RULE_TYPES` entries plus `other`; the + form; the 100-character cap;
`sweep_expired_rules()` stops sweeping `hard`; the expiry threshold becomes days, default 90.
*Saving: the user no longer navigates to the settings screen to write down what went wrong.*

### S-8 — the scheduling page (route B, largest)

§1 in full, up to the tree and manual publishing. Automatic publishing is a greyed placeholder.
*Saving: the user no longer pastes brand context into a chat window one piece at a time.*

### S-9 — name matching (route B)

Bind a hand-published campaign to its plan by unique name match, then keep the id.
*Saving: the user no longer reconciles results to plans by hand.*

## 4. Still open

1. **The creative module** is designed only to its boundary: it takes one ad from an approved
   plan, and its feedback works identically. Everything else is unstarted.
2. **Automatic publishing** — greyed placeholder until manual has run for real.
3. **Variance is still unmeasured.** The probe at `D:\0UserProfile\Desktop\MarketingOS Shell\
   variance-probe\` has never run; it needs a real brand typed into
   `workspace/{brand,products,rules}.md`. Until it does, the retry budget is a guess. This
   matters more now: the scheduling run does a live web lookup, so two runs see different
   source material by design.
4. **ADR 0004 is stale** — its premise is single-user desktop, overturned by ADR 0027.
   `authorized_by` auto-filled with a fixed value is an audit gap under multi-tenancy.
