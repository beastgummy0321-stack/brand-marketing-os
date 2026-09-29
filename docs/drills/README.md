# Usability drill — the ad loop, twice, by strangers

A drill puts people who have never seen this product through the whole loop — build the brand,
plan the schedule, publish, collect performance, adopt what the diagnosis says, plan again,
publish again — and scores every step 1–10. It is not a test suite. Its output is a ranked list
of places where a real person stalls, which becomes tickets and issues.

本頁是演練流程入口，只在使用者要求演練時讀。歷次 plan／operator／findings／synthesis 是當次實驗快照；其中舊模型、工具、禁止修復等指令不覆蓋本頁或當前授權。新的演練重用此入口與需要的 persona，不複製整套文件。
修復停止條件下的共通阻塞仍須在已授權範圍內，且記錄前後版本使分數可比較。一般修復留待演練結束。

## Roles

| Role | Who | May |
|---|---|---|
| Persona | one subagent per character, `personas/*.md` | drive a real browser, read what is on screen |
| Operator | the main session | everything else: environment, the Meta stand-in, root cause, tickets |

A persona **may not read source, query the database, read `docs/`, or ask anyone anything.**
A persona that knows where the button is has stopped being a user. Root cause is the operator's
job — the persona reports the symptom and the evidence, nothing more.

The operator **fixes nothing while a drill is running** — with one exception, proven necessary in drill 4: a defect that trips a stop condition and would block every persona at the same station is fixed, the blocked persona restarts from that station on the fixed build, and the results section says so. Anything less than that waits. A fix between two personas means the
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
whether the product's judgement is any good** — business effectiveness is outside this simulated drill. What the
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

重啟 worker 會留下狀態 `doing` 的工作，procrastinate 不會自己收回；重啟後跑一次
`docker exec supabase_db_marketing psql -U postgres -tAc "set search_path to public__queue, public; update procrastinate_jobs set status='todo' where status='doing'"`，
否則那個品牌的素材／檢討會永遠停在「排隊中」（drill 5 遇到三次）。

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
stand-in's ROAS numbers are invented. Business effectiveness is outside the simulated drill; do not request live spend for acceptance.

## Results, fourth drill (2026-09-13) — the final internal test before release

Three personas (阿明／Sonnet, 小杰／Haiku then Sonnet from station 6, Vivian／Opus), two full loops each, three
separate orgs, the Meta stand-in for publish/bind/spend. Plan: `drill-4-final-internal-test.md`. Everything durable
is in `drill-4/`: `synthesis.md` (eight root causes with causal chains, the 7-stations × 3-personas verdict table,
the six pass criteria, the F05 shape and the rulings the user must make), `findings-<persona>.md` (operator-verified
DB evidence per station). Raw run logs and screenshots were scratch.

Golden Path: every station reached and evidenced for all three; the learning written at 結案 is read by the next
campaign's strategy (learning ids in `budget_basis_json.basis.learnings`, allocation moved, Vivian's loop-2 strategy
refused to over-weight on a low sample and was right). But all six closes judged 「看不出」, because the sample
bucket is tied to a purchase count the Meta path never stores — the loop transmits, it does not yet learn.
One stop condition fired (阿明, station 5: blank page after 自訂預算) and was fixed mid-drill (F04-I24–I26) —
a deliberate deviation from the no-fixes rule, recorded here; 阿明 resumed from station 5 on the fixed build.
Money invariants held in every one of the six settlements; no cross-tenant data; no HTTP 5xx observed.

What the drill cost the fixture this time: `fake_meta mirror` mirrored the ads-module tree (it used to read the
retired schedule tree), and its fallback to `accounts[0]` when a brand had no bound account put one persona's
campaigns under another persona's account — now it refuses instead. Loop-2 campaigns dated in the future were
time-shifted by SQL so outcomes could exist (a fixture step, noted in each run).

## Drill 6 additions (2026-09-26) — planner vs product, compressed time

`docs/drills/drill-6/` holds the plan, contract, judge rubric, brand facts, report and the two code audits.
New stand-in tooling, drill only:

- `scripts/drill/clock.py set YYYY-MM-DD` — `today_for_org` and `db.now_utc` follow the file `.scratch/drill/today`;
  `serve.py` / `worker.py` install it. The browser's own date and `runtime._due` (real clock) do not move:
  request syncs by hand (`external_sync.request_sync`) and tell personas to set review windows explicitly.
- `scripts/drill/tw_sim.py run plan.json --judge fit.json --out rows.json [--prior …]` — Taiwan Meta simulator
  (calendar, audience pools built by prior delivery, fatigue, judge multipliers). Invented numbers; relative only.
- `scripts/drill/export_plan.py <brand> --period N --campaign <id>` — product campaign → contract JSON.
- `scripts/drill/fake_meta.py load-rows <brand> rows.json` — simulator rows → stand-in insights (then `pull --until`).
- Account `900000000000006` ← `EAAG-drill-token-beast`.

## Drill 7 (2026-09-29) — the same drill 6, B side only, after F38

`docs/drills/drill-7/`: `plan.md` (what changed: only the system version and the two F38 steps — proof facts
registered, promo offers enabled by hand), `sim_B_1..3.md`, `simulation-summary.md`, `report.md` (A-vs-B before/after
table first), `plans/` (run logs, exported plans, judge fits). Side A is reused from drill 6, never re-run.
Result: B 0.38 -> 1.46 total ROAS, A still 2.25.
What the drill cost the fixture this time: the drill clock covers `now_utc` only; `ads.month_budget._fresh`
(`datetime.now`) and `observed_at` (SQL `now()`) keep real time, so a planning day earlier than the real date
blocks launch approval and a later one zeroes the month known spend (report §3 #17). Start the worker as a detached
process, not a shell background job.
