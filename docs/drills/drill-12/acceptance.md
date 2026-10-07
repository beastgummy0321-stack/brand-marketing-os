# F52 acceptance specification

Status (2026-10-07): the 24-ticket repair queue is implemented and locally merged with scoped
checks, independent reviews and bounded UI evidence. The user requested pausing after repairs;
final integrated acceptance and the next three-period/control/fault/quality round are deferred.
No A01–A14 whole-clause pass or revised drill-12 score is implied. This remains the mandatory
acceptance contract; product choices live in domain architecture pages.

## Roles and admission

The authorized repair execution used a supervisor, implementation workers and independent
reviewers. Resuming final acceptance requires an explicit new instruction and these separated
roles; the latest pause overrides the earlier whole-queue/drill approval.
Workers may not approve their own material money/interface/security changes. The supervisor
owns queue metadata, merges, scope adjustments and one combined acceptance presentation.

Before running product checks: record checkout/head/dirty state, owned server/worker PIDs,
port, database scope, provider, queue and org/account clocks without secrets. Restart owned
backend and worker on the final build. Use a fresh isolated local run and fake platform; preserve
drill12 and other sessions. Do not reset shared databases or kill unowned processes.
Remove inherited drill provider/queue variables for machine integration per docs/verification.md.
Use current host browser tools. Missing tool capability is a gap, never a pass.
F51's active-AI-queue W14 exception remains; F52 does not redesign that outcome.

## A01 — accepted strategy is executable

Fixtures cover cold start and two carryover periods; ceiling 1, 2 and larger; a prior retained
ad in explore; a promised new student audience; free_shipping vs discount; missing/deleted
audience or offer; unknown/zero/nonpositive cap; reduced budget; no eligible retained ad;
cross-brand identifiers; duplicate slot IDs; changed input revision and simultaneous adoption.

- Structured role/audience/offer/carry IDs agree across proposed strategy, adoption receipt,
  persisted groups/ads, displayed structure, copy brief and handoff export.
- For ceiling2, retain the chosen fitness ad and explore students exactly as accepted, or refuse
  the infeasible proposal before adoption with a usable revise-budget/assignment exit.
  No hidden substitution or dropped promise; no automatic promotion of every relative winner.
- Carried creative preserves bytes/version/copy and source identity. A reassignment of role is
  explicit in the accepted proposal and preserves the chosen allocation amounts.
- Program split totals equal the adopted budget. Percentages are recommendations, with reasons
  tied to evidence IDs and sample limits, not a claim that a precise optimum was calculated.
- Before adoption, available/proposed counts are labelled accordingly. After adoption, actual
  unique audience count and delivery-group count are separately correct.
- Adoption is idempotent and atomic: a rejected/retried proposal creates no partial plan.
  A saved legacy strategy is readable but must be regenerated/reconfirmed before a new adoption
  requiring the contract; historical approved plans are not rewritten.

## A02 — learning and creative quality

Use structured accepted slots from A01. Program supplies chosen audience, known facts, selected
registered offer sentence, prior results/sample limits, earlier creative and eligible calendar
events. The model chooses a distinct useful proposition and writes copy; it does not calculate
money, invent product evidence or infer demographic eligibility from a name.

- Distinguish a deliberate retained control from a new test. Rewording “no water/no mixing”
  is not a new test merely because its headline changes. A new test states the intended
  audience/situation/proposition difference and which known observation motivates it.
- A relevant known event is used or a reason for not using it is recorded; invented urgency,
  unavailable offers and hardcoded holidays/audiences do not satisfy this check.
- Registered selected offer is present where required in consumer-visible copy. An offer=none
  slot remains legal to propose when disclosed; it cannot silently replace an accepted offer slot.
  Do not require both discount and free shipping on every ad.
- Exact retained copy is not regenerated simply to raise a score. Relative best above target
  remains above target; do not call a small sample proof.
- Scripted tests establish input/output contracts; fresh independent judging establishes quality.
  Neither keyword counts nor a model self-score substitutes for the latter.

## A03 — one scoped claim guard

Reconstruct D08's exact current registered names, active statuses, selected sell-way and selected
copy. Exact active registered name spans containing 特惠/優惠/免運 are identity, not offer promises.
Outside those spans, an unsupported discount in a free-shipping slot still refuses.
Cover overlapping/long names, delimiter-derived sell-way names, archived/other-brand names,
unregistered shortened names, names next to an actual promise and forbidden product statements.
Do not add arbitrary aliases or exempt the whole sentence. Workbench warning, asset slot and
manual edit route must yield the same scoped result. Keep statutory warnings distinct from
forbidden/unsupported facts. If current code passes the original case, record non-reproduction
with exact differences instead of claiming a speculative repair.

## A04 — first approval and real conflicts

Capture expected/current hash component diff before repair (red test), including slow settings
load, pixel-cache refresh, reversed response order, no user edits and real concurrent edits.
An unchanged, fully loaded list approves on the first click; approving twice records one operation.
A genuine price/date/budget/audience/material/offer change still stops and displays the change.
A refresh does not automatically approve or replay a write. Unknown network result follows the
existing central HTTP contract. Do not remove hash/permission/month-budget checks to pass.

