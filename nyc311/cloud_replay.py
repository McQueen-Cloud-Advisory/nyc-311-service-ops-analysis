"""Execute a labeled synthetic replay proof in the dedicated BigQuery project.

This opt-in command performs real cloud writes and dbt builds. It holds the same
operator lock as the normal CLI and restores the previously active real release.
It never runs during local validation and does not obtain or change user login.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import cloud
from .contracts import ContractError, REPO_ROOT, atomic_json, content_hash, file_hash, operator_lock, utc_now
from .release import input_identity
from .source import read_capture

RELEASE_A = "cloud_replay_a"
RELEASE_B = "cloud_replay_b"
FAILED_RELEASE = "cloud_replay_failed_validation"
OWNED_RELEASES = (RELEASE_A, RELEASE_B, FAILED_RELEASE)


class RecordedQueries:
    """Retain actual verification SQL, parameters, output rows and job metadata."""

    def __init__(self, warehouse, evidence):
        self.warehouse = warehouse
        self.evidence = evidence

    def run(self, name, sql, parameters=None):
        parameters = parameters or {}
        record = {"name": name, "sql": sql, "parameters": parameters,
                  "use_query_cache": False, "outcome": "running"}
        self.evidence["queries"].append(record)
        jobs_before = len(self.warehouse.jobs)
        try:
            rows = self.warehouse.query(sql, [self.warehouse.param(key, value) for key, value in parameters.items()], cache=False)
            record.update(outcome="completed", output_rows=rows)
            return rows
        except Exception as error:
            record.update(outcome="failed", error_type=type(error).__name__)
            raise
        finally:
            record["jobs"] = self.warehouse.jobs[jobs_before:]

    def active(self, name):
        warehouse = self.warehouse
        return self.run(name, f"""SELECT p.slot,p.release_id,r.snapshot_id,r.input_hash,r.marts_hash,o.source_kind
FROM `{warehouse.table('control', 'publication')}` p
LEFT JOIN `{warehouse.table('control', 'releases')}` r ON r.release_id=p.release_id
LEFT JOIN `{warehouse.table('raw', 'observations')}` o ON o.snapshot_id=r.snapshot_id
WHERE p.slot='active'""")


def restore_original_release(queries, original):
    """Compare-and-swap only a pointer owned by this proof; never overwrite drift."""
    current = queries.active("active_before_restoration")
    if current == [original]:
        return {"outcome": "already_original", "restored": True, "release_id": original["release_id"]}
    if len(current) != 1 or current[0]["release_id"] not in OWNED_RELEASES:
        raise ContractError("Active release changed outside this proof; restoration refused without changing that pointer")
    warehouse = queries.warehouse
    queries.run("restore_original_active_release", f"""BEGIN TRANSACTION;
ASSERT (SELECT COUNT(*) FROM `{warehouse.table('control', 'publication')}` WHERE slot='active')=1 AS 'Active pointer is not singular';
ASSERT (SELECT COUNT(*) FROM `{warehouse.table('control', 'publication')}` WHERE slot='active' AND release_id=@owned)=1 AS 'Active pointer changed before restoration';
ASSERT (SELECT COUNT(*) FROM `{warehouse.table('control', 'releases')}`
  WHERE release_id=@original AND snapshot_id=@snapshot AND input_hash=@input_hash AND marts_hash=@marts_hash)=1 AS 'Original release identity changed';
