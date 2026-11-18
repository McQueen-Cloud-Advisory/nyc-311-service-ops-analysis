# Claim-to-evidence map

This is the repository review outline. A source file demonstrates implementation;
a recorded execution demonstrates that a check ran. Keep those claims separate.
Link actual results under the same release ID from the README and portfolio page
once those artifacts exist.

| Reviewer question | Inspectable source | Execution evidence required |
| --- | --- | --- |
| Which segment should be reviewed first? | [Decision memo](decision-memo.md), [report source](../powerbi/NYC311.pbip), finding query in dbt analyses | Real-release numbers, scope/as-of, query output, and verified report image/export. |
| What do the KPIs mean? | [Metric contracts](metrics.md), [dbt marts](../dbt/models/marts), [DAX measures](../powerbi/NYC311.SemanticModel/definition/tables/Metrics.tmdl) | Overall, filtered, date-role, and empty-slice SQL/DAX outputs with exact count matches and documented p90 tolerance. |
| Does replay preserve history? | [Release runner](../nyc311/release.py), [runbook](runbook.md) | Labeled synthetic before/after, unchanged original snapshot, same-key update, repeated-input hashes/counts/metrics. |
| Does a bad refresh reach readers? | Candidate tests, immutable release tables, publication manifest, Power BI release pin | Failed validation/publication audit and unchanged last-good publication; report still reads that release. |
| Is the source bounded and privacy-conscious? | [Source client](../nyc311/source.py), [scope configuration](../config/demo.json), [source profile](../artifacts/source/profile.json) | Complete capture manifest, allowlisted columns, count/key checks, extraction interval, target hash. |
| Are credentials and access controlled? | [Security model](security.md), [infra plan/checks](../infra), [Power Query function](../powerbi/queries/ReadReporting.m) | Private-policy inspection, zero user-managed service-account keys, positive reporting SELECT and denied raw SELECT/reporting-write probes. |
| Is Power BI's actual login read-only? | [One-account limitation](security.md), [refresh instructions](powerbi.md) | A distinct least-privileged Desktop identity must be tested separately. Owner OAuth refresh is not this evidence. |
| Is the cloud cost claim measured? | [BigQuery benchmark command](runbook.md), warehouse benchmark SQL | Same result set, cache disabled, actual bytes and job IDs; no inferred speedup or cost saving. |
| Can another engineer run it? | [Runbook](runbook.md), local CLI, fixtures and CSV reviewer mode | Successful bounded local validation plus explicit cloud/Desktop status and reproduction steps. |
| Can Scott explain his contribution? | Contribution note and [walkthrough](walkthrough.md) | Scott-reviewed account of the decisions, implementation, and checks he personally substantiates. |

For release `dsny_20261118`, the
[executed SQL/DAX comparison](../artifacts/releases/dsny_20261118/sql_dax_comparison.json)
passed **41 of 41 checks** against the refreshed Power BI Desktop CSV Import
model. The [DAX outputs](../artifacts/releases/dsny_20261118/powerbi) cover overall,
filtered, date-role, empty, and release-integrity results. Desktop also completed
the CSV refresh with Private sources and the privacy firewall enabled, and
drill-through carried the selected segment into request investigation.

Both final CSV pages passed Desktop inspection, and the cached PBIX and PDF were
saved after refresh. Both cached PBIX pages subsequently reopened without refresh,
and independent PDF rendering passed. Native BigQuery Import separately passed
[41 SQL/DAX checks](../artifacts/releases/dsny_20261118/sql_dax_bigquery_comparison.json)
and [33 timestamp checks](../artifacts/releases/dsny_20261118/powerbi_bigquery/timestamp_comparison.json)
after correcting timestamp transport. Its
[active model parameters](../artifacts/releases/dsny_20261118/powerbi_bigquery/connection_verification.json)
confirm the intended source and release. The native Desktop login is the operator's
OAuth account; least privilege is established by separate reporter-role probes.
Filenames, file hashes, and export status belong in the
[report artifact record](../artifacts/report/dsny_20261118/README.md).

Power BI source-only checks live under
[powerbi/validation](../powerbi/validation). They validate Microsoft JSON schemas
and TMDL parsing; they do not certify report rendering, refresh, DAX, or BigQuery.
Release metrics identify their engine in `verification.json`; the current real
release result was executed in BigQuery. Cloud and Desktop evidence identify
their own execution engines and release IDs.
