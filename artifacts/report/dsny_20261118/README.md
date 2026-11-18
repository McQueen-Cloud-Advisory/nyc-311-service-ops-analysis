# Desktop report artifact record

Release: `dsny_20261118`. Snapshot: `dsny_20261118_a`.
Source observation ended: `2026-11-18T11:31:28.284936+00:00`.
Power BI Desktop: `2.159.1231.0`.

The editable source is [NYC311.pbip](../../../powerbi/NYC311.pbip).
Both pages use a 1440 x 960 canvas with Fit to page. The report page order is:

1. Weekly operations
2. Backlog investigation

## Executive briefing redesign

The editable source now contains the executive briefing redesign: an explicit
investigation priority, a complete-cohort-week trend, and an aging-driven request
worklist. The redesigned CSV Desktop model passed
[41/41 base SQL/DAX comparisons](executive_v2/qa/final_csv/sql_dax_comparison.json),
[105/105 briefing comparisons](executive_v2/qa/final_csv/briefing_comparison.json),
and [33/33 UTC timestamp checks](executive_v2/qa/final_csv/timestamps/timestamp_comparison.json).

The final [two-page executive PDF](executive_v2/NYC311_dsny_20261118_executive.pdf)
was exported by Desktop and independently rendered for full-page visual review.
Both pages passed, including complete filter controls, the segment ranking, and
the Queens request worklist. Previews: [page 1](executive_v2/NYC311_dsny_20261118_executive_page-1.png)
and [page 2](executive_v2/NYC311_dsny_20261118_executive_page-2.png).

The final local cached CSV file, `executive_v2/NYC311_dsny_20261118_executive.pbix`,
was closed and reopened from disk without refresh. Both pages retained the
correct values: 23,101 intake / 22,369 closures / 728 open / 131.5-hour p90 in the
overall briefing; 181 open / 92 aged seven days / 38 aged 30 days / 70.5-day oldest
request in Queens Dirty Condition. The selected target result remained
2,087 / 3,240, with 33 immature requests outside its denominator.

| Redesigned artifact | Size | Verification |
| --- | --- | --- |
| Executive PDF | 213,034 bytes | Both pages rendered and visually inspected |
| [Cached CSV executive PBIX](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/download/dsny_20261118-executive-v2/NYC311_dsny_20261118_executive.pbix) | 1,390,870 bytes | Current saved file reopened successfully without refresh |

See [file hashes](executive_v2/artifact_files.json) and
[preview/reopen evidence](executive_v2/preview-verification.json). The native
BigQuery working copy has been generated but not refreshed and reverified for
this design. The [executive release](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/tag/dsny_20261118-executive-v2)
distributes the verified CSV PBIX and PDF. Repository access is required. The
original published artifacts and their verification history remain below;
those downloads have not been replaced.

## Original published design evidence

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
| Cached CSV reviewer report | `NYC311_dsny_20261118_reviewer.pbix` (local only) | Current file: 1,342,309 bytes, saved again at 12:47:33 UTC; archive integrity passes, but current-file Desktop revalidation was interrupted; excluded from release assets |
| Two-page reviewer PDF | [NYC311_dsny_20261118_reviewer.pdf](NYC311_dsny_20261118_reviewer.pdf) | Exported by Desktop; 341,136 bytes; both rendered pages independently inspected |
| Native BigQuery cached report | [NYC311_dsny_20261118_bigquery.pbix](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/download/dsny_20261118/NYC311_dsny_20261118_bigquery.pbix) | Saved by Desktop; 1,354,254 bytes; native refresh, 41+33 comparisons, both pages and drill-through passed; cached reopen not tested |

The originally verified CSV PBIX file time was 2026-11-18 12:22:01 UTC; the PDF file time is
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

The PDF and native BigQuery PBIX are distributed as assets of [release `dsny_20261118`](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/tag/dsny_20261118).
PBIX files remain excluded from Git history. The repository and its release assets
are private; downloads require repository access. Their release hashes still match
the verified Desktop exports. Native BigQuery refresh requires access to the
configured GCP project; the PDF needs no GCP credentials.

The original CSV PBIX was 1,342,279 bytes with SHA-256
`2998750f0678c0967fefa9ffbc9a562a3272fdd94bf1179322e1b65b70ab399e`.
The cached-reopen and PDF-source evidence above applies to that original file.
A subsequent save at 2026-11-18 12:47:33 UTC changed the CSV PBIX checksum. Its
archive integrity passes, but the attempted Desktop recheck was interrupted;
the current file is held locally and is not a release download. Current and
historical hashes are recorded in `artifact_files.json`. Use the editable PBIP
and included CSV exports for a reproducible reviewer refresh. Do not store
authentication material beside these artifacts.