## A05 — one refreshed view and truthful delivery guidance

Fake platform changes 2 paused ads to running and updates performance. Complete one normal UI
refresh with no page reload: totals, row status, running count, overview and opened detail agree.
Repeat with slow/reversed requests, changed campaign during refresh, partial read, empty result,
failure and retry; no late response can overwrite a newer campaign/view.

Lifecycle and platform delivery remain distinct. Test draft, locally approved/unbuilt, read
paused, scheduled/not-yet-running, active, unknown/stale read, ended and closed.
Known paused=0 running does not say unread. A lifecycle live label does not imply actual delivery.
The screen offers a capability-aware next action (review approved platform checklist/read again/
view known paused state) without automatic activation or requiring live ad spend.

## A06 — new-ad verification

Using an isolated confirmed placement, approve a new-ad change, bind a native candidate and read.
From both handoff and Verify, recheck uses the same handoff item and same org/brand/campaign/set.
Single and multi-item paths work after reload; placement ID is never queried as an external entity.
Cross-brand/campaign candidate remains rejected. Missing, superseded, changed revision, partial,
deviated and concurrent stale-attempt branches remain safe.

Show last successful observed time only when supplied, attempted time separately on failure.
Match/unknown/self-confirmed material evidence remains visible and distinct. Settings matched with
unreadable image does not claim independently confirmed pixels or delivery. Reread cannot create
a duplicate new ad or clear a newer mismatch through an old response.

## A07 — period money has one explicit window

Use c-15: rows10/21–23 each500/1/1560, rows10/24–26 each300/4/6240, campaign10/24–30,
as-of10/27, same currency. Campaign period projection = spend900, purchases12, CPA75,
ROAS20.8; the raw older rows remain available for an explicitly requested comparison.
Reconcile totals, daily series, group/ad tables and shares, grade, campaign list/detail,
closeout and learning inputs against their declared windows. Monthly account spend remains
a different scope and may legitimately contain all six rows.

Test pre-start, exact start/end, post-end, future, incomplete current day, unknown dates,
no data, null purchase/revenue, zero purchases, multiple currencies, imported campaigns,
unbound entities, old attribution rows and different org/account timezones.
Ordinary period totals use completed account days through min(end,last_complete_day); explicitly
shown current-day provisional data stays separate. Date-less imported history uses an explicit
observed/requested range, never an invented campaign start. Recent, comparison, monthly and
period windows must not be collapsed into one global repository filter.

## A08 — recover the same failed operation

- Fail October monthly read; move clock to November; use ordinary visible retry. October gets
  a real targeted retry and November refresh still works. Retain last good data while pending;
  failed/partial/unknown remain so until actual scoped success. Retry is idempotent and scoped
  to the authorized account; no replay of closed campaigns merely to clear a monthly error.
  Check cursor restart/resume rules, partial pages, two failed months and repeated clicks.
- Stop the actual owned web process during strategy generation, not just worker. After restart,
  the normal UI preserves inputs and offers a bounded recoverable result, with no forever-running
  record, duplicate accepted strategy or duplicate charge claim. Test both before persistence
  and persisted-response-lost boundaries. If product recovery fails, the supervisor adds a narrow
  repair issue from this demonstrated case before acceptance; it is not solved by changing W14.
- Repeat worker prefill and copy interruptions using actual worker PID. Persisted task identity,
  editable input, old failure/new attempt and retrievable output are accounted for.
- Authentic isolated session expiry: exercise invalid/expired access and failed refresh through
  supported local Auth/browser operations; successful refresh alone is a separate case. Login
  reason, original route and unsent form survive; a rejected write is never automatically replayed.
  Logout or a mocked component event is not authentic expiry proof.
- No missing-work-order message in these scenarios is sample evidence, not a global absence claim.
- Every fault records reason, exit and data retention; any actual data loss fails dimension9.

## A09 — fresh end-to-end quality gate

Follow drill-10 plan's unchanged nine-dimensional ruler and drill-6 simulation/judge contract.
Freeze source facts and persona facts with differences disclosed. Independent persona, operator,
control/fault testers and blind judge must not coach one another. Judge sees masked plans/copy/
results with uniform packaging and retained limitations, not repair tickets or desired answers.

B starts from a fresh account and completes three periods on one integrated product build.
Keep frozen A historical scores; A is a comparison, not a passing gold standard.
Retain actual/aligned date × per-ad/group audience variants and all earlier-period priors.
Do not tune tw_sim, cherry-pick a seed/copy/run, round across thresholds, or call simulations real results.
Record requested and used budgets/ad counts and any asymmetry.

