# Drill 12 remediation ledger

Planning snapshot: 2026-10-06 (Asia/Taipei), code HEAD `84a5640a`, branch
`feature/audit-d-http-figures-wizard-platform`. Latest supplied report: `report.md`,
17:20:52 local file modification time. Read-only source inspection; no new runtime verdict.

This ledger reconciles the four drill-12 documents with their linked operator, persona, control
and fault records. Historical observations remain immutable. F52 owns the follow-up, not a
retroactive pass for drill 12. Issue numbers below mean F52-Ixx.

Classification: **O** observed unresolved defect; **C** source-confirmed mechanism;
**H** hypothesis requiring a discriminating reproduction; **R** repaired in the baseline,
regression only; **V** verification gap; **X** tool/fixture limit or explicitly unsupported capability.
Severity follows drill-10's original blocking/detour/appearance ruler, not a new severity scale.

## Exhaustive disposition

| ID | Finding / correction | Status and source boundary | Owner / acceptance |
|---|---|---|---|
| D01 | Strategy promises audiences, retained ads and offers that the built allocation does not implement, in P1 as well as P2/P3 | O+C. `B/run_1..3.md`, `operator/p2-strategy-root-cause.md`; strategy validates prose/percentages, plan independently preplaces carried ads | I01, I03, I04; A01 |
| D02 | Carry retains the former role; capacity can exclude a promised new audience | C, not a mandate to promote all relative winners. Exact P2 carry-selection runtime input remains unknown | I01; explicit role assignment and feasibility before acceptance |
| D03 | Candidate audience list says “this period targets 3 groups” before adoption | O+C. Unique customer groups differ from delivery-group count. Post-adoption persistence of this exact label was not proven | I01, I03; distinguish available/proposed/built |
| D04 | 72/28 rationale is unexplained; numbers alone are not an evidence-derived optimal split | O. Model chooses percentages; program calculates amounts | I01, I03; show recommendation and cited reason, not an invented formula |
| D05 | Known calendar opportunity omitted or late; P2 creative repeats retained proposition | O, independent blind judgment. P2 0.95 already includes repetition penalty; do not deduct twice | I02; A02/A09 |
| D06 | B copy fit 6.85/6 is below 1.15; P3 new student copy lacks a purchase reason/offer despite strategy promise | O. No observed incorrect registered offer or none-offer leakage. It is not a rule that every ad must carry every available offer | I01/I02; A02/A09 |
| D07 | Aligned CPA 824.0109375, score 3; learning score 5 despite actual removal of worse ads | O outcome, not an independently proven software defect or proof of zero learning. Unequal dates/budgets/counts prevent causal winner claims | I01/I02 plus fresh A09; no simulator tuning |
| D08 | Product-name “特惠” rejected in a free-shipping slot | O; H exact mechanism. Current guard already strips registered active names; inspect persisted name/status/sell-way context and exact matched span before changing it | I05; A03 |
| D09 | First approval rejects unchanged settings in P2/P3 | O; H exact runtime cause. `PublishList` reads hash separately from settings; `launch_settings.view` can update the pixel cache. This is a plausible race, not proven runtime causality | I07/I08; A04 |
| D10 | Refresh updates totals but paused detail remains until reload | O; H timing/ownership. Current workspace already reloads campaign on settlement; performance also reloads on busy transition. Do not claim a missing refresh callback without reproduction | I13; A05 |
| D11 | “Live” with 0 running/2 paused, no clear next action | O+C semantic distinction missing. Lifecycle live does not prove platform delivery | I12/I13/I14; A05 |
| D12 | New-ad recheck treats placement ID as external-entity ID | O+C. `handoff_new_ad.create` sets target_id=placement; `change_routes.check` calls generic `change_control_verify.check`, which queries `bindings.entity(target_id)` | I09/I10; A06 |
| D13 | New-ad confirmed screen says not yet read; material equivalence still unknown | O+C projection mismatch. Handoff-item timestamps and aggregate action evidence are different carriers; a settings match must not imply independent image equivalence | I09/I10; A06 |
| D14 | Period 10/24–30 includes 10/21–23 performance (2400 vs in-period 900) | O+C blocking money scope. `outcome.summary` buckets unbounded `performance_rows`; `repository._outcome_totals` also unbounded. Injected pre-start rows establish boundary defect, not real delivery loss | I06; A07 |
| D15 | November retry retains failed October monthly read | O+C detour. `external_sync.request_sync` retains all monthly keys but requests current month by default; operator explicit backfill is not unaided recovery | I11; A08 |
| D16 | Coordinate category resets after toggle save | O+C, A453, a-13. Loading unmounts child holding selectedCategory | I15; A10 |
| D17 | Last visible home block checkbox disabled without reason | O+C, a-14. Not fixed by a Button-only scanner because it is a native checkbox | I16; A10 |
| D18 | Free-job preview looks interactive but is intentionally inert | O appearance/accessibility, not failed job creation. Same reusable card on workbench home | I17/I18; A10 |
| D19 | Count 1 returns 5 copy variants | O UI contract only. `prompts.py` and `jobs.py` require 5; video_script uses count. Do not change server copy cardinality | I19; A10 |
| D20 | Image run briefly says another part is generating after navigation | H, final B inventory. Not proof of wrong job execution | I19: reproduce exact job/part IDs; fix only if confirmed, otherwise retain bounded non-reproduction |
| D21 | Applicable return policy cannot carry conditions in its own row; fixed universal legal wording conflicts with source qualifications | O+C from `operator/prefill-root-cause.md`. Applicable=true drops disclosure; custom policy is a detour. No legal-validity conclusion | I20/I21; A11 |
| D22 | Suspected source-free prefill inventions | Corrected: the specifically quoted statements occur in frozen website text. Source presence is not truth/efficacy/legal clearance. Exact raw per-run prompt and all five rejected claims are not proven | I22; A12. No blanket deletion or hallucination score inferred |
| D23 | Prefill validator permits weak/missing source notes | C risk, not an observed fabricated statement entering data. Confirmed proposals and undecided claims have different barriers | I22 source-boundary characterization; fail/replan a narrow repair if a violated existing contract is demonstrated |
| D24 | Negative break-even -5 clamped to 0 (I15) | R; d46b3c75. Historical dimension 8 failure remains | A13 regression, no duplicate implementation ticket |
| D25 | Save acknowledged later unsent money edits (I17) | R; 2f3570c0. Historical data-loss falsifier remains | A13 delayed response and reload |
| D26 | Launch reservation counted again after platform owner readback (I18) | R; 6f3691b9 plus I19 ab1a701f. Confirmed final 672 ongoing / 0 reserve / 2181.92 available only for that fixture | A13 positive and conservative fallback cases |
| D27 | AdsHome omitted central offline reason (I16) | R; 54bae15c after original fault run; actual outage/retry evidence exists | A13 live outage on final build |
| D28 | Integration first had three failures; intermediate contaminated environment run stopped | R for final recorded integration, not fresh validation here. a38ff123 receipt: backend 3858 + 803 subtests, frontend 1812/129 files; verify against head before reuse | Supervisor environment isolation; A14 |
| D29 | Stopping worker during strategy did not stop the web-owned call | V. A successful strategy here is not crash-recovery proof | I23; A08 proper web-process interruption |
| D30 | Authentic session expiry unverified; 0 work-order-missing observations is not absence proof | V. Logout is not expiry; only two interrupted worker jobs were sampled | I23; A08 authenticated expiry and persisted job identity |
| D31 | A/B/C control totals use different grains; repeated/generated entries and conditional branches remain untested | V. 582 / 244 / 403 must not be summed into a pass denominator. C inventory contains historical IN PROGRESS text superseded by final c.md | I24; A10, use final ledger sections |
| D32 | Cleanup end-to-end, eligible-month settlement, date/source/candidate/history alternatives, download/print/dialog outcomes not all established | V, precise list in acceptance.md; ended spare cleanup is inapplicable, not passed | I24 fixtures and new control/fault agents |
| D33 | Raster output/service and reference upload unavailable | X, declared unsupported, not proof of broken image generation; no provider procurement or paid activation in F52 | Capability-honesty check only; visual quality stays unverified |
| D34 | Clock mismatch, file-access setting, Chrome disconnect, selector/SQL/tool errors | X as observed. Do not turn drill-time mismatch into a production clock verdict. Independently test actual org/account zones only where scope changed | A14 test-environment admission |
| D35 | 48-station averages and repaired station replacement | V quality accounting. Original avg 8.2292/min1 fails; repaired avg8.3958/min5 is supplementary, five-question denominator unproven | A09 fresh stations, no retrospective rescoring |
| D36 | Frozen A is not a flawless gold standard; partial masking and unverified A claims | V comparison limit. A strategy also scores5; A P2 exact ROAS<2 even if displayed2.00 | I24/A09 preserve history, disclose uncertainty, do not copy A blindly |

