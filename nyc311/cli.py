"""One explicit CLI for offline checks, captures, replay, and opt-in cloud execution."""
import argparse
import json
import sys
from pathlib import Path

from .contracts import REPO_ROOT, ContractError, atomic_json, load_config, operator_lock, safe_id, utc_now


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nyc311")
    sub = parser.add_subparsers(dest="command", required=True)
    profile = sub.add_parser("profile", help="Read source metadata and agency/category counts")
    profile.add_argument("--config", type=Path, default=Path("config/demo.json"))
    profile.add_argument("--output", type=Path, default=Path("artifacts/source/profile.json"))
    capture = sub.add_parser("capture", help="Capture a complete bounded cohort; never overwrite input")
    capture.add_argument("--config", type=Path, default=Path("config/demo.json"))
    capture.add_argument("--snapshot-id", required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--sheet-id")
    capture.add_argument("--sheet-range", default="Targets!A:E")
    run = sub.add_parser("run", help="Validate and publish a captured input locally or to GCP")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--release-id", required=True)
    run.add_argument("--state-dir", type=Path, default=Path(".local"))
    run.add_argument("--export-dir", type=Path, default=Path("data/demo_exports"))
    run.add_argument("--cloud-config", type=Path)
    run.add_argument("--simulate-failure", choices=["validation", "publication"])
    validate = sub.add_parser("validate", help="Run local contract/security/replay tests without GCP")
    validate.add_argument("--output", type=Path, default=Path("artifacts/validation/local.json"))
    benchmark = sub.add_parser("benchmark", help="Run same-result BigQuery benchmark, cache disabled")
    benchmark.add_argument("--cloud-config", type=Path, required=True)
    benchmark.add_argument("--release-id", required=True)
    replay_cloud = sub.add_parser("replay-cloud", help="Run opt-in synthetic BigQuery replay proof and restore the real active release",
        description="First-run proof using an unused synthetic fixture scope and a new evidence output path. Performs real cloud writes/dbt builds under the shared operator lock, then restores the previously active real release. Retains all history; subsequent exact replays use the ordinary run command. See artifacts/replay/README.md.")
    replay_cloud.add_argument("--cloud-config", type=Path, required=True)
    replay_cloud.add_argument("--output", type=Path, default=Path("artifacts/replay/bigquery-replay.json"))
    args = parser.parse_args(argv)
    try:
        if args.command == "profile":
            from .source import Socrata
            result = Socrata(load_config(args.config)).profile()
            atomic_json(args.output, result)
            print(json.dumps({"profile": str(args.output), "agency": result["agency"], "category_status_groups": len(result["counts"])}))
        elif args.command == "capture":
            from .source import Socrata, write_capture
            from .targets import load_csv, load_sheets
            # Validate before any audit path, lock, target access, or source request.
            safe_id(args.snapshot_id)
            cfg = load_config(args.config)
            targets, version = load_sheets(args.sheet_id, args.sheet_range) if args.sheet_id else load_csv(REPO_ROOT / cfg["targets_csv"])
            state_dir = REPO_ROOT / cfg["state_directory"]
            audit = {"operation": "capture", "snapshot_id": args.snapshot_id, "started_at": utc_now(), "outcome": "running"}
            audit_path = state_dir / "audits" / (args.snapshot_id + "_capture.json")
            with operator_lock(state_dir):
                try:
                    observation = Socrata(cfg).capture(args.snapshot_id, targets, version)
                    write_capture(args.output, observation)
                    audit.update(outcome="complete", source_count=observation["manifest"]["source_count"], output=str(args.output))
                    print(json.dumps(observation["manifest"], indent=2))
                except Exception as exc:
                    audit.update(outcome="failed", error_type=type(exc).__name__, error_detail=str(exc) if isinstance(exc, ContractError) else "Capture failed; sensitive response details omitted")
                    raise
                finally:
                    audit["ended_at"] = utc_now()
                    atomic_json(audit_path, audit)
        elif args.command == "run":
            from .source import read_capture
            observation = read_capture(args.input)
            with operator_lock(args.state_dir):
                if args.cloud_config:
                    from .cloud import publish_cloud
                    result = publish_cloud(observation, args.input, args.release_id, args.cloud_config, args.state_dir, args.export_dir, args.simulate_failure)
                else:
                    from .release import publish_local
                    result = publish_local(observation, args.release_id, args.state_dir, args.export_dir, args.simulate_failure)
            print(json.dumps(result, indent=2))
        elif args.command == "validate":
            from .validation import validate_local
            return validate_local(args.output)
        elif args.command == "benchmark":
            from .cloud import benchmark_cloud
            print(json.dumps(benchmark_cloud(args.cloud_config, args.release_id), indent=2))
        elif args.command == "replay-cloud":
            from .cloud_replay import run_cloud_replay
            # The proof owns the single lock across all runs and restoration.
            result = run_cloud_replay(args.cloud_config, args.output)
            print(json.dumps({"outcome": result["outcome"], "passed_checks": result["passed_checks"],
                              "total_checks": result["total_checks"], "restoration": result["restoration"],
                              "output": str(args.output)}, indent=2))
        return 0
    except ContractError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