UPDATE `{warehouse.table('control', 'publication')}` SET release_id=@original WHERE slot='active' AND release_id=@owned;
COMMIT TRANSACTION;""", {"owned": current[0]["release_id"], "original": original["release_id"],
                       "snapshot": original["snapshot_id"], "input_hash": original["input_hash"], "marts_hash": original["marts_hash"]})
    restored = queries.active("active_after_restoration")
    if restored != [original]:
        raise ContractError("Original real release restoration could not be verified")
    return {"outcome": "restored", "restored": True, "release_id": original["release_id"]}


def run_cloud_replay(config_path: Path | str, output_path: Path | str = REPO_ROOT / "artifacts/replay/bigquery-replay.json"):
    """Run A, B, exact B replay and one injected validation-gate failure.

    This first-run transition proof requires its fixture scope to be unused.
    Existing proof observations are never deleted or reset to manufacture a new
    transition. Published releases can be replayed individually via `nyc311 run`.
    """
    config_path, output_path = Path(config_path), Path(output_path)
    if output_path.exists():
        raise ContractError("Existing replay evidence is retained; choose a new --output path for another attempt")
    config = cloud.config_cloud(config_path)
    paths = {key: REPO_ROOT / "data/fixtures" / ("synthetic_" + key + ".json") for key in ("a", "b")}
    captures = {key: read_capture(path) for key, path in paths.items()}
    a, b = captures["a"], captures["b"]
    if a["manifest"]["source_kind"] != "synthetic" or b["manifest"]["source_kind"] != "synthetic":
        raise ContractError("Cloud replay proof only accepts the explicitly synthetic fixtures")
    if a["manifest"]["scope_hash"] != b["manifest"]["scope_hash"]:
        raise ContractError("Replay fixtures must share one source scope")
    state_dir = REPO_ROOT / ".local"
    work_state, exports = state_dir / "cloud_replay", state_dir / "cloud_replay_exports"
    evidence = {"started_at_utc": utc_now(), "source_kind": "synthetic", "engine": "Executed BigQuery SQL and dbt; no DAX proof",
                "description": "Fabricated lifecycle evidence, not historical NYC service-performance evidence.",
                "outcome": "running", "queries": [], "checks": {}, "runs": {},
                "fixture_files": {key: str(path.relative_to(REPO_ROOT)).replace('\\', '/') for key, path in paths.items()},
                "fixture_file_hashes": {key: file_hash(path) for key, path in paths.items()},
                "captured_observed_at": {key: capture["manifest"]["observed_at"] for key, capture in captures.items()},
                "failure_injection": "Intentional application validation gate after a real dbt build; not a naturally failing dbt SQL test.",
                "row_count_scope": "Only this synthetic source kind/scope and proof release IDs; run audit rows intentionally grow on replay.",
                "restoration": {"outcome": "not_started", "restored": False}}
    original, queries, operation_error = None, None, None

    # This lock is deliberately the same .local/operator.lock used by normal runs.
    with operator_lock(state_dir):
        if output_path.exists():
            raise ContractError("Another operation created the replay evidence; it was not overwritten")
        try:
            warehouse = cloud.Warehouse(config)
            queries = RecordedQueries(warehouse, evidence)
            original_rows = queries.active("original_active_release")
            if len(original_rows) != 1 or original_rows[0]["source_kind"] != "real":
                raise ContractError("Publish and verify one real release before running the synthetic cloud proof")
            original = original_rows[0]
            evidence["original_active_release"] = original
            # Persist the restoration target before the first mutation. An OS or
            # process crash cannot execute finally, so this is the recovery ledger.
            atomic_json(output_path, evidence)
            scope = {"scope": a["manifest"]["scope_hash"], "kind": "synthetic"}
            existing = queries.run("unused_proof_scope", f"""SELECT
  (SELECT COUNT(*) FROM `{warehouse.table('raw', 'observations')}` WHERE scope_hash=@scope AND source_kind=@kind) AS observation_count,
  (SELECT COUNT(*) FROM `{warehouse.table('raw', 'requests_current')}` WHERE scope_hash=@scope AND source_kind=@kind) AS current_count,
  (SELECT COUNT(*) FROM `{warehouse.table('control', 'releases')}` WHERE release_id IN (@a,@b,@failed)) AS release_count""",
                dict(scope, a=RELEASE_A, b=RELEASE_B, failed=FAILED_RELEASE))[0]
            if any(existing.values()):
                raise ContractError("Proof scope already contains observations or releases; retain prior evidence and use ordinary exact-release replay instead of resetting history")

            def check(name, passed):
                evidence["checks"][name] = bool(passed)
                atomic_json(output_path, evidence)
                if not passed:
                    raise ContractError("Cloud replay verification failed: " + name)

            def current(label):
                return queries.run(label, f"SELECT * FROM `{warehouse.table('raw', 'requests_current')}` WHERE scope_hash=@scope AND source_kind=@kind ORDER BY request_id", scope)

            def raw_a(label):
                return queries.run(label, f"""SELECT r.* FROM `{warehouse.table('raw', 'observation_requests')}` r
