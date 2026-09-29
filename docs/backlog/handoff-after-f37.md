# Handoff after F37 (2026-09-29)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-f34.md`.
Goal of the next session (user, 2026-09-29): finish every remaining drill-6 item in **one feature, one dispatch** —
`/dig` the open questions below once, `/carve` one feature, the user approves the plan once, `/crank` the whole queue.
Re-verify each claim in code first (file:line as of `8ef6d5ec`).

## State
- No open feature; queue empty. F37 closed on `master` (`8ef6d5ec`, **not pushed** — the user pushes manually; F35/F36/F37
  are all unpushed local commits on master).
- F37 (one performance pipeline, ads.md §6.41) accepted by the user 2026-09-29: sync table `ads_external_daily` + recorded
  coverage is the only performance source; `ads_outcome_daily` and `POST …/ingest` are gone (dropped on the dev DB 54322 and
  registered in `supabase_migrations.schema_migrations`); simulated channel = a platform (`SimulatedReader`); closeout refuses
  missing days (skip only after a failed re-read, or always for isolated simulation recovery).
- The user's backend and worker windows must be restarted (`啟動行銷系統.bat`) before any browser check — they run pre-F37 code.
- Simulated campaigns published before F37 have no entity chain → no performance until re-published (test data).

## Drill-6 progress (report `docs/drills/drill-6/report.md` §3 rows 1–20 + 4 planning failures = 24; #21 is a drill limit)
Done 19, half 2 → **≈ 83 %**. Done: #1 #2 #4 #5 #6 #7 #9 #10 #11 #12 #13 #14 #16 #17 #18 #19 #20, plus planning failures
"17 ads one copy" (F35) and "524／天" (F36 #15). Not re-measured: the A-vs-B ROAS gap (2.25 vs 0.38) has not been re-run.

## Remaining (the scope of the next feature)
1. **Proof coordinates claim evidence the brand does not have** (report §4 規劃失敗). Verified 2026-09-29 on the dev DB:
   `brd_bughunt` has all 7 `proof` keys enabled (`customer_review`, `lab_report`, `sales_numbers`, `media_coverage`,
   `expert_endorsement`, `founder_voice`, `none`). Seeds: `app/schedule/repository.py:155-164`; the plan/prompt vocabulary is
   every enabled row (`app/ads/repository.py:1012-1023 coordinate_vocabulary`, `disabled_at IS NULL`); `plan.py:28` lets the
   delivery plan pick any of them. No rule ties a proof key to a confirmed brand fact (`strategy.py:52 _brand_facts_section`
   reads confirmed facts but nothing gates `proof`). **Open question for /dig:** gate by default-off seeds (like RC-C below)
   vs. derive "available proof" from confirmed brand facts at plan time (program rule, no LLM), vs. both.
2. **Offers default on; 「限時限量」 has no deadline** (report §4). All 7 `offer` keys enabled for `brd_bughunt`.
   **Already ruled, never built:** drill-4 ruling RC-C (`docs/backlog/issue-drill-4-root-causes-pending-rulings.md:63-65`):
   `ensure_coordinates_seeded` seeds the six promo offer keys with `disabled_at = now()`, only `none` on; brands enable real
   offers in the existing coordinate screen; existing test brands get a one-off UPDATE (test data). `limited_time` needs a
   deadline decision in /dig (e.g. enabling it requires an end date; copy never invents one).
3. **#3 站內出圖** — `app/workbench/image_port.py` is a reserved seat (`connected()` always False). It spends money and needs a
   **provider decision from the user** (which service, cost cap) before it can be carved; ARCHITECTURE §5.11. If the user does
   not pick a provider in /dig, leave it out of the feature and say so — do not stub it.
4. **#8 audience suggestions — half** (F36 built a read-only 「受眾提示」 row: role + audience labels, `launch_view.py:41-56`).
   Report asked for age／interest／exclusion suggestions on the manual checklist. F36 ruling E: never a platform targeting
   mapping. **Open question:** is a plain-language suggestion line (program-derived from the plan's audience coordinates +
   brand facts, not Meta targeting) wanted, or is the hint enough (mark done)?
5. **#15 account-history source — half** (F36 fixed the divisor). `channels.account_spend_history` (`channels.py:89`) still
   reads `meta_entity_spend` via `app/meta/daily_pull`, while connections/home read the sync table. F37 kept it because the sync
   table has no account-wide read (only bound campaigns). **Open question:** move the account base to the sync `monthly`
   account rows (`read_monthly`, `MONTHLY_BUDGET_ATTRIBUTION_KEY`) or accept two sources with a caption naming which one.

After the feature: run **drill 7** (same script as drill 6, `docs/drills/README.md`) to measure the A-vs-B gap.

## Unverified / open (carried)
- `test_ads_launch_view::test_an_audience_key_without_a_vocabulary_row_prints_itself` failed once under `-n 4` (F37-I03),
  passed 3/3 alone; suspected order dependence on shared vocabulary rows.
- Readback 「讀不到」 26/27 items may be only the drill stand-in (no creative fields mirrored).
- Judge leniency (Haiku scored A 1.3–1.35) — ranking holds, multipliers soft.
- `ads_action.sync_state='confirmed_manual'`: column exists, no writer, read once in `judgment.py:196` (dead path, left).
- F33 agent choices open to reversal: retarget rule uses 90-day external purchases; starting-point facts are prompt-only;
  期中／期末／開學 rows are `kind: "exam"`.
- F34 agent choices open to reversal: conditional 改善／預防 fires only within 6 chars before a symptom word; the seed
  pattern list in `statutory_tw.py` is curated.

## Rejected routes (with reasons)
- Mirroring sync rows into `ads_outcome_daily`, or keeping it for simulated brands only (F37: a second copy of the truth /
  every reader would branch real／simulated).
- Unlocking the closeout skip from any stale error text (F37: only the current observations status counts).
- Deriving `ads_campaign.status` at read time everywhere (F32: one writer at bind time was smaller).
- Letting the LLM decide role availability or holidays (F33: program data).
- Blocking on statutory hits or injecting the word list into prompts (F34: soft reminder only).
- Using `brd_bughunt` for drill personas (real Meta binding pollutes triage; personas register a fresh org).

## Workflow notes that held (F35–F37)
- UI: HTML prototype approved before any frontend ticket; ticket cites the hash; lead compares 參考圖｜成品 before merge;
  one embedded side-by-side page for the user (`.harness/scratch/prototype/F3x-side-by-side.html`).
- Carving: run `harness validate` and read every impact note; list same-folder files explicitly (no `review/**` in
  do_not_touch — it shadows touch). Before tightening a gate, grep **all** tests that call the gated function.
- A new reader class widens union types — the full pyright (not changed-files) catches it at finish.
- Commit closeout docs **before** `integrate`; a doc commit after it forces a second integration run.
- Migrations: apply to 54322 and insert into `supabase_migrations.schema_migrations` before `harness merge`.
- Timing (metrics): F37 six issues, authorize→last merge ≈ 68 min, 3 rescopes, 0 returns; integrate ≈ 3–5 min.

## Drill tooling (drill only, never product)
`scripts/drill/clock.py set|clear`, `tw_sim.py run … --prior …`, `export_plan.py <brand> --period N --campaign <id>`,
`fake_meta load-rows`, `fake_meta pull <org> --since --until`, a hand-requested `external_sync.request_sync`.
Launch configs in `.claude/launch.json`: `drill-backend` (8710), `prototype` (static server for `.harness/scratch/prototype`, 8741).

## Next step
New session: `/dig` items 1, 2, 4, 5 (and ask the user for a provider for 3) → `/carve` one feature → plan approval → `/crank`.
