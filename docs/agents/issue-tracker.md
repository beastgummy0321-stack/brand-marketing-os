# Issue tracker: Local Markdown

Issues live as markdown files in `.scratch/<effort>/issues/`.

## Conventions

- One effort per directory: `.scratch/<effort-slug>/` (e.g. `.scratch/cockpit/`)
- Tickets are one file per issue at `.scratch/<effort-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Each ticket has a `**Status:**` line near the top (e.g. `done`); canonical triage roles are mapped in `docs/agents/triage-labels.md`
- Each ticket has a `**Blocked by:**` line listing the ticket numbers/titles it depends on, when applicable
- Finished tickets move into `.scratch/<effort-slug>/issues/done/`

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<effort-slug>/issues/` (creating the directory if needed), following the numbering and Status/Blocked-by conventions above.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path (check `issues/done/` if not found in `issues/` directly).
