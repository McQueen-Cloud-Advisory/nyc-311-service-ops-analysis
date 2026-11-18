"""Run the labeled synthetic replay/recovery demonstration against local SQLite.

These outputs prove the local reference path only. Cloud and Power BI evidence
must come from their own executed checks, never from this simulation.
"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from .contracts import ContractError, REPO_ROOT, atomic_json, content_hash, file_hash, utc_now
from .release import publish_local
from .source import read_capture


def run_replay_demo(output_path: Path | str):
    fixtures = REPO_ROOT / "data" / "fixtures"
    a_path, b_path = fixtures / "synthetic_a.json", fixtures / "synthetic_b.json"
    a, b = read_capture(a_path), read_capture(b_path)
    with TemporaryDirectory(prefix="nyc311-replay-") as directory:
        state, exports = Path(directory) / "state", Path(directory) / "exports"

        def rows(sql, parameters=()):
            with closing(sqlite3.connect(state / "reference.sqlite")) as connection:
                return connection.execute(sql, parameters).fetchall()

        def counts():
            return {name: rows(f"SELECT COUNT(*) FROM {name}")[0][0]
                    for name in ("observations", "current_requests", "releases", "publication")}

        def active():
            return rows("SELECT release_id FROM publication WHERE slot='active'")[0][0]

        def request():
            rowid, serialized = rows("SELECT rowid,row_json FROM current_requests WHERE request_id='synthetic_0001'")[0]
            value = json.loads(serialized)
            return {"sqlite_rowid": rowid, "request_id": value["request_id"], "status": value["status"],
                    "closed_at": value["closed_at"], "payload_hash": value["payload_hash"]}

        first = publish_local(a, "replay_a", state, exports)
        first_counts, first_request = counts(), request()
        original_capture = rows("SELECT capture_json FROM observations WHERE snapshot_id='synthetic_a'")[0][0]
        original_marts = rows("SELECT marts_json FROM releases WHERE release_id='replay_a'")[0][0]
        original_backlog_export_hash = file_hash(exports / "replay_a" / "fct_backlog.csv")
        failure_results = []
        for failure in ("validation", "publication"):
            before_counts = counts()
            before_current = request()
            before_pointer = (state / "published.json").read_bytes()
            try:
                publish_local(b, "failed_" + failure, state, exports, simulate_failure=failure)
            except ContractError as error:
                detail = str(error)
            else:
                raise AssertionError(f"Expected simulated {failure} failure was not raised")
            failure_results.append({
                "simulated_failure": failure, "expected_error": detail,
                "active_release_after": active(), "row_counts_after": counts(),
                "last_good_preserved": active() == "replay_a" and counts() == before_counts,
                "request_update_rolled_back": request() == before_current,
                "publication_file_unchanged": (state / "published.json").read_bytes() == before_pointer,
            })
        missing = deepcopy(b)
        missing["manifest"]["snapshot_id"] = "synthetic_missing"
        missing["rows"] = missing["rows"][1:]
        missing["manifest"].update(expected_count=len(missing["rows"]), source_count=len(missing["rows"]),
                                    source_count_after=len(missing["rows"]), payload_hash=content_hash(missing["rows"]))
        try:
            publish_local(missing, "failed_missing", state, exports)
        except ContractError as error:
            missing_error = str(error)
        else:
            raise AssertionError("Expected disappearing-request publication failure was not raised")
        missing_proof = {"error": missing_error, "active_release_after": active(),
                         "request_status_after": request()["status"],
                         "absence_did_not_imply_closure": request()["status"] == "Open" and active() == "replay_a"}

        later = publish_local(b, "replay_b", state, exports)
        later_counts, later_request = counts(), request()
        published_b_pointer = (state / "published.json").read_bytes()
        replayed = publish_local(b, "replay_b", state, exports)
        replay_counts = counts()
        historical_capture_preserved = original_capture == rows("SELECT capture_json FROM observations WHERE snapshot_id='synthetic_a'")[0][0]
        historical_release_preserved = original_marts == rows("SELECT marts_json FROM releases WHERE release_id='replay_a'")[0][0]
        historical_export_preserved = original_backlog_export_hash == file_hash(exports / "replay_a" / "fct_backlog.csv")
        later_marts = json.loads(rows("SELECT marts_json FROM releases WHERE release_id='replay_b'")[0][0])
        captured_backlog_counts = {
            snapshot: sum(row["open_count"] for row in later_marts["fct_backlog"] if row["snapshot_id"] == snapshot)
            for snapshot in ("synthetic_a", "synthetic_b")
        }
        old_replay = publish_local(a, "replay_a", state, exports)
        checks = {
            "same_request_key_and_physical_current_row": first_request["request_id"] == later_request["request_id"] and first_request["sqlite_rowid"] == later_request["sqlite_rowid"],
            "old_open_became_closed": first_request["status"] == "Open" and later_request["status"] == "Closed",
            "later_input_changed_one_current_row": later["inserted_count"] == 0 and later["changed_count"] == 1,
            "original_capture_unchanged": historical_capture_preserved,
            "original_release_unchanged": historical_release_preserved,
            "original_backlog_export_unchanged": historical_export_preserved,
            "later_backlog_changed_original_did_not": captured_backlog_counts == {"synthetic_a": 6, "synthetic_b": 5},
            "replay_row_counts_identical": later_counts == replay_counts,
            "replay_metrics_identical": later["overall"] == replayed["overall"],
            "replay_marts_hash_identical": later["marts_hash"] == replayed["marts_hash"],
            "replay_observation_time_unchanged": rows("SELECT observed_at FROM observations WHERE snapshot_id='synthetic_b'")[0][0] == b["manifest"]["observed_at"],
            "older_exact_replay_kept_newer_active_release": old_replay["outcome"] == "replayed" and active() == "replay_b" and (state / "published.json").read_bytes() == published_b_pointer,
            "failed_validation_kept_last_good": all(failure_results[0][key] for key in ("last_good_preserved", "request_update_rolled_back", "publication_file_unchanged")),
            "failed_publication_rolled_back": all(failure_results[1][key] for key in ("last_good_preserved", "request_update_rolled_back", "publication_file_unchanged")),
            "disappearing_request_did_not_imply_closure": missing_proof["absence_did_not_imply_closure"],
        }
        result = {
            "generated_at_utc": utc_now(), "source_kind": "synthetic",
            "verification_engine": "SQLite persistence + Python reference; not BigQuery or Power BI",
            "description": "Fabricated lifecycle, idempotent replay, failed validation, transactional rollback, and disappearance evidence.",
            "fixture_files": {"a": "data/fixtures/synthetic_a.json", "b": "data/fixtures/synthetic_b.json"},
            "fixture_file_hashes": {"a": file_hash(a_path), "b": file_hash(b_path)},
            "observed_at": {"a": a["manifest"]["observed_at"], "b": b["manifest"]["observed_at"]},
            "first_publish": first, "later_publish": later, "later_replay": replayed,
            "current_request_before": first_request, "current_request_after": later_request,
            "row_counts": {"after_a": first_counts, "after_b": later_counts, "after_replay_b": replay_counts},
            "backlog_by_captured_snapshot": captured_backlog_counts,
            "failure_recovery": failure_results, "disappearance": missing_proof,
            "checks": checks, "passed_checks": sum(checks.values()), "total_checks": len(checks),
            "outcome": "pass" if all(checks.values()) else "fail",
        }
    atomic_json(Path(output_path), result)
    if result["outcome"] != "pass":
        raise AssertionError("Replay proof failed; inspect the written evidence")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/replay/local-replay.json"))
    arguments = parser.parse_args()
    proof = run_replay_demo(arguments.output)
    print(json.dumps({"outcome": proof["outcome"], "passed_checks": proof["passed_checks"], "total_checks": proof["total_checks"], "output": str(arguments.output)}))
