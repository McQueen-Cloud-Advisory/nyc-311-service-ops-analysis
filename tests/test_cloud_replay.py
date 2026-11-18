"""Offline safety checks for the opt-in live replay proof's restoration boundary."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from nyc311.cloud_replay import OWNED_RELEASES, RecordedQueries, restore_original_release, run_cloud_replay
from nyc311.contracts import ContractError


def original():
    return dict(slot="active", release_id="real_release", snapshot_id="real_snapshot",
                input_hash="original_input", marts_hash="original_marts", source_kind="real")


def recorder(active_rows):
    result = Mock()
    result.active.side_effect = active_rows
    result.warehouse.table.side_effect = lambda kind, name: "test-project." + kind + "." + name
    return result


class RestoreBoundaryTests(TestCase):
    def test_already_original_pointer_requires_no_write(self):
        queries = recorder([[original()]])
        result = restore_original_release(queries, original())
        self.assertTrue(result["restored"])
        self.assertEqual(result["outcome"], "already_original")
        queries.run.assert_not_called()

    def test_unowned_duplicate_and_missing_active_pointers_are_never_written(self):
        for rows in ([dict(original(), release_id="another_operator_release")], [], [original(), original()]):
            with self.subTest(rows=rows):
                queries = recorder([rows])
                with self.assertRaisesRegex(ContractError, "restoration refused"):
                    restore_original_release(queries, original())
                queries.run.assert_not_called()

    def test_owned_pointer_restores_with_identity_and_compare_and_swap_guards(self):
        for release_id in OWNED_RELEASES:
            with self.subTest(release_id=release_id):
                queries = recorder([[dict(original(), release_id=release_id)], [original()]])
                self.assertTrue(restore_original_release(queries, original())["restored"])
                name, sql, params = queries.run.call_args.args
                self.assertEqual(name, "restore_original_active_release")
                self.assertEqual(params["owned"], release_id)
                self.assertEqual(params["original"], original()["release_id"])
                self.assertEqual(params["input_hash"], original()["input_hash"])
                self.assertEqual(params["marts_hash"], original()["marts_hash"])
                self.assertIn("BEGIN TRANSACTION", sql)
                self.assertIn("release_id=@owned", sql)
                self.assertIn("input_hash=@input_hash AND marts_hash=@marts_hash", sql)
                self.assertIn("COMMIT TRANSACTION", sql)

    def test_failed_post_restore_verification_is_not_reported_as_success(self):
        queries = recorder([[dict(original(), release_id=OWNED_RELEASES[1])], [dict(original(), input_hash="changed")]])
        with self.assertRaisesRegex(ContractError, "could not be verified"):
            restore_original_release(queries, original())

    def test_existing_evidence_blocks_before_credentials_or_cloud_access(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "proof.json"
            original_bytes = b'{"outcome":"pass","retained":true}'
            output.write_bytes(original_bytes)
            with patch("nyc311.cloud_replay.cloud.config_cloud") as config, patch("nyc311.cloud_replay.cloud.Warehouse") as warehouse:
                with self.assertRaisesRegex(ContractError, "Existing replay evidence"):
                    run_cloud_replay(Path("unused"), output)
            config.assert_not_called()
            warehouse.assert_not_called()
            self.assertEqual(output.read_bytes(), original_bytes)


class RecordedQueryTests(TestCase):
    def test_queries_record_actual_rows_jobs_and_disable_cache(self):
        warehouse = SimpleNamespace(jobs=[], param=lambda name, value: (name, value))
        def query(sql, parameters, *, cache):
            self.assertFalse(cache)
            self.assertEqual(parameters, [("request", "synthetic_0001")])
            warehouse.jobs.append({"job_id": "simulated-unit-test", "bytes_processed": 1})
            return [{"actual_fixture_output": 7}]
        warehouse.query = query
        evidence = {"queries": []}
        result = RecordedQueries(warehouse, evidence).run("fixture", "SELECT @request", {"request": "synthetic_0001"})
        self.assertEqual(result, evidence["queries"][0]["output_rows"])
        self.assertEqual(evidence["queries"][0]["jobs"], warehouse.jobs)
        self.assertEqual(evidence["queries"][0]["outcome"], "completed")

    def test_arbitrary_api_exception_body_is_not_copied_to_evidence(self):
        warehouse = SimpleNamespace(jobs=[], param=Mock(), query=Mock(side_effect=RuntimeError("sensitive response body")))
        evidence = {"queries": []}
        with self.assertRaises(RuntimeError):
            RecordedQueries(warehouse, evidence).run("failure", "SELECT 1")
        self.assertEqual(evidence["queries"][0]["error_type"], "RuntimeError")
        self.assertNotIn("sensitive response body", str(evidence))
