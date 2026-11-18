"""Check CSV serialization and relationships before a Desktop Import refresh.

This validates the typed data contract, not the Power Query engine or DAX.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

BASE = Path(__file__).resolve().parent


def typed(value: str, kind: str):
    if value == "":
        return None
    if kind == "text":
        return value
    if kind == "date":
        return date.fromisoformat(value)
    if kind == "datetimezone":
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
            raise ValueError("Timestamp must carry UTC offset")
        return result
    if kind == "int64":
        result = int(value)
        if not -(2**63) <= result < 2**63:
            raise ValueError("Integer outside Int64 range")
        return result
    if kind == "number":
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite numeric value")
        return result
    if kind == "logical":
        if value not in ("true", "false"):
            raise ValueError("Boolean must be lowercase true/false")
        return value == "true"
    raise ValueError(f"Unknown type: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=BASE.parent / "data/demo_exports")
    parser.add_argument("--release-id", default="dsny_20261118")
    parser.add_argument("--output", type=Path, default=BASE / "validation/csv_validation.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", args.release_id):
        raise ValueError("Invalid release ID")
    folder = args.root / args.release_id
    contract = json.loads((BASE / "export-contract.json").read_text(encoding="utf-8"))
    tables, hashes = {}, {}
    for spec in contract["tables"]:
        file = folder / (spec["source"] + ".csv")
        hashes[file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
        with file.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError(f"{file.name}: missing/duplicate header")
            if not set(spec["columns"]) <= set(reader.fieldnames):
                raise ValueError(f"{file.name}: missing required columns")
            rows = []
            for line, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"{file.name}:{line}: malformed CSV record")
                try:
                    result = {column: typed(row[column], kind) for column, kind in spec["columns"].items()}
                except ValueError as exc:
                    raise ValueError(f"{file.name}:{line}: {exc}") from exc
                if result["release_id"] != args.release_id:
                    raise ValueError(f"{file.name}:{line}: mixed release")
                rows.append(result)
            tables[spec["model"]] = rows
    if len(tables["Release"]) != 1:
        raise ValueError("Release metadata must have one row")
    release = tables["Release"][0]
    cases = tables["Cases"]
    backlog = [row for row in tables["Backlog"] if row["is_release_snapshot"] and row["snapshot_id"] == release["snapshot_id"]]
    assert len(cases) == release["source_count"] == release["expected_count"]
    assert len({row["request_id"] for row in cases}) == len(cases)
    assert {row["snapshot_id"] for row in cases} == {release["snapshot_id"]}
    for model in ("Agency", "Problem", "Borough"):
        key = model.lower() + "_key"
        keys = {row[key] for row in tables[model]}
        assert len(keys) == len(tables[model])
        assert all(row[key] in keys for row in cases + backlog)
    dates = {row["date_key"] for row in tables["Date"]}
    assert len(dates) == len(tables["Date"])
    for row in cases:
        assert row["created_date"] is None or row["created_date"] in dates
        assert row["closed_date"] is None or row["closed_date"] in dates
    open_count = sum(row["is_backlog"] for row in cases)
    assert open_count == sum(row["open_count"] for row in backlog)
    age_columns = ["age_under_24h_count", "age_24_to_72h_count", "age_72_to_168h_count", "age_168h_plus_count", "age_unknown_count"]
    assert all(sum(row[name] for name in age_columns) == row["open_count"] for row in backlog)
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "outcome": "passed", "release_id": args.release_id,
        "snapshot_id": release["snapshot_id"], "source_kind": release["source_kind"],
        "observed_at": release["observed_at"].isoformat(),
        "checks": ["CSV headers and typed values", "UTC timestamp offsets", "release and snapshot pin", "case count and request-key uniqueness", "dimension relationships", "date-role coverage", "open cases versus backlog", "age bucket totals"],
        "row_counts": {name: len(rows) for name, rows in tables.items()},
        "observed_backlog": open_count,
        "target_numerator": sum(row["target_numerator"] for row in cases),
        "target_denominator": sum(row["target_denominator"] for row in cases),
        "sha256": hashes,
        "power_query_execution": "unverified", "desktop_refresh": "unverified", "dax_execution": "unverified",
        "note": "Typed CSV contract checks do not execute Power Query, Desktop, BigQuery, or DAX."
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(cases)} case rows, {open_count} observed open; CSV types/relationships verified. Desktop refresh remains unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
