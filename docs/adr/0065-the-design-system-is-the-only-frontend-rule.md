---
id: 0065
decision: docs/design-system.md governs how every screen looks and reads; every other frontend rule is retired into it.
applies-to: [frontend/, docs/design-system.md, CONSTITUTION.md]
supersedes: 0051
status: in-force
---

# The design system is the only frontend rule

2026-09-07, decided by the user. The user commissioned a full desktop redesign, approved a
reference dashboard (`docs/design-system.png`), and asked for three things: turn it into a design
system, delete every other frontend/UI rule, build every later page to that standard.

## What was measured before deciding

Frontend rules lived in five places, none of which agreed with the shipped `tokens.css`:

| Source | What it said | Fate |
|---|---|---|
| ADR 0051 (13 rules + gate notes) | dashboard not document, fluid 1920, copy rules; rule 13 left palette/font open | retired; rules folded into design-system §1, §2.6, §4, §8, §9 |
| `docs/ui-reset-handoff/UI-INVENTORY.md` §7 "red lines" + §6 token inventory | four 🚫 rules; token table still described the **old** Calistoga / `#0369a1` set | deleted (handoff consumed; the token table was already false) |
| `docs/issues/ui/issue-u3-font-and-palette.md` | "needs-user-decision" on the font, Inter flagged as generic | closed: the user approved a design set in Inter + Noto Sans TC |
| `.claude/settings.local.json` impeccable hook | a third-party design detector running its own rules on every write and on Stop | removed; it is the source of the Inter objection and would keep grading against a rulebook that is not ours |
| `CONSTITUTION.md` rule 12 | pointed at ADR 0051 | re-pointed to this ADR and the design system |

Five dead components of the old look (`FluidCard`, `StatBig`, `ProgressRing`, `TrendSparkline`,
`StatusLight`) had zero importers outside their own stories; deleted.

Raw hex in `.ts/.tsx`: 8 literals in 3 files. Two files are now the only allowed carriers
(`tokens.css`, `lib/chartColors.ts`); the rest were moved there, and a vitest gate keeps it so.

## Decision

1. `docs/design-system.md` is the single frontend rule document. Precedence:
   `CONSTITUTION.md` rule 12 → design system → ticket. No other document, comment, issue or hook
   may state a rule about layout, colour, type, spacing, component choice, copy or motion.
   If one is found, it is folded into the design system or deleted, never left standing.
2. `frontend/src/styles/tokens.css` is the only token source; `lib/chartColors.ts` mirrors the
   chart palette for canvas. Raw hex or `font-family` anywhere else fails
   `frontend/src/designTokens.test.ts`.
3. Changing the design system is an ADR-level decision (ask the user); adding to it inside its
   existing shape (a new pattern row, a new status word) is a ticket.
4. Font and palette are decided: Inter Variable + Noto Sans TC Variable, violet `#7055d8` on
   `#f6f7fb`. Board row U3 is closed.

## Consequences

- ADR 0051 moves to `docs/adr/retired/` with a pointer here. Its measured findings (the fake
  `documentElement.scrollWidth` gate, the 1024/1920 width measurements) stay readable there as
  history; the live gate is `frontend/e2e/width-overflow.spec.ts`.
- ADR 0003's consequence line and `CONTEXT.md` references to 0051 now point here.
- `docs/issues/ui/spec.md` is rewritten: U3 gone, U1 (banned-word gate) remains and cites
  design-system §8; the long-scroll issue cites §1.
- The impeccable hook entries are removed from `.claude/settings.local.json`; the skills stay
  installed as tools that may be invoked by hand.
- The Codex redesign in the working tree (62 files) is what this document describes; it builds,
  lints and passes vitest as of this ADR. Committing it is the user's call.