JOIN `{warehouse.table('raw', 'observations')}` o USING(snapshot_id)
WHERE o.scope_hash=@scope AND o.source_kind=@kind AND r.snapshot_id=@snapshot ORDER BY r.request_id""",
                                   dict(scope, snapshot=a["manifest"]["snapshot_id"]))

            def counts(label):
                return queries.run(label, f"""SELECT
  (SELECT COUNT(*) FROM `{warehouse.table('raw', 'observations')}` WHERE scope_hash=@scope AND source_kind=@kind) AS observations,
  (SELECT COUNT(*) FROM `{warehouse.table('raw', 'observation_requests')}` r JOIN `{warehouse.table('raw', 'observations')}` o USING(snapshot_id) WHERE o.scope_hash=@scope AND o.source_kind=@kind) AS captured_rows,
  (SELECT COUNT(*) FROM `{warehouse.table('raw', 'requests_current')}` WHERE scope_hash=@scope AND source_kind=@kind) AS current_rows,
  (SELECT COUNT(DISTINCT request_id) FROM `{warehouse.table('raw', 'requests_current')}` WHERE scope_hash=@scope AND source_kind=@kind) AS current_unique_keys,
  (SELECT COUNT(*) FROM `{warehouse.table('control', 'releases')}` WHERE release_id IN (@a,@b,@failed)) AS registered_releases""",
                    dict(scope, a=RELEASE_A, b=RELEASE_B, failed=FAILED_RELEASE))[0]

            def reported(label, model, release_id):
                order = "request_id" if model == "fct_cases" else "snapshot_id,agency_key,problem_key,borough_key"
                return queries.run(label, f"SELECT * FROM `{warehouse.table('reporting', model + '__r_' + release_id)}` ORDER BY {order}")

            def summary(label, release_id):
                return queries.run(label, f"""WITH cases AS (SELECT * FROM `{warehouse.table('reporting', 'fct_cases__r_' + release_id)}`)
SELECT COUNT(*) AS case_count,COUNTIF(created_date IS NOT NULL) AS intake,
  COUNTIF(is_recorded_closure) AS recorded_closures,COUNTIF(is_backlog) AS observed_backlog,
  SUM(target_numerator) AS target_numerator,SUM(target_denominator) AS target_denominator,
  SAFE_DIVIDE(SUM(target_numerator),SUM(target_denominator)) AS within_demo_target,
  COUNTIF(is_p90_eligible) AS p90_eligible_count,
  (SELECT ANY_VALUE(p90) FROM (SELECT PERCENTILE_CONT(elapsed_hours,0.9) OVER() AS p90 FROM cases WHERE is_p90_eligible)) AS p90_elapsed_hours
