# Drill 12 control audit

Execution ended2026-10-06 with explicit limitations. This is an audit of exercised states, not a full-coverage certificate.
All product interactions used normal UI in isolated local drill accounts/spares. Original persona periods were protected.

|Area|Ledger grain|Results|Evidence|
|---|---|---|---|
|A: accounts, brand, library, report, settings, home|582 observation rows|567pass,2defect,3partial,4tool-blocked,3untested,3disabled-with-reason|[actions](../../../.harness/scratch/drill12/controls/a.md), [inventory](../../../.harness/scratch/drill12/controls/a-inventory.md)|
|B: products, bundles, workbench|244 historical observations|225pass-labelled rows; repeats and resolved older pending rows remain|[actions](../../../.harness/scratch/drill12/controls/b.md), [ledger](../../../.harness/scratch/drill12/controls/b-observations.csv), [inventory](../../../.harness/scratch/drill12/controls/b-inventory.md)|
|C: launch, decisions, platform verification, monthly view|403 unique exercised controls|379pass,23partial,1failure; additional1disabled-with-reason|[actions](../../../.harness/scratch/drill12/controls/c.md), [inventory](../../../.harness/scratch/drill12/controls/c-inventory.md)|

Different ledger grains must not be added into one denominator. A/B repeat instances and generated controls are not a
catalog of every possible conditional state. C cleanup completion was not applicable after campaign end; source alternatives,
candidate alternatives, date helpers, upload/download results and some history selectors remain unverified. B raster output
is unavailable because the product says its image service is not connected. Tool failures are not product failures.

Original I17 save loss and I18 reserve duplication block a7-band verdict; repaired observations do not erase those runs.
Other confirmed defects: coordinate category reset, missing last-block disabled reason, new-ad candidate recheck mismatch.
Detailed source pointers and screenshots are in the area ledgers and report. Ended-campaign cleanup state is c-24.

I17 real reruns: b-11 values180/200/60/10 give110; b-08 price50/cost10/shipping0 gives40; b-09 cross-bundle persisted.
I18: c-23 after full UI sync shows monthly31500−spend28646.08−ongoing672−reserved0=2181.92. Read-only backend independently
matches in operator/controls-c-month-budget-after.json. These are local fixed-platform evidence, not live Meta results.
