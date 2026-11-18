# Desktop report artifact record

Release: `dsny_20261118`. Snapshot: `dsny_20261118_a`.
Source observation ended: `2026-11-18T11:31:28.284936+00:00`.
Power BI Desktop: `2.159.1231.0`.

The editable source is [NYC311.pbip](../../../powerbi/NYC311.pbip).
Both pages use a 1440 x 960 canvas with Fit to page. The report page order is:

1. Weekly operations
2. Backlog investigation

## Current evidence

- CSV Import refresh completed with Private source classification and the privacy
  firewall enabled. Overall counts and the Queens / Dirty Condition drill-through
  were inspected in Desktop.
- [41 of 41 SQL/DAX comparisons passed](../../releases/dsny_20261118/sql_dax_comparison.json)
  against the actual BigQuery release results. Those results establish CSV Import
  model calculation, not native BigQuery connector behavior.
- Both final CSV report pages refreshed and passed Desktop visual inspection,
  including the visible selected-segment context. Desktop saved the cached PBIX
  and exported the PDF after that refresh. The saved PBIX was then reopened from
  disk without refreshing: both pages rendered with the correct release as-of,
  overall KPIs, and retained Queens investigation context. Independent PDF
  render inspection passed for both pages; see
  [preview-verification.json](preview-verification.json).
- Native BigQuery Import independently refreshed successfully and passed
  [41/41 SQL/DAX checks](../../releases/dsny_20261118/sql_dax_bigquery_comparison.json)
  and [33/33 UTC timestamp checks](../../releases/dsny_20261118/powerbi_bigquery/timestamp_comparison.json).
  The [active source parameters](../../releases/dsny_20261118/powerbi_bigquery/connection_verification.json)
  confirm the intended BigQuery project, dataset, and release. The operator's
  OAuth session proves functionality, not least-privileged Desktop access.
  Both native pages and Queens drill-through also passed Desktop inspection,
  and Desktop saved the native cached PBIX. Reopening that native PBIX has not
  been tested; the cached reopen result above applies to the CSV reviewer PBIX.

## Files

| Artifact | Filename | Status |
| --- | --- | --- |
| Cached CSV reviewer report | [NYC311_dsny_20261118_reviewer.pbix](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/download/dsny_20261118/NYC311_dsny_20261118_reviewer.pbix) | Saved by Desktop after successful refresh; 1,342,279 bytes; both cached pages reopened successfully without refresh |
| Two-page reviewer PDF | [NYC311_dsny_20261118_reviewer.pdf](NYC311_dsny_20261118_reviewer.pdf) | Exported by Desktop; 341,136 bytes; both rendered pages independently inspected |
| Native BigQuery cached report | [NYC311_dsny_20261118_bigquery.pbix](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/download/dsny_20261118/NYC311_dsny_20261118_bigquery.pbix) | Saved by Desktop; 1,354,254 bytes; native refresh, 41+33 comparisons, both pages and drill-through passed; cached reopen not tested |

The saved PBIX file time is 2026-11-18 12:22:01 UTC; the PDF file time is
2026-11-18 12:22:36 UTC. These are filesystem modification times, not evidence of
a fresh source observation. The cached reopen was checked separately after save.
File hashes are recorded in
[artifact_files.json](artifact_files.json).
The native PBIX file time is 2026-11-18 12:37:14 UTC.

The PDF shows the overall Weekly operations page followed by the Backlog
investigation page filtered to DSNY / Dirty Condition / QUEENS. Its 181 open
requests, 92 aged at least seven days, and 2,087 / 3,240 target result match the
selected segment. The PNG previews are [page 1](NYC311_dsny_20261118_page-1.png)
and [page 2](NYC311_dsny_20261118_page-2.png). Native table viewports retain normal
scroll controls and partial final visible rows; the exported page boundaries do
not clip whole visuals.

The PBIX files are distributed as assets of [release `dsny_20261118`](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/tag/dsny_20261118)
and remain excluded from Git history. The repository and its release assets are
private; downloads require repository access. File hashes above identify the
verified Desktop exports. CSV refresh requires configuring the local export path;
native BigQuery refresh requires access to the configured GCP project. Neither is
needed to view the cached reviewer report. Do not store authentication material
beside these artifacts.
