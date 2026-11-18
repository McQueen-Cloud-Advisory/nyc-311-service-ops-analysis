"""Credential-free cloud contract simulations, not proof of live GCP behavior.

The minimal installation skips these checks when google-api-core is absent.
Install the cloud extra to execute them; all clients and SQL execution are mocked.
"""
import gzip
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main, skipIf
from unittest.mock import Mock, patch

try:
    from google.api_core.exceptions import NotFound
except ModuleNotFoundError as exc:
    if exc.name not in {"google", "google.api_core", "google.api_core.exceptions"}:
        raise
    NotFound = None
from nyc311 import cloud
from nyc311.contracts import ContractError, content_hash
from nyc311.reference import build_marts, summarize
from nyc311.release import input_identity
from test_metrics import manifest, request, targets

CFG = dict(project_id="test-project", billing_project_id="test-project", location="us-central1",
           raw_dataset="raw", work_dataset="work", reporting_dataset="reporting", control_dataset="control",
           raw_bucket="test-bucket", impersonate_service_account="pipeline@test-project.iam.gserviceaccount.com",
           maximum_bytes_billed=1000000000)


@skipIf(NotFound is None, "Optional cloud dependencies absent; install .[cloud] to run simulated cloud checks")
class CloudContractSimulations(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest = manifest()
        self.rows = [request("a")]
        self.targets = targets()
        self.capture = {"manifest": self.manifest, "rows": self.rows, "targets": self.targets}
        self.release_id = "test_release"
        self.marts = build_marts(self.rows, self.manifest, self.targets, self.release_id)
        self.dbt = {"release_id": self.release_id, "snapshot_id": self.manifest["snapshot_id"],
                    "results": [{"status": "pass"}], "compiled_analyses": {},
                    "reconciliation_period": {"start": "2026-11-09", "end": "2026-11-16"}}
        self.overall = summarize(self.marts["fct_cases"])
        self.sql_overall = dict(self.overall, target_rate=self.overall["within_demo_target"])

    def fake_warehouse(self, prior=None):
        warehouse = Mock(spec=cloud.Warehouse)
        warehouse.cfg, warehouse.jobs = CFG, []
        warehouse.bq = SimpleNamespace(LoadJobConfig=lambda **kwargs: kwargs)
        warehouse.client = Mock()
        warehouse.param.side_effect = lambda name, value, type_name="STRING": SimpleNamespace(name=name, value=value)
        warehouse.table.side_effect = lambda kind, name: f"test-project.{kind}.{name}"
        self.events = []
        def query(sql, *args, **kwargs):
            if sql.lstrip().startswith("BEGIN TRANSACTION"):
                self.events.append("commit")
                return []
            if "SELECT *" in sql and "control.releases" in sql:
                return prior or []
            return []
        warehouse.query.side_effect = query
        warehouse.copy_mart.side_effect = lambda name, rid: self.events.append("copy:" + name)
        warehouse.load_observation.return_value = dict(inserted_count=1, changed_count=0, unchanged_count=0)
        warehouse.upload_capture.return_value = "gs://test-bucket/capture.json.gz"
        warehouse.load_stage.return_value = "test-project.work.publish_test_release"
        warehouse.export_marts.return_value = self.marts
        return warehouse

    def invoke(self, warehouse, failure=None):
        with patch.object(cloud, "Warehouse", return_value=warehouse), \
                patch.object(cloud, "config_cloud", return_value=CFG), \
                patch.object(cloud, "validate_capture", return_value=(self.rows, self.targets)), \
                patch.object(cloud, "run_dbt", return_value=self.dbt), \
                patch.object(cloud, "execute_reconciliation", return_value={"simulated": True}), \
                patch.object(cloud, "verify_sql_reconciliation", return_value=self.sql_overall), \
                patch.object(cloud, "write_exports"), patch.object(cloud, "atomic_json"):
            return cloud.publish_cloud(self.capture, Path("input"), self.release_id, Path("config"),
                                       self.root / "state", self.root / "exports", failure)

    def test_metadata_copy_precedes_atomic_promotion(self):
        warehouse = self.fake_warehouse()
        result = self.invoke(warehouse)
        self.assertEqual(result["outcome"], "published")
        self.assertEqual(self.events, ["copy:" + name for name in cloud.MART_NAMES] + ["commit"])

    def test_simulated_publication_failure_preserves_previous_pointer(self):
        warehouse = self.fake_warehouse()
        with self.assertRaises(ContractError):
            self.invoke(warehouse, "publication")
        self.assertNotIn("commit", self.events)
        self.assertNotIn("copy:release_metadata", self.events)

    def test_committed_release_missing_metadata_recovers_without_repromoting(self):
        prior = [{"input_hash": input_identity(self.capture), "marts_hash": content_hash(self.marts),
                  "validation_json": json.dumps(self.dbt)}]
        warehouse = self.fake_warehouse(prior)
        warehouse.export_marts.side_effect = [NotFound("missing metadata"), self.marts, self.marts]
        result = self.invoke(warehouse)
        self.assertEqual(result["outcome"], "replayed")
        self.assertNotIn("commit", self.events)
        self.assertEqual(self.events, ["copy:" + name for name in cloud.MART_NAMES])

    def test_recovery_refuses_candidate_with_changed_rows(self):
        prior = [{"input_hash": input_identity(self.capture), "marts_hash": content_hash(self.marts),
                  "validation_json": json.dumps(self.dbt)}]
        warehouse = self.fake_warehouse(prior)
        different = deepcopy(self.marts)
        different["fct_cases"][0]["age_hours"] += 1
        warehouse.export_marts.side_effect = [NotFound("missing metadata"), different]
        with self.assertRaises(ContractError):
            self.invoke(warehouse)
        self.assertEqual(self.events, [])

    def test_existing_verified_copy_is_not_overwritten(self):
        warehouse = cloud.Warehouse.__new__(cloud.Warehouse)
        warehouse.cfg = CFG
        warehouse.client = Mock()
        warehouse.bq = Mock()
        warehouse.assert_same_rows = Mock()
        warehouse.copy_mart("fct_cases", self.release_id)
        warehouse.client.copy_table.assert_not_called()
        warehouse.assert_same_rows.assert_called_once()

    def test_long_physical_names_accept_a_valid_long_release_id(self):
        warehouse = cloud.Warehouse.__new__(cloud.Warehouse)
        warehouse.cfg = CFG
        name = "release_metadata__r_" + "r" * 63
        self.assertTrue(warehouse.table("work", name).endswith(name))
        with self.assertRaises(ContractError):
            warehouse.table("work", "bad`;DROP TABLE x")

    def test_existing_gcs_metadata_does_not_hide_changed_content(self):
        warehouse = cloud.Warehouse.__new__(cloud.Warehouse)
        warehouse.cfg = CFG
        warehouse.storage = Mock()
        blob = warehouse.storage.bucket.return_value.blob.return_value
        blob.exists.return_value = True
        blob.metadata = {"input_hash": input_identity(self.capture)}
        payload = gzip.compress(b'{"tampered":true}')
        blob.size, blob.generation = len(payload), "1"
        blob.download_as_bytes.return_value = payload
        with self.assertRaises(ContractError):
            warehouse.upload_capture(Path("unused"), self.capture)
        blob.upload_from_string.assert_not_called()

    def test_invalid_cloud_config_exception_is_not_swallowed_by_audit_finally(self):
        with patch.object(cloud, "config_cloud", side_effect=ContractError("missing config")), \
                patch.object(cloud, "validate_capture", return_value=(self.rows, self.targets)), \
                patch.object(cloud, "atomic_json") as audit:
            with self.assertRaises(ContractError):
                cloud.publish_cloud(self.capture, Path("input"), self.release_id, Path("config"),
                                    self.root / "state", self.root / "exports")
            self.assertEqual(audit.call_args.args[1]["outcome"], "failed")

    def test_executed_sql_evidence_uses_reporting_tables_on_replay(self):
        warehouse = SimpleNamespace(cfg=CFG, jobs=[])
        calls = []
        def query(sql, *, cache, dry_run=False):
            calls.append((sql, cache, dry_run))
            if dry_run:
                return SimpleNamespace(total_bytes_processed=123)
            warehouse.jobs.append({"job_id": "simulated", "bytes_processed": 123})
            return []
        warehouse.query = query
        dbt = {"compiled_analyses": {name: "SELECT * FROM `test-project`.`work`.`fct_cases__r_test_release`"
                                    for name in cloud.RECONCILIATION_ANALYSES}}
        evidence = cloud.execute_reconciliation(warehouse, dbt, reporting=True)
        self.assertEqual(set(evidence), set(cloud.RECONCILIATION_ANALYSES))
        self.assertTrue(all("`reporting`" in sql and cache is False for sql, cache, dry in calls))
        self.assertEqual(sum(dry for _, _, dry in calls), len(cloud.RECONCILIATION_ANALYSES))

    def test_sql_comparison_checks_real_percentile_and_date_role_outputs(self):
        cases = build_marts([request("closed", closed="2026-11-11T07:00:00", status="Closed"), request("open")],
                            self.manifest, self.targets, self.release_id)["fct_cases"]
        overall = summarize(cases)
        sliced = []
        for name, rows in (("overall", cases), ("DSNY / Dirty Condition / BROOKLYN", []), ("empty", [])):
            summary = summarize(rows)
            sliced.append(dict(summary, release_id=self.release_id, snapshot_id=self.manifest["snapshot_id"],
                slice=name, target_rate=summary["within_demo_target"],
                **{key + "_cases": summary["eligibility_counts"].get(key, 0)
                   for key in ("missing_target", "invalid_outcome", "unknown_outcome", "immature")}))
        evidence = {
            "reconciliation": {"output_rows": sliced},
            "date_role_reconciliation": {"output_rows": [dict(intake_creation_slice=2, closures_closure_slice=1,
                target_numerator_creation_slice=1, target_denominator_creation_slice=2,
                p90_eligible_closure_slice=1, p90_hours_closure_slice=24, backlog_observation=1, backlog_without_period=1)]},
            "release_integrity_reconciliation": {"output_rows": [dict(release_rows=1, case_release_count=1,
                case_snapshot_count=1, backlog_snapshot_count=1, open_case_rows=1, observed_backlog=1)]},
        }
        result = cloud.verify_sql_reconciliation(evidence, cases, self.manifest, self.dbt)
        self.assertEqual(result["p90_elapsed_hours"], 24)
        evidence["reconciliation"]["output_rows"][0]["p90_elapsed_hours"] = 99
        with self.assertRaises(ContractError):
            cloud.verify_sql_reconciliation(evidence, cases, self.manifest, self.dbt)


if __name__ == "__main__":
    main(verbosity=2)
