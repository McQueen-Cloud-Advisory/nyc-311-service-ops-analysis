"""Compare executed BigQuery outputs with executed Desktop DAX output files."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql", type=Path, required=True)
    parser.add_argument("--dax-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--import-mode", choices=("CSV", "BigQuery"), required=True)
    args = parser.parse_args()
    sql = json.loads(args.sql.read_text(encoding="utf-8"))
    manifest = json.loads((args.dax_directory / "manifest.json").read_text(encoding="utf-8-sig"))
    slices = {row["slice"]: row for row in sql["reconciliation"]["output_rows"]}
    expected = {
        "A": slices["overall"],
        "B": slices["DSNY / Dirty Condition / BROOKLYN"],
        "C": sql["date_role_reconciliation"]["output_rows"][0],
        "D": slices["empty"],
        "E": sql["release_integrity_reconciliation"]["output_rows"][0],
    }
    checks = []
    file_hashes = {"sql": hashlib.sha256(args.sql.read_bytes()).hexdigest()}
    for section, expected_row in expected.items():
        file = args.dax_directory / f"{section}.json"
        file_hashes[section] = hashlib.sha256(file.read_bytes()).hexdigest()
        actual = json.loads(file.read_text(encoding="utf-8-sig"))
        if isinstance(actual, list):
            if len(actual) != 1:
                raise ValueError(f"Section {section}: expected one result row")
            actual = actual[0]
        if not isinstance(actual, dict) or not actual:
            raise ValueError(f"Section {section}: missing output row")
        for field, value in actual.items():
            if field not in expected_row:
                raise ValueError(f"Section {section}: no SQL counterpart for {field}")
            sql_value = expected_row[field]
            tolerance = 1e-6 if "p90" in field and "count" not in field and "eligible" not in field else 1e-12 if field == "target_rate" else 0
            if value is None or sql_value is None:
                difference = None
                passed = value is sql_value
            elif isinstance(value, (int, float)) and isinstance(sql_value, (int, float)):
                difference = abs(value - sql_value)
                passed = difference <= tolerance
            else:
                difference = None
                passed = value == sql_value
            checks.append({"section": section, "metric": field, "sql": sql_value, "dax": value, "absolute_difference": difference, "tolerance": tolerance, "passed": passed})
    outcome = "passed" if all(check["passed"] for check in checks) else "failed"
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "release_id": manifest["release_id"], "outcome": outcome,
        "scope": f"Executed BigQuery SQL versus executed Power BI Desktop DAX ({args.import_mode} Import)",
        "native_bigquery_connector": "not established by CSV Import reconciliation" if args.import_mode == "CSV" else "see Desktop connection evidence",
        "checks_compared": len(checks), "checks": checks, "input_sha256": file_hashes,
        "visual_inspection": "separate check; query execution does not validate visual layout",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{outcome.upper()}: {len(checks)} SQL/DAX comparisons; mode={args.import_mode}.")
    return 0 if outcome == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