FROM cases""")[0]

            def publish(key, capture_key, release_id, failure=None):
                evidence["current_phase"] = key
                atomic_json(output_path, evidence)
                print(json.dumps({"cloud_replay_phase": key, "release_id": release_id}), flush=True)
                result = cloud.publish_cloud(captures[capture_key], paths[capture_key], release_id, config_path, work_state, exports, failure)
                evidence["runs"][key] = result
                atomic_json(output_path, evidence)
                return result

            publish("a", "a", RELEASE_A)
            current_a, captured_a = current("current_after_a"), raw_a("captured_a_before_b")
            facts_a = reported("reporting_facts_a_before_b", "fct_cases", RELEASE_A)
            backlog_a = reported("reporting_backlog_a_before_b", "fct_backlog", RELEASE_A)
            counts_a, metrics_a = counts("counts_after_a"), summary("metrics_after_a", RELEASE_A)
            original_a = next(row for row in current_a if row["request_id"] == "synthetic_0001")
            check("a_has_thirteen_unique_current_keys", counts_a["current_rows"] == counts_a["current_unique_keys"] == 13)
            check("a_records_old_open_request", original_a["status"] == "Open" and original_a["closed_at"] is None)
            check("a_has_six_open_and_three_recorded_closures", metrics_a["observed_backlog"] == 6 and metrics_a["recorded_closures"] == 3)

            publish("b", "b", RELEASE_B)
            current_b, counts_b = current("current_after_b"), counts("counts_after_b")
            facts_b = reported("reporting_facts_b_before_replay", "fct_cases", RELEASE_B)
            backlog_b = reported("reporting_backlog_b_before_replay", "fct_backlog", RELEASE_B)
            metrics_b = summary("metrics_after_b", RELEASE_B)
            later_b = next(row for row in current_b if row["request_id"] == "synthetic_0001")
            check("same_request_key_is_closed_in_b", original_a["request_id"] == later_b["request_id"] and later_b["status"] == "Closed" and later_b["closed_at"] is not None)
            check("current_key_count_did_not_increase", counts_b["current_rows"] == counts_b["current_unique_keys"] == counts_a["current_rows"])
            by_key_a = {row["request_id"]: row["payload_hash"] for row in current_a}
            by_key_b = {row["request_id"]: row["payload_hash"] for row in current_b}
            check("only_one_current_payload_changed", set(by_key_a) == set(by_key_b) and sum(by_key_a[key] != by_key_b[key] for key in by_key_a) == 1)
            check("original_captured_a_rows_unchanged", captured_a == raw_a("captured_a_after_b"))
            check("original_a_reporting_facts_unchanged", facts_a == reported("reporting_facts_a_after_b", "fct_cases", RELEASE_A))
            check("original_a_backlog_unchanged", backlog_a == reported("reporting_backlog_a_after_b", "fct_backlog", RELEASE_A))
            backlog_by_snapshot = {snapshot: sum(row["open_count"] for row in backlog_b if row["snapshot_id"] == snapshot)
                                   for snapshot in (a["manifest"]["snapshot_id"], b["manifest"]["snapshot_id"])}
            check("b_preserves_original_backlog_six_and_records_later_five", backlog_by_snapshot == {"synthetic_a": 6, "synthetic_b": 5})
            check("b_has_five_open_and_four_recorded_closures", metrics_b["observed_backlog"] == 5 and metrics_b["recorded_closures"] == 4)

            result_replay = publish("replayed_b", "b", RELEASE_B)
            check("exact_b_replay_path_used", result_replay["outcome"] == "replayed")
            check("exact_replay_row_counts_unchanged", counts_b == counts("counts_after_exact_b_replay"))
            check("exact_replay_current_rows_unchanged", current_b == current("current_after_exact_b_replay"))
            check("exact_replay_metrics_unchanged", metrics_b == summary("metrics_after_exact_b_replay", RELEASE_B))
            check("exact_replay_case_and_backlog_rows_unchanged", facts_b == reported("reporting_facts_b_after_replay", "fct_cases", RELEASE_B)
                  and backlog_b == reported("reporting_backlog_b_after_replay", "fct_backlog", RELEASE_B))
            check("exact_replay_marts_hash_unchanged", evidence["runs"]["b"]["marts_hash"] == result_replay["marts_hash"])

            try:
                publish("injected_validation_failure", "b", FAILED_RELEASE, "validation")
            except ContractError as error:
                if str(error) != "Simulated failed cloud validation; previous release retained":
                    raise
                evidence["runs"]["injected_validation_failure"] = {"outcome": "expected_application_gate_error_observed", "error_type": type(error).__name__, "error_detail": str(error)}
            else:
                raise ContractError("Expected injected validation error was not observed")
            active_after_failure = queries.active("active_after_injected_validation_failure")
            check("failed_validation_kept_last_good_b_active", len(active_after_failure) == 1 and active_after_failure[0]["release_id"] == RELEASE_B)
            check("failed_validation_registered_no_new_release", counts_b == counts("counts_after_injected_validation_failure"))
            check("failed_validation_kept_current_rows", current_b == current("current_after_injected_validation_failure"))
            check("failed_validation_kept_old_a_facts_and_backlog", facts_a == reported("reporting_facts_a_after_failure", "fct_cases", RELEASE_A)
                  and backlog_a == reported("reporting_backlog_a_after_failure", "fct_backlog", RELEASE_A))
            check("failed_validation_kept_last_good_b_facts_and_backlog", facts_b == reported("reporting_facts_b_after_failure", "fct_cases", RELEASE_B)
                  and backlog_b == reported("reporting_backlog_b_after_failure", "fct_backlog", RELEASE_B))
            observations = queries.run("immutable_observation_identity", f"""SELECT snapshot_id,observed_at,input_hash,source_kind,scope_hash
