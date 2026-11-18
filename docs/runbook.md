# Run, replay, and recover

Run commands from the repository root. The local runner is a Python reference
implementation with SQLite persistence; it does not stand in for BigQuery, dbt,
or DAX execution. The cloud runner uses the same captured input and release ID.

## Local validation and the checked-in real capture

```powershell
.\.venv\Scripts\python.exe -m nyc311 validate
.\.venv\Scripts\python.exe -m nyc311 run --input data/public/dsny_20261118_a.json.gz --release-id dsny_20261118
```

The first command runs network-free contract, metric, replay/recovery, and security
checks and writes `artifacts/validation/local.json`. Read its outcome and executed
checks; the existence of an output file alone is not a pass. The second validates
the saved real capture, builds reference marts, and publishes CSV reviewer exports
under `data/demo_exports/dsny_20261118/`. Its `verification.json` identifies the
engine and contains the recorded metrics. Operational audits are under
`.local/audits/`; `.local/published.json` names the selected release.

Reissue the same `run` command to replay. It must report `replayed` with the same
metrics and mart hash. Captured observation time, extraction interval, source
scope, target version, and raw row hashes remain fixed. Replay does not age cases
using today's clock or change the active release. Never overwrite a captured file
or reuse a snapshot/release ID for changed input.

## Capture a new observation

The checked-in configuration covers DSNY, Dirty Condition and Illegal Dumping,
with local creation dates in `[2026-09-07, 2026-11-16)`. It deliberately remains a
fixed cohort, so later observations show updates to those requests, not all new
citywide work. Choose a new unique ID and a new output filename for each capture:

```powershell
.\.venv\Scripts\python.exe -m nyc311 profile --config config/demo.json
.\.venv\Scripts\python.exe -m nyc311 capture --config config/demo.json --snapshot-id dsny_next_capture --output .local/captures/dsny_next_capture.json.gz
.\.venv\Scripts\python.exe -m nyc311 run --input .local/captures/dsny_next_capture.json.gz --release-id dsny_next_release
```

Replace the two `next` IDs before each actual capture. IDs must match
`[a-z][a-z0-9_]{0,62}`. Review the profile before changing agency, categories, or
scope. A changed creation window is a different cohort; do not present its backlog
difference as a like-for-like change.

The capture requests the entire bounded cohort in key order, compares counts
before/after, verifies keys and source metadata, and fails incomplete downloads.
The as-of time is extraction end, and the extraction interval is retained. The API
does not provide an atomic point-in-time snapshot, so disclose that limitation.
Historical backlog is supported only by actual saved captures. Synthetic lifecycle
fixtures remain explicitly labeled and separate from the real source scope.

Targets default to `data/targets/demo_targets.csv`. The optional Sheets path is:

```powershell
.\.venv\Scripts\python.exe -m nyc311 capture --config config/demo.json --snapshot-id dsny_sheet_capture --output .local/captures/dsny_sheet_capture.json.gz --sheet-id YOUR_TARGET_SHEET_ID --sheet-range 'Targets!A:E'
```

This requires the read-only Sheets setup described in [cloud setup](cloud-setup.md).
Do not change captured target rows to alter an already published result.

## Cloud publication

Follow [cloud setup](cloud-setup.md), including the private resource plan,
keyless pipeline authentication, and security preflight. Keep infrastructure
configuration in `.local/gcp.json`. Separately copy `config/cloud.example.json`
to `.local/cloud.json` and fill in the same project, region, dataset, bucket, and
pipeline-impersonation details. These are configuration files, not credential
files; credentials remain outside the repository.

```powershell
.\.venv\Scripts\python.exe -m nyc311 run --input data/public/dsny_20261118_a.json.gz --release-id dsny_20261118 --cloud-config .local/cloud.json
.\.venv\Scripts\python.exe -m nyc311 benchmark --cloud-config .local/cloud.json --release-id dsny_20261118
```

The cloud path stages captured inputs, updates current requests by key and payload
hash, builds the candidate in `nyc311_work`, and runs dbt checks before publication.
Published reporting tables have names `<model>__r_<release_id>` in
`nyc311_reporting`; reporting imports pin the same release for every table. The
publication manifest is the final publication step. Keep earlier published
tables available. A failed candidate is not a new reporting release.

The benchmark compares identical outputs with query caching disabled and records
processed bytes. Treat cloud checks as unverified until actual job and dbt outputs
exist. A successful local run is not a measured cloud performance result.

## Power BI refresh and export

Stop pipeline/promotion work before refreshing the report. Read the published
release ID, set it once, then refresh all tables using that fixed ID. Never refresh
some tables with a new ID while others retain an old ID.

