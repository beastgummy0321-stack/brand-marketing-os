---
id: 0033
decision: There is no workspace folder: brand inputs live in Postgres and context_compiler composes the prompt.
applies-to: [app/llm/context_compiler.py]
supersedes: none
status: in-force
---

# There is no workspace folder

Every version of this plan until now had a `workspace/<brand>/` folder holding `brand.md`,
`products.md`, `business.md` and `rules.md`, with the shell packing it, the agent working in it,
and the folder standing as the one contract between them. That design was drawn for a **new,
empty repo** with no database and no screens. This repo has both, and the folder has no job
left.

- **Inputs already live in Postgres.** Of the 82 tables, `brand`, `brand_fact`, `product`,
  `product_fact`, `product_economics`, `rule`, `claim`, `persona`, `offer` and `sku_cost` hold
  exactly what the four markdown files were going to hold, and they are written by the intake,
  products, library and settings screens — four of the eleven that survive the amputation.
- **Composing the prompt from them already exists.** `app/llm/context_compiler.py:compile()`
  does it, and it does it more strictly than the markdown plan specified: only `confirmed`
  facts, never `pending`; only `active` rules and claims; verified learnings and unverified
  hypotheses in separate sections with hypotheses forbidden from being stated as fact; and a
  signature that takes a single `brand_id`, which makes cross-brand assembly structurally
  impossible rather than merely discouraged. It lives in `app/llm/`, so the amputation does not
  touch it.
- **Outputs already have a home.** ADR 0032: `llm_task.rendered_output` and
  `structured_output_json` are `plan.md` and `plan.json`.
- **Department task files are repo files**, sitting beside `app/methodology/`. They are the
  product's own content, identical for every brand and every tenant, so copying them into each
  brand's folder would have been N copies to maintain and, under SaaS, the product's own
  material sitting inside tenant storage.

So: departments live in the repo, brand data lives in Postgres, and there is no folder between
them.

## What this costs

Brand facts stop being editable in a text editor; they are edited through the screens. That is
a real loss of directness, and it buys two things worth more: the `confirmed` / `pending`
distinction a markdown file cannot express, and per-tenant isolation that a shared filesystem
would have had to re-implement.

## Consequences

- **ADR 0029 is amended, not reversed.** Its rule — paste whole files in verbatim, never parse
  them — still governs the department's task and methodology `.md` files. Brand data reaches
  the prompt through `context_compiler` instead, which was always the precedent 0029 cited.
- **`CONTEXT.md`'s definition of 工作區 is wrong and is removed.** With ADR 0031 the agent reads
  nothing from disk and with ADR 0032 it writes nothing, so there was no shell-agent contract
  left for a folder to be. The contract with the agent is the prompt.
- **Pack/unpack disappears**, and with it one of the three tests the plan had budgeted for.
  What remains worth testing is the budget cap and the runner contract.
- **The cloud story gets simpler, not harder.** There is no per-tenant workspace to move into
  Storage. Ticket 06-1's per-org bucket is for uploaded creative files, which is a different
  thing and still needed.
- **Watch `context_compiler` during the amputation.** It does not import `app.ads`, but it
  reads `strategy_hypothesis`, whose owning code may not survive. Read it before deleting
  around it.
