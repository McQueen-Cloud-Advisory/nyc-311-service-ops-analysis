# Executive briefing: decision to investigation

This is the redesigned reviewer report for release `dsny_20261118`, built around
Senior BIE ownership: a clear investigation priority, explainable measures, and a
usable analyst handoff.

**[Open the two-page briefing](NYC311_dsny_20261118_executive.pdf)** ·
[Download the interactive CSV PBIX](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/download/dsny_20261118-executive-v2/NYC311_dsny_20261118_executive.pbix) ·
[Overview preview](NYC311_dsny_20261118_executive_page-1.png) ·
[Investigation preview](NYC311_dsny_20261118_executive_page-2.png)

The first page shows the full cohort and recommends DSNY / Dirty Condition /
QUEENS: 92 of 379 observed open requests aged at least seven days, or 24.3%.
The second retains that segment's investigation context: 181 open, 92 aged at
least seven days, 38 aged at least 30 days, and an oldest open request of 70.5
days. It connects the aging distribution to an oldest-first request worklist.

The trend shows ten complete cohort weeks; partial weeks are omitted. Creation,
closure, and observation date roles remain explicit. A selected aging bar narrows
the worklist while the snapshot cards retain their segment totals. Right-click a
ranked segment and choose **Drill through > Backlog investigation**. Desktop also
provides an investigation button after selecting a segment; its enabled state and
destination tooltip were inspected, while the executed navigation check used the
context menu.

The PBIX was saved again after the initial export. The exact release candidate
was frozen, reopened without refresh, and passed all 179 checks again.
[Candidate and download verification](release-preflight.json) identifies the
published bytes; the PDF remains the unchanged, visually verified export.

## Verified delivery

- Desktop refreshed the CSV Import model and saved
  `NYC311_dsny_20261118_executive.pbix`. The saved file was closed and reopened
  without refreshing. Both pages rendered with the expected metrics and retained
  Queens investigation context.
- [41 base SQL/DAX comparisons](qa/final_csv/sql_dax_comparison.json),
  [105 briefing comparisons](qa/final_csv/briefing_comparison.json), and
  [33 UTC timestamp checks](qa/final_csv/timestamps/timestamp_comparison.json)
  passed against executed Desktop results. The briefing reference is independently
  calculated from the saved warehouse exports. This is CSV-mode evidence.
- [All 13 semantic-model source files match](qa/final_csv/source_equivalence.json)
  between the DAX-tested copy and final delivery copy. Subsequent changes addressed
  visual geometry only.
- Desktop exported the PDF. Both complete pages were rendered with Poppler and
  visually inspected. PNGs are direct renders, with no redrawing or retouching.
  [Visual verification](preview-verification.json) and
  [artifact hashes](artifact_files.json) identify the exact files.

The PDF contains visible table rows only. The cached PBIX contains the interactive
tables and needs no GCP connection to view. To refresh elsewhere, prepare the
editable PBIP with a local CSV export path using the [setup guide](../../../../docs/powerbi.md).

The [executive release](https://github.com/McQueen-Cloud-Advisory/nyc-311-service-ops-analysis/releases/tag/dsny_20261118-executive-v2)
contains the verified PDF and CSV PBIX; downloads require repository access.
PBIX files remain excluded from Git history. The original native BigQuery release
and its verification are preserved in the [parent artifact record](../README.md).
The redesigned native source is prepared but has not been refreshed or reverified
in Desktop.

The data remains a fixed creation cohort observed November 18, 2026, not citywide
workload or a current live queue. Targets are illustrative. No NYC operational
improvement, staffing requirement, or fulfillment outcome is claimed. Earlier
iteration outputs under `qa/` are retained; `qa/final_csv/` is the current model
verification set for the source model. The later saved PBIX is independently
verified under `qa/release_candidate/`.