All nine B dimensions >=7 and zero blocking defects. Specifically:
strategy/learning follow original rubric; copy mean>=1.15 with original claim criteria;
aligned aggregate CPA<=559 meets the original 7-band (trend adjustment follows the unchanged
rubric, not a new cutoff); completion has no product-data rescue and <=3 detours per period;
controls >=95% under A10 and <=3 detours; comprehension average>=7, minimum>=5,
five-question pass stations>=80%; honest numbers have no wrong money or admitted fabricated facts;
recovery>=80% with reason+exit+data retained and no silent deadlock/data loss.
If any metric fails, report failure and leave F52 open; do not keep sampling until one passes.
A necessary emergency product repair invalidates “single clean build”; retain that run and schedule
a new clean run after repair, without erasing it. Subjective user acceptance follows this evidence.

## A10 — UI and control coverage

Inventory key = route + semantic state + control/action, with stable ID, prerequisite, expected
observable effect, source screenshot, final verdict and exclusions. Generated identical instances
are one semantic control unless their branches differ. Repeat/retest events attach to that key.
Denominator = all applicable inventoried controls; unknown/untested/partial stay in denominator
but not pass numerator. Document inapplicable/unsupported exclusions separately. A complete
inventory is required before any “all controls” or >=95% acceptance statement.

Outstanding drill12 branches to cover on fresh spares:
- A216 refresh outcome; A247 margin reset and A248 cancel; A349 persona regeneration confirmation;
  A420 retry-to-success; A421 print/PDF output; A561 alert dismissal. A017 valid invitation and
  A233/A234 credential-save remain excluded unless an isolated local fixture safely supplies
  them; no external messages or real credential mutation is implied.
- B empty assumption-fill branch if not otherwise evidenced; original suggestion continue/discard
  recreated on a new spare; copy/plain/warning selection branches; reference upload and raster
  output marked unavailable. Image-run job-label hypothesis gets a targeted trace.
- C 23 partial verdict rows; date helpers, upload/download results including monthly CSV bytes,
  candidate/source/placement alternatives, change history and exits; full cleanup approve/handoff/
  verify on a campaign still eligible at the deferred date; eligible-month settlement wizard and
  legacy redirect on separate spares. Never repair the old ended spare dates to force applicability.
- All changed screens: 1024/1920, long real names, keyboard focus, loading/empty/failure, and
  reference|built screenshots under docs/design-system.md §1.7. Keep existing HTML prototype
  for ads. Limited control fixes use their drill12 screenshot/current screen as reference;
  substantial hierarchy changes need Harness demo before implementation.
- Coordinate category survives successful/failed save and brand switch resets appropriately;
  final home block has visible, keyboard-associated reason; previews contain no dead focusable
  controls; copy says fixed5 and script count1/2 still works.

## A11 — applicable policy conditions

Save/read/reload an applicable policy with user-entered conditions and source note; preserve
non-applicable disclosure separately. Toggling applicability does not destroy unsent conditions.
No generic “all online goods may be returned” claim. Display these as merchant-provided policy
details, without deciding statutory exemptions or legal validity. Existing custom-policy records
stay readable; preserve unknown provenance rather than fabricating a URL. Test no conditions,
long conditions, empty exemption refusal, old payloads and tenant isolation.

## A12 — source presence, user confirmation and truth are separate

Use the exact frozen product/refund snippets cited by the operator. Report source-backed statements
as such, whether or not persona retains them. Feed absent snippets, forged source labels, missing
notes and undesired transformed customer groups to characterize the current proposal boundary.
Proposals remain distinguishable from confirmed facts, claims require explicit decisions, and
rejected claims do not silently return as approved downstream inputs.
The tests must not call website text independently verified truth. If a source-free sentence can
cross an existing promised barrier, record the failing case and have the supervisor carve the
smallest demonstrated repair; do not silently widen this plan into a universal fact checker.

## A13 — keep baseline repairs

I15: signed -5/0/positive break-even; no invented allowance.
I17: in-flight older save + newer edits, blur/Done/error/reload;180/200/60/10→110 and50/10/0→40.
I18/I19: matched owner not reserved twice; partial/missing/stale/cross-account evidence still holds
conservative reserve; ABO/CBO and fixture adapter vocabulary;31500−28646.08−672−0=2181.92 only
when all those scoped facts hold.
I16: real local backend outage after loading SPA, independent money/decision panel errors,
restart without reset and visible retry recovery. Reuse existing tests through final integration;
fresh live evidence is needed for the new integrated build, not duplicate repair tickets.

## A14 — evidence package and closeout

Required: head/environment receipt; targeted red/green tests for confirmed defects; money and
tenant-risk independent review; final full Harness integration; API/DB exports for numeric
reconciliation; reference|built UI page; normalized controls; per-fault screenshots; fresh
three-period persona logs; masked judge packet, raw fit files and independent verdict; exact
simulation aggregates; unresolved/excluded matrix; owned-process cleanup receipt.

Machine checks, local fake-platform E2E, actual model output quality, native browser evidence
and human approval must be labelled separately. All acceptance clauses link to evidence or explicit
failure. F48–F51 retain their existing open/human items; F52 does not close them by implication.
Only explicit user acceptance of the combined result can satisfy human items. No push, real
platform writes, paid service activation or request for the user to run live ads.
