# The agent CLI is a provider, and it returns text

`HANDOFF-shell-shell.md` planned a new seam, `run_task(workspace, task) -> result`, that would
spawn a CLI and let it write into the workspace. Reading the code first killed both halves of
that plan.

**`run_task` already exists.** `app/llm/gateway.py:run_task()` is the single entry point for
every LLM call in this codebase. It already resolves the org from the brand, enforces the
per-org monthly spend cap (ticket 04-1a), writes the `llm_task` row, accounts cost, and retries.
It lives in `app/llm/`, so the amputation does not touch it. Adding a second function with the
same name and most of the same job would have been the mistake, not the design.

**`Provider` is a one-method Protocol.** `app/llm/providers.py` defines `Provider` with a single
`complete(...) -> ProviderResponse`, implemented today by `AnthropicProvider` and `FakeProvider`.

So the local agent CLI is a **third provider**, not a second runner. `ClaudeCodeProvider` and
`CodexProvider` implement `complete()` by spawning the CLI with the composed prompt on stdin
(argv is not viable — the prompt exceeds Windows' ~8191-char limit) and returning its reply.
`gateway.run_task()` is unchanged.

## The agent returns text; the shell writes the files

The agent is given everything in the prompt (ADR 0029) and hands back one reply containing the
human-readable plan and a fenced `json` block. The shell extracts, validates, and writes
`plan.md` and `plan.json` into the workspace.

This is what makes the two CLIs and the cloud API genuinely interchangeable — all three are
"text in, text out", so moving to SaaS changes where the prompt is sent, not how the runner
works. Had the agent written its own files, the two CLIs would diverge again immediately:
claude needs `--permission-mode acceptEdits` and codex needs `-s workspace-write`, two
different mechanisms with two different failure modes. Text-out also means ADR 0031's
`--restricted` needs no write permission at all.

The folder remains the contract *with the agent*; the `llm_task` row is the record *for the
system*. They are not competing sources of truth — the row is the audit trail, the folder is
the working surface the next prompt is composed from.

The limit, stated so nobody is surprised by it: an agent that cannot open files cannot read a
large results CSV for itself. v1 stops before review, so this does not bite yet. When it does,
either the shell pastes the CSV in, or that one task gets file tools and accepts that the two
CLIs diverge for it.

## Consequences

- **`resolve_ai_credentials()` needs a third source, `'local-cli'`**: nobody's API key pays, the
  user's own subscription does. `api_key=None`, `cap_applies=False`, and `llm_task.cost` is 0.
  The existing two sources (`'platform'`, `'own'`) are unchanged.
- **The planned `run` table is deleted.** `llm_task` already carries id, `org_id`, `brand_id`,
  `task_type`, `provider`, `model`, `status`, `attempt_no`, `started_at`, `finished_at`, `error`
  and `cost` — and `structured_output_json` / `rendered_output` are exactly `plan.json` and
  `plan.md`, so there is no `out_path` to store. At most it gains a `department` column, and
  even that may fold into `task_type`. `approval` survives: a human approving a budget is not an
  LLM call and has nowhere to live in `llm_task`.
- **Running in the background is ticket 05-1, not a new invention.** `run_task()` is synchronous
  and a CLI run takes minutes, so it needs the procrastinate `enqueue / status / cancel`
  contract that slice ⑤ already specifies. procrastinate is not installed yet. 05-1's payload
  (`_auto_sync_loop`, the weekly engine) dies with ads; its contract is what the shell needs.

## 2026-08-30: only one CLI provider is built

This ADR named two — `ClaudeCodeProvider` and `CodexProvider`. Only `CodexCliProvider`
was built (`app/llm/providers.py`, switched by `BRAND_OS_LLM_PROVIDER=codex_cli`), and on
2026-08-29 it carried a full real-brand run end to end at $0 without failing once. The
second one is **not built**: it would be ~150 more lines of subprocess and event-stream
plumbing doing the job a working provider already does, and nothing has yet hurt for want
of it. The ADR's claim — that a local agent CLI is a provider, not a second runner — is
already proven by one implementation; a second proves nothing new.

Two known gaps in the codex line are accepted, not reasons to build the second: it cannot
return `search_sources` (so the plan's source list is empty in $0 mode), and it cannot
detect truncated output. If either starts to hurt, the cheaper fix is inside the existing
line — have the model cite its own sources in the structured output — not a second CLI.

Reopen this only with a written record of the codex line actually failing.
