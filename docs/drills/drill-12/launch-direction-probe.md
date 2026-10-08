# First-release direction: pre-implementation probe

Date: 2026-10-07. Product HEAD: `2375e161d06da0455977e87a8010db6dc4f7137f`.

The user approved a first release that prioritizes defensible strategy, faithful execution
and evidence-based adaptation over polished copy/images or profitable simulated results.
The latest instruction requires probes before implementation to reduce avoidable rework.
This report records that preflight; it does not close F52, revise historical scores, certify
deployment, or authorize public publication/platform writes. No product source was changed.

Subsequent `/dig` closeout: the user requested basic planning and a frontend prototype for
another session to `/carve` and `/crank`. See the [planning Handoff](first-release/Handoff.md)
and its canonical roadmap link. The historical probe sequence below remains evidence, not
authority to start work. The new prototype does not change product behavior or this receipt.

## Evidence and limits

- [Function/SQL results](../../../.harness/scratch/launch-direction-probe-20261007/results.json):
  11 fixed cases, 7 matching the proposed release expectations and 4 gaps. The first two
  diagnostic runs agreed. A final assertion-mode run returned nonzero on the same gaps.
  Production functions and real PostgreSQL SQL ran against connection-local TEMP tables.
  The event writer's persistence sink was intercepted; its reader/query path was real.
- [Planning/configuration results](../../../.harness/scratch/launch-direction-probe-20261007/planning-results.json):
  8 checks, 6 matches and 2 contract gaps. These are counterexamples/static consistency and
  configuration checks, not an end-to-end model-quality verdict.
- [Targeted checks](../../../.harness/scratch/launch-direction-probe-20261007/targeted-tests.txt):
  5 existing tests and 2 subtests passed in 12.16 seconds on the current product source.
  They cover accepted audience/offer bindings, changed revisions, original creative carryover
  and duplicate verification. Controlled providers prove contracts, not marketing judgment.
- One actual `CodexCliProvider` call used the actual strategy department prompt and a fixed
  synthetic context, with tools disabled in an empty temporary directory. The existing
  `gpt-5.6-luna` provider model timed out after 60 seconds. No model output was obtained;
  there was no second model attempt or directly billed API call. This does not identify
  whether the timeout originated in model latency, authentication, CLI or transport.
- Production configuration guards reject dev tokens, local HS256, memory queues and scripted
  replies. A synthetic valid configuration passes validation; no production connection,
  genuine session-expiry, backup restoration or deployed model has been verified.
- The initial planning probe omitted a required campaign ID and failed before a model call.
  Correcting this diagnostic fixture is recorded separately, not counted as a product defect.

The counts are diagnostic-case counts, not release completeness percentages. Expectations
marked GAP describe the newly approved release direction; some differ from older intentional
brand-level contracts. A local counterexample does not prove an observed production incident.

## Findings and required plan corrections

| Finding | Evidence | Correction before dispatch |
|---|---|---|
| Confidence borrows evidence from other sell-ways | C03: two other-product campaign verdicts promote the current product to `validated`; E01: matching event text from another product also promotes | Define promotion cohorts by the claim's actual applicability. Audit campaign, pause, A/B, month-settle, coordinate and visual writers/readers together; do not fix only one counter. |
| Simulation qualification is incomplete at the confidence boundary | C04: an isolated simulation can receive `validated`; existing text still says it is simulation | Preserve existing simulation labels/isolation and give simulation a structurally distinct evidential meaning. This is not evidence that simulation already contaminated a real brand. |
| Old and changed-condition evidence relies too heavily on annotations | R02: a 400-day-old event reaches the planner; R04: revalidation is preserved as a flag. Full caller tracing found no age gate in the ads-track reader | Evaluate applicability at read time using source conditions and current facts. Do not impose a blanket expiry on every brand fact. Old results may remain visible as history without proving today's recommendation. |
| Decision revisions miss learning semantics | D02: changing same-ID `learning_text`, confidence and revalidation leaves the decision revision unchanged. `decision_context` reads `text`, not the ledger's `learning_text` | Normalize the actual learning fields once and include decision-relevant eligibility/meaning in the revision. This is a contract counterexample; current writers do not establish that same-ID semantic mutations already occur in production. |
| The strategy prompt contradicts its own offer contract | D01: actual validator accepts a disclosed `none` slot with available offers. D03: the older prompt requires an offer while Contract S permits `none` | Align existing prompt and validator rules; preserve the accepted explicit no-offer case. A model sample has not resolved the uncertainty because the single attempt timed out. |
| Final-release operational proof remains incomplete | Existing startup guards pass; old SQLite backup code was retired for Postgres. No current restore/deployment receipt was found in the inspected paths | Verify the selected deployment's backup and restoration path rather than adding an unrelated backup framework or claiming a backups directory proves recoverability. |

## Existing behavior to preserve

Other-product/explicitly-expired rows are already excluded by the planner learning reader.
Tenant and result-family confidence filters work. A current insufficient sample remains
`observed`. Rechecking the same action does not create another learning. The newest period
verdict deliberately supersedes the old verdict for that sell-way; historical ranked results
are separately available. Do not restore stale conclusions as equally current or rebuild
the strategy-to-adoption flow that passed the targeted checks.

## Refined sequence within the approved three-step direction

1. Settle one narrow evidence contract in the existing domain pages: source identity, product,
   result/claim meaning, period/provenance, applicability, confidence qualification and revision
   impact. Inventory all its actual writers, readers and fixture factories before cutting work.
   Retain fact-based cross-product knowledge only when its brand-level applicability is explicit.
2. Repair demonstrated gaps at those existing boundaries: scoped confidence, eligibility on
   read, normalized learning revisions and the contradictory strategy instruction. Use these
   frozen counterexamples as regression checks. Do not redesign the UI, introduce another
   learning ledger, add full automation, weaken numerical rules or redo the 24 completed repairs.
3. Validate the first-release cycle on one final build: cold start, insufficient data, usable
   evidence, contradictory outcomes and changed conditions. Expected behavior must admit
   reasonable alternatives while rejecting fabricated facts or unsupported certainty. Verify
   actual next-period adoption, not merely a changed explanation. Run required integration once
   on that final tree, plus the missing operational/model checks and one combined acceptance.

Poor prose/style, unattractive imagery and simulated profit are not first-release blockers.
Fabrication, inconsistent target/configuration, wrong money, inappropriate learning promotion,
silent data loss and inability to recover the supported main path remain blockers. The historical
F52 nine-dimensional threshold is not retroactively relaxed or reported as passed.

## Stopping rule and current status

Bounded preflight is complete with demonstrated gaps and explicit uncertainties. Do not sample
another model run or launch an entire drill merely to seek a green result. Future implementation
addresses these causes first, then reruns affected checks only after relevant changes. The model
and operational gates must remain unverified until an appropriate successful receipt exists.

Current status: probe artifacts and the refined sequence are saved; no repair issue was started,
no product behavior changed, no public deployment/push/platform mutation occurred, and the
previously paused F52 integration/drill remains paused.

Reproduction (local diagnostics only):

`uv run --frozen --no-sync python .harness/scratch/launch-direction-probe-20261007/probe.py --assert-release`

This presently returns nonzero by design because the proposed release criteria have gaps.
Source hashes and exact outputs are retained with the linked artifacts.
