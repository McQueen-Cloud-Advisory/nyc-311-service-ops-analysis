"""Local file-recovery simulations; no credentials, cloud queries, or dbt runs."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipIf
from unittest.mock import Mock, patch

try:
    from google.api_core.exceptions import NotFound
except ModuleNotFoundError as error:
    if error.name not in {"google", "google.api_core", "google.api_core.exceptions"}:
        raise
    NotFound = None

from nyc311 import cloud
from nyc311.contracts import REPO_ROOT, content_hash
from nyc311.reference import build_marts, summarize
from nyc311.release import input_identity, validate_capture
from nyc311.source import read_capture


@skipIf(NotFound is None, "Optional cloud dependencies absent; install .[cloud] to run simulated cloud checks")
class CommittedReplayEvidenceRecovery(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.release_id = "evidence_recovery"
        self.capture = read_capture(REPO_ROOT / "data/fixtures/synthetic_b.json")
        rows, targets = validate_capture(self.capture)
        self.marts = build_marts(rows, self.capture["manifest"], targets, self.release_id)
        self.dbt = {"release_id": self.release_id, "snapshot_id": self.capture["manifest"]["snapshot_id"],
                    "results": [{"unique_id": "simulated_test", "status": "pass"}]}
        self.sql = {"test_only": "Simulated SQL output; this check verifies file recovery only"}
        overall = summarize(self.marts["fct_cases"])
        self.sql_overall = dict(overall, target_rate=overall["within_demo_target"])
        self.directory = self.root / "artifacts/releases" / self.release_id
        self.cfg = {"maximum_bytes_billed": 1000000000, "location": "us-central1"}
        self.warehouse = Mock(spec=cloud.Warehouse)
        self.warehouse.jobs = []
        self.warehouse.bq = SimpleNamespace(LoadJobConfig=lambda **kwargs: kwargs)
        self.warehouse.client = Mock()
        self.warehouse.table.side_effect = lambda kind, name: f"test-project.{kind}.{name}"
        self.warehouse.export_marts.return_value = self.marts
        self.warehouse.query.return_value = [{"input_hash": input_identity(self.capture),
            "marts_hash": content_hash(self.marts), "validation_json": json.dumps(self.dbt)}]

    def replay(self):
        with patch.object(cloud, "REPO_ROOT", self.root), \
                patch.object(cloud, "Warehouse", return_value=self.warehouse), \
                patch.object(cloud, "config_cloud", return_value=self.cfg), \
                patch.object(cloud, "execute_reconciliation", return_value=self.sql), \
                patch.object(cloud, "verify_sql_reconciliation", return_value=self.sql_overall), \
                patch.object(cloud, "write_exports"), patch.object(cloud, "run_dbt") as dbt:
            result = cloud.publish_cloud(self.capture, Path("unused"), self.release_id, Path("unused"),
                                         self.root / "state", self.root / "exports")
        self.assertEqual(result["outcome"], "replayed")
        dbt.assert_not_called()
        self.warehouse.copy_mart.assert_not_called()
        self.assertEqual(self.warehouse.query.call_count, 1)  # Existing release lookup; no promotion.
        return result

    def test_committed_replay_recreates_all_missing_standard_evidence(self):
        self.assertFalse(self.directory.exists())
        self.replay()
        saved_dbt = json.loads((self.directory / "dbt_results.json").read_text())
        saved_sql = json.loads((self.directory / "sql_reconciliation.json").read_text())
        saved_bigquery = json.loads((self.directory / "bigquery.json").read_text())
        self.assertEqual(saved_dbt, self.dbt)
        self.assertEqual(saved_sql, self.sql)
        self.assertEqual(saved_bigquery["dbt"], self.dbt)
        self.assertEqual(saved_bigquery["sql_reconciliation"], self.sql)
        self.assertEqual(saved_bigquery["marts_hash"], content_hash(self.marts))
        self.assertEqual(saved_bigquery["release_id"], self.release_id)
        self.assertEqual(len(list((self.directory / "replays").glob("*/sql_reconciliation.json"))), 1)

    def test_committed_replay_preserves_original_evidence_bytes(self):
        self.directory.mkdir(parents=True)
        originals = {name: ("{\n  \"original_record\": \"" + name + "\"\n}\n").encode()
                     for name in ("bigquery.json", "dbt_results.json", "sql_reconciliation.json")}
        for name, value in originals.items():
            (self.directory / name).write_bytes(value)
        self.replay()
        for name, value in originals.items():
            self.assertEqual((self.directory / name).read_bytes(), value)
        refreshed = list((self.directory / "replays").glob("*/sql_reconciliation.json"))
        self.assertEqual(len(refreshed), 1)
        self.assertEqual(json.loads(refreshed[0].read_text()), self.sql)