FROM `{warehouse.table('raw', 'observations')}` WHERE scope_hash=@scope AND source_kind=@kind ORDER BY snapshot_id""", scope)
            check("original_input_hashes_and_observation_times_unchanged", len(observations) == 2 and all(
                next(row for row in observations if row["snapshot_id"] == capture["manifest"]["snapshot_id"])["input_hash"] == input_identity(capture)
                and next(row for row in observations if row["snapshot_id"] == capture["manifest"]["snapshot_id"])["observed_at"] == capture["manifest"]["observed_at"]
                for capture in captures.values()))
            audit = queries.run("failed_validation_actual_cloud_audit", f"""SELECT release_id,recorded_at,
JSON_VALUE(audit_json,'$.outcome') AS outcome,JSON_VALUE(audit_json,'$.phase') AS phase,
JSON_VALUE(audit_json,'$.cloud_release_committed') AS cloud_release_committed,
JSON_VALUE(audit_json,'$.error_type') AS error_type,JSON_VALUE(audit_json,'$.error_detail') AS error_detail
FROM `{warehouse.table('control', 'run_audits')}` WHERE release_id=@failed ORDER BY recorded_at DESC LIMIT 1""", {"failed": FAILED_RELEASE})
            check("injected_gate_failure_recorded_in_cloud_audit", len(audit) == 1 and audit[0]["outcome"] == "failed"
                  and audit[0]["phase"] == "building_and_testing" and audit[0]["cloud_release_committed"] == "false")
            evidence.update(row_counts={"after_a": counts_a, "after_b": counts_b}, metrics={"a": metrics_a, "b": metrics_b},
                            backlog_by_captured_snapshot=backlog_by_snapshot,
                            original_a_hashes={"captured_rows": content_hash(captured_a), "reporting_cases": content_hash(facts_a), "reporting_backlog": content_hash(backlog_a)})
        except Exception as error:
            operation_error = error
            evidence["error"] = {"type": type(error).__name__, "detail": str(error) if isinstance(error, ContractError) else "Cloud proof failed; inspect private logs without credential tracing"}
        finally:
            if original is not None and queries is not None:
                try:
                    evidence["restoration"] = restore_original_release(queries, original)
                except Exception as error:
                    evidence["restoration"] = {"outcome": "failed_or_refused", "restored": False, "error_type": type(error).__name__,
                                               "detail": str(error) if isinstance(error, ContractError) else "Restoration could not be verified; inspect active release before another run"}
                    operation_error = operation_error or error
            evidence.update(ended_at_utc=utc_now(), passed_checks=sum(evidence["checks"].values()), total_checks=len(evidence["checks"]))
            evidence["outcome"] = "pass" if operation_error is None and evidence["restoration"]["restored"] else "fail"
            atomic_json(output_path, evidence)
        if operation_error is not None:
            raise ContractError("Cloud replay proof did not complete; inspect its evidence and restoration result") from operation_error
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/replay/bigquery-replay.json"))
    args = parser.parse_args(argv)
    try:
        result = run_cloud_replay(args.cloud_config, args.output)
    except ContractError as error:
        print(str(error))
        return 2
    print(json.dumps({"outcome": result["outcome"], "passed_checks": result["passed_checks"], "total_checks": result["total_checks"],
                      "restoration": result["restoration"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
