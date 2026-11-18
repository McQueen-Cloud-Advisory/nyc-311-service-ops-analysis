# Contributing

Use a feature branch and a pull request for every change to `main`, including
documentation and workflow updates. Keep each pull request focused on one outcome
and describe the behavior changed, the validation performed, and any remaining
limits.

1. Start from current `main`: `git switch main`, then `git pull --ff-only`.
2. Create a descriptive branch, for example `git switch -c ci/validate-dbt`.
3. Make the change and run the relevant local checks below. Review `git diff`
   before committing, particularly generated evidence and configuration files.
4. Push the branch and open a pull request against `main`.
5. Resolve review conversations, update the branch if required, and wait for all
   required checks to pass for the current change.
6. Use **Squash and merge** or **Rebase and merge** to keep `main` linear.

An approving review is not required: this is a solo-contributor portfolio. The
pull request still records the change and its validation. Administrators follow
the same required checks and conversation-resolution policy.

## Main branch policy

The intended protection settings are:

| Setting | Value |
| --- | --- |
| Require a pull request | Enabled |
| Require approving reviews | Disabled; zero required approvals |
| Require status checks | Enabled after the CI checks have completed successfully |
| Require conversation resolution | Enabled |
| Require signed commits | Disabled |
| Require linear history | Enabled |
| Do not allow bypassing | Enabled, including administrators |
| Allow force pushes | Disabled |
| Allow deletions | Disabled |
| Lock branch | Disabled |

These settings apply to `main`; topic branches can be removed after merging.
GitHub repository settings enforce this policy; this document describes it.

## Local checks and CI scope

Require these exact job names in branch protection after their first successful
GitHub Actions run:

| Check | Coverage |
| --- | --- |
| `Python tests (3.12)` | Python contracts, metrics, security, and replay/recovery on Python 3.12 |
| `Python tests (3.13)` | The same checks on Python 3.13 |
| `dbt validation` | Offline dbt project and BigQuery SQL validation |
| `Configuration validation` | Repository configuration and Power BI source/export contracts |

Use Python 3.12 or 3.13 in a virtual environment. From the repository root:

```shell
python -m pip install -e .
python -m nyc311 validate
```

The local validation command runs the Python contracts, metric, security, and
replay/recovery tests. It writes fresh evidence under `artifacts/validation/` and
`artifacts/replay/`; include regenerated evidence only when it belongs to the
change. The checked-in files document specific prior executions.

The [GitHub Actions workflow](.github/workflows/local-checks.yml) is the source of
truth for CI commands and dependency versions. CI runs on pull requests and
pushes to `main` without cloud credentials. dbt/SQL validation checks the project
before warehouse execution; a green CI run does not establish that BigQuery data
tests or Power BI Desktop refresh and DAX comparisons passed. Use the
[cloud runbook](docs/runbook.md) and [Power BI verification guide](docs/powerbi.md)
when a change needs those checks, and attach the resulting evidence to the pull
request.

Keep local cloud settings in `.local/` and credentials outside version control.
Use the checked-in example configuration when documenting setup.