## Source-level corrections that matter for implementation

1. Budget arithmetic already reconciles while semantic assignment does not. Another money calculator would miss D01.
2. Name stripping already exists (`claims.registered_names/unsupported`). D08 needs a reproducing input/context, not a second guard.
3. Workspace settlement already calls `load(true)`. D10 needs request-order and data-carrier evidence, not an unconditional extra reload.
4. A new-ad action's target is a placement, by design. D12 is dispatch/ownership confusion; removing tenant checks would make it worse.
5. Raw performance history remains useful for explicitly labelled comparisons. Fix D14 at scoped projections; do not globally delete or clamp historical rows.
6. The fixed-five copy contract remains. Variable count is retained for video scripts; image prompt behavior is unchanged.
7. Platform “confirmed” is scoped evidence. Self-confirmed images, matching settings, delivery state and sales causality are separate.
8. The report is a multi-build historical run. None of the later repairs makes its original nine-dimension failure a clean pass.

## Evidence preservation

Raw root: `.harness/scratch/drill12/`. Read `B/run_1.md`, `run_2.md`, `run_3.md`;
`controls/{a,b,c}.md` final sections and inventories; `faults/faults.md`;
`operator/{p2-strategy-root-cause,prefill-root-cause}.md`; `blind/verdict.md`.
The originals, fake state, scores and exports must not be edited to make F52 pass.
The 143-file / 113-JPEG integrity receipt is historical evidence, not a new check by this planning session.

