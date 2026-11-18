# Three-minute walkthrough

## 0:00–0:35 — The decision and its limits

Open the [decision memo](decision-memo.md). State the segment selected for the next
backlog review and quote its verified numbers directly from the memo's linked
release evidence. Explain that the stakeholder is hypothetical and the source
records are real NYC 311 service requests. Show the exact creation cohort and
observation time. Agency-recorded closure is not proof of fulfillment or a staffing
estimate.

The real release has executed BigQuery results and a **41/41 SQL/DAX match** in
Desktop's CSV Import reviewer model. Native BigQuery Import independently passed
the same 41 checks plus 33 UTC timestamp checks. The public PDF and cached
reviewer PBIX use CSV mode; the native connection has separate evidence.

## 0:35–1:15 — The report explains where to look

Open the verified cached PBIX/export, or the editable
[Power BI project](../powerbi/NYC311.pbip) after its documented refresh. On **Weekly
operations**, point to the release ID, capture coverage, and as-of time. Explain
that intake uses creation dates, closures/p90 use recorded closure dates, and
backlog stays fixed at the observation.

Select the memo's agency/problem/borough segment. Drill through to **Backlog
investigation**. Show aging, the demo-target numerator and denominator, exclusions,
and eligible request details. Explain why late-closed and overdue-open mature
cases count as misses, while immature cases do not enter the denominator.

## 1:15–1:55 — Follow a KPI into its implementation

Open [metric contracts](metrics.md), the corresponding
[dbt reporting model](../dbt/models/marts/fct_cases.sql), and
[explicit DAX measures](../powerbi/NYC311.SemanticModel/definition/tables/Metrics.tmdl).
Use the recorded overall and filtered SQL/DAX results to show that counts,
numerator, denominator, and p90 agree. P90 is calculated over eligible case rows;
segment percentiles and percentages are not averaged.
Open the [41-check comparison](../artifacts/releases/dsny_20261118/sql_dax_comparison.json)
and point to its explicit CSV Import execution scope.
Then show the [independent native result](../artifacts/releases/dsny_20261118/sql_dax_bigquery_comparison.json)
and [timestamp verification](../artifacts/releases/dsny_20261118/powerbi_bigquery/timestamp_comparison.json).
Matching counts alone would have missed the initial connector timestamp defect.

Run the bounded local check, or show its saved actual output if demonstration
time is short:

```powershell
.\.venv\Scripts\python.exe -m nyc311 validate
```

## 1:55–2:30 — Show recovery and security evidence

Open the [24 passed live BigQuery replay/recovery checks](../artifacts/replay/bigquery-replay.json),
which retain 33 executed SQL queries and their results. Explain that these use
labeled synthetic inputs. Show an old open request becoming closed under the same
request key, the unchanged original snapshot, identical replay, and a failed
candidate retaining the last-good publication. The real release was restored
after the exercise. Link the [runbook](runbook.md) for reproduction commands.

Open the [security model](security.md). Explain private storage, the allowlisted
public fields, keyless pipeline impersonation, and the isolated reporting role.
Show the [26 passed live reporting-role checks](../artifacts/security/gcp-reporter.json).
Desktop uses the owner's OAuth account: its successful refresh establishes
functionality. The separate keyless reporter probes establish scoped access,
including allowed reporting reads and denied raw reads/reporting writes.

## 2:30–3:00 — Cost, portability, and contribution

Show the [executed same-output benchmark](../artifacts/releases/dsny_20261118/benchmark.json):
processed bytes fell from 1,304,253 to 166,973 (87.2%), but both queries billed
10 MiB. Claim no billed-byte savings or repeatable speed improvement. The report
imports the full release, so the selective-query reduction does not describe its
refresh cost. Explain the retained low-cost project and manual refresh tradeoff.

Finish with one concrete adaptation: replace the request key with a shipment
exception ID, map closure to verified shipment events, and agree on effective-dated
targets with the operations lead. Review Scott's contribution note before public
use so he can substantiate the metric, recovery case, and architecture tradeoff.
