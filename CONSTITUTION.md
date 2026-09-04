# CONSTITUTION — Ads & Scheduling module

**Scope**: this governs the **ads & scheduling** module only. Brand Marketing OS will also carry brand content, SEO and more; each gets its own contract under `docs/contracts/`. Rules 1–3 and 12 are program-wide and bind every module and every agent working in this repo.

**Status: SIGNED 2026-09-01.** Gate A passed. The seven previously approved ad-loop tickets are retired; this document and the ad-loop diagram are the only source.

1. **Program goal**: a multi-tenant cloud SaaS for brand owners and small agencies who buy ads. Other companies sign up, log in and pay; tenant isolation is a requirement, not a feature. Single-machine is today's deployment, never a design premise.
2. **Program-wide data model**: organisation → member → brand; every table carries `org_id`. Irreversible decisions — schema, module boundary, money, permission — are settled **before** code, in `docs/adr/`.
3. **Architecture is never narrowed to fit v1.** "Not building it yet", "not supported", "it's only an MVP" are never reasons to write the schema shut. What is expensive to change later is decided first: the column, the enum value and the foreign key exist from day one even when the feature does not. Opening a deferred feature must be **flipping a switch, never a migration**. Where the road ahead is unclear, send a cheap probe before laying track — find the wall before you build up to it.
4. **This module's product is the loop** — creative → launch → performance back → next creative. Advice alone is not the product; never ship one more tool that only gives opinions.
5. The loop works only because creative carries its **seven-dimension fingerprint** — audience · pain · angle · hook · proof · offer · format — from the moment it is generated. Without it, the numbers coming back are dead.
6. Ads belong to a **channel**. A campaign period is a **filter, never a folder**.
7. **Never answer "what was true then" with a current-state column.** Versions and date ranges, not in-place updates.
8. **The manual path is always first class.** Automation is addition, never replacement.
9. **Money**: the system spends nothing without the user's press. It may save money on its own, and must be able to undo it.
10. **Not in v1**: image generation, video files, landing pages, the agency client tier, any platform but Meta — each already has its seat in the schema, per rule 3.
11. Board `BOARD.md` · vocabulary `CONTEXT.md` · decisions `docs/adr/` · module contracts `docs/contracts/` · tickets and issues `docs/issues/<goal>/` (tracked since 2026-09-04). The constitution says *what*; the *how* is ADR 0050 (data model of record) and `docs/contracts/schedule.md`. The published diagram <https://claude.ai/code/artifact/534811bd-7078-424c-b839-7493b2c73b25> is the readable overview only — where it and ADR 0050 differ, the ADR wins.
12. **The interface is a dashboard, not a document.** Overview first, legible at a glance; dense information is split by tabs and disclosure, never one long scroll; interface text uses standard UI vocabulary and never talks down to the user. The rules are `docs/adr/0051`.
