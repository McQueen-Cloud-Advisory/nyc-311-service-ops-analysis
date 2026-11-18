# Power BI connection and verification

## What is implemented

The project at [powerbi/NYC311.pbip](../powerbi/NYC311.pbip) contains the two required
pages and a star schema with one-direction dimension filters. Agency, Problem,
and Borough filter both facts. Date actively filters case creation dates; closure
and p90 measures activate the closure-date relationship explicitly with
`USERELATIONSHIP`. Backlog is independent of the activity-date period.

The case table is one row per request for the selected release observation.
The backlog table imports only that release's `is_release_snapshot=true` rows.
Earlier observations remain in the warehouse, but investigating earlier request
details requires loading that earlier release ID. This keeps historical aggregates
from being paired with today's request state.

Native Power BI visuals only; no custom visual packages, embedded credentials,
external images, Publish to web, or Power BI Service license is required for the
Desktop reviewer path.

## Executive briefing and current verification

The current two-page design leads with an investigation priority and connects it
to a request worklist. The default recommendation is **DSNY / Dirty Condition /
QUEENS**: 92 of the cohort's 379 requests open at least seven days (24.3%).
The investigation shows 181 open requests, 92 aged seven days or more, 38 aged
30 days or more, and a 70.5-day oldest open request. These are observations from
the fixed release below, not a claim about today's citywide backlog.

The redesigned CSV Import model passed fresh Desktop checks:

| Check | Result | Actual evidence |
| --- | --- | --- |
| Base metrics against saved BigQuery SQL results | 41 / 41 | [SQL/DAX comparison](../artifacts/report/dsny_20261118/executive_v2/qa/final_csv/sql_dax_comparison.json) |
| Priority, complete-week trends, aging, empty states, and worklist behavior against an independent CSV reference | 105 / 105 | [Briefing comparison](../artifacts/report/dsny_20261118/executive_v2/qa/final_csv/briefing_comparison.json) |
| Release timestamps and ten case samples, at whole-second precision | 33 / 33 | [UTC timestamp comparison](../artifacts/report/dsny_20261118/executive_v2/qa/final_csv/timestamps/timestamp_comparison.json) |

Both redesigned pages passed Desktop inspection and independent rendering of
the exported two-page PDF. The final cached CSV PBIX was closed and reopened from
disk without refresh: the overall briefing and retained Queens investigation
both rendered correctly. See the
[preview verification](../artifacts/report/dsny_20261118/executive_v2/preview-verification.json)
and [file hashes](../artifacts/report/dsny_20261118/executive_v2/artifact_files.json).
The redesigned native BigQuery working copy is prepared but has not been
refreshed and reverified. The native connector results below apply to the
original design and remain preserved as historical evidence.

## Verified data release

The real release `dsny_20261118` covers DSNY Dirty Condition and Illegal Dumping
requests created in `[2026-09-07, 2026-11-16)` NYC local dates. Its observation ended
at **2026-11-18 11:31:28 UTC**. The recorded
[BigQuery release result](../data/demo_exports/dsny_20261118/verification.json)
contains 23,101 cases, 22,369 recorded closures, 728 observed open requests, and
379 open requests aged at least 168 hours. The demo-target numerator/denominator
is 14,461 / 22,907 (63.13%); p90 is 131.504388889 hours over 22,369 eligible closures.

These results now reconcile to actual BigQuery SQL through the refreshed CSV
Import model in Power BI Desktop: **41 comparisons passed** across the overall,
filtered, date-role, empty, and release-integrity checks. See the
[SQL/DAX comparison](../artifacts/releases/dsny_20261118/sql_dax_comparison.json)
and [executed DAX outputs](../artifacts/releases/dsny_20261118/powerbi).
This proves DAX calculation against the reviewer export; it does not by itself
verify the native BigQuery connector. A separate authenticated native refresh
also passed [41 SQL/DAX checks](../artifacts/releases/dsny_20261118/sql_dax_bigquery_comparison.json)
and [33 UTC timestamp checks](../artifacts/releases/dsny_20261118/powerbi_bigquery/timestamp_comparison.json)
after the transport correction described below. The
[active-model parameter evidence](../artifacts/releases/dsny_20261118/powerbi_bigquery/connection_verification.json)
confirms BigQuery mode and the intended project, dataset, and release.
The complete CSV contract is separately checked in
[csv_validation.json](../powerbi/validation/csv_validation.json). That check proves
types, UTC offsets, keys, counts, and relationships; it does not execute M or
Power BI. The working PBIP is prepared under `powerbi/.local/` for Desktop refresh.

