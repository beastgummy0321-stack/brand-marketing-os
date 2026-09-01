---
id: 0029
decision: The shell pastes whole .md files into the prompt verbatim and never parses them.
applies-to: [app/departments/, app/methodology/, app/llm/context_compiler.py]
supersedes: none
status: in-force
---

# The shell cats files into the prompt, but never parses them

_Status: amended by ADR 0033. The rule — paste whole files verbatim, never parse them — still governs department task and methodology `.md` files. Brand data reaches the prompt through `app/llm/context_compiler.py` instead of a workspace folder, which no longer exists._

Three ways to get brand data in front of the agent were considered: leave the files in the
workspace and let the agent open them itself; read and parse them in the shell and assemble a
prompt for a plain model API; or paste them in whole.

We paste them in whole. The shell concatenates the relevant `.md` files verbatim into the
prompt and hands the result to the agent CLI, which still runs inside the workspace and still
writes its own files back. Reading a file in full and pasting it is not parsing it, so the
workspace stays the only contract — the shell never learns what `brand.md` looks like inside.

The rejected alternatives, and why:

- **Agent opens the files itself.** Prompt content becomes unpredictable run to run, and the
  user asked specifically for a prompt library whose input they can see.
- **Parse in the shell, call a plain model API.** This breaks the contract (the shell would
  have to understand the file format), makes prompt length the shell's problem, removes the
  agent's ability to go read the results CSV when review arrives, and moves cost from the
  user's existing CLI subscription onto per-token API billing.

The source repo already proved the pattern: `app/llm/methodology.py` composed methodology
files into prompts verbatim, and its own glossary called those files "program parts, not
documents — every line costs tokens."
