"""Reproduce priority comparisons from the pinned CSV export; no cloud access.

Run: python scripts/analyze_priority_context.py
Uses the Python standard library, independently recomputes ages from UTC instants,
and cross-checks counts against the recorded BigQuery release evidence.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "dsny_20261118"
HOUR_US = 3_600_000_000
OPEN_STATUSES = {"open", "assigned", "in progress", "pending", "started"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.utcoffset() is not None, "Timestamp has no UTC offset")
    return parsed.astimezone(timezone.utc)


def ratio(numerator, denominator):
    require(denominator > 0, "Ratio denominator must be positive")
    return {"numerator": numerator, "denominator": denominator,
            "fraction": numerator / denominator, "percent": numerator / denominator * 100}


def analyze(output):
    export = ROOT / "data/demo_exports" / RELEASE
    paths = {"case_rows": export / "fct_cases.csv", "release_metadata": export / "release_metadata.csv",
             "warehouse_evidence": ROOT / "artifacts/releases" / RELEASE / "bigquery.json",
             "original_capture": ROOT / "data/public/dsny_20261118_a.json.gz",
             "analysis_script": Path(__file__).resolve()}
    rows, metadata = read_csv(paths["case_rows"]), read_csv(paths["release_metadata"])
    warehouse = json.loads(paths["warehouse_evidence"].read_text(encoding="utf-8"))
    require(len(metadata) == 1, "Expected exactly one release metadata row")
    meta = metadata[0]
    require(meta["release_id"] == warehouse["release_id"] == RELEASE, "Release mismatch")
    require(meta["snapshot_id"] == warehouse["snapshot_id"], "Snapshot mismatch")
    require(meta["source_kind"] == warehouse["source_kind"] == "real", "Expected real source")
    require(meta["cohort_start"] == warehouse["scope"]["cohort_start"] == "2026-09-07"
            and meta["cohort_end"] == warehouse["scope"]["cohort_end"] == "2026-11-16", "Cohort mismatch")
    observed = utc(meta["observed_at"])
    require(observed == utc(warehouse["observed_at"]), "Warehouse observation mismatch")
    ids, segments, open_rows = set(), defaultdict(Counter), defaultdict(list)
    ages_checked = 0
    max_age_difference = Decimal(0)
    for row in rows:
        key = (row["agency_key"], row["problem_key"], row["borough_key"])
        require(row["request_id"] not in ids, "Duplicate request key")
        ids.add(row["request_id"])
        require(row["release_id"] == RELEASE and row["snapshot_id"] == meta["snapshot_id"], "Mixed release/snapshot")
        require(utc(row["observed_at"]) == observed, "Mixed observation time")
        require(row["agency_key"] == "DSNY" and row["problem_key"] in warehouse["scope"]["problems"], "Unexpected source segment")
        require(row["created_date"] and meta["cohort_start"] <= row["created_date"] < meta["cohort_end"], "Creation outside pinned cohort")
        status = row["status"].strip().lower()
        status_class = "open" if status in OPEN_STATUSES else "closed" if status == "closed" else "unknown"
        require(row["status_class"] == status_class, "Source status classification differs")
        is_open = status_class == "open" and not row["closed_at"]
        require((row["is_backlog"] == "true") == is_open, "Backlog flag differs from status/closure")
        segments[key]["intake"] += 1
        age_us = None
        if row["created_at"] and utc(row["created_at"]) <= observed:
            delta = observed - utc(row["created_at"])
            age_us = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
            exact_hours = Decimal(age_us) / HOUR_US
            require(row["age_hours"], "Missing exported age for valid instants")
            difference = abs(Decimal(row["age_hours"]) - exact_hours)
            require(difference <= Decimal("0.000001"), "Exported age differs from UTC instant arithmetic")
            max_age_difference = max(max_age_difference, difference)
            ages_checked += 1
        else:
            require(not row["age_hours"], "Unexpected age for missing/future creation instant")
        if is_open:
            segments[key]["observed_open"] += 1
            for days in (7, 14, 30, 42, 60):
                if age_us is not None and age_us >= days * 24 * HOUR_US:
                    segments[key][f"open_at_least_{days}_days"] += 1
            open_rows[key].append((age_us, row))
    require(len(rows) == int(meta["source_count"]) == int(meta["expected_count"]) == 23101, "Capture/export count mismatch")
    overall = Counter()
    for count in segments.values():
        overall.update(count)
    for local, recorded in (("intake", "intake"), ("observed_open", "observed_backlog"),
                            ("open_at_least_7_days", "aged_168h_plus")):
        require(overall[local] == warehouse["overall"][recorded], "Overall CSV/warehouse count mismatch")
    require(len(segments) == len(warehouse["segments"]), "Segment population mismatch")
    for segment in warehouse["segments"]:
        count = segments[("DSNY", segment["problem"], segment["borough"])]
        require((count["intake"], count["observed_open"], count["open_at_least_7_days"])
                == (segment["intake"], segment["observed_backlog"], segment["aged_168h_plus"]), "Segment CSV/warehouse count mismatch")
    queen_key, brooklyn_key = ("DSNY", "Dirty Condition", "QUEENS"), ("DSNY", "Dirty Condition", "BROOKLYN")
    queens, brooklyn = segments[queen_key], segments[brooklyn_key]
    require((queens["intake"], queens["observed_open"], queens["open_at_least_7_days"],
             queens["open_at_least_30_days"], queens["open_at_least_60_days"])
            == (3273, 181, 92, 38, 11), "Pinned Queens headline differs")
    require((brooklyn["intake"], brooklyn["open_at_least_7_days"]) == (5081, 76), "Pinned Brooklyn comparison differs")
    require(queens["open_at_least_7_days"] == max(s["open_at_least_7_days"] for s in segments.values()), "Queens is not the largest aged segment")
    oldest_us, oldest = max(((age, row) for age, row in open_rows[queen_key] if age is not None),
                            key=lambda item: item[0])
    evidence = {
        "outcome": "passed", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "Independent Python standard-library CSV row counts and UTC arithmetic; no new BigQuery execution",
        "release_id": RELEASE, "snapshot_id": meta["snapshot_id"], "source_kind": "real",
        "observed_at": meta["observed_at"], "scope": warehouse["scope"],
        "definitions": {"intake": "Cases created in the pinned NYC-date cohort",
                        "open": "Reviewed source status maps to open and recorded closure instant is absent",
                        "age": "Observation UTC instant minus creation UTC instant; thresholds are inclusive elapsed 24-hour days",
                        "share_denominator": "All selected DSNY categories and boroughs in this single captured cohort, including unknown borough"},
        "sources": {name: {"path": path.relative_to(ROOT).as_posix(), "size_bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in paths.items()},
        "overall": dict(overall), "queens_dirty_condition": dict(queens), "brooklyn_dirty_condition": dict(brooklyn),
        "comparisons": {
            "queens_share_of_7_day_open": ratio(queens["open_at_least_7_days"], overall["open_at_least_7_days"]),
            "queens_share_of_intake": ratio(queens["intake"], overall["intake"]),
            "queens_7_day_share_divided_by_intake_share": (queens["open_at_least_7_days"] / overall["open_at_least_7_days"]) / (queens["intake"] / overall["intake"]),
            "queens_intake_change_relative_to_brooklyn": ratio(queens["intake"] - brooklyn["intake"], brooklyn["intake"]),
            "queens_7_day_open_change_relative_to_brooklyn": ratio(queens["open_at_least_7_days"] - brooklyn["open_at_least_7_days"], brooklyn["open_at_least_7_days"]),
            "queens_share_of_own_open_at_least_7_days": ratio(queens["open_at_least_7_days"], queens["observed_open"]),
            "queens_and_brooklyn_dirty_condition_share_of_7_day_open": ratio(queens["open_at_least_7_days"] + brooklyn["open_at_least_7_days"], overall["open_at_least_7_days"])},
        "oldest_open_queens_dirty_condition": {"request_id": oldest["request_id"], "created_at": oldest["created_at"],
            "status": oldest["status"], "elapsed_hours": oldest_us / HOUR_US, "elapsed_days": oldest_us / (24 * HOUR_US)},
        "assertions": {"unique_request_keys": True, "single_release_snapshot_and_observation": True,
            "source_kind_scope_and_capture_counts_match": True, "backlog_flags_recomputed_from_status_and_closure": True,
            "ages_recomputed_from_utc_instants": True, "ages_checked": ages_checked,
            "maximum_age_difference_hours": float(max_age_difference), "age_tolerance_hours": 0.000001,
            "overall_counts_match_recorded_warehouse": True, "all_segment_counts_match_recorded_warehouse": True,
            "pinned_headline_counts_match": True, "queens_has_largest_7_day_open_count": True},
        "limitations": ["One real observation; no observed backlog trend or causal inference.",
            "Creation timing and case mix are not controlled; relative shares are descriptive, not risk-adjusted.",
            "Recorded open status does not prove service is unfulfilled or establish staffing needs.",
            "These comparisons cover only the pinned cohort, not citywide service demand or backlog."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"outcome": "passed", "output": str(output), "case_rows_checked": len(rows),
                      "queens_counts": dict(queens), "comparisons": evidence["comparisons"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/analysis/priority-context.json")
    analyze(parser.parse_args().output)