## Prepare and open the reviewer report

For immediate review, [open the executive briefing PDF](../artifacts/report/dsny_20261118/executive_v2/NYC311_dsny_20261118_executive.pdf).
Download the [cached CSV executive PBIX](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/download/dsny_20261118-executive-v2/NYC311_dsny_20261118_executive.pbix)
from the [executive release](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/tag/dsny_20261118-executive-v2).
This exact file passed reopening without refresh and needs no GCP connection to
view. PBIX binaries remain excluded from Git history and are distributed as
release assets. A local copy is retained in the same `executive_v2` folder.

The existing [release downloads](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/tag/dsny_20261118)
still contain the original PDF and native BigQuery PBIX. The native file was saved
after verified refresh and model checks; its cached reopen was not separately
tested. The original CSV reviewer PBIX was saved again after its first reopen
check and remains held locally pending revalidation. These historical files are
separate from the verified executive CSV PBIX. The GitHub release downloads are
publicly available. For a reproducible CSV refresh, prepare the portable source
project using the steps below.

1. Use the included CSV exports under `data/demo_exports/dsny_20261118/`.
   To regenerate them, follow the [bounded local runbook](runbook.md).
   Exports must follow [export-contract.json](../powerbi/export-contract.json).
2. Run from the repository root:

   ```powershell
   .\powerbi\Prepare-LocalReport.ps1 -ExportRoot .\data\demo_exports -ReleaseId dsny_20261118
   ```

3. Open the returned `powerbi/.local/NYC311.pbip` in Power BI Desktop. If Desktop
   requests enabling PBIP/TMDL/PBIR support, use its supported settings and reopen.
4. Refresh. On first use, approve the local file source within Desktop and confirm
   the release ID, source kind, complete-capture count, and as-of timestamp.
5. Inspect both pages. Save a cached PBIX using Desktop's **File > Save as** and
   export a PDF/screenshots only after all visuals have refreshed successfully.
   Put verified exports in the release evidence folder and record their filenames.
6. Keep any PBIX under an ignored local folder until it has been checked for the
   intended public fields and published as a deliberate release artifact.

The source files are editable; they are not a cached report. Opening an unrefreshed
PBIP does not prove that the measures or visuals work. A cached PBIX must be saved
by Desktop, not manufactured or merely renamed from the project source.

### Private file-source refresh

Keep the data privacy firewall enabled and classify the local release folder as
Private. The import function uses a single `Folder.Contents` origin per release
and selects both the metadata and data binaries from that folder. It does not
combine separate `File.Contents` sources or reference another query's metadata
while opening a data source. The BigQuery branch similarly obtains both tables
through one connector/dataset inside the same invocation. Each model partition
calls that function directly; there is no shared `ReleaseContract` data query.

