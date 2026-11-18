"""Capture/release integration tests against the actual local persistence path."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from nyc311.contracts import ContractError, REPO_ROOT, content_hash
from nyc311.release import publish_local, validate_capture
from nyc311.source import read_capture


def fixture(name):
    return read_capture(REPO_ROOT / "data" / "fixtures" / f"synthetic_{name}.json")


def rehash(capture):
    """Describe a deliberately changed but internally coherent captured payload."""
    capture["manifest"].update(expected_count=len(capture["rows"]), source_count=len(capture["rows"]),
                               source_count_after=len(capture["rows"]), payload_hash=content_hash(capture["rows"]))
    return capture


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state, self.exports = self.root / "state", self.root / "exports"
        self.a, self.b = fixture("a"), fixture("b")

    def publish(self, capture, release, failure=None):
        return publish_local(capture, release, self.state, self.exports, failure)

    def query(self, sql, args=()):
        with closing(sqlite3.connect(self.state / "reference.sqlite")) as connection:
            return connection.execute(sql, args).fetchall()

    def counts(self):
        return {table: self.query(f"SELECT COUNT(*) FROM {table}")[0][0]
                for table in ("observations", "current_requests", "releases", "publication")}

    def active(self):
        return self.query("SELECT release_id FROM publication WHERE slot='active'")[0][0]

    def test_same_key_update_preserves_original_observation_and_backlog(self):
        a_result = self.publish(self.a, "fixture_a")
        original_capture = self.query("SELECT capture_json FROM observations WHERE snapshot_id='synthetic_a'")
        original_marts = self.query("SELECT marts_json FROM releases WHERE release_id='fixture_a'")
        original_export = (self.exports / "fixture_a" / "fct_backlog.csv").read_bytes()
        old_rowid = self.query("SELECT rowid FROM current_requests WHERE request_id='synthetic_0001'")[0][0]
        b_result = self.publish(self.b, "fixture_b")
        rowid, row_json = self.query("SELECT rowid,row_json FROM current_requests WHERE request_id='synthetic_0001'")[0]
        self.assertEqual(rowid, old_rowid)
        self.assertEqual(json.loads(row_json)["status"], "Closed")
        self.assertEqual(b_result["inserted_count"], 0)
        self.assertEqual(b_result["changed_count"], 1)
        self.assertEqual(self.counts(), dict(observations=2, current_requests=13, releases=2, publication=1))
        self.assertEqual(self.query("SELECT capture_json FROM observations WHERE snapshot_id='synthetic_a'"), original_capture)
        self.assertEqual(self.query("SELECT marts_json FROM releases WHERE release_id='fixture_a'"), original_marts)
        self.assertEqual((self.exports / "fixture_a" / "fct_backlog.csv").read_bytes(), original_export)
        self.assertEqual(a_result["overall"]["observed_backlog"], 6)
        self.assertEqual(b_result["overall"]["observed_backlog"], 5)
        marts_b = json.loads(self.query("SELECT marts_json FROM releases WHERE release_id='fixture_b'")[0][0])
        historical = [row for row in marts_b["fct_backlog"] if row["snapshot_id"] == "synthetic_a"]
        self.assertEqual(sum(row["open_count"] for row in historical), 6)
        self.assertTrue(all(not row["is_release_snapshot"] for row in historical))

    def test_exact_replay_is_idempotent_and_does_not_age_requests(self):
        self.publish(self.a, "fixture_a")
        published = self.publish(self.b, "fixture_b")
        counts = self.counts()
        pointer = (self.state / "published.json").read_bytes()
        case_export = (self.exports / "fixture_b" / "fct_cases.csv").read_bytes()
        replayed = self.publish(deepcopy(self.b), "fixture_b")
        self.assertEqual(replayed["outcome"], "replayed")
        self.assertEqual(replayed["overall"], published["overall"])
        self.assertEqual(replayed["marts_hash"], published["marts_hash"])
        self.assertEqual(self.counts(), counts)
        self.assertEqual((self.state / "published.json").read_bytes(), pointer)
        self.assertEqual((self.exports / "fixture_b" / "fct_cases.csv").read_bytes(), case_export)
        self.assertEqual(self.query("SELECT observed_at FROM observations WHERE snapshot_id='synthetic_b'")[0][0], self.b["manifest"]["observed_at"])

    def test_replay_of_original_release_keeps_newer_active_release(self):
        self.publish(self.a, "fixture_a")
        self.publish(self.b, "fixture_b")
        self.publish(self.a, "fixture_a")
        self.assertEqual(self.active(), "fixture_b")
        current = json.loads(self.query("SELECT row_json FROM current_requests WHERE request_id='synthetic_0001'")[0][0])
        self.assertEqual(current["status"], "Closed")

    def test_older_observation_cannot_be_repromoted_under_new_release_id(self):
        self.publish(self.a, "fixture_a")
        self.publish(self.b, "fixture_b")
        with self.assertRaises(ContractError):
            self.publish(self.a, "fixture_stale")
        self.assertEqual(self.active(), "fixture_b")

    def test_validation_failure_keeps_last_good_release(self):
        self.publish(self.a, "fixture_a")
        before = self.counts()
        with self.assertRaisesRegex(ContractError, "Simulated validation failure"):
            self.publish(self.b, "fixture_failed", "validation")
        self.assertEqual(self.active(), "fixture_a")
        self.assertEqual(self.counts(), before)
        self.assertFalse((self.exports / "fixture_failed").exists())

    def test_publication_failure_rolls_back_merge_and_observation(self):
        self.publish(self.a, "fixture_a")
        before = self.counts()
        pointer = (self.state / "published.json").read_bytes()
        with self.assertRaisesRegex(ContractError, "transaction rolled back"):
            self.publish(self.b, "fixture_failed", "publication")
        self.assertEqual(self.active(), "fixture_a")
        self.assertEqual(self.counts(), before)
        self.assertEqual((self.state / "published.json").read_bytes(), pointer)
        current = json.loads(self.query("SELECT row_json FROM current_requests WHERE request_id='synthetic_0001'")[0][0])
        self.assertEqual(current["status"], "Open")
        failed_audit = json.loads(next((self.state / "audits").glob("fixture_failed_*.json")).read_text())
        self.assertEqual(failed_audit["outcome"], "failed")
        recovered = self.publish(self.b, "fixture_b")
        self.assertEqual(recovered["changed_count"], 1)
        self.assertEqual(self.active(), "fixture_b")

    def test_disappeared_request_blocks_publication_without_inventing_closure(self):
        self.publish(self.a, "fixture_a")
        missing = deepcopy(self.b)
        missing["rows"] = [row for row in missing["rows"] if row["unique_key"] != "synthetic_0001"]
        with self.assertRaisesRegex(ContractError, "disappeared"):
            self.publish(rehash(missing), "fixture_missing")
        current = json.loads(self.query("SELECT row_json FROM current_requests WHERE request_id='synthetic_0001'")[0][0])
        self.assertEqual(current["status"], "Open")
        self.assertEqual(self.active(), "fixture_a")

    def test_changed_content_under_same_snapshot_id_is_rejected(self):
        self.publish(self.a, "fixture_a")
        changed = deepcopy(self.a)
        changed["rows"][0]["borough"] = "BROOKLYN"
        with self.assertRaisesRegex(ContractError, "Snapshot ID already exists"):
            self.publish(rehash(changed), "fixture_changed")
        self.assertEqual(self.active(), "fixture_a")

    def test_changed_observation_time_under_same_snapshot_id_is_rejected(self):
        self.publish(self.a, "fixture_a")
        changed = deepcopy(self.a)
        changed["manifest"]["observed_at"] = changed["manifest"]["extraction_ended_at"] = "2026-11-15T17:00:00+00:00"
        with self.assertRaisesRegex(ContractError, "Snapshot ID already exists"):
            self.publish(changed, "fixture_changed")

    def test_hash_tampering_is_rejected_before_publication(self):
        tampered = deepcopy(self.a)
        tampered["rows"][0]["status"] = "Closed"
        with self.assertRaisesRegex(ContractError, "row hash mismatch"):
            self.publish(tampered, "fixture_tampered")
        self.assertFalse((self.state / "published.json").exists())

    def test_overlapping_target_input_is_rejected(self):
        changed = deepcopy(self.a)
        changed["targets"].append(deepcopy(changed["targets"][0]))
        changed["manifest"]["target_version"] = content_hash(changed["targets"])
        with self.assertRaisesRegex(ContractError, "overlapping"):
            validate_capture(changed)

    def test_malformed_scope_hash_is_rejected(self):
        changed = deepcopy(self.a)
        changed["manifest"]["scope"]["agency"] = "HPD"
        with self.assertRaisesRegex(ContractError, "scope hash mismatch"):
            validate_capture(changed)

    def test_forbidden_source_field_blocks_publication_even_with_matching_hash(self):
        changed = deepcopy(self.a)
        changed["rows"][0]["incident_address"] = "SYNTHETIC REDACTED ADDRESS"
        with self.assertRaisesRegex(ContractError, "privacy allowlist"):
            self.publish(rehash(changed), "fixture_private")
        self.assertFalse((self.state / "published.json").exists())

    def test_real_input_rows_must_match_declared_scope(self):
        real = deepcopy(self.a)
        real["manifest"]["source_kind"] = "real"
        real["rows"] = real["rows"][:2]
        rehash(real)
        validate_capture(real)  # Both baseline rows are within the declared scope.
        for field, value in (("agency", "HPD"), ("complaint_type", "Outside Scope"),
                             ("created_date", "2026-09-06T23:59:59"), ("created_date", "2026-11-16T00:00:00")):
            with self.subTest(field=field, value=value):
                changed = deepcopy(real)
                changed["rows"][0][field] = value
                with self.assertRaises(ContractError):
                    validate_capture(rehash(changed))

    def test_fixture_metrics_cover_boundaries_and_exclusions(self):
        result = self.publish(self.a, "fixture_a")
        marts = json.loads(self.query("SELECT marts_json FROM releases WHERE release_id='fixture_a'")[0][0])
        cases = {row["request_id"]: row for row in marts["fct_cases"]}
        self.assertEqual(result["overall"]["target_numerator"], 3)
        self.assertEqual(result["overall"]["target_denominator"], 5)
        self.assertAlmostEqual(result["overall"]["p90_elapsed_hours"], 43.2)
        self.assertEqual(cases["synthetic_0002"]["elapsed_hours"], 24)
        self.assertEqual(cases["synthetic_0002"]["target_numerator"], 1)
        self.assertEqual(cases["synthetic_0011"]["target_hours"], 48)
        self.assertEqual(cases["synthetic_0011"]["elapsed_hours"], 48)
        self.assertEqual(cases["synthetic_0011"]["target_numerator"], 1)
        self.assertEqual(cases["synthetic_0003"]["target_denominator"], 1)
        self.assertEqual(cases["synthetic_0003"]["target_numerator"], 0)
        self.assertTrue(cases["synthetic_0004"]["is_immature"])
        self.assertTrue(cases["synthetic_0005"]["is_unknown_outcome"])
        self.assertEqual(cases["synthetic_0006"]["borough_key"], "UNKNOWN")
        self.assertEqual(cases["synthetic_0007"]["age_bucket"], "Unknown age")
        self.assertEqual(cases["synthetic_0008"]["temporal_quality"], "ambiguous_created")
        self.assertEqual(cases["synthetic_0009"]["temporal_quality"], "negative_elapsed")
        self.assertTrue(cases["synthetic_0010"]["is_missing_target"])
        self.assertTrue(cases["synthetic_0012"]["is_invalid_outcome"])
        self.assertEqual(cases["synthetic_0013"]["temporal_quality"], "future_closed")


if __name__ == "__main__":
    unittest.main()
