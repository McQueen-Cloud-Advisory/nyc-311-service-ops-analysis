"""Parse/compile dbt and check BigQuery SQL syntax without warehouse access.

These checks do not execute SQL or dbt data tests. Each run uses a fresh temporary
profile and target directory, synthetic release variables, and no credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel
import yaml

ROOT = Path(__file__).resolve().parents[1]
OFFLINE_DBT = """
from unittest.mock import patch
blocked = RuntimeError("Network access is disabled during offline dbt validation")
with patch("socket.socket.connect", side_effect=blocked), \\
     patch("socket.socket.connect_ex", side_effect=blocked), \\
     patch("socket.getaddrinfo", side_effect=blocked):
    from dbt.cli.main import cli
    cli()
"""
RELEASE_VARS = {
    "release_id": "ci_fixture",
    "snapshot_id": "ci_fixture",
    "target_version": "ci_targets",
    "scope_hash": "0" * 64,
    "source_kind": "synthetic",
    "observed_at": "2026-11-18T12:00:00Z",
    "cohort_start": "2026-09-07",
    "cohort_end": "2026-11-16",
}


def validate_compiled_sql(manifest: dict) -> dict[str, int]:
    counts = {"model": 0, "analysis": 0, "test": 0}
    for node_id, node in manifest["nodes"].items():
        kind = node["resource_type"]
        if kind not in counts:
            continue
        sql = node.get("compiled_code", "")
        if not sql.strip():
            raise ValueError(f"{node_id}: missing compiled SQL")
        try:
            statements = sqlglot.parse(sql, read="bigquery", error_level=ErrorLevel.RAISE)
        except sqlglot.errors.ParseError as error:
            raise ValueError(f"{node_id}: invalid BigQuery SQL: {error}") from error
        if not statements or any(statement is None or isinstance(statement, exp.Command) for statement in statements):
            raise ValueError(f"{node_id}: empty or unsupported SQL statement")
        counts[kind] += 1
    if not all(counts.values()):
        raise ValueError(f"Expected compiled models, analyses, and tests; found {counts}")
    return counts


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="nyc311-dbt-ci-") as directory:
        scratch = Path(directory)
        profiles = scratch / "profiles"
        profiles.mkdir()
        profile = yaml.safe_load((ROOT / "dbt/profiles.example.yml").read_text(encoding="utf-8"))
        output = profile["nyc311"]["outputs"]["dev"]
        # BigQuery initializes a client even with introspection disabled.
        # This fake token avoids ADC discovery; loopback prevents cloud access
        # if a future macro tries to query during compilation.
        output.update({
            "method": "oauth-secrets",
            "token": "ci-placeholder-not-a-real-token",
            "api_endpoint": "http://127.0.0.1:9",
            "job_retries": 0,
            "job_execution_timeout_seconds": 5,
        })
        output.pop("impersonate_service_account", None)
        (profiles / "profiles.yml").write_text(yaml.safe_dump(profile), encoding="utf-8")
        environment = os.environ.copy()
        environment.update({
            "RUN_CACHE_DISABLED": "true",
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            "DBT_LOG_PATH": str(scratch / "logs"),
            "GCP_PROJECT_ID": "unconfigured-project",
            "GCP_BILLING_PROJECT_ID": "unconfigured-project",
            "GCP_PIPELINE_SERVICE_ACCOUNT": "unconfigured@unconfigured-project.iam.gserviceaccount.com",
            "GCP_LOCATION": "US",
            "DBT_DATASET": "nyc311_ci",
            # A future macro that attempts authentication must fail closed,
            # rather than silently discovering the developer's local ADC.
            "GOOGLE_APPLICATION_CREDENTIALS": str(scratch / "credentials-do-not-exist.json"),
            "CLOUDSDK_CONFIG": str(scratch / "gcloud"),
        })
        shared = [
            "--project-dir", str(ROOT / "dbt"),
            "--profiles-dir", str(profiles),
            "--target-path", str(scratch / "target"),
            "--vars", json.dumps(RELEASE_VARS),
            "--no-partial-parse",
        ]
        for command, flags in (
            ("parse", []),
            ("compile", ["--no-introspect", "--no-populate-cache"]),
        ):
            subprocess.run(
                [sys.executable, "-c", OFFLINE_DBT, command, *shared, *flags],
                cwd=ROOT, env=environment, check=True, timeout=120,
            )
        manifest = json.loads((scratch / "target/manifest.json").read_text(encoding="utf-8"))
        counts = validate_compiled_sql(manifest)
        print(json.dumps({
            "status": "passed", "compiled_sql": counts,
            "scope": "dbt parse, Jinja compilation, SQLGlot BigQuery syntax parsing; no warehouse queries or data tests executed",
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
