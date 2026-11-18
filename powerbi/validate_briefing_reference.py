"""Reproduce expected briefing helper values from the saved release exports.

These are independent Python reference calculations, not Power BI execution.
The saved output supports subsequent DAX reconciliation after Desktop refresh.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGE_BUCKETS = {
    "Under 24h": "Under 24 hours",
    "24–72h": "24 to under 72 hours",
    "72–168h": "72 to under 168 hours",
    "168h+": "168 hours or more",
    "Unknown age": "Unknown age",
}
KEYS = ("agency_key", "problem_key", "borough_key")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def selected(row: dict[str, str], filters: dict[str, str]) -> bool:
    return all(row[key] == value for key, value in filters.items())


def truth(value: str) -> bool:
    return value.lower() == "true"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-id", default="dsny_20261118")
    parser.add_argument("--export-root", type=Path, default=ROOT / "data/demo_exports")
    parser.add_argument("--output", type=Path, default=ROOT / "powerbi/briefing-reference.json")
    args = parser.parse_args()
    source = args.export_root / args.release_id
    inputs = {name: source / f"{name}.csv" for name in ("release_metadata", "fct_cases", "fct_backlog", "dim_date")}
    metadata_rows = read_csv(inputs["release_metadata"])
    if len(metadata_rows) != 1:
        raise ValueError("Expected exactly one release metadata row")
    metadata = metadata_rows[0]
    if metadata["release_id"] != args.release_id:
        raise ValueError("Reference release mismatch")
    cases = read_csv(inputs["fct_cases"])
    backlog = [r for r in read_csv(inputs["fct_backlog"])
               if truth(r["is_release_snapshot"]) and r["snapshot_id"] == metadata["snapshot_id"]]
    dates = {date.fromisoformat(r["date_key"]) for r in read_csv(inputs["dim_date"])}
    for rows in (cases, backlog):
        if any(row["release_id"] != args.release_id for row in rows):
            raise ValueError("Mixed release in reference input")
    if len(cases) != int(metadata["source_count"]):
        raise ValueError("Case reference is incomplete")
    cohort_start = date.fromisoformat(metadata["cohort_start"])
    cohort_end = date.fromisoformat(metadata["cohort_end"])
    scenarios = [
        ("overall", {}, None),
        ("brooklyn_dirty", {"agency_key": "DSNY", "problem_key": "Dirty Condition", "borough_key": "BROOKLYN"}, None),
        ("queens_dirty", {"agency_key": "DSNY", "problem_key": "Dirty Condition", "borough_key": "QUEENS"}, None),
        ("empty_borough", {"borough_key": "__NO_SUCH_BOROUGH__"}, None),
        ("activity_week_2026_11_09", {}, (date(2026, 11, 9), date(2026, 11, 16))),
    ]
    results = []
    for name, filters, activity in scenarios:
        selected_dates = {d for d in dates if activity is None or activity[0] <= d < activity[1]}
        segment_cases = [row for row in cases if selected(row, filters)]
        activity_cases = [row for row in segment_cases
                          if row["created_date"] and date.fromisoformat(row["created_date"]) in selected_dates]
        segment_backlog = [row for row in backlog if selected(row, filters)]
        # Snapshot priorities intentionally do not depend on the activity date.
        ranking = sorted((row for row in segment_backlog if int(row["age_168h_plus_count"]) > 0), key=lambda row: (
            -int(row["age_168h_plus_count"]), -int(row["open_count"]),
            *(row[key] for key in KEYS),
        ))
        priority = ranking[0] if ranking else None
        total_aged = sum(int(row["age_168h_plus_count"]) for row in segment_backlog)
        total_open = sum(int(row["open_count"]) for row in segment_backlog)
        weeks = []
        for week in sorted(d for d in selected_dates if d.weekday() == 0):
            week_end = week + timedelta(days=7)
            if week < cohort_start or week_end > cohort_end:
                continue
            if not all(week + timedelta(days=offset) in selected_dates for offset in range(7)):
                continue
            weeks.append({
                "week_start": week.isoformat(),
                "intake": sum(bool(row["created_date"]) and week <= date.fromisoformat(row["created_date"]) < week_end for row in segment_cases),
                "recorded_closures": sum(truth(row["is_recorded_closure"]) and bool(row["closed_date"])
                                         and week <= date.fromisoformat(row["closed_date"]) < week_end for row in segment_cases),
            })
        aged = int(priority["age_168h_plus_count"]) if priority else None
        opened = int(priority["open_count"]) if priority else None
        target_met = sum(int(row["target_numerator"]) for row in activity_cases)
        target_eligible = sum(int(row["target_denominator"]) for row in activity_cases)
        all_open_rows = [row for row in segment_cases if truth(row["is_backlog"])]
        detail_open_rows = [row for row in activity_cases if truth(row["is_backlog"])]
        base_detail_rows = [row for row in activity_cases
                            if row["snapshot_id"] == metadata["snapshot_id"]
                            and (truth(row["is_backlog"]) or int(row["target_denominator"]) == 1)]
        open_age_hours = [float(row["age_hours"]) for row in all_open_rows if row["age_hours"]]
        output = {
            "scenario": name, "filters": filters,
            "activity_start": activity[0].isoformat() if activity else None,
            "activity_end_exclusive": activity[1].isoformat() if activity else None,
            "priority_agency": priority["agency_key"] if priority else None,
            "priority_problem": priority["problem_key"] if priority else None,
            "priority_borough": priority["borough_key"] if priority else None,
            "priority_label": " / ".join(priority[key] for key in KEYS) if priority else None,
            "priority_aged_count": aged,
            "priority_open_count": opened,
            "priority_aged_display": f"{aged:,}" if aged is not None else "—",
            "priority_aged_share": aged / total_aged if total_aged else None,
            "priority_within_segment_aged_rate": aged / opened if opened else None,
            "selected_aged_count": total_aged,
            "selected_open_count": total_open,
            "snapshot_open_30d_plus": sum(age >= 720 for age in open_age_hours),
            "oldest_open_age_days": max(open_age_hours) / 24 if open_age_hours else None,
            "target_met": target_met,
            "target_eligible": target_eligible,
            "target_misses": target_eligible - target_met,
            "first_complete_week": weeks[0]["week_start"] if weeks else None,
            "last_complete_week": weeks[-1]["week_start"] if weeks else None,
            "complete_week_count": len(weeks),
            "nov16_trend_intake": None,
            "nov16_trend_recorded_closures": None,
            "weekly": weeks,
            "age_filter_open_counts_at_snapshot": {label: sum(row["age_bucket"] == bucket for row in all_open_rows) for label, bucket in AGE_BUCKETS.items()},
            "age_filter_open_counts_in_activity_period": {label: sum(row["age_bucket"] == bucket for row in detail_open_rows) for label, bucket in AGE_BUCKETS.items()},
            "worklist_unfiltered_age_row_count": len(base_detail_rows),
            "worklist_age_filtered_row_counts": {
                label: sum(truth(row["is_backlog"]) and row["age_bucket"] == bucket for row in base_detail_rows)
                for label, bucket in AGE_BUCKETS.items()
            },
            "worklist_age_7d_plus_row_count": sum(truth(row["is_backlog"]) and row["age_bucket"] == AGE_BUCKETS["168h+"] for row in base_detail_rows),
        }
        if sum(output["age_filter_open_counts_at_snapshot"].values()) != total_open:
            raise ValueError(f"Backlog/case age counts disagree: {name}")
        results.append(output)
    result = {
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        "release_id": args.release_id,
        "snapshot_id": metadata["snapshot_id"],
        "engine": "Independent Python calculations over saved BigQuery release CSV exports; not DAX execution",
        "dax_execution": "pending separate actual Desktop comparison",
        "priority_order": "Candidates must have aged >=168h count >0; aged count descending, open count descending, agency/problem/borough ascending",
        "date_contract": "Priority uses selected snapshot, independent of activity dates; trend includes Monday weeks fully contained in cohort and selected activity dates; target metrics use creation dates",
        "empty_contract": "Additive counts are zero; priority identity, priority counts, and ratios are null when no ranked aged segment exists; activity counts for valid complete weeks are zero; the complete-week count follows the date selection; outside-cohort trend points are null",
        "priority_display_contract": "An absent ranked aged segment has no priority count, not an observed zero; its presentation is an em dash while selected-scope additive counts remain zero",
        "worklist_contract": "Without an age selection, show current-snapshot requests that are open OR target denominator=1, respecting the creation-date period; an age selection further narrows to OPEN requests in that exact Cases.age_bucket mapping",
        "input_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()},
        "scenarios": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Computed {len(results)} briefing reference scenarios from {len(cases):,} real cases.")
    print(f"Priority: {results[0]['priority_label']}; aged={results[0]['priority_aged_count']}; share={results[0]['priority_aged_share']:.12f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
