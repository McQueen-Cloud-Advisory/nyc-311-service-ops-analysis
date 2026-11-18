"""Rebuild the tiny synthetic inputs: python -m data.fixtures.build_fixtures.

These are fabricated edge cases, not historical NYC observations. Dates are fixed
so a replay can never age a request by substituting the current wall clock.
"""
from copy import deepcopy
import json
from pathlib import Path

from nyc311.contracts import content_hash
from nyc311.targets import validate_targets


def build_captures():
    scope = {
        "dataset_id": "erm2-nwe9", "agency": "DSNY",
        "problems": ["Dirty Condition", "Illegal Dumping", "Synthetic No Target"],
        "cohort_start": "2026-09-07", "cohort_end": "2026-11-16",
        "source_timezone": "America/New_York",
    }
    targets, target_version = validate_targets([
        dict(agency="DSNY", problem="Dirty Condition", effective_start="2026-09-07", effective_end="2026-11-01", target_hours=24),
        dict(agency="DSNY", problem="Dirty Condition", effective_start="2026-11-01", effective_end="2026-11-16", target_hours=48),
        dict(agency="DSNY", problem="Illegal Dumping", effective_start="2026-09-07", effective_end="2026-11-16", target_hours=72),
    ])

    def row(number, created, closed=None, status="Open", problem="Dirty Condition", borough="QUEENS"):
        return dict(unique_key=f"synthetic_{number:04}", created_date=created, closed_date=closed,
                    agency="DSNY", complaint_type=problem, status=status, borough=borough,
                    open_data_channel_type="ONLINE")

    rows = [
        row(1, "2026-10-25T12:00:00"),  # Old open; B supplies recorded closure on the same key.
        row(2, "2026-10-01T09:00:00", "2026-10-02T09:00:00", "Closed"),  # Exactly 24 hours.
        row(3, "2026-11-01T12:00:00", problem="Illegal Dumping"),  # Overdue open.
        row(4, "2026-11-14T11:00:00", problem="Illegal Dumping"),  # Immature in both A (1h) and B (49h).
        row(5, "2026-11-01T12:00:00", status="Unknown"),
        row(6, "2026-10-10T09:00:00", "2026-10-10T10:00:00", "Closed", borough=None),
        row(7, None),  # Missing creation time; unknown-age open case.
        row(8, "2026-11-01T01:30:00"),  # Ambiguous New York fall-back local time.
        row(9, "2026-10-20T12:00:00", "2026-10-19T12:00:00", "Closed"),  # Negative elapsed time.
        row(10, "2026-10-02T12:00:00", problem="Synthetic No Target"),
        row(11, "2026-11-01T00:00:00", "2026-11-02T23:00:00", "Closed"),  # New target interval; 48 elapsed hours across DST.
        row(12, "2026-10-05T09:00:00", status="Closed"),  # Closed status without a closure time.
        row(13, "2026-11-13T12:00:00", "2026-11-17T12:00:00", "Closed"),  # Closure after both observations.
    ]

    def capture(identifier, observation, captured_rows):
        return {
            "manifest": {
                "snapshot_id": identifier, "observed_at": observation,
                "extraction_started_at": observation, "extraction_ended_at": observation,
                "source_kind": "synthetic", "scope": scope, "scope_hash": content_hash(scope),
                "expected_count": len(captured_rows), "source_count": len(captured_rows),
                "source_count_after": len(captured_rows), "payload_hash": content_hash(captured_rows),
                "target_version": target_version, "complete": True,
                "source_metadata": {"id": "synthetic_fixture", "name": "Fabricated lifecycle and boundary cases"},
                "capture_semantics": "SIMULATED fixture. Fixed observations and fictional request IDs; not NYC historical evidence.",
            },
            "targets": deepcopy(targets), "rows": captured_rows,
        }

    captured_a = capture("synthetic_a", "2026-11-14T17:00:00+00:00", deepcopy(rows))
    changed = deepcopy(rows)
    changed[0]["status"] = "Closed"
    changed[0]["closed_date"] = "2026-11-15T12:00:00"
    captured_b = capture("synthetic_b", "2026-11-16T17:00:00+00:00", changed)
    return captured_a, captured_b


if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    for name, captured in zip(("synthetic_a.json", "synthetic_b.json"), build_captures()):
        (directory / name).write_text(json.dumps(captured, indent=2) + "\n", encoding="utf-8")
