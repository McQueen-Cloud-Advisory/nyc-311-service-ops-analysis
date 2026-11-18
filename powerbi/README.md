# Power BI report source

Open `NYC311.pbip` in Power BI Desktop after preparing local parameters. The project
contains two native Power BI pages, a TMDL semantic model, explicit DAX measures,
and native BigQuery Import plus CSV reviewer modes.

Release `dsny_20261118` passed 41 SQL/DAX comparisons in each mode. Native
BigQuery also passed 33 UTC timestamp checks after an explicit UTC-text transport
correction. The cached CSV PBIX reopened successfully without refresh. See
[connection and verification evidence](../docs/powerbi.md).

```powershell
.\powerbi\Prepare-LocalReport.ps1 -ExportRoot .\data\demo_exports -ReleaseId dsny_20261118
```

Open the returned `powerbi/.local/NYC311.pbip`, then refresh. The `.local` copy keeps
machine paths and local credentials out of version control. The source project
intentionally contains placeholder paths. Close any open working copy before
preparing it again; preparation overwrites that working copy's source files.

See [connection, refresh, and validation instructions](../docs/powerbi.md),
[CSV contract](export-contract.json), and [DAX reconciliation queries](reconciliation.dax).

The committed [JSON-schema check](validation/source_validation.json) and
[TMDL parse check](validation/tmdl_validation.json) verify source only. Desktop
refresh, rendering, exports, and SQL-to-DAX comparisons require separate evidence.

Regenerate the checked-in source with `node powerbi/build-project.cjs` only when
intentionally changing the source generator. This overwrites generated PBIR/TMDL
files and does not import changes made in Desktop.
