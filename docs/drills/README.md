# Usability drill — the ad loop, twice, by strangers

A drill puts people who have never seen this product through the whole loop — build the brand,
plan the schedule, publish, collect performance, adopt what the diagnosis says, plan again,
publish again — and scores every step 1–10. It is not a test suite. Its output is a ranked list
of places where a real person stalls, which becomes tickets and issues.

## Roles

| Role | Who | May |
|---|---|---|
| Persona | one subagent per character, `personas/*.md` | drive a real browser, read what is on screen |
| Operator | the main session | everything else: environment, the Meta stand-in, root cause, tickets |

A persona **may not read source, query the database, read `docs/`, or ask anyone anything.**
A persona that knows where the button is has stopped being a user. Root cause is the operator's
job — the persona reports the symptom and the evidence, nothing more.

The operator **fixes nothing while a drill is running.** A fix between two personas means the
second persona never meets the same defect and the two reports stop being comparable.

## Scoring

Every step gets one integer, 1–10, anchored:

| Score | Meaning |
|---|---|
| 10 | Did it without thinking |
| 7 | Paused, worked it out alone |
| 4 | Guessed, or had to go back and look for something |
| 1 | Stuck; a real person would call someone |

Anything below 7 needs evidence — a screenshot and the sentence on screen that caused the
stall. A score without evidence does not count.

## Stop conditions

Stop the run immediately and report when any of these happen. Everything else is scored and
worked around, because a run that stops early never reaches the later steps.

1. Money is computed wrong (a total that does not match its parts, a currency that changes).
2. Data belonging to another organisation or another brand becomes visible.
3. Data is destroyed or corrupted with no way back.
4. A screen dies with no way forward — no error, no back, no retry.

## The Meta stand-in

Steps 6 and 8 of the loop need a human inside Meta Ads Manager and real money. The drill
replaces the network edge instead: `scripts/drill/fake_meta.py` serves invented platform data
to the product's own Graph client, and the backend runs under `scripts/drill/serve.py`.
Binding and the spend pull run their real code. **The invented ROAS numbers say nothing about
whether the product's judgement is any good** — only real spend can answer that. What the
drill proves is that the pipeline carries a signal from one end to the other, and that what a
persona adopts changes what they are offered next.

## Running one

```bash
# once per drill
.venv/Scripts/python.exe -m scripts.drill.fake_meta reset
.venv/Scripts/python.exe -m scripts.drill.serve --port 8710      # backend, stand-in installed
.venv/Scripts/python.exe -m app.worker                            # jobs

# after the persona has approved their tree and reached "go build these in Meta"
.venv/Scripts/python.exe -m scripts.drill.fake_meta mirror <brand_id>
# after the persona has bound the tree
.venv/Scripts/python.exe -m scripts.drill.fake_meta spend <brand_id> --round 1
.venv/Scripts/python.exe -m scripts.drill.fake_meta pull <org_id> --since <month start>
# round two, after they have adopted and re-planned
.venv/Scripts/python.exe -m scripts.drill.fake_meta spend <brand_id> --round 2
.venv/Scripts/python.exe -m scripts.drill.fake_meta pull <org_id> --since <month start>
```

Personas run one at a time. Reports land in `.scratch/drill/<persona>/` — scratch, not history.
What survives a drill is the issue files it produced; the raw run logs are disposable.

## What the first drill cost the fixture (read this before running the next one)

Two of the drill's own defects produced findings that were not the product's:

1. **Every persona shared one invented ad account.** One org's pull came back holding another
   persona's campaigns, because `/act_<id>/insights` cannot tell two tenants apart when both
   bound the same account. Fixed: one account per persona, matched by the token they paste.
   Fixture data that can bleed across tenants makes every tenant-isolation conclusion worthless.
2. **The backend kept running the pre-fix stand-in.** A persona then saw two other tenants' ad
   account names on the binding screen and reported a leak. Restart whatever process holds the
   stand-in after editing it — otherwise the thing you think you fixed is still running old code.

Both were caught because the operator went and checked the database instead of believing the
report. A persona's report is a symptom; the cause is never theirs to name.

3. **Second drill (2026-09-09): Orca `type-text` garbles Chinese.** The first persona driven
   through the user's own Chrome with Orca computer-use typed 「常春健康」 and the database
   received 「8%e愆」, the products 「吰?」／「??」 — the drill tool's synthetic key delivery, not
   the product. `set-value --element-index N --value "…"` delivers Chinese intact (verified on the
   product-name field before re-running). Every persona prompt now says: text fields only via
   `set-value`, never `type-text`; re-read the field's `Value:` before moving on. Data written by
   the garbled run (org of `aming2@example.com`) is junk to delete after the drill.

4. **Second drill: Orca cannot pick an option in a native `<select>`.** Chrome opens the list
   as a separate 463×220 window whose accessibility tree is three empty panes; keyboard Down/Return,
   `set-value` on the combobox and coordinate clicks inside the popup all left the value at
   「請選擇」, and while the popup is open the main window drops out of `list-windows`. Every
   form here uses native selects (來源, 種類, 平台, 風格…), so the persona driver switched to
   `playwright-cli` (headed window; `select <ref> <值>` works) from 阿明 step 4 on. Orca stays
   the tool for "look at the user's own Chrome", not for driving forms.

5. **Third drill (2026-09-09): playwright-cli "screenshots" saved as text.** Three of the persona's
   `stepNN-….png` files were 331-byte ASCII (the CLI's markdown reply pointing at
   `.playwright-cli/page-*.png`), and that folder is deleted at clean-up — the settle screens left
   no image. Every persona prompt now says: after `screenshot`, copy the file the CLI names into
   `.scratch/<drill>/` and run `file` on it before writing the path into run.md; a path that is
   not `PNG image data` is a missing screenshot, not evidence.

## Results, first drill (2026-09-06)

Three personas, two full cycles each, three separate orgs. No malignant stop condition was hit.
Two money-correctness defects, both reproduced independently in more than one org, are in
`docs/issues/plan-quality/`; the screen-level findings are in `docs/issues/ui/`.

What the drill could not answer, and no drill can: whether the judgement is any good. The
stand-in's ROAS numbers are invented. Only real spend answers that.
