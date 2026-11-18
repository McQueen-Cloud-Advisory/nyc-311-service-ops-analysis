"""Keyless BigQuery execution, immutable capture storage, and gated reporting releases."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .contracts import REPO_ROOT, ContractError, atomic_json, canonical_json, content_hash, file_hash, parse_utc, read_json, safe_id, utc_now
from .reference import metrics_evidence, write_exports
from .release import input_identity, validate_capture

MART_NAMES = ("dim_agency", "dim_problem", "dim_borough", "dim_date", "fct_cases", "fct_backlog", "release_metadata")
RECONCILIATION_ANALYSES = ("reconciliation", "date_role_reconciliation", "release_integrity_reconciliation",
                         "segment_investigation", "weekly_demand_and_closures")
REQUEST_FIELDS = {
    "snapshot_id": "STRING", "request_id": "STRING", "created_date": "STRING", "closed_date": "STRING",
    "created_at": "TIMESTAMP", "closed_at": "TIMESTAMP", "created_local_date": "DATE", "closed_local_date": "DATE",
    "temporal_quality": "STRING", "status": "STRING", "agency": "STRING", "problem": "STRING", "borough": "STRING",
    "channel": "STRING", "payload_hash": "STRING",
}
OBSERVATION_FIELDS = {
    "snapshot_id": "STRING", "observed_at": "TIMESTAMP", "extraction_started_at": "TIMESTAMP", "extraction_ended_at": "TIMESTAMP",
    "source_kind": "STRING", "cohort_start": "DATE", "cohort_end": "DATE", "expected_count": "INTEGER", "source_count": "INTEGER",
    "target_version": "STRING", "scope_hash": "STRING", "input_hash": "STRING", "is_published": "BOOLEAN", "capture_uri": "STRING",
}
TARGET_FIELDS = {"target_version": "STRING", "agency": "STRING", "problem": "STRING", "effective_start": "DATE", "effective_end": "DATE", "target_hours": "INTEGER"}
RELEASE_FIELDS = {"release_id": "STRING", "snapshot_id": "STRING", "input_hash": "STRING", "observed_at": "TIMESTAMP", "published_at": "TIMESTAMP",
                  "validation_json": "STRING", "marts_hash": "STRING"}


def config_cloud(path: Path):
    cfg = read_json(path)
    required = {"project_id", "billing_project_id", "location", "raw_dataset", "work_dataset", "reporting_dataset", "control_dataset",
                "raw_bucket", "impersonate_service_account", "maximum_bytes_billed"}
    if set(cfg) != required:
        raise ContractError("Cloud configuration must match config/cloud.example.json exactly")
    for field in ("project_id", "billing_project_id"):
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", cfg[field]) or "replace" in cfg[field]:
            raise ContractError("Configure a dedicated real GCP project ID")
    for field in ("raw_dataset", "work_dataset", "reporting_dataset", "control_dataset"):
        safe_id(cfg[field])
    if len({cfg[field] for field in ("raw_dataset", "work_dataset", "reporting_dataset", "control_dataset")}) != 4:
        raise ContractError("Raw, work, reporting, and control datasets must be distinct")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,61}[a-z0-9]", cfg["raw_bucket"]):
        raise ContractError("Invalid capture bucket name")
    if not re.fullmatch(r"[a-z]+-[a-z]+[0-9]+", cfg["location"]):
        raise ContractError("Use one configured region for BigQuery and GCS")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]@" + re.escape(cfg["project_id"]) + r"\.iam\.gserviceaccount\.com", cfg["impersonate_service_account"]):
        raise ContractError("Use a pipeline service account in the dedicated project")
    if type(cfg["maximum_bytes_billed"]) is not int or not 1 <= cfg["maximum_bytes_billed"] <= 10000000000:
        raise ContractError("A positive per-query limit of at most 10 GB is required")
    return cfg


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class Warehouse:
    def __init__(self, config: dict):
        import google.auth
        from google.auth import impersonated_credentials
        from google.cloud import bigquery, storage
        from google.oauth2 import service_account
        self.cfg = config
        self.bq = bigquery
        source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if isinstance(source, service_account.Credentials):
            raise ContractError("Downloaded service-account keys are unsupported; use user ADC plus impersonation")
        credentials = impersonated_credentials.Credentials(source_credentials=source,
            target_principal=config["impersonate_service_account"], target_scopes=["https://www.googleapis.com/auth/cloud-platform"], lifetime=900)
        self.client = bigquery.Client(project=config["billing_project_id"], credentials=credentials, location=config["location"])
        self.storage = storage.Client(project=config["project_id"], credentials=credentials)
        self.jobs = []

    def table(self, dataset_kind: str, table: str):
        # Release IDs have a short public contract; physical table names include
        # model/snapshot prefixes and legitimately exceed that limit.
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,1023}", table):
            raise ContractError("Invalid generated BigQuery table identifier")
        return f"{self.cfg['project_id']}.{self.cfg[dataset_kind + '_dataset']}.{table}"

    def query(self, sql: str, parameters=None, *, cache=True, dry_run=False):
        job_config = self.bq.QueryJobConfig(maximum_bytes_billed=self.cfg["maximum_bytes_billed"], use_query_cache=cache,
                                          dry_run=dry_run, query_parameters=parameters or [], labels={"purpose": "nyc311", "component": "pipeline"})
        job = self.client.query(sql, job_config=job_config, location=self.cfg["location"])
        if dry_run:
            return job
        completed = False
        try:
            rows = list(job.result(timeout=300))
            completed = True
        finally:
            self.jobs.append({"job_id": job.job_id, "bytes_processed": job.total_bytes_processed, "bytes_billed": job.total_bytes_billed,
                              "cache_hit": job.cache_hit, "statement_type": job.statement_type,
                              "outcome": "completed" if completed and not job.error_result else "failed_or_incomplete"})
        return [{key: json_value(value) for key, value in dict(row).items()} for row in rows]

    def param(self, name, value, type_name="STRING"):
        return self.bq.ScalarQueryParameter(name, type_name, value)

    def ensure_table(self, kind, name, fields):
        table = self.bq.Table(self.table(kind, name), schema=[self.bq.SchemaField(name, typ) for name, typ in fields.items()])
        table.labels = {"managed_by": "nyc311", "purpose": "portfolio"}
        existing = self.client.create_table(table, exists_ok=True)
        type_aliases = {"INT64": "INTEGER", "BOOL": "BOOLEAN", "FLOAT64": "FLOAT"}
        expected = {column: type_aliases.get(typ, typ) for column, typ in fields.items()}
        actual = {field.name: type_aliases.get(field.field_type, field.field_type) for field in existing.schema}
        if (actual != expected or list(actual) != list(expected)
                or any(field.mode != "NULLABLE" or field.fields for field in existing.schema)):
            raise ContractError(f"Cloud table schema drift in {kind}.{name}")

    def load_stage(self, table_name, rows, fields):
        job_config = self.bq.LoadJobConfig(schema=[self.bq.SchemaField(name, typ) for name, typ in fields.items()],
                                          write_disposition="WRITE_TRUNCATE", labels={"purpose": "nyc311"})
        job = self.client.load_table_from_json(rows, self.table("work", table_name), job_config=job_config, location=self.cfg["location"])
        job.result(timeout=300)
        if job.output_rows != len(rows):
            raise ContractError("BigQuery loaded row count differs from captured input")
        return self.table("work", table_name)

    def setup_tables(self):
        for kind in ("raw", "work", "reporting", "control"):
            dataset = self.client.get_dataset(f"{self.cfg['project_id']}.{self.cfg[kind + '_dataset']}")
            if dataset.location.lower() != self.cfg["location"].lower():
                raise ContractError("BigQuery dataset location differs from configured region")
        for kind, name, fields in [
            ("raw", "observation_requests", REQUEST_FIELDS), ("raw", "requests_current", REQUEST_FIELDS | {"source_kind": "STRING", "scope_hash": "STRING"}),
            ("raw", "observations", OBSERVATION_FIELDS), ("raw", "targets", TARGET_FIELDS),
            ("control", "releases", RELEASE_FIELDS), ("control", "publication", {"slot": "STRING", "release_id": "STRING"}),
            ("control", "run_audits", {"attempt_id": "STRING", "recorded_at": "TIMESTAMP", "release_id": "STRING", "audit_json": "STRING"}),
        ]:
            self.ensure_table(kind, name, fields)

    def upload_capture(self, input_path, capture):
        identity = input_identity(capture)
        name = f"captures/{capture['manifest']['snapshot_id']}/{identity}.json.gz"
        blob = self.storage.bucket(self.cfg["raw_bucket"]).blob(name)
        expected = canonical_json(capture).encode("utf-8")
        if blob.exists():
            blob.reload()
            if (blob.metadata or {}).get("input_hash") != identity:
                raise ContractError("Existing immutable capture object has unexpected metadata")
            # Metadata alone is not proof that the object still has the captured
            # content. Pin the generation and bound decompression on verification.
            if blob.size is None or blob.size > max(len(expected) * 2, 1024):
                raise ContractError("Existing capture object has an unexpected size")
            payload = blob.download_as_bytes(if_generation_match=int(blob.generation), timeout=120)
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
                actual = stream.read(len(expected) + 1)
            if actual != expected:
                raise ContractError("Existing immutable capture content differs from captured input")
        else:
            payload = gzip.compress(expected, mtime=0)
            blob.metadata = {"input_hash": identity, "source_kind": capture["manifest"]["source_kind"]}
            blob.upload_from_string(payload, content_type="application/gzip", if_generation_match=0, timeout=120)
        return f"gs://{self.cfg['raw_bucket']}/{name}"

    def assert_same_rows(self, first, second, *, second_where="", parameters=None, columns=None):
        """Exact set and count comparison of tested flat tables, not a weak checksum."""
        first_table, second_table = self.client.get_table(first), self.client.get_table(second)
        def schema(table):
            return [(field.name, field.field_type, field.mode) for field in table.schema]
        if schema(first_table) != schema(second_table):
            raise ContractError("Immutable table copy has a different schema")
        selection = ",".join(columns) if columns else "*"
        first_query = f"SELECT {selection} FROM `{first}`"
        second_query = f"SELECT {selection} FROM `{second}` {second_where}"
        check = self.query(f"""SELECT
            (SELECT COUNT(*) FROM ({first_query})) AS first_count,
            (SELECT COUNT(*) FROM ({second_query})) AS second_count,
            (SELECT COUNT(*) FROM ({first_query} EXCEPT DISTINCT {second_query})) AS first_only,
            (SELECT COUNT(*) FROM ({second_query} EXCEPT DISTINCT {first_query})) AS second_only""", parameters, cache=False)[0]
        if check["first_count"] != check["second_count"] or check["first_only"] or check["second_only"]:
            raise ContractError("Existing immutable stored rows differ; investigate before retrying")

    def copy_mart(self, name, release_id):
        """Recover partial copies without ever overwriting an existing reporting table."""
        from google.api_core.exceptions import Conflict, NotFound
        source = self.table("work", name + "__r_" + release_id)
        destination = self.table("reporting", name + "__r_" + release_id)
        try:
            self.client.get_table(destination)
        except NotFound:
            try:
                self.client.copy_table(source, destination,
                    job_config=self.bq.CopyJobConfig(write_disposition="WRITE_EMPTY"),
                    location=self.cfg["location"]).result(timeout=120)
            except Conflict:
                # Another writer is unsupported; if the identical copy appeared,
                # checking it is safe. A different copy blocks publication.
                pass
        self.assert_same_rows(source, destination)

    def load_observation(self, capture, rows, targets, capture_uri):
        manifest, identity = capture["manifest"], input_identity(capture)
        params = [self.param("snapshot", manifest["snapshot_id"]), self.param("scope", manifest["scope_hash"]),
                  self.param("kind", manifest["source_kind"]), self.param("observed", manifest["observed_at"], "TIMESTAMP")]
        existing = self.query(f"SELECT input_hash FROM `{self.table('raw','observations')}` WHERE snapshot_id=@snapshot", params[:1])
        if existing and (len(existing) != 1 or existing[0]["input_hash"] != identity):
            raise ContractError("Cloud snapshot ID already has different immutable inputs")
        later = self.query(f"SELECT COUNT(*) n FROM `{self.table('raw','observations')}` WHERE scope_hash=@scope AND source_kind=@kind AND observed_at>@observed", params[1:])
        if later[0]["n"]:
            raise ContractError("Older captures can only replay their existing published release")
        staged = self.load_stage("load_requests_" + manifest["snapshot_id"], rows, REQUEST_FIELDS)
        missing = self.query(f"""WITH prior AS (SELECT snapshot_id FROM `{self.table('raw','observations')}`
            WHERE scope_hash=@scope AND source_kind=@kind ORDER BY observed_at DESC,snapshot_id DESC LIMIT 1)
            SELECT COUNT(*) n FROM `{self.table('raw','observation_requests')}` r JOIN prior USING(snapshot_id)
            LEFT JOIN `{staged}` c USING(request_id) WHERE c.request_id IS NULL""", params[1:3])
        if missing[0]["n"]:
            raise ContractError("Requests disappeared from the complete cloud capture; last published release retained")
        observation = {key: manifest[key] for key in ("snapshot_id", "observed_at", "extraction_started_at", "extraction_ended_at", "source_kind", "expected_count", "source_count", "target_version", "scope_hash")}
        observation.update(cohort_start=manifest["scope"]["cohort_start"], cohort_end=manifest["scope"]["cohort_end"], input_hash=identity, is_published=False, capture_uri=capture_uri)
        staged_observation = self.load_stage("load_observation_" + manifest["snapshot_id"], [observation], OBSERVATION_FIELDS)
        staged_targets = self.load_stage("load_targets_" + manifest["snapshot_id"], [dict(target_version=manifest["target_version"], **row) for row in targets], TARGET_FIELDS)
        if existing:
            self.assert_same_rows(staged, self.table("raw", "observation_requests"),
                                  second_where="WHERE snapshot_id=@snapshot", parameters=params[:1])
            self.assert_same_rows(staged_observation, self.table("raw", "observations"),
                                  second_where="WHERE snapshot_id=@snapshot", parameters=params[:1],
                                  columns=[column for column in OBSERVATION_FIELDS if column != "is_published"])
        else:
            orphaned = self.query(f"SELECT COUNT(*) n FROM `{self.table('raw','observation_requests')}` WHERE snapshot_id=@snapshot", params[:1])
            if orphaned[0]["n"]:
                raise ContractError("Unregistered snapshot rows exist; investigate before loading")
        target_parameters = [self.param("target_version", manifest["target_version"])]
        existing_targets = self.query(f"SELECT COUNT(*) n FROM `{self.table('raw','targets')}` WHERE target_version=@target_version", target_parameters)
        if existing_targets[0]["n"]:
            self.assert_same_rows(staged_targets, self.table("raw", "targets"),
                                  second_where="WHERE target_version=@target_version", parameters=target_parameters)
        merge_counts = self.query(f"""SELECT COUNT(*) joined_rows,
            COUNTIF(T.request_id IS NULL) inserted_count,
            COUNTIF(T.request_id IS NOT NULL AND T.payload_hash IS DISTINCT FROM S.payload_hash) changed_count,
            COUNTIF(T.request_id IS NOT NULL AND T.payload_hash IS NOT DISTINCT FROM S.payload_hash) unchanged_count
            FROM `{staged}` S LEFT JOIN `{self.table('raw','requests_current')}` T
              ON T.request_id=S.request_id AND T.source_kind=@kind AND T.scope_hash=@scope""", params[1:3])[0]
        if merge_counts.pop("joined_rows") != len(rows):
            raise ContractError("Current request keys are duplicated within the captured scope")
        names = list(REQUEST_FIELDS)
        update = ",".join(f"T.{name}=S.{name}" for name in names if name != "request_id")
        query = f"""BEGIN TRANSACTION;
        INSERT INTO `{self.table('raw','observations')}` SELECT * FROM `{staged_observation}`
          WHERE NOT EXISTS (SELECT 1 FROM `{self.table('raw','observations')}` WHERE snapshot_id=@snapshot);
        INSERT INTO `{self.table('raw','observation_requests')}` SELECT S.* FROM `{staged}` S
          WHERE NOT EXISTS (SELECT 1 FROM `{self.table('raw','observation_requests')}` T WHERE T.snapshot_id=S.snapshot_id AND T.request_id=S.request_id);
        INSERT INTO `{self.table('raw','targets')}` SELECT S.* FROM `{staged_targets}` S
          WHERE NOT EXISTS (SELECT 1 FROM `{self.table('raw','targets')}` T WHERE T.target_version=S.target_version);
        MERGE `{self.table('raw','requests_current')}` T USING `{staged}` S
          ON T.request_id=S.request_id AND T.source_kind=@kind AND T.scope_hash=@scope
          WHEN MATCHED AND T.payload_hash IS DISTINCT FROM S.payload_hash THEN UPDATE SET {update}
          WHEN NOT MATCHED THEN INSERT ({','.join(names)},source_kind,scope_hash) VALUES ({','.join('S.'+name for name in names)},@kind,@scope);
        COMMIT TRANSACTION;"""
        self.query(query, params[:3])
        count = self.query(f"SELECT COUNT(*) n,COUNT(DISTINCT request_id) unique_n FROM `{self.table('raw','observation_requests')}` WHERE snapshot_id=@snapshot", params[:1])[0]
        if count["n"] != len(rows) or count["unique_n"] != len(rows):
            raise ContractError("Loaded snapshot count/key reconciliation failed")
        return merge_counts

    def export_marts(self, release_id, kind="reporting"):
        # Hash the full governed mart schema, including payload lineage. The
        # Power BI CSV writer selects its narrower import-column contract later.
        contract = read_json(REPO_ROOT / "dbt/reporting_schema.json")
        marts = {}
        for name, table in contract["tables"].items():
            columns = [column["name"] for column in table["columns"]]
            order = {"fct_cases": "request_id", "fct_backlog": "snapshot_id,agency_key,problem_key,borough_key",
                     "dim_date": "date_key", "release_metadata": "snapshot_id"}.get(name, name.removeprefix("dim_") + "_key")
            marts[name] = self.query(f"SELECT {','.join(columns)} FROM `{self.table(kind, name + '__r_' + release_id)}` ORDER BY {order}")
        return marts


def run_dbt(config, capture, release_id, state_dir):
    manifest = capture["manifest"]
    profile_dir = state_dir.resolve() / "dbt_profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO_ROOT / "dbt/profiles.example.yml", profile_dir / "profiles.yml")
    reconciliation_end = manifest["scope"]["cohort_end"]
    reconciliation_start = (date.fromisoformat(reconciliation_end) - timedelta(days=7)).isoformat()
    variables = {"release_id": release_id, "snapshot_id": manifest["snapshot_id"], "observed_at": manifest["observed_at"],
                 "target_version": manifest["target_version"], "source_kind": manifest["source_kind"], "scope_hash": manifest["scope_hash"],
                 "cohort_start": manifest["scope"]["cohort_start"], "cohort_end": manifest["scope"]["cohort_end"], "raw_dataset": config["raw_dataset"],
                 "reconciliation_start": reconciliation_start, "reconciliation_end": reconciliation_end}
    environment = os.environ.copy()
    environment.update(GCP_PROJECT_ID=config["project_id"], GCP_BILLING_PROJECT_ID=config["billing_project_id"],
                       GCP_LOCATION=config["location"], DBT_DATASET=config["work_dataset"],
                       GCP_PIPELINE_SERVICE_ACCOUNT=config["impersonate_service_account"],
                       NYC311_MAXIMUM_BYTES_BILLED=str(config["maximum_bytes_billed"]),
                       DBT_SEND_ANONYMOUS_USAGE_STATS="false", RUN_CACHE_DISABLED="true")
    dbt_executable = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    target_dir = state_dir.resolve() / "dbt_targets" / release_id
    common = ["--project-dir", str(REPO_ROOT / "dbt"), "--profiles-dir", str(profile_dir), "--target-path", str(target_dir),
              "--vars", json.dumps(variables), "--no-use-colors"]
    command = [str(dbt_executable), "build", *common]
    completed = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    private_log = state_dir / "audits" / (release_id + "_dbt.log")
    private_log.parent.mkdir(parents=True, exist_ok=True)
    private_log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    results_path = target_dir / "run_results.json"
    if completed.returncode != 0:
        raise ContractError("dbt build failed; private log retained and previous release unchanged")
    result = read_json(results_path)
    if any(row["status"] not in ("success", "pass") for row in result["results"]):
        raise ContractError("dbt returned a failed or unverified model/test")
    # Build does not promise compiled analysis artifacts. Compile them explicitly
    # after saving the actual build results; this second command executes no SQL.
    compiled = subprocess.run([str(dbt_executable), "compile", *common, "--select", "resource_type:analysis",
                               "--no-introspect", "--no-populate-cache"], env=environment,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    with private_log.open("a", encoding="utf-8") as stream:
        stream.write("\n--- Analysis compilation ---\n" + compiled.stdout + compiled.stderr)
    if compiled.returncode != 0:
        raise ContractError("dbt reconciliation analysis compilation failed; publication unchanged")
    analyses = {}
    for name in RECONCILIATION_ANALYSES:
        path = target_dir / "compiled" / "nyc311" / "analyses" / (name + ".sql")
        if not path.is_file():
            raise ContractError("A required compiled SQL reconciliation query is missing")
        analyses[name] = path.read_text(encoding="utf-8")
    return {"release_id": release_id, "snapshot_id": manifest["snapshot_id"],
            "dbt_version": result["metadata"]["dbt_version"], "generated_at": result["metadata"]["generated_at"],
            "elapsed_time": result["elapsed_time"], "results": [{key: row[key] for key in ("unique_id", "status", "execution_time", "failures") if key in row} for row in result["results"]],
            "compiled_analyses": analyses, "reconciliation_period": {"start": reconciliation_start, "end": reconciliation_end}}


def execute_reconciliation(warehouse, dbt_results, *, reporting=False):
    """Run real GoogleSQL, including PERCENTILE_CONT, and retain queries/results."""
    analyses = dbt_results.get("compiled_analyses", {})
    if not all(name in analyses for name in RECONCILIATION_ANALYSES):
        raise ContractError("Published validation lacks original SQL analyses; investigate before replay")
    evidence = {}
    for name in RECONCILIATION_ANALYSES:
        sql = analyses[name]
        if reporting:
            project, work, report = (warehouse.cfg[key] for key in ("project_id", "work_dataset", "reporting_dataset"))
            sql = sql.replace(f"`{project}`.`{work}`.", f"`{project}`.`{report}`.")
            sql = sql.replace(f"`{project}.{work}.", f"`{project}.{report}.")
        estimate = warehouse.query(sql, cache=False, dry_run=True)
        results = warehouse.query(sql, cache=False)
        evidence[name] = {"sql": sql, "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                          "dry_run_bytes": estimate.total_bytes_processed,
                          "job": dict(warehouse.jobs[-1]), "output_rows": results}
    return evidence


def verify_sql_reconciliation(sql_evidence, cases, manifest, dbt_results):
    """Compare SQL outputs with local expectations; never label the latter SQL."""
    from .reference import summarize
    slices = {
        "overall": cases,
        "DSNY / Dirty Condition / BROOKLYN": [row for row in cases if row["agency_key"] == "DSNY"
            and row["problem_key"] == "Dirty Condition" and row["borough_key"] == "BROOKLYN"],
        "empty": [],
    }
    rows = sql_evidence["reconciliation"]["output_rows"]
    actual_slices = {row["slice"]: row for row in rows}
    if set(actual_slices) != set(slices) or len(rows) != len(slices):
        raise ContractError("SQL reconciliation did not return exactly the expected slices")
    def equal_number(actual, expected, label, tolerance=1e-6):
        if (actual is None) != (expected is None) or (actual is not None and abs(actual - expected) > tolerance):
            raise ContractError(f"SQL/reference numeric reconciliation failed: {label}")
    for name, selection in slices.items():
        actual, expected = actual_slices[name], summarize(selection)
        if actual["release_id"] != dbt_results["release_id"] or actual["snapshot_id"] != manifest["snapshot_id"]:
            raise ContractError("SQL reconciliation returned the wrong release or snapshot")
        for metric in ("case_count", "intake", "recorded_closures", "observed_backlog", "target_numerator", "target_denominator", "p90_eligible_count"):
            if actual[metric] != expected[metric]:
                raise ContractError(f"SQL/reference reconciliation failed: {name}/{metric}")
        equal_number(actual["p90_elapsed_hours"], expected["p90_elapsed_hours"], name + "/p90")
        equal_number(actual["target_rate"], expected["within_demo_target"], name + "/target_rate", tolerance=1e-12)
        for key in ("missing_target", "invalid_outcome", "unknown_outcome", "immature"):
            if actual[key + "_cases"] != expected["eligibility_counts"].get(key, 0):
                raise ContractError("SQL/reference exclusion-count reconciliation failed")
    period = dbt_results["reconciliation_period"]
    creation = [row for row in cases if row["created_date"] and period["start"] <= row["created_date"] < period["end"]]
    closure = [row for row in cases if row["closed_date"] and period["start"] <= row["closed_date"] < period["end"] and row["is_p90_eligible"]]
    created_summary, closed_summary, overall = summarize(creation), summarize(closure), summarize(cases)
    dated_rows = sql_evidence["date_role_reconciliation"]["output_rows"]
    if len(dated_rows) != 1:
        raise ContractError("Date-role SQL reconciliation returned an unexpected row count")
    dated = dated_rows[0]
    expected_dates = {"intake_creation_slice": created_summary["intake"],
        "closures_closure_slice": closed_summary["recorded_closures"],
        "target_numerator_creation_slice": created_summary["target_numerator"],
        "target_denominator_creation_slice": created_summary["target_denominator"],
        "p90_eligible_closure_slice": closed_summary["p90_eligible_count"],
        "backlog_observation": overall["observed_backlog"], "backlog_without_period": overall["observed_backlog"]}
    if any(dated[key] != expected for key, expected in expected_dates.items()):
        raise ContractError("SQL/reference date-role reconciliation failed")
    equal_number(dated["p90_hours_closure_slice"], closed_summary["p90_elapsed_hours"], "closure-date p90")
    integrity_rows = sql_evidence["release_integrity_reconciliation"]["output_rows"]
    if len(integrity_rows) != 1:
        raise ContractError("Release-integrity SQL returned an unexpected row count")
    integrity = integrity_rows[0]
    expected_integrity = {"release_rows": 1, "case_release_count": 1 if cases else 0,
        "case_snapshot_count": 1 if cases else 0, "backlog_snapshot_count": 1 if cases else 0,
        "open_case_rows": overall["observed_backlog"], "observed_backlog": overall["observed_backlog"]}
    if any(integrity[key] != expected for key, expected in expected_integrity.items()):
        raise ContractError("SQL release/snapshot integrity reconciliation failed")
    return actual_slices["overall"]


def publish_cloud(capture, input_path, release_id, config_path, state_dir, export_dir, simulate_failure=None):
    safe_id(release_id)
    manifest, identity = capture["manifest"], input_identity(capture)
    warehouse, published_committed = None, False
    audit = {"attempt_id": uuid.uuid4().hex, "release_id": release_id, "snapshot_id": manifest["snapshot_id"],
             "started_at": utc_now(), "outcome": "running", "source_count": len(capture["rows"]), "loaded_count": 0,
             "rejected_rows": 0, "engine": "BigQuery + dbt"}
    try:
        rows, targets = validate_capture(capture)
        cfg = config_cloud(config_path)
        audit.update(maximum_bytes_billed=cfg["maximum_bytes_billed"],
                     temporal_rejected_rows=sum(row["temporal_quality"] != "valid" for row in rows))
        warehouse = Warehouse(cfg)
        warehouse.setup_tables()
        params = [warehouse.param("release", release_id)]
        prior = warehouse.query(f"SELECT * FROM `{warehouse.table('control','releases')}` WHERE release_id=@release", params)
        if prior:
            if len(prior) != 1 or prior[0]["input_hash"] != identity:
                raise ContractError("Published cloud release ID has different inputs")
            from google.api_core.exceptions import NotFound
            published_committed = True
            dbt_results = json.loads(prior[0]["validation_json"])
            try:
                marts = warehouse.export_marts(release_id)
            except NotFound:
                # Recovery for an interrupted older publication order: only a
                # candidate matching the committed full mart hash may fill gaps.
                try:
                    candidate = warehouse.export_marts(release_id, kind="work")
                except NotFound as exc:
                    raise ContractError("Committed release is incomplete and its original candidate is unavailable; restore the original candidate before replay") from exc
                if content_hash(candidate) != prior[0]["marts_hash"]:
                    raise ContractError("Recovery candidate differs from the committed release; reporting tables were not overwritten")
                for name in MART_NAMES:
                    warehouse.copy_mart(name, release_id)
                marts = warehouse.export_marts(release_id)
                audit["recovered_missing_reporting_tables"] = True
            if content_hash(marts) != prior[0]["marts_hash"]:
                raise ContractError("Published reporting rows changed after publication")
            sql_evidence = execute_reconciliation(warehouse, dbt_results, reporting=True)
            from .reference import build_marts
            reference_cases = build_marts(rows, manifest, targets, release_id)["fct_cases"]
            sql_overall = verify_sql_reconciliation(sql_evidence, reference_cases, manifest, dbt_results)
            evidence = metrics_evidence(marts, manifest, release_id)
            evidence.update(verification_engine="Executed BigQuery SQL and previously passed dbt tests; DAX pending",
                            dbt=dbt_results, sql_reconciliation=sql_evidence)
            evidence["overall"]["p90_elapsed_hours"] = sql_overall["p90_elapsed_hours"]
            evidence["overall"]["within_demo_target"] = sql_overall["target_rate"]
            write_exports(marts, export_dir / release_id)
            atomic_json(export_dir / release_id / "verification.json", evidence)
            evidence_dir = REPO_ROOT / "artifacts" / "releases" / release_id
            atomic_json(evidence_dir / "replays" / audit["attempt_id"] / "sql_reconciliation.json", sql_evidence)
            # Promotion can commit before the local handoff finishes. Restore
            # missing standard evidence on replay without replacing the original
            # successful build/SQL records when they already exist.
            for filename, recorded in (("bigquery.json", evidence), ("dbt_results.json", dbt_results),
                                       ("sql_reconciliation.json", sql_evidence)):
                path = evidence_dir / filename
                if not path.exists():
                    atomic_json(path, recorded)
            audit.update(outcome="replayed", loaded_count=len(rows))
            return {"outcome": "replayed", "release_id": release_id, "overall": evidence["overall"], "marts_hash": evidence["marts_hash"]}
        audit["phase"] = "capturing"
        capture_uri = warehouse.upload_capture(input_path, capture)
        audit["phase"] = "loading"
        merge_counts = warehouse.load_observation(capture, rows, targets, capture_uri)
        audit.update(loaded_count=len(rows), capture_uri=capture_uri, **merge_counts)
        audit["phase"] = "building_and_testing"
        dbt_results = run_dbt(cfg, capture, release_id, state_dir)
        if simulate_failure == "validation":
            raise ContractError("Simulated failed cloud validation; previous release retained")
        marts = warehouse.export_marts(release_id, kind="work")
        evidence = metrics_evidence(marts, manifest, release_id)
        evidence["verification_engine"] = "Executed BigQuery SQL and passed dbt tests; DAX pending"
        evidence["dbt"] = dbt_results
        # Compare same captured input to independently calculated local expectations.
        from .reference import build_marts, summarize
        expected = summarize(build_marts(rows, manifest, targets, release_id)["fct_cases"])
        actual = evidence["overall"]
        for metric in ("case_count", "intake", "recorded_closures", "observed_backlog", "target_numerator", "target_denominator", "p90_eligible_count", "eligibility_counts"):
            if actual[metric] != expected[metric]:
                raise ContractError(f"BigQuery/reference reconciliation failed for {metric}")
        if (actual["p90_elapsed_hours"] is None) != (expected["p90_elapsed_hours"] is None) or (
            actual["p90_elapsed_hours"] is not None and abs(actual["p90_elapsed_hours"] - expected["p90_elapsed_hours"]) > 1e-6):
            raise ContractError("BigQuery/reference p90 reconciliation failed")
        audit["phase"] = "sql_reconciliation"
        sql_evidence = execute_reconciliation(warehouse, dbt_results)
        sql_overall = verify_sql_reconciliation(sql_evidence, build_marts(rows, manifest, targets, release_id)["fct_cases"], manifest, dbt_results)
        evidence["sql_reconciliation"] = sql_evidence
        # This percentile comes from actual PERCENTILE_CONT execution, after
        # comparison to the independent local reference over captured inputs.
        evidence["overall"]["p90_elapsed_hours"] = sql_overall["p90_elapsed_hours"]
        evidence["overall"]["within_demo_target"] = sql_overall["target_rate"]
        audit["phase"] = "copying_reporting_tables"
        for name in MART_NAMES[:-1]:
            warehouse.copy_mart(name, release_id)
        if simulate_failure == "publication":
            raise ContractError("Simulated failed cloud publication; release metadata and active pointer unchanged")
        # Metadata is the last table. The active pointer is promoted only after
        # every tested immutable reporting table is present and verified.
        warehouse.copy_mart("release_metadata", release_id)
        release_row = {"release_id": release_id, "snapshot_id": manifest["snapshot_id"], "input_hash": identity,
                       "observed_at": manifest["observed_at"], "published_at": utc_now(),
                       "validation_json": canonical_json(dbt_results), "marts_hash": evidence["marts_hash"]}
        staged_release = warehouse.load_stage("publish_" + release_id, [release_row], RELEASE_FIELDS)
        audit["phase"] = "promoting_control"
        warehouse.query(f"""BEGIN TRANSACTION;
            ASSERT (SELECT COUNT(*) FROM `{warehouse.table('control','releases')}` WHERE release_id=@release)=0 AS 'Release ID already registered';
            ASSERT (SELECT COUNT(*) FROM `{warehouse.table('control','publication')}` WHERE slot='active')<=1 AS 'Duplicate active publication';
            ASSERT (SELECT COUNT(*) FROM `{warehouse.table('raw','observations')}` WHERE snapshot_id=@snapshot AND input_hash=@input_hash)=1 AS 'Observation identity changed';
            INSERT INTO `{warehouse.table('control','releases')}` SELECT * FROM `{staged_release}`;
            UPDATE `{warehouse.table('raw','observations')}` SET is_published=TRUE WHERE snapshot_id=@snapshot;
            MERGE `{warehouse.table('control','publication')}` T USING (SELECT 'active' slot,@release release_id) S ON T.slot=S.slot
              WHEN MATCHED THEN UPDATE SET release_id=S.release_id WHEN NOT MATCHED THEN INSERT(slot,release_id) VALUES(S.slot,S.release_id);
            COMMIT TRANSACTION;""", [warehouse.param("snapshot", manifest["snapshot_id"]), warehouse.param("release", release_id),
                                      warehouse.param("input_hash", identity)])
        published_committed = True
        audit["phase"] = "exporting_evidence"
        write_exports(marts, export_dir / release_id)
        atomic_json(export_dir / release_id / "verification.json", evidence)
        evidence_dir = REPO_ROOT / "artifacts" / "releases" / release_id
        atomic_json(evidence_dir / "bigquery.json", evidence)
        atomic_json(evidence_dir / "dbt_results.json", dbt_results)
        atomic_json(evidence_dir / "sql_reconciliation.json", sql_evidence)
        audit["outcome"] = "published"
        return {"outcome": "published", "release_id": release_id, "overall": evidence["overall"], "marts_hash": evidence["marts_hash"], "dbt_checks": len(dbt_results["results"])}
    except Exception as exc:
        outcome = ("published_handoff_failed" if published_committed else "publication_outcome_unknown"
                   if audit.get("phase") == "promoting_control" else "failed")
        audit.update(outcome=outcome, error_type=type(exc).__name__,
                     error_detail=str(exc) if isinstance(exc, ContractError) else "Cloud operation failed; inspect API error without HTTP credential logging")
        raise
    finally:
        audit.update(ended_at=utc_now(), jobs=warehouse.jobs if warehouse else [], cloud_release_committed=published_committed)
        atomic_json(state_dir / "audits" / (release_id + "_cloud_" + audit["attempt_id"] + ".json"), audit)
        try:
            if warehouse is not None:
                warehouse.client.load_table_from_json([{"attempt_id": audit["attempt_id"], "recorded_at": audit["ended_at"], "release_id": release_id, "audit_json": canonical_json(audit)}],
                    warehouse.table("control", "run_audits"), job_config=warehouse.bq.LoadJobConfig(write_disposition="WRITE_APPEND"), location=cfg["location"]).result(timeout=60)
        except Exception:
            # A local audit still survives permission or connectivity failures.
            pass


def benchmark_cloud(config_path, release_id):
    safe_id(release_id)
    warehouse = Warehouse(config_cloud(config_path))
    source = warehouse.table("reporting", "fct_cases__r_" + release_id)
    baseline = warehouse.table("work", "benchmark_baseline__r_" + release_id)
    metadata = warehouse.query(f"SELECT cohort_start,cohort_end FROM `{warehouse.table('reporting','release_metadata__r_'+release_id)}`")
    if len(metadata) != 1:
        raise ContractError("Benchmark requires one completed release scope")
    start = date.fromisoformat(metadata[0]["cohort_start"])
    end = min(start + timedelta(days=7), date.fromisoformat(metadata[0]["cohort_end"]))
    parameters = [warehouse.param("from_date", start, "DATE"), warehouse.param("to_date", end, "DATE"),
                  warehouse.param("borough", "BROOKLYN")]
    # CTAS intentionally omits partitioning and clustering. The setup scan is
    # recorded separately from the two compared, cache-disabled query scans.
    warehouse.query(f"CREATE OR REPLACE TABLE `{baseline}` AS SELECT * FROM `{source}`")
    setup_job = dict(warehouse.jobs[-1])
    baseline_table = warehouse.client.get_table(baseline)
    optimized_table = warehouse.client.get_table(source)
    if baseline_table.time_partitioning or baseline_table.range_partitioning or baseline_table.clustering_fields:
        raise ContractError("Benchmark baseline unexpectedly has partitioning or clustering")
    if not optimized_table.time_partitioning or not optimized_table.clustering_fields:
        raise ContractError("Optimized benchmark table is missing its configured storage design")
    query_pattern = ("SELECT agency_key,problem_key,borough_key,COUNT(*) request_count,"
                     "SUM(target_numerator) target_numerator,SUM(target_denominator) target_denominator "
                     "FROM `{table}` WHERE created_date>=@from_date AND created_date<@to_date AND borough_key=@borough "
                     "GROUP BY 1,2,3 ORDER BY 1,2,3")
    results, measures = {}, {}
    for label, table in (("baseline", baseline), ("optimized", source)):
        sql = query_pattern.format(table=table)
        estimate = warehouse.query(sql, parameters, cache=False, dry_run=True)
        results[label] = warehouse.query(sql, parameters, cache=False)
        measures[label] = dict(warehouse.jobs[-1], dry_run_bytes=estimate.total_bytes_processed, sql=sql)
    if results["baseline"] != results["optimized"]:
        raise ContractError("Benchmark queries returned different results")
    evidence = {"release_id": release_id, "run_at": utc_now(),
                "scope": {"creation_start": start.isoformat(), "creation_end_exclusive": end.isoformat(), "borough": "BROOKLYN"},
                "query_cache_disabled": True, "setup_job": setup_job,
                "same_outputs": True, "output_rows": results["optimized"], "output_sha256": content_hash(results["optimized"]), "measurements": measures,
                "interpretation": "Measured bytes on this bounded cohort only; do not infer production savings or elapsed-time improvement."}
    atomic_json(REPO_ROOT / "artifacts" / "releases" / release_id / "benchmark.json", evidence)
    return evidence
