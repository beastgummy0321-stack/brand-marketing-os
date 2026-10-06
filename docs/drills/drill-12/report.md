# Drill 12 — acceptance report (in progress)

The completed strategy, copy and learning dimensions each score5, below the required7. The drill does not pass overall.
Controls/faults and final integration remain in progress; this document is not a closure receipt. All advertising figures
are local fixed simulation results. No real Meta delivery or performance is claimed.

## Ruler and evidence boundary
Use drill10's nine dimensions without changing thresholds. A is frozen drill6 evidence; B completed3 periods, independently
operated and judged. Dates, budgets and ad counts differ; X/Y masking was partial because formatting differs. P3 B reduced
budget independently from10500 to6300, so aligned dates do not make spend or creative selection equal. Independent verdict:
`../../../.harness/scratch/drill12/blind/verdict.md`. Raw evidence is under `.harness/scratch/drill12/`.

|Dimension|Frozen A|B original/observed|Status and basis|
|---|---:|---:|---|
|1 Strategy|5|5|Independent blind verdict; built audience/roles/offers do not consistently follow reasons|
|2 Copy/material|7|5|B fit6.85/6=1.141666, below1.15; no rounding across threshold|
|3 Simulated results|8|3|Aligned B aggregate CPA824.0109375; mixed period trend gives no monotonic bonus. A CPA512.0175 and improving trend+1|
|4 Learning|7|5|Independent verdict: changes exist but rationale and built structure disagree|
|5 Completion|—|5|All3 periods closed after one product-blocker repair/restart during persona; not an unaided pass|
|6 Controls|—|Pending|A/B/C inventories still in progress; incomplete routes and tool-blocked controls are not passes|
|7 Understandability|—|5 original; repaired observations separate|48 distinct stations average8.2292,min1; original minimum fails7-band. Replacing only repaired money station gives8.3958,min5; five-question aggregation still qualitative|
|8 Honest numbers|—|0 original; repairs separately verified|I15 displayed-5 as0. I17 later lost unsent money edits. Original failures remain despite repair|
|9 Recovery|—|Pending|Fault rows and disruptive worker/platform cases still in progress|

Station normalization excludes the extra I15 rerun from original aggregation and the interim host-upload-only observation,
then keeps the completed upload station. Source lines and all50 recorded scores are in operator/station-score-extract.json.
The repaired replacement is a supplementary comparison, not a new clean persona run or an overall acceptance score.

## Simulation comparison
|Side|P1 CPA|P2 CPA|P3 CPA|Total spend|Purchases|Blended CPA|ROAS|
|---|---:|---:|---:|---:|---:|---:|---:|
|Frozen A|1011.96|526.78|316.46|28672.98|56|512.0175|2.25491|
|B actual dates|782.43|1001.48|605.97|26246.08|33|795.3358|1.25607|
|B aligned A dates|1128.80|675.99|758.65|26368.35|32|824.0109|1.21236|

Four B variants (actual/aligned dates × per-ad/group audience) were retained. Group variants match per-ad variants because
each B group has one ad. Every period uses all corresponding earlier-period priors. Source: operator/simulation-comparison.json.
A P2 ROAS remains below2 (exact aggregate1.996531...), regardless of rounded2.00. Blind verdict's textual calculation differs
slightly; the canonical row aggregate here governs numeric reporting, and both values remain below2.

## Defects and interventions
|Finding|Severity|Evidence / bounded status|
|---|---|---|
|I15 negative break-even clamped to0|Blocking money|Original persona1/10; same input after fix9/10. Red7 tests failed, green58 passed; independent review and merge passed|
|I17 save response acknowledged newer unsent money edits|Blocking money/data|Original controls b-02/b-03; red2 tests failed then24 passed, independent review and merge. Real UI saved/reloaded180/200/60/10 ->110, and50/10/0 ->40|
|P2/P3 strategy-to-structure mismatch|Detour / material planning|P2 promised students, built fitness; P3 roles reversed and student offer absent. operator/p2-strategy-root-cause.md; no ordinary repair during drill|
|Free-shipping guard rejected product name containing 特惠|Detour|P1/control-C visible neutral-wording exit worked; original evidence retained|
|P2/P3 first approval rejected as changed settings|Detour|No intervening persona edit; second click recovered|
|Performance refresh left stale paused detail|Detour|Updated totals but detail required page reload in P2/P3|
|Live wording with0active/paused ads, no activation instruction|Detour|Three wait stations score6; fake activation belongs to operator; status guidance remains unclear|
|AdsHome dropped central offline reason (I16)|F51 acceptance failure|Separate seed-account browser evidence; isolated repair105 tests passes, deployment deferred until drill ends|

Quoted prefill claims were found in the frozen website source. Preserve persona skepticism, but do not label those quotations
source-free inventions. Source presence is not truth verification; operator/prefill-root-cause.md distinguishes both.
Original date-input tool behavior, Chrome file-access dependency, browser reconnection and frontend/backend drill-clock
mismatch are instrumentation limitations, not product passes or defects. Original screenshots remain available.

## Money, offers and platform proof
Campaign/adset/ad totals reconcile separately in operator/reconcile_1..3.json. This establishes those scoped numbers, not
every screen. F44 offer counts: P1 2/2, P2 2/2, P3 1/2; incorrect registered offer0 and none-offer leakage0. P3 absence of
an offer still conflicts with the strategy promise. Pain selections are valid and no video was generated. One planning task
per period; this is not current advertising policy/legal clearance. Platform image versions were approval self-confirmations,
not independent image readback. The user-approved W14 active-AI-queue exception remains outside backend outcome redesign.

## Build transitions and outstanding work
Original baselineec72ce1a -> I15d46b3c75 during persona stop -> I172f3570c0 after all control agents paused. No database,
fake-state or clock reset at restarts. Raw original and rerun results are separate. 143 B/plan files are frozen with SHA256;
A source evidence unchanged. I16 remains isolated. Finish control/fault inventories, then merge I16, run fresh F51 integration,
repeat real network/recovery acceptance and present the combined F48-F51 screenshots. All four features remain open pending
explicit human acceptance; no remote push.
