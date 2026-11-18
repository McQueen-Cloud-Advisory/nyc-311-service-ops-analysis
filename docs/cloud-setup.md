# Dedicated GCP setup

Provisioning is an explicit operator action. Local validation does not need a
billing account or Google Cloud credentials.

## Review first

From the repository root:

```powershell
powershell -NoProfile -File infra/Test-Local.ps1
powershell -NoProfile -File infra/Initialize-Gcp.ps1 -ConfigPath infra/gcp.example.json
```

The second command prints a concrete resource/access plan and makes **zero cloud
calls**. It does not need `gcloud`. A new project, four regional datasets, a private
raw-capture bucket, pipeline and reporter service accounts, narrowly scoped grants, audit
settings, and a project-filtered alert budget comprise the plan.

Create a local, git-ignored `.local/gcp.json` from the example. Replace the unique
project/bucket names, billing account ID, and operator email. Leave
`reporter_email` null for the supported one-account setup. A distinct human
reporter can be added later, but is not required for the role-design checks.
Keep actual account configuration out of committed files. The default
region is `us-central1`; change it before resource creation if required.
When creating the dedicated project inside an organization, set the optional
numeric `organization_id`; bootstrap passes that exact parent to project creation.

## Operator prerequisites

Install the Google Cloud CLI. Sign in interactively as the bootstrap operator:

```powershell
gcloud auth login
gcloud auth list
gcloud billing accounts list
```

The operator needs authority to create a project, attach the chosen billing
account, enable APIs, create the resources, manage project/service-account IAM,
and manage the billing-account budget. This may require a billing administrator
to complete the budget step. These are bootstrap privileges, not pipeline roles.
Do not solve a denied pipeline command by adding project Owner or Editor.

The script uses explicit project arguments and never changes gcloud's default
project. Run bootstrap without a global service-account impersonation setting.
Do not copy tokens, ADC files, or service-account keys into the workspace.

## Apply the reviewed configuration

```powershell
powershell -NoProfile -File infra/Initialize-Gcp.ps1 -ConfigPath .local/gcp.json -Apply
```

The script refuses example values and an active account that differs from the
operator. It creates a new project, or resumes only a project labeled
`managed_by=nyc311,purpose=portfolio`. Existing resources are checked for ownership;
the script does not silently replace existing dataset ACLs. Existing budget
settings are preserved, so inspect them if configuration changed between runs.

If setup fails midway, inspect the named step, fix the permission or configuration,
and rerun the same file. Do not delete the project to work around a recoverable
permission error. The preflight below detects missing resources and access drift
before the pipeline should load data. No dataset table-expiration or storage
lifecycle deletion policy is applied, so archived releases remain usable.
Non-authentication CLI failures report the path to sanitized stderr under
git-ignored `.local/gcloud-diagnostics/`. Authentication output is never logged;
do not enable SDK HTTP tracing or copy these local diagnostics into public evidence.
An IAM binding can briefly reject a newly created service-account principal.
Only that exact principal-not-found error receives six bounded attempts with
1/2/4/8/16-second waits; permission, project, role, and other errors fail immediately.

## Authenticate the pipeline without keys

Use the real project ID in place of `PROJECT_ID`:

```powershell
gcloud auth application-default login --project=PROJECT_ID --impersonate-service-account nyc311-pipeline@PROJECT_ID.iam.gserviceaccount.com
```

This creates local ADC outside the repository. Configure the Python/GoogleSQL/dbt
runtime for `PROJECT_ID`, the same region, and the four dataset names from the
cloud configuration. Never set `GOOGLE_APPLICATION_CREDENTIALS` to a committed
private key file. The pipeline's `maximum_bytes_billed` setting applies to its
query jobs; verify the chosen value with dry runs before a real refresh.

Google Sheets is optional. Its live path must use the read-only spreadsheets
scope and an explicitly configured spreadsheet ID. Share only the demonstration
target spreadsheet with the pipeline identity when needed; do not grant Drive
wide access or build a service-account key path. The checked-in CSV remains the
default. Google Docs publication uses the connected Workspace tool and is a
separate user-visible document operation.

## Verify cloud policy and report permissions

```powershell
powershell -NoProfile -File infra/Test-GcpSecurity.ps1 -ConfigPath .local/gcp.json -OutputPath .local/security-policy-result.json
```

This reads project/dataset/bucket policies, service-account keys, and audit
settings. It does not mutate resources, read table rows, or claim that policy
inspection proves effective access. Inspect inherited/group grants separately.
Confirm the $10 project budget and that intended recipients receive alerts.

For the one-account setup, sign in to Power BI with the operator's Google OAuth
account and configure the native BigQuery connector in Import mode. That login
retains its owner/admin access: label Desktop least-privilege verification
**unverified**, even after a functional refresh succeeds. The report queries only
reporting tables, but its owner's permissions are broader than those queries.

The separate `nyc311-reporter` service account receives only project-level Job
User/Service Usage Consumer and reporting dataset READER. It is used for keyless
authorization probes, not injected into Desktop through a credential file.
The shipped connector sets `UseStorageApi=false`, so it does not
need the additional Storage Read API/Read Session User grant. Revisit those
permissions together if changing the connector option.

After physical tables exist, run the following while the operator is signed in:

```powershell
powershell -NoProfile -File infra/Test-GcpSecurity.ps1 -ConfigPath .local/gcp.json -TestReporter -ReportingTable ACTUAL_RELEASE_TABLE -RawTable ACTUAL_RAW_TABLE -OutputPath .local/security-reporter-result.json
```

Replace both table names with existing **physical tables**, not views. The three
probes impersonate `nyc311-reporter` with a temporary token and are dry runs:
reporting SELECT must succeed, raw SELECT must be denied,
and reporting DELETE must be denied. No DELETE executes. Missing tables, malformed
SQL, or network failures do not count as a successful denial test. The policy
inspection explicitly uses the operator account; the probes explicitly use
`--impersonate-service-account` for the reporter. No second Google login or
service-account key file is needed. Passing probes prove the isolated reporter
role design only; they do not prove the owner's Desktop OAuth is read-only.

If a separate human Google account becomes available, set `reporter_email` to
that distinct account, apply its scoped grants, and verify its actual effective
access and Desktop OAuth session separately. It must not be an owner/editor or
inherit broader access through an organization or group. For an already-created
dataset, add the human reporting grant deliberately: bootstrap preserves existing
dataset ACLs and does not silently rewrite them on a rerun.

Then refresh Power BI, reconcile DAX to SQL, and keep a sanitized copy of the
security result with the release evidence. The cached PBIX contains imported
data; publish only the approved limited public fields and inspect its metadata.

## Retain or clean up deliberately

Keep the project available for manual demos within the allowance. Review usage
after cloud validation and periodically while retained. A $10 alert is an early
warning, not a hard cap; set appropriate project/user BigQuery query quotas as an
additional control. Keep recurring schedules disabled.

Before optional cleanup, export the verified report, memo, real extract, release
manifest, SQL/DAX reconciliation, benchmark, replay, and security evidence. Verify
the local review path. To remove the dedicated cloud environment later, delete
the exact project through Google Cloud project settings or the documented gcloud
project deletion workflow after checking its ID and exports. This repository
does not run teardown automatically. Review the billing-account budget separately
because budgets are billing-account resources and may outlive the project.

See [security model](security.md) for the access matrix, sources, limitations,
and checks that must remain marked unverified until executed.
