# Security model and evidence

This project uses public NYC 311 records, but the cloud environment, credentials,
raw captures, and administration interfaces remain private. A public input does
not justify a public bucket or a broadly privileged reporting account.

## Identities and trust boundaries

| Identity | Intended access | Excluded from normal use |
| --- | --- | --- |
| Bootstrap operator | Create the dedicated project and resources; manage their IAM and billing; inspect audit evidence | Do not run ingestion/dbt as the project owner or use this identity to claim a read-only reporting test |
| `nyc311-pipeline` service account | Submit BigQuery jobs; edit data only in the four named datasets; create and read raw capture objects | No project Owner/Editor, IAM administration, billing administration, object deletion, service-account key files, or scheduled execution |
| `nyc311-reporter` service account | Submit jobs in the billing project; read only the reporting dataset; keyless permission probes | No raw/work/control dataset grant, raw bucket grant, reporting write grant, or credential key file |
| Optional independent Power BI user | Same reporting read/job grants when a second Google account is available | No raw/work/control or raw bucket grant |
| Public reviewer | Inspect the deliberately published sanitized extract, exports, and evidence in the repository | No access to the private GCP project, credentials, or IAM evidence containing personal account details |

The bootstrap creates `nyc311_raw`, `nyc311_work`, `nyc311_reporting`, and
`nyc311_control`. Dataset ACLs explicitly name the operator and pipeline account;
only reporting also names the reporter service account and any optional human
reporter. It does not add the default
`projectReaders` or `projectWriters` groups. BigQuery project-level Job User
allows submitting jobs; it does not by itself grant table data access. The
report uses `UseStorageApi=false` for this bounded import, so the bootstrap does
not enable the Storage Read API or grant Read Session User. Add those only if a
later, explicitly reviewed connector change requires them.
[BigQuery IAM roles](https://docs.cloud.google.com/bigquery/docs/access-control)

The supported one-account setup uses Scott's Google OAuth login in Power BI and
two separate service accounts for pipeline execution and read-only role tests.
`reporter_email` is optional; leave it null if no second Google account exists.
The operator impersonates `nyc311-reporter` to prove reporting SELECT succeeds,
raw SELECT is denied, and reporting writes are denied, without downloading keys.

IAM permissions are additive. A human who owns the project retains administrative
access even if given a reporting-only dataset grant. A successful refresh under
the owner's account proves report functionality, not least privilege. The
reporter service-account probes prove the scoped role design, not the permissions
of that owner-authenticated Desktop session. An optional second human reporter
can provide a distinct Desktop identity later. Inspect inherited
organization/folder roles and group memberships when applicable; the supplied
project-policy checker cannot prove their absence.

## Authentication and credentials

The pipeline uses Application Default Credentials with service-account
impersonation. Only the operator receives Token Creator on the pipeline and
reporter service accounts, with each grant scoped to its individual account.
Google issues temporary service-account credentials; no downloaded
private key is needed. The operator's local ADC refresh credentials are still
sensitive and must stay outside the repository and synced project directory.
[Impersonation and ADC](https://docs.cloud.google.com/docs/authentication/use-service-account-impersonation)

Power BI uses interactive Google OAuth with the operator in the one-account
setup, or with the optional distinct reporting user if configured. Never paste
service-account JSON into Power Query or save credentials in PBIP/TMDL files.
The report can also use an approved, sanitized local export for offline review.
Authentication itself is an operator step; recorded evidence must omit tokens,
authorization headers, account recovery details, and credentials.

## Source and storage controls

- Allowlist source fields: request ID, created/closed dates, status, agency,
  problem, borough, and channel only when useful. Do not capture street addresses,
  coordinates, resolution descriptions, or other free text. Validate the output
  schema before storing or publishing extracts.
- Upload captures under immutable snapshot/hash names with an object creation
  precondition (`if_generation_match=0`). Replay reads the saved object. The
  pipeline receives Object Creator and Object Viewer on the capture bucket;
  it cannot replace or delete existing objects using those grants.
  [Cloud Storage object roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles)
- Enable uniform bucket-level access and enforce public access prevention.
  This removes the separate object-ACL permission path and blocks public IAM/ACL
  grants. Do not generate signed URLs as a substitute for the reviewer export.
  [Uniform access](https://docs.cloud.google.com/storage/docs/uniform-bucket-level-access),
  [public access prevention](https://docs.cloud.google.com/storage/docs/public-access-prevention)
- Keep the storage bucket and datasets in one configured region. The bootstrap
  requests seven days of bucket soft delete, with no lifecycle deletion rule or
  locked retention policy. Preserve published evidence before any manual cleanup.
  [Bucket creation options](https://docs.cloud.google.com/sdk/gcloud/reference/storage/buckets/create)

Published marts are physically copied into the reporting dataset only after
candidate checks. Their names contain the release ID, and the manifest is
published last. Power BI pins that release across all imports. A failed candidate
cannot alter the tables that a reader is already importing. This is an
application publication contract, not a claim of tamper-proof BigQuery storage:
the pipeline's dataset write permission could alter old tables if its code or
credentials were compromised. Raw captures, hashes, and independent exports
provide recovery evidence; release protection tests must accompany the code.

## Auditability and spending controls

Enable Cloud Storage `DATA_READ` and `DATA_WRITE` audit logging for this dedicated
project. BigQuery supplies audit records for its data activity. Logs can contain
query text, resource identifiers, and account identities, so only the operator
should inspect private logs. Export a sanitized finding or check result, not a
raw authentication or IAM dump. Data Access logs can incur charges; the bounded
manual demo keeps their volume limited.
[Data Access audit configuration](https://docs.cloud.google.com/logging/docs/audit/configure-data-access),
[BigQuery audit records](https://docs.cloud.google.com/bigquery/docs/reference/auditlogs)

The example budget is a **$10 monthly project alert**, below the user's $30 GCP
allowance. It measures spend before credits and alerts at 50%, 80%, and 100%.
Confirm the allowance's billing period and inspect notification recipients during
setup. A budget alert does not stop queries or guarantee a spending ceiling.
No VM, scheduler, reservation, gateway, or always-running service is provisioned.
[Budget API](https://docs.cloud.google.com/billing/docs/how-to/budget-api-overview)

Bound each pipeline query with a dry run and `maximum_bytes_billed`; record
processed/billed bytes in the run audit. A project/user query quota is a useful
additional operator control, especially for Power BI queries that do not expose
the same per-query option. Limits need to be set and verified for the actual
billing project; a row `LIMIT` does not by itself bound bytes scanned.
[BigQuery cost controls](https://docs.cloud.google.com/bigquery/docs/best-practices-costs)

## Verification status and review path

The read-only live preflight on 2026-11-18 at 12:03 UTC passed all 23
project-local policy and configuration checks. The sanitized result is retained
in [gcp-preflight.json](../artifacts/security/gcp-preflight.json). This verifies
the inspected dataset grants, private bucket controls, scoped impersonation,
absence of user-managed service-account keys, and audit configuration at that
time. It does not demonstrate actual audit events or effective inherited access.
Reporter functional authorization probes and Desktop OAuth least privilege
remain explicitly unverified in that preflight result.

The subsequent [reporter authorization result](../artifacts/security/gcp-reporter.json)
at 12:16 UTC passed all 26 executed checks. Keyless reporter impersonation could
dry-run a SELECT on the real reporting table. Both the raw-table SELECT and the
reporting-table DELETE dry runs returned HTTP 403 with BigQuery's structured
`accessDenied` reason. No DELETE was executed. The owner account used by Desktop
still has broader permissions; that separate least-privilege claim remains
unverified. Windows PowerShell sometimes leaves `ErrorDetails` empty; the verifier
also parses its bounded response stream in memory and retains only the reason.
Unrelated HTTP 403 errors do not count as permission-denial proof.

The [sanitized audit-event evidence](../artifacts/security/audit-events.json)
contains 27 observed events from the configured pipeline principal, including
Cloud Storage object creation/read actions and BigQuery job insertion/completion.
The query was limited to this dedicated project, that exact principal and the
execution time window. Principal email addresses and user delegation details
are excluded from the public artifact. This verifies observed events in addition
to the earlier audit configuration checks; it is not a claim of complete log
coverage or organization-wide access review.

The [executed BigQuery replay](../artifacts/replay/bigquery-replay.json) passed all
24 checks at 12:26 UTC. The synthetic A/B transition retained the same current
keys, preserved the original captured rows/hash and backlog, and replayed B
without changing rows or metrics. An intentionally injected application
validation error after a real dbt build left B active and both published releases
unchanged. The original real release was then restored with a guarded transaction
and read back successfully. This is not proof of a naturally failing dbt SQL
test or a mid-publication network interruption. The
[replay protocol](../artifacts/replay/README.md) documents its first-run-only
fixture-scope requirement, retained history, immutable evidence output, shared
operator lock and restoration boundary. It makes no DAX verification claim.

| Control/evidence | Local implementation | Executed evidence / remaining scope |
| --- | --- | --- |
| Default provisioning mode | Offline plan; explicit `-Apply` required | None for offline plan |
| Configuration guardrails | Reject public principals, same operator/reporter, shell-like IDs, duplicate datasets, and budgets above $30 | Review real configuration and ownership |
| Scoped grants/private bucket | Provisioning source and read-only inspection script | Passed live policy checks; inherited access remains a separate review |
| No service-account key files | Impersonation setup and user-managed-key inspection | Both accounts had zero user-managed keys in live inspection |
| Reporter role isolation | Positive/negative BigQuery dry-run probes using reporter service-account impersonation | Reporting SELECT succeeded; raw SELECT and reporting DELETE dry runs returned accessDenied |
| Desktop OAuth identity | Explicit one-account limitation; optional distinct reporter user supported | Owner OAuth is not least privilege; verify a separate actual Desktop identity if later available |
| Capture and release integrity | Required runtime behavior described above | 24 live synthetic replay checks passed; real active pointer restored; failure-injection scope bounded above |
| Audit access | Targeted audit configuration | 27 observed pipeline events including Storage object actions and BigQuery job actions |
| Low spend | Alert configuration and bounded-query contract | Confirm budget, recipients, actual bytes and actual billing |

Run `powershell -NoProfile -File infra/Test-Local.ps1` for offline checks.
Run the commands in [cloud setup](cloud-setup.md) to reproduce cloud evidence.
Keep policy inspection, live functional authorization, mocked contract tests,
and Desktop identity checks separate; a pass in one does not prove the others.

The [local test environment evidence](../artifacts/security/local-test-environments.json)
records both supported paths. A clean `pip install -e .` discovered 72 checks:
60 passed, including all six security checks, and 12 optional cloud simulations
were explicitly skipped. With the cloud dependencies installed, those 12
simulations and seven restoration-safety checks passed using mocked clients and
no credentials. They exercise
publication order, interrupted-release recovery, immutable copies, capture
content validation, identifier validation, and reconciliation comparisons.
The [complete local validation](../artifacts/validation/local.json) then passed
all 72 tests with the cloud extra installed and no skips. These local checks
still make no cloud calls.

## Dependency supply chain

Direct application dependencies are pinned in `pyproject.toml`, and
`requirements.lock.txt` records the installed application and transitive versions.
The version lock does not include artifact hashes. Install from the official
PyPI index, review dependency changes, and rerun the audit when rebuilding the
environment. The audit tool is
kept in a separate ignored virtual environment so it does not add application
dependencies or alter a running pipeline.

The executed [initial dependency scan](../artifacts/security/dependency-audit-before.json)
used PyPA `pip-audit` 2.10.1 against the actual project environment, including the
cloud extra. It checked 120 installed distributions and excluded the editable
first-party package. The only package with reported advisories was the packaging
tool `pip` 25.0.1: six unique advisory IDs appeared in 12 returned advisory rows.
Upgrading only `pip` to 26.3 resolved those reported findings. The executed
[post-remediation scan](../artifacts/security/dependency-audit-after.json) checked
the same 120 distributions and reported no known vulnerabilities. Its before/after
inventory comparison confirms all application and cloud dependency versions
remained unchanged. The editable first-party project remains outside the advisory
scan in both results.

```powershell
# The audit environment is separate from the application environment.
python -m venv .local/audit-venv
./.local/audit-venv/Scripts/python.exe -m pip --isolated install --index-url https://pypi.org/simple --upgrade --no-deps pip==26.3
./.local/audit-venv/Scripts/python.exe -m pip --isolated install --index-url https://pypi.org/simple pip-audit==2.10.1
./.local/audit-venv/Scripts/python.exe -m pip_audit --path .venv/Lib/site-packages --skip-editable --vulnerability-service pypi --format json --output .local/dependency-audit-raw.json --progress-spinner off
```

This scan matches installed versions to known advisories; it does not establish
that packages are non-malicious or cover first-party code, the operating system,
or unknown vulnerabilities. See the [PyPA pip-audit documentation](https://github.com/pypa/pip-audit)
and its [official PyPI distribution](https://pypi.org/project/pip-audit/).

## Recovery and scope limits

If a credential is exposed, stop new runs, revoke the affected user session or
impersonation grant, disable the pipeline identity if necessary, and inspect
audit logs. Do not print the exposed credential while documenting the incident.
Retain the last verified export and release while investigating changes.

The design uses Google's managed service encryption and authenticated APIs.
It does not add a VM network, custom encryption keys, VPC Service Controls, a
security operations platform, or a compliance claim. Those controls are not
needed to demonstrate this bounded public-data pipeline, and adding them would
create costs and operating responsibilities outside the portfolio's scope.
