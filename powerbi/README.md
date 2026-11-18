# Power BI report source

Open `NYC311.pbip` in Power BI Desktop after preparing local parameters. The project
contains two native Power BI pages, a TMDL semantic model, explicit DAX measures,
and native BigQuery Import plus CSV reviewer modes.

The current executive briefing turns the report into a decision flow: a dynamic
investigation priority, ten complete cohort weeks, and segment drill-through to
aging and an oldest-first request worklist. Selecting an age bucket narrows that
worklist while the fixed-snapshot cards retain the segment totals.

The redesigned CSV model passed **41 base SQL/DAX comparisons, 105 briefing
comparisons, and 33 UTC timestamp checks** in Desktop. See the
[current comparison evidence](../artifacts/report/dsny_20261118/executive_v2/qa/final_csv).
Both exported PDF pages passed visual review, and the final cached CSV PBIX
reopened correctly without refresh. Open the
[executive briefing PDF](../artifacts/report/dsny_20261118/executive_v2/NYC311_dsny_20261118_executive.pdf)
or inspect [artifact status](../artifacts/report/dsny_20261118/README.md).
The original native BigQuery release passed 41
SQL/DAX and 33 timestamp checks after its UTC-text transport correction; the
redesigned native working copy has not yet been refreshed and verified. See
[connection and verification evidence](../docs/powerbi.md).

```powershell
.\powerbi\Prepare-LocalReport.ps1 -ExportRoot .\data\demo_exports -ReleaseId dsny_20261118
```

Open the returned `powerbi/.local/NYC311.pbip`, then refresh. The `.local` copy keeps
machine paths and local credentials out of version control. The source project
intentionally contains placeholder paths. Close any open working copy before
preparing it again; preparation overwrites that working copy's source files.

See [connection, refresh, and validation instructions](../docs/powerbi.md),
[CSV contract](export-contract.json), [base DAX queries](reconciliation.dax), and
[briefing DAX queries](reconciliation-briefing.dax). The
[independent briefing reference](briefing-reference.json) is calculated from the
saved release CSVs; [the comparator](compare_briefing_dax.py) checks it against
executed Desktop results.

The committed [JSON-schema check](validation/source_validation.json) and
[TMDL parse check](validation/tmdl_validation.json) verify source only. Desktop
refresh, rendering, exports, and SQL-to-DAX comparisons require separate evidence.

Regenerate the checked-in source with `node powerbi/build-project.cjs` only when
intentionally changing the source generator. This overwrites generated PBIR/TMDL
files and does not import changes made in Desktop.
The visual hierarchy and interactions are defined in
[briefing-layout.cjs](briefing-layout.cjs).
