"""Offline reference calculations, never a substitute for BigQuery/DAX verification.

This intentionally small implementation lets a reviewer inspect the public captured
input without cloud credentials. SQL is the production transformation contract.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .contracts import REPO_ROOT, ContractError, content_hash, parse_utc, read_json
from .temporal import NYC

BOROUGHS = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"}
OPEN_STATUSES = {"open", "assigned", "in progress", "pending", "started"}
REVIEWED_STATUSES = OPEN_STATUSES | {"closed", "unknown", "unspecified"}
BUCKET_COLUMNS = {
    "Under 24 hours": "age_under_24h_count", "24 to under 72 hours": "age_24_to_72h_count",
    "72 to under 168 hours": "age_72_to_168h_count", "168 hours or more": "age_168h_plus_count",
    "Unknown age": "age_unknown_count",
}


def key(value, upper=False):
    value = str(value or "").strip()
    return (value.upper() if upper else value) or "UNKNOWN"


def percentile_inc(values: list[float], probability=0.9):
    if not 0 <= probability <= 1:
        raise ValueError("Percentile probability must be between zero and one")
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * probability
    lower = int(position)
    if lower == len(values) - 1:
        return values[lower]
    return values[lower] + (values[lower + 1] - values[lower]) * (position - lower)


def case_metrics(rows: list[dict], manifest: dict, targets: list[dict], release_id: str):
    """Mirror the case mart locally; this does not execute or verify GoogleSQL."""
    observation = parse_utc(manifest["observed_at"])
    cohort_start = manifest["scope"]["cohort_start"]
    cohort_end = manifest["scope"]["cohort_end"]
    cases = []
    seen = set()
    for row in sorted(rows, key=lambda item: item["request_id"]):
        if row["snapshot_id"] != manifest["snapshot_id"]:
            raise ContractError("Case row does not belong to the capture snapshot")
        if not row["request_id"] or row["request_id"] in seen:
            raise ContractError("Missing or duplicate case request key")
        seen.add(row["request_id"])
        agency, problem = key(row["agency"], True), key(row["problem"])
        borough = key(row["borough"], True)
        borough = borough if borough in BOROUGHS else "UNKNOWN"
        status = str(row["status"] or "Unknown").strip() or "Unknown"
        if status.lower() not in REVIEWED_STATUSES:
            raise ContractError("Unreviewed source status blocks publication")
        status_class = "closed" if status.lower() == "closed" else "open" if status.lower() in OPEN_STATUSES else "unknown"
        created = parse_utc(row["created_at"]) if row["created_at"] else None
        closed = parse_utc(row["closed_at"]) if row["closed_at"] else None
        created_date, closed_date = row["created_local_date"], row["closed_local_date"]
        matching = [t for t in targets if key(t["agency"], True) == agency and key(t["problem"]) == problem and created_date
                    and t["effective_start"] <= created_date and (t["effective_end"] is None or created_date < t["effective_end"])]
        if len(matching) > 1:
            raise ContractError("Target join fanout")
        target_hours = matching[0]["target_hours"] if matching else None
        age = (observation - created).total_seconds() / 3600 if created and created <= observation else None
        elapsed = (closed - created).total_seconds() / 3600 if created and closed and created <= closed <= observation else None
        invalid = (row["temporal_quality"] != "valid" or created is None or (created and created > observation)
                   or (closed is not None and (created is None or closed < created or closed > observation))
                   or (status_class == "closed" and closed is None) or (status_class == "open" and closed is not None))
        reason = ("invalid_outcome" if invalid else "unknown_outcome" if status_class == "unknown" else
                  "missing_target" if target_hours is None else "immature" if age < target_hours else "eligible_mature")
        is_closure = not invalid and status_class == "closed" and closed is not None
        bucket = ("Unknown age" if age is None else "Under 24 hours" if age < 24 else "24 to under 72 hours"
                  if age < 72 else "72 to under 168 hours" if age < 168 else "168 hours or more")
        cases.append({
            "release_id": release_id, "request_id": row["request_id"], "snapshot_id": row["snapshot_id"],
            "observed_at": manifest["observed_at"],
            "created_date": created_date if created_date and cohort_start <= created_date < cohort_end else None,
            "closed_date": closed_date if is_closure else None,
            "created_at": row["created_at"], "closed_at": row["closed_at"], "agency_key": agency,
            "problem_key": problem, "borough_key": borough, "status": status, "status_class": status_class,
            "temporal_quality": row["temporal_quality"], "channel": key(row["channel"]),
            "elapsed_hours": elapsed, "age_hours": age, "age_bucket": bucket,
            "target_hours": target_hours, "target_version": manifest["target_version"],
            "target_numerator": int(reason == "eligible_mature" and status_class == "closed" and elapsed is not None and elapsed <= target_hours),
            "target_denominator": int(reason == "eligible_mature"), "is_backlog": status_class == "open" and closed is None,
            "is_p90_eligible": is_closure, "is_recorded_closure": is_closure,
            "is_missing_target": reason == "missing_target", "is_immature": reason == "immature",
            "is_invalid_outcome": reason == "invalid_outcome", "is_unknown_outcome": reason == "unknown_outcome",
            "target_eligibility_reason": reason,
            "payload_hash": row["payload_hash"],
        })
    return cases


def summarize(cases: list[dict]):
    numerator = sum(row["target_numerator"] for row in cases)
    denominator = sum(row["target_denominator"] for row in cases)
    eligible = [row["elapsed_hours"] for row in cases if row["is_p90_eligible"]]
    return dict(case_count=len(cases), intake=sum(row["created_date"] is not None for row in cases),
                recorded_closures=sum(row["is_recorded_closure"] for row in cases),
                observed_backlog=sum(row["is_backlog"] for row in cases),
                aged_168h_plus=sum(row["is_backlog"] and row["age_bucket"] == "168 hours or more" for row in cases),
                target_numerator=numerator, target_denominator=denominator,
                within_demo_target=numerator / denominator if denominator else None,
                p90_elapsed_hours=percentile_inc(eligible), p90_eligible_count=len(eligible),
                eligibility_counts=dict(sorted(Counter(row["target_eligibility_reason"] for row in cases).items())))


def build_marts(rows: list[dict], manifest: dict, targets: list[dict], release_id: str,
                previous_snapshots: list[tuple[list[dict], dict, list[dict]]] | None = None):
    """Build bounded reviewer tables from captured inputs using local reference logic.

    ``previous_snapshots`` must contain published captures. Other cohort/source
    kinds and captures later than this observation are ignored, matching dbt's
    source selection. The caller owns publication authorization and evidence.
    """
    cases = case_metrics(rows, manifest, targets, release_id)
    all_cases = []
    seen_snapshots = {manifest["snapshot_id"]}
    for old_rows, old_manifest, old_targets in previous_snapshots or []:
        if (old_manifest["scope"] != manifest["scope"]
                or old_manifest["source_kind"] != manifest["source_kind"]
                or parse_utc(old_manifest["observed_at"]) > parse_utc(manifest["observed_at"])):
            continue
        if old_manifest["snapshot_id"] in seen_snapshots:
            raise ContractError("Duplicate snapshot in release history")
        seen_snapshots.add(old_manifest["snapshot_id"])
        all_cases.extend(case_metrics(old_rows, old_manifest, old_targets, release_id))
    all_cases.extend(cases)
    marts = {"fct_cases": cases}
    for dimension in ("agency", "problem", "borough"):
        keys = sorted({row[dimension + "_key"] for row in all_cases} | {"UNKNOWN"})
        if dimension == "borough":
            keys = sorted(BOROUGHS | {"UNKNOWN"})
        marts["dim_" + dimension] = [{"release_id": release_id, dimension + "_key": value,
                                       dimension: value} for value in keys]
    start = date.fromisoformat(manifest["scope"]["cohort_start"])
    observed_date = parse_utc(manifest["observed_at"]).astimezone(NYC).date()
    # Match the SQL calendar; do not use invalid source dates as dimension bounds.
    last_date = max(date.fromisoformat(manifest["scope"]["cohort_end"]) - timedelta(days=1), observed_date)
    marts["dim_date"] = []
    for day_offset in range((last_date - start).days + 1):
        day = start + timedelta(days=day_offset)
        marts["dim_date"].append(dict(release_id=release_id, date_key=day.isoformat(), year=day.year,
                                     month=day.month, month_name=day.strftime("%B"),
                                     week_start=(day - timedelta(days=day.weekday())).isoformat()))
    grouped = {}
    for row in all_cases:
        grain = tuple(row[field] for field in ("snapshot_id", "agency_key", "problem_key", "borough_key"))
        if grain not in grouped:
            grouped[grain] = {field: row[field] for field in ("snapshot_id", "agency_key", "problem_key", "borough_key", "observed_at")}
            grouped[grain].update(release_id=release_id, snapshot_date=parse_utc(row["observed_at"]).astimezone(NYC).date().isoformat(),
                                   is_release_snapshot=row["snapshot_id"] == manifest["snapshot_id"], open_count=0,
                                   **{column: 0 for column in BUCKET_COLUMNS.values()})
        if row["is_backlog"]:
            grouped[grain]["open_count"] += 1
            grouped[grain][BUCKET_COLUMNS[row["age_bucket"]]] += 1
    marts["fct_backlog"] = [grouped[grain] for grain in sorted(grouped)]
    marts["release_metadata"] = [{"release_id": release_id,
        **{field: manifest[field] for field in ("snapshot_id", "observed_at", "extraction_started_at", "extraction_ended_at",
                                               "source_kind", "target_version", "expected_count", "source_count")},
        **{field: manifest["scope"][field] for field in ("cohort_start", "cohort_end")}}]
    return marts


def write_exports(marts: dict, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    contract = read_json(REPO_ROOT / "powerbi/export-contract.json")
    for table in contract["tables"]:
        columns = list(table["columns"])
        with (directory / (table["source"] + ".csv")).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise")
            writer.writeheader()
            for row in marts[table["source"]]:
                writer.writerow({column: (str(row[column]).lower() if isinstance(row[column], bool) else row[column]) for column in columns})


def metrics_evidence(marts: dict, manifest: dict, release_id: str):
    cases = marts["fct_cases"]
    segments = defaultdict(list)
    for row in cases:
        segments[(row["problem_key"], row["borough_key"])].append(row)
    return {"release_id": release_id, "snapshot_id": manifest["snapshot_id"], "observed_at": manifest["observed_at"],
            "scope": manifest["scope"], "verification_engine": "local Python reference; BigQuery and DAX reconciliation pending",
            "source_kind": manifest["source_kind"], "overall": summarize(cases),
            "segments": [{"problem": problem, "borough": borough, **summarize(segment)} for (problem, borough), segment in sorted(segments.items())],
            "marts_hash": content_hash(marts)}
