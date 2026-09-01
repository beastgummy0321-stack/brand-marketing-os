---
id: 0031
decision: Run the agent CLI isolated from the developer's own config, so no local persona leaks into brand prompts.
applies-to: [app/llm/providers.py]
supersedes: none
status: in-force
---

# Agent runs are isolated from the developer's own config

`claude -p` loads the machine's personal agent configuration into every run. Measured on
2026-08-28: a bare probe asking for the single word "ok" came back `Beast，ok`, and asked
directly, the run confirmed that `ponytail`, `ADHD` and `skeleton-slice` were all present in
its instructions. Every brand prompt was therefore carrying a lazy-senior-developer persona, an
ADHD output-shaping ruleset, and a set of module-boundary rules for a different codebase.

That is not merely noise. `ponytail` instructs the model toward the smallest thing that works
— the opposite of what a creative brief needs — so the contamination was steering the product's
actual output, not just its formatting.

Runs use `claude -p --restricted --permission-mode acceptEdits`.

## What was measured

| Attempt | User `CLAUDE.md` | Plugin hooks | Verdict |
| --- | --- | --- | --- |
| `claude -p` | leaks (`Beast，ok`) | ponytail / ADHD / skeleton-slice all present | baseline |
| `--setting-sources project` | leaks | present | blocks neither |
| `--settings '{"claudeMdExcludes":[...]}'` | blocked | **all three still present** | half a fix |
| `--bare` | blocked | blocked | **rejected — see below** |
| `--restricted` | blocked | blocked | chosen |

`--bare` is rejected on cost, not capability. Its help is explicit: *"Anthropic auth is strictly
`ANTHROPIC_API_KEY` or `apiKeyHelper` via `--settings` (OAuth and keychain are never read)."*
It forces per-token API billing and forfeits the user's existing subscription, which is the
whole reason this product shells out to a CLI instead of calling the API.

## Consequences

- **The prompt is the only input.** `--restricted` also blocks the *workspace's* own
  `CLAUDE.md` — verified with a workspace file demanding a `ZZZ` prefix that never appeared.
  That is exactly what ADR 0029 wants: the shell composes the prompt, and nothing else reaches
  the model. Run-to-run input is fully determined by what the shell pasted.
- **The workspace needs no `CLAUDE.md` and no `AGENTS.md`.** This removes one of the six
  differences between the two CLIs recorded in `HANDOFF-shell-slice.md`.
- **File tools are confined to the working directory**, so the agent cannot wander outside the
  brand's workspace. Sandboxing arrives free with the isolation.
- **Bash, PowerShell, REPL and WebFetch are removed.** File writes still work — verified: the
  agent created a `plan.json` with the right contents under
  `--restricted --permission-mode acceptEdits`. If a task genuinely needs the web, name the
  tool back with `--tools` on that task alone; never add it speculatively.
- **Codex is not contaminated on this machine** — it does not read `~/.claude/`, and
  `~/.codex/AGENTS.md` is empty. Verified: a codex probe reported no `ponytail` and no `ADHD`.
  Pass `--ignore-user-config` anyway for symmetry (its help confirms auth still resolves from
  `CODEX_HOME`), keep `~/.codex/AGENTS.md` empty, and put no `AGENTS.md` in a workspace.
