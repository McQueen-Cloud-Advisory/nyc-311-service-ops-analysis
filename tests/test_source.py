"""No-network contract tests for bounded source observations and captured input."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from nyc311.contracts import ContractError, REPO_ROOT, SOURCE_FIELDS, SOURCE_TYPES, load_config
from nyc311.source import BASE_URL, Socrata, read_capture, write_capture
from nyc311.targets import load_csv


def row(key):
    return dict(unique_key=key, created_date="2026-10-01T12:00:00", closed_date=None,
                agency="DSNY", complaint_type="Dirty Condition", status="Open",
                borough="QUEENS", open_data_channel_type="ONLINE")


class SourcePaginationTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(REPO_ROOT / "config/demo.json")
        self.config.update(page_size=2, maximum_rows=10)
        self.client = Socrata(self.config, sleep=Mock())
        self.client.metadata = Mock(return_value={"id": "erm2-nwe9", "rows_updated_at": 1})
        self.targets, self.target_version = load_csv(REPO_ROOT / "data/targets/demo_targets.csv")

    def capture(self):
        return self.client.capture("source_test", self.targets, self.target_version)

    def test_keyset_pagination_has_stable_order_and_no_private_fields(self):
        self.client.query = Mock(side_effect=[
            [{"request_count": "3"}], [row("001"), row("002")], [row("003")], [], [{"request_count": "3"}],
        ])
        capture = self.capture()
        self.assertEqual([value["unique_key"] for value in capture["rows"]], ["001", "002", "003"])
        queries = [call.args[0] for call in self.client.query.call_args_list]
        page_queries = queries[1:-1]
        self.assertTrue(all("ORDER BY unique_key ASC LIMIT 2" in query for query in page_queries))
        self.assertNotIn("unique_key >", page_queries[0])
        self.assertIn("unique_key > '002'", page_queries[1])
        self.assertIn("unique_key > '003'", page_queries[2])
        self.assertTrue(all("OFFSET" not in query for query in queries))
        self.assertTrue(all("incident_address" not in query and "latitude" not in query for query in queries))
        self.assertTrue(all(set(value) == set(SOURCE_FIELDS) for value in capture["rows"]))
        self.assertEqual(capture["manifest"]["expected_count"], 3)
        self.assertEqual(capture["manifest"]["source_count_after"], 3)
        self.assertEqual(self.client.metadata.call_count, 2)

    def test_download_count_mismatch_fails_observation(self):
        self.client.query = Mock(side_effect=[[{"request_count": "3"}], [row("001")], [], [{"request_count": "3"}]])
        with self.assertRaisesRegex(ContractError, "Incomplete or changing extract"):
            self.capture()

    def test_source_count_change_fails_observation(self):
        self.client.query = Mock(side_effect=[[{"request_count": "1"}], [row("001")], [], [{"request_count": "2"}]])
        with self.assertRaisesRegex(ContractError, "Incomplete or changing extract"):
            self.capture()

    def test_metadata_change_fails_observation(self):
        self.client.metadata = Mock(side_effect=[{"rows_updated_at": 1}, {"rows_updated_at": 2}])
        self.client.query = Mock(side_effect=[[{"request_count": "1"}], [row("001")], [], [{"request_count": "1"}]])
        with self.assertRaisesRegex(ContractError, "metadata changed"):
            self.capture()

    def test_duplicate_or_reordered_keys_fail_observation(self):
        for values in ([row("001"), row("001")], [row("002"), row("001")]):
            with self.subTest(keys=[value["unique_key"] for value in values]):
                self.client.query = Mock(side_effect=[[{"request_count": "2"}], values])
                with self.assertRaisesRegex(ContractError, "duplicate, or out-of-order"):
                    self.capture()

    def test_unrequested_source_field_fails_before_capture_persistence(self):
        unexpected = row("001") | {"incident_address": "SYNTHETIC ADDRESS MUST NEVER BE CAPTURED"}
        self.client.query = Mock(side_effect=[[{"request_count": "1"}], [unexpected]])
        with self.assertRaisesRegex(ContractError, "unrequested column"):
            self.capture()

    def test_initial_count_beyond_bound_stops_before_paging(self):
        self.client.query = Mock(return_value=[{"request_count": "11"}])
        with self.assertRaisesRegex(ContractError, "exceeds maximum_rows"):
            self.capture()
        self.assertEqual(self.client.query.call_count, 1)


class SourceTransportTests(unittest.TestCase):
    def client(self, effects, attempts=3):
        client = Socrata({"maximum_attempts": attempts}, sleep=Mock())
        client.opener.open = Mock(side_effect=effects)
        return client

    @staticmethod
    def response(body=b"[]"):
        response = io.BytesIO(body)
        response.url = BASE_URL + "/resource/erm2-nwe9.json"
        return response

    def test_transient_http_error_retries_with_backoff(self):
        error = HTTPError(BASE_URL, 429, "Too many requests", {}, None)
        client = self.client([error, self.response()])
        self.assertEqual(client.get("/resource/erm2-nwe9.json"), [])
        self.assertEqual(client.opener.open.call_count, 2)
        self.assertEqual(client.sleep.call_count, 1)
        self.assertGreaterEqual(client.sleep.call_args.args[0], 1)
        self.assertLess(client.sleep.call_args.args[0], 2)

    def test_non_transient_error_fails_without_retry_or_sensitive_body(self):
        error = HTTPError(BASE_URL, 403, "SENSITIVE RESPONSE DETAIL", {}, None)
        client = self.client([error])
        with self.assertRaisesRegex(ContractError, "Source HTTP 403; response body omitted") as raised:
            client.get("/resource/erm2-nwe9.json")
        self.assertNotIn("SENSITIVE", str(raised.exception))
        self.assertEqual(client.opener.open.call_count, 1)
        client.sleep.assert_not_called()

    def test_connection_retry_exhaustion_is_bounded(self):
        client = self.client([URLError("SENSITIVE HOST DETAIL")] * 3)
        with self.assertRaisesRegex(ContractError, "connection failed after bounded retries") as raised:
            client.get("/resource/erm2-nwe9.json")
        self.assertNotIn("SENSITIVE", str(raised.exception))
        self.assertEqual(client.opener.open.call_count, 3)
        self.assertEqual(client.sleep.call_count, 2)

    def test_schema_drift_fails_before_row_download(self):
        client = Socrata({})
        columns = [{"fieldName": field, "dataTypeName": kind, "name": field} for field, kind in SOURCE_TYPES.items()]
        columns[0]["dataTypeName"] = "number"
        client.get = Mock(return_value={"id": "erm2-nwe9", "name": "Synthetic schema response", "columns": columns})
        with self.assertRaisesRegex(ContractError, "Source schema drift"):
            client.metadata()


class CapturedInputTests(unittest.TestCase):
    def test_capture_file_cannot_be_overwritten(self):
        capture = read_capture(REPO_ROOT / "data/fixtures/synthetic_a.json")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observation.json.gz"
            write_capture(path, capture)
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_capture(path, capture)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(read_capture(path), capture)

    def test_payload_tampering_is_detected_when_reading(self):
        capture = read_capture(REPO_ROOT / "data/fixtures/synthetic_a.json")
        changed = deepcopy(capture)
        changed["rows"][0]["status"] = "Closed"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "payload hash mismatch"):
                read_capture(path)


if __name__ == "__main__":
    unittest.main()