An initial Desktop refresh exposed an incompatible-private-source error in the
earlier two-file/cross-query arrangement. After this architecture change, Desktop
successfully loaded the real 23,101-row release with Private selected and
**Ignore Privacy Levels** unchecked. Measure execution and visual checks are
separate from this refresh result. Do not weaken privacy settings to make a
failed refresh pass. See Microsoft's
[firewall explanation](https://learn.microsoft.com/en-us/power-query/data-privacy-firewall).

To prepare a new working copy while an earlier copy is still open, use a distinct
directory without changing the live files:

```powershell
.\powerbi\Prepare-LocalReport.ps1 -ExportRoot .\data\demo_exports -ReleaseId dsny_20261118 -WorkingCopyName privacy_fixed
```

## BigQuery Import and security

Prepare a separate working copy using `-Mode BigQuery`, `-SourceProject`,
`-BillingProject`, and `-Dataset nyc311_reporting`. The export root parameter is
unused in BigQuery mode but remains a required local preparation argument.

In Power Query, the shared `fnReadReporting` function navigates the native
`GoogleBigQuery.Database` connector in Import mode. It uses explicit billing
project, connector `Implementation="2.0"`, and `UseStorageApi=false`. Read-only
`Value.NativeQuery` projections select only contract columns from allowlisted
immutable tables. Project, dataset, release, and column identifiers are validated.
The query formats TIMESTAMP fields as explicit UTC ISO text inside BigQuery
before transport; `Table.StopFolding` keeps the subsequent UTC parsing local.
Power Query then parses that text to UTC datetime. DATE fields
retain their native type. This compatibility step avoids the incorrect native
timestamp decoding observed in the installed ADBC path; it never guesses a
numeric offset or rescales a corrupted timestamp. Native-query consent, when
requested, applies to these inspectable SELECT projections. Authenticate
interactively using the operator's Google account for the supported one-account
setup, or a distinct report-reader Google account when configured. Do not place
tokens, passwords, or service-account key JSON in M, TMDL, Git, or the report.
The separate reporter role can read reporting only and submit query jobs; see
[security design](security.md). The operator's Desktop OAuth session retains its
broader owner/admin permissions. Its successful refresh proves functionality,
not read-only effective access. Keyless reporter-service-account probes verify
the scoped role design separately without requiring a second human login.

The connector's behavior and permissions must be checked in the installed Desktop
version. If Storage API is deliberately enabled later, update IAM and API enablement
explicitly. A distinct human reporter, if added, must also be checked for inherited
broader grants before its Desktop session can establish least privilege.

### One consistent release

Every imported table uses the same `pSourceProject`, `pDataset`, and sanitized
`pReleaseId`. The physical table name is `<model>__r_<release_id>`. The release
metadata table must contain exactly one row with equal source/expected counts;
every returned row must match the requested release. Case snapshots must match
metadata. The observation cannot precede cohort start and must equal extraction
end, with start no later than end. Cases and selected backlog must also match
the metadata observation time. An unknown/mixed release or invalid capture
interval fails the refresh.

There is no mutable "latest" lookup in the refresh. The operator copies a completed
release ID from the publication manifest, pins it once, and refreshes serially
while promotion is locked out according to the runbook. Existing immutable
releases remain readable. Keep the previous PBIX intact until the candidate report
passes reconciliation, then save the new cached PBIX under its release ID.

## Read the report

**Weekly operations** names the segment with the most requests aged at least
168 hours within the selected scope. Ties use open count, then agency, problem,
and borough. The evidence line states its share of that scope's aged backlog.
The headline ignores activity dates, as all snapshot backlog measures do.
When no aged segment exists, the priority is absent and its display is an em dash.

The trend includes only Monday-based weeks fully inside both the creation cohort
and selected activity dates. The default view has ten complete weeks; it omits
the partial final week rather than presenting it as a collapse in demand.
Individual cards show intake, recorded closures, fixed observed backlog, and p90
with its eligible count. The segment table is ranked by requests aged at least
168 hours. Right-click a row and select **Drill through > Backlog investigation**.
Agency/problem/borough filters travel to that page. A selected row also enables
the native investigation button; in Desktop edit mode, its tooltip specifies
Ctrl+click. The recorded navigation check used the context-menu drill-through.

**Backlog investigation** gives a next check, open / 7-day / 30-day counts, oldest
open age, age buckets, target numerator and denominator, excluded-case diagnostics,
and an oldest-first request worklist. The worklist initially includes open or
mature target-eligible requests from the same capture. Clicking an age bar narrows
it to open requests in that bucket; clicking again clears the selection. Snapshot
cards retain their segment totals. The visible segment heading reflects
drill-through filters, even when a slicer caption still says All. The activity
period filters details and target eligibility by creation date; it does not
change the backlog observation. Both pages state that restriction.

Demo-target rates use sums of numerator and denominator. P90 uses
`PERCENTILEX.INC` over eligible request rows. Empty count slices return zero;
empty eligible rates and p90 return BLANK. All thresholds are labeled demo targets.
Agency-recorded closure is not an assertion about fulfillment or staffing demand.

## Verification and evidence

Run source integrity checks with:

```powershell
.\.venv\Scripts\python.exe powerbi\validate_source.py
.\.venv\Scripts\python.exe powerbi\validate_source.py --schemas
.\.venv\Scripts\python.exe powerbi\validate_exports.py --release-id dsny_20261118
```

The second command downloads only Microsoft's public schemas, caches them in an
ignored directory, and validates all PBIP/PBIR/semantic-definition JSON. It needs
the `jsonschema` package. The observed source-validation output is recorded in
[source_validation.json](../powerbi/validation/source_validation.json).

[Validate-Tmdl.ps1](../powerbi/Validate-Tmdl.ps1) additionally deserializes the TMDL
with Microsoft's `Microsoft.AnalysisServices` AMO library. The current recorded
check uses version 19.120.1 from the official NuGet package, extracted into the
ignored `powerbi/.tools/amo-19.120.1` directory. Pass another installed AMO net472
library folder via `-AmoLibrary` when reproducing. Library binaries are not committed.
This check does not execute DAX or Power Query.

`node powerbi/validate_m.cjs` performs a separate syntax pass using Microsoft's
`@microsoft/powerquery-parser@5.0.0` and Node 22 or later. Its optional, ignored
tool dependency can be installed with `npm install --prefix powerbi/.tools/pq-parser
--ignore-scripts --no-audit --no-fund @microsoft/powerquery-parser@5.0.0`.
The actual result is in [m_validation.json](../powerbi/validation/m_validation.json).
It checks M syntax only, not library resolution or execution of the refresh.

After Desktop refresh, run [reconciliation.dax](../powerbi/reconciliation.dax) in
DAX Query View and save the actual result tables. Compare each output with the
matching warehouse SQL result: overall view, DSNY / Dirty Condition / BROOKLYN,
the 2026-11-09 to 2026-11-16 half-open date slice, and an empty borough slice.
Counts, target numerator, and denominator must match exactly. P90 tolerance is
`1e-6` hours before display rounding. Confirm the single snapshot and open-case
count agree with the aggregate backlog.

Record release ID, input/target hashes, Desktop version, connector mode, query
outputs, screenshots of both pages, and pass/fail results together. Mark each
check unverified until actually executed. Source checks alone never establish
Desktop success or BigQuery correctness.

### Read-only Desktop query evidence

The recorded DAX results were executed through Desktop's local Analysis Services
engine with the installed Microsoft ADOMD client. The
[export script](../powerbi/Export-DaxEvidence.ps1) accepts an explicit
`localhost:PORT` and optional catalog, verifies the loaded release, and runs only
the five reviewed `EVALUATE` queries. It does not refresh, process, or modify the
model. Use the current engine endpoint while the intended report is open; ports
are session-specific and are not project configuration.

After exporting the actual results, reproduce their comparison with:

```powershell
.\.venv\Scripts\python.exe powerbi/compare_sql_dax.py --sql artifacts/releases/dsny_20261118/sql_reconciliation.json --dax-directory artifacts/releases/dsny_20261118/powerbi --output artifacts/releases/dsny_20261118/sql_dax_comparison.json --import-mode CSV
```

For the executive briefing, the same read-only exporter accepts
`-QueryFile powerbi/reconciliation-briefing.dax`. Its five scenarios cover the
overall scope, Brooklyn and Queens Dirty Condition, an empty slice, and a
creation-date slice. Each includes age-filtered worklist checks. Rebuild the
independent reference and compare the
saved, executed results with:

```powershell
.\.venv\Scripts\python.exe powerbi/validate_briefing_reference.py --output powerbi/.local/briefing-reference.json
.\.venv\Scripts\python.exe powerbi/compare_briefing_dax.py --reference powerbi/.local/briefing-reference.json --dax-directory artifacts/report/dsny_20261118/executive_v2/qa/final_csv/briefing --output powerbi/.local/briefing-comparison.json
```

The first command calculates expected values from saved release exports; it does
not execute DAX. The second compares those expectations with the actual Desktop
query outputs. Use a new evidence directory when rerunning Desktop queries so
earlier observations remain available.

Native BigQuery Import requires a separate working copy, refresh, and evidence
directory. Use `--import-mode BigQuery` only after that actual connection and
refresh succeeds; do not relabel the CSV checks as connector verification.

The first authenticated native refresh passed the 41 KPI comparisons but exposed
incorrect TIMESTAMP values, including a release as-of year of 0395. Its
[timestamp comparison](../artifacts/releases/dsny_20261118/powerbi_bigquery_initial/timestamp_comparison.json)
is a failed acceptance check, despite matching precomputed counts. The corrected
UTC-text projection subsequently passed a fresh native refresh, **41/41 KPI
comparisons**, and **33/33 timestamp comparisons**. Repeat both checks when the
connector or transport changes, using
[Export-TimestampEvidence.ps1](../powerbi/Export-TimestampEvidence.ps1). That
read-only script compares release observation/extraction times and ten case
samples against the matching exported release, at whole-second precision.
Whole-second timestamp checks detect transport/timezone errors; they do not
assert preservation of subsecond precision in the semantic model.

With the intended native report open and its current local engine endpoint
identified, reproduce the checks using the installed ADOMD library path:

```powershell
.\powerbi\Export-DaxEvidence.ps1 -Server localhost:CURRENT_PORT -AdomdLibrary 'PATH_TO_Microsoft.PowerBI.AdomdClient.dll' -ReleaseId dsny_20261118 -OutputDirectory artifacts/releases/dsny_20261118/powerbi_bigquery
.\powerbi\Export-TimestampEvidence.ps1 -Server localhost:CURRENT_PORT -AdomdLibrary 'PATH_TO_Microsoft.PowerBI.AdomdClient.dll' -ReferenceDirectory data/demo_exports/dsny_20261118 -ImportMode BigQuery -OutputDirectory artifacts/releases/dsny_20261118/powerbi_bigquery
.\.venv\Scripts\python.exe powerbi/compare_sql_dax.py --sql artifacts/releases/dsny_20261118/sql_reconciliation.json --dax-directory artifacts/releases/dsny_20261118/powerbi_bigquery --output artifacts/releases/dsny_20261118/sql_dax_bigquery_comparison.json --import-mode BigQuery
```

Replace `CURRENT_PORT` and the library path with the actual current session
values. Retain earlier evidence in a separate directory when testing a new
connector version. These scripts only query the loaded model; they do not refresh
or alter it.

The Desktop model also exposed two naming issues during execution: the measure
table is now named `Metrics`, and DAX table references are quoted, including
`'Cases'`. The refreshed model and the 41 executed comparisons validate those
corrections in the original design. Both original CSV pages passed Desktop
inspection, and Desktop saved a cached PBIX and exported a PDF after refresh.
That original saved PBIX reopened without refresh, with both pages rendering
the correct values and context. A later save changed that file; the current
original-design CSV PBIX remains held locally pending revalidation.
Native BigQuery acceptance passed separately and is recorded in the
[report artifact record](../artifacts/report/dsny_20261118/README.md). Both native
pages and Queens drill-through passed Desktop inspection, then Desktop saved a
separate native PBIX. Reopening that native PBIX has not been tested.

## Primary references

- [Microsoft PBIP report structure](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report)
- [Microsoft TMDL specification](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview)
- [Microsoft BigQuery connector](https://learn.microsoft.com/en-us/power-query/connectors/google-bigquery)
- [Microsoft native-query folding](https://learn.microsoft.com/en-us/power-query/native-query-folding)
- [Microsoft Table.StopFolding](https://learn.microsoft.com/en-us/powerquery-m/table-stopfolding)
- [Google FORMAT_TIMESTAMP](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/timestamp_functions#format_timestamp)
- [Microsoft published report schema](https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json)