```powershell
.\powerbi\Prepare-LocalReport.ps1 -ExportRoot .\data\demo_exports -ReleaseId dsny_20261118
```

Open the returned `.local` PBIP copy. Follow [Power BI verification](powerbi.md)
for native BigQuery mode, DAX Query View, both-page inspection, and saving the
cached PBIX and exports. Preserve the previous verified PBIX until the new one
passes. Source-schema and TMDL parsing checks do not establish Desktop success.

The recorded `dsny_20261118` CSV Import model passed
[all 41 SQL/DAX comparisons](../artifacts/releases/dsny_20261118/sql_dax_comparison.json)
after actual Desktop refresh. File privacy remains Private, with Ignore Privacy
Levels unchecked. The native BigQuery connector separately passed
[41 KPI checks](../artifacts/releases/dsny_20261118/sql_dax_bigquery_comparison.json)
and [33 timestamp checks](../artifacts/releases/dsny_20261118/powerbi_bigquery/timestamp_comparison.json).
Retain those outputs in a separate evidence directory. Its read-only SQL
projection transports UTC timestamps as ISO text to avoid the observed ADBC
decoding defect; downstream parsing stays local. Recheck both KPIs and timestamps
after changing connector versions or transport. Save final
cached PBIX/PDF files under `artifacts/report/dsny_20261118/` and update its
[artifact record](../artifacts/report/dsny_20261118/README.md) after inspection.

## Failure and repair guide

| Symptom | Action | Evidence before retry |
| --- | --- | --- |
| API timeout, changing counts, schema drift, or incomplete capture | Keep the last release. Inspect the sanitized capture audit. Retry with a fresh observation ID/file after the source stabilizes; review schema changes explicitly. | Complete count/key/metadata checks on the new capture. |
| A known request disappears | Block promotion and investigate source corrections, changed categorization, or cohort configuration. Absence is not closure. | Explanation and explicit scope/source decision; no silently manufactured closed row. |
| Unknown new status, target overlap, invalid target schema, or hash mismatch | Correct the live/configuration input or reviewed mapping. Capture again under a new ID. Preserve the rejected input and audit. | Passing contract tests, reviewed mapping, new hashes. |
| dbt test or candidate validation fails | Fix the model/input issue, run relevant local checks, and rebuild under an appropriate new release ID if code or input changed. | dbt test results and metric reconciliation for the candidate. |
| Upload/load/publication fails | Inspect the run audit and published manifest. Retry the same immutable captured input with the same logical IDs where supported. Do not point Power BI at orphan candidate tables/exports. | Last good manifest unchanged, retry result, and original snapshot unchanged. |
| Authentication expires or a permission is denied | Reauthenticate interactively as the intended identity. Check scoped IAM using the security scripts. Do not grant broad project Editor/Owner to the pipeline. | Intended principal and successful scoped checks; no tokens in evidence. |
| Local `operator.lock` remains after a crash | Read its PID/time, confirm that process has stopped and that no report refresh or pipeline run is active, then remove only that stale lock. | Confirmed stopped process and unchanged last good release. |
| Power BI refresh/reconciliation fails | Keep the prior cached PBIX. Verify all parameters, source account, date roles, and source schema. Reconcile before saving a new public artifact. | Matching release ID and SQL/DAX counts, denominators, and p90. |

For a stale lock, inspect it first:

```powershell
Get-Content -LiteralPath .local/operator.lock
```

Check the recorded PID with `Get-Process -Id ACTUAL_PID`. Only after confirming it
is stale, use `Remove-Item -LiteralPath .local/operator.lock`. Do not delete the
state directory, database, captures, or cloud project to clear a lock.

To exercise a validation failure without changing the real published release:

```powershell
.\.venv\Scripts\python.exe -m nyc311 run --input data/public/dsny_20261118_a.json.gz --release-id dsny_validation_failure --simulate-failure validation
```

This intentionally returns a validation error. Compare the publication before and
after and inspect the failed audit. Use the automated validation evidence for the
full synthetic open-to-closed, identical replay, and publication-rollback scenario.
Never label that simulated incident as an actual NYC lifecycle observation.

## Retention and optional cleanup

Keep the dedicated GCP project available for manual demonstrations within the
allowance. Review recorded bytes, billing, audit volume, and alert delivery. No
recurring schedule is required. Budget alerts are early warnings, not hard caps.

Before eventual teardown, retain the real capture, target input/version, manifest,
verified SQL/DAX results, benchmark, security evidence, report exports, memo, and
cached PBIX. Confirm the local reviewer path first. Follow the deliberate cleanup
procedure in [cloud setup](cloud-setup.md); no pipeline command performs teardown.
