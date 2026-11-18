# Architecture and release lifecycle

## One bounded system

Python handles collection, input contracts, UTC normalization, immutable input storage,
auditing, and orchestration. GoogleSQL/dbt owns production transformations. Power BI
Import owns filter-aware aggregation and presentation. GCS, BigQuery, IAM, and Cloud
Logging are the only cloud-platform services in the core path. CSV and Docs-ready
Markdown keep the reviewer path independent of Workspace availability.

Local reference calculations are a deliberately small executable oracle for fixture
tests and an offline report. They are not evidence that BigQuery or DAX executed.

## Storage boundaries

| Location | Purpose | Who needs access |
| --- | --- | --- |
| Private GCS capture bucket | Immutable compressed source rows, targets, scope, timestamps, hashes | Pipeline create/read; operator admin |
| `nyc311_raw` | Captured request facts, observation register, versioned targets, current-state MERGE | Pipeline write; no reporter access |
| `nyc311_work` | Bounded loads, dbt staging/candidates, benchmark baseline | Pipeline write; no reporter access |
| `nyc311_reporting` | Immutable `<model>__r_<release_id>` tables | Pipeline publish; reporter read |
| `nyc311_control` | Releases, selected publication, run audits | Pipeline write; no reporter access |
| `data/public` and `data/demo_exports` | Deliberately published minimal-field capture and reviewer exports | Repository readers |
| `.local` | Credentials-free machine configuration, local state, private diagnostics | Local operator; excluded from Git |

Credentials themselves remain in the user's GCP credential store. Service-account
keys are not created. The pipeline exchanges the authenticated operator identity
for short-lived credentials for one dedicated service account.

## Capture and promotion

1. Lock the single-operator runner; no concurrent refresh/promotion is supported.
2. Read source metadata and count the exact configured cohort.
3. Download approved fields using request-key ordering and keyset pagination.
4. Check uniqueness, full counts, unchanged source metadata, and target contracts.
5. Seal the capture with a logical snapshot ID, original observation time, input
   hashes, extraction interval, source kind, and scope hash.
6. Load normalized captured rows and payload-hash MERGE current requests. Historical
   reporting reads immutable captures, not mutable current state.
7. Run dbt build in the work dataset. Execute SQL reconciliation against independent
   expected results. A failed check leaves the selected reporting release unchanged.
8. Copy and verify the immutable reporting tables, then update the control publication
   transaction. Keep prior releases. A retry verifies existing copies before reuse.
9. Set Power BI's release parameter once, refresh all tables together, and reconcile
   explicit measures. Save the prior cached report until the new refresh passes.

SQL/date tests, shared dimensions, target hashes, and per-table release validation
prevent silent fanout and mixed-release imports. Publishing six independent mutable
`latest` views would not guarantee that a sequential Import refresh sees one release.

## Snapshots and investigation

The backlog fact preserves each published captured snapshot for an identical cohort
and source kind. The report's request-level investigation imports only its release's
snapshot. Inspect an older capture by selecting its older release and refreshing all
tables. This avoids a second case-by-snapshot reporting fact while keeping details
consistent with the displayed backlog.

The trade-off is deliberate storage duplication across immutable releases. This is
small for the bounded demo, simplifies recovery and auditing, and allows an explicit
retention decision later. No automatic expiration silently removes the last good
release. No scheduler, VM, managed dbt service, or paid BI sharing license is required.

## Threat and evidence boundaries

Input contracts reject extra private fields, unsafe IDs, schema drift, unreviewed
statuses, target overlap, incomplete extracts, and changed input under an existing
logical ID. Requests that disappear block promotion; disappearance is not closure.
Network clients retain TLS verification and prevent authenticated cross-origin
redirects. Git excludes credentials, local settings, and report caches.

The source remains a public, mutable API. Matching counts and metadata reduce
inconsistency risk but do not create an atomic upstream snapshot. Report conclusions
are limited to the captured cohort and agency-recorded closure. See
[security](security.md), [metric contracts](metrics.md), and [recovery](runbook.md).
