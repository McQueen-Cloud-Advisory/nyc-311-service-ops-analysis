"""Check committed configuration and example contracts without cloud access.

Run from a checkout with the package and PyYAML installed:
    python scripts/validate_config.py

Git selects source files so ignored credentials, caches, and local dbt profiles
are never loaded. YAML/JSON parsing checks syntax, not external vendor schemas.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from nyc311.contracts import REPO_ROOT, load_config, safe_id
from nyc311.targets import load_csv

JSON_SUFFIXES = {".json", ".pbip", ".pbir", ".pbism"}
CONFIG_SUFFIXES = JSON_SUFFIXES | {".toml", ".yaml", ".yml"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate mapping key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"),
                      object_pairs_hook=unique_object, parse_constant=reject_constant)


def read_yaml(path: Path):
    # Keep the normal Python test suite usable with the minimal package install.
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        return unique_object((loader.construct_object(key, deep=deep),
                              loader.construct_object(value, deep=deep))
                             for key, value in node.value)

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(path.read_text(encoding="utf-8-sig"), Loader=UniqueLoader)


def source_files(root: Path):
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, check=True, capture_output=True,
    )
    return sorted({root / name for name in result.stdout.decode("utf-8").split("\0")
                   if name and Path(name).suffix in CONFIG_SUFFIXES})


def check_syntax(path: Path):
    if path.suffix in JSON_SUFFIXES:
        read_json(path)
    elif path.suffix == ".toml":
        tomllib.loads(path.read_text(encoding="utf-8-sig"))
    else:
        read_yaml(path)


def check_example_contracts(root: Path):
    demo = load_config(root / "config/demo.json")
    target_path = (root / demo["targets_csv"]).resolve()
    if not target_path.is_relative_to(root.resolve()):
        raise ValueError("config/demo.json: targets_csv must stay inside the checkout")
    targets, _ = load_csv(target_path)
    configured = {(demo["agency"], problem) for problem in demo["problems"]}
    if not configured <= {(row["agency"], row["problem"]) for row in targets}:
        raise ValueError("config/demo.json: the target register omits a configured agency/problem")
    if type(demo["request_timeout_seconds"]) is not int or demo["request_timeout_seconds"] <= 0:
        raise ValueError("config/demo.json: request_timeout_seconds must be a positive integer")

    runtime = read_json(root / "config/cloud.example.json")
    infrastructure = read_json(root / "infra/gcp.example.json")
    datasets = {kind: safe_id(runtime[kind + "_dataset"])
                for kind in ("raw", "work", "reporting", "control")}
    if len(set(datasets.values())) != len(datasets):
        raise ValueError("config/cloud.example.json: datasets must be distinct")
    if datasets != infrastructure["dataset_ids"]:
        raise ValueError("Runtime and infrastructure examples disagree on dataset IDs")
    if runtime["location"] != infrastructure["location"]:
        raise ValueError("Runtime and infrastructure examples disagree on the GCP region")
    for name, config in (("config/demo.json", demo), ("config/cloud.example.json", runtime)):
        limit = config["maximum_bytes_billed"]
        if type(limit) is not int or not 1 <= limit <= 10_000_000_000:
            raise ValueError(f"{name}: maximum_bytes_billed must be an integer from 1 to 10 GB")


def main() -> int:
    errors = []
    try:
        files = source_files(REPO_ROOT)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: Cannot list configuration files with git: {exc}", file=sys.stderr)
        return 1
    for path in files:
        try:
            check_syntax(path)
        except Exception as exc:
            errors.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
    try:
        check_example_contracts(REPO_ROOT)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"Example configuration contract: {exc}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(files)} JSON/YAML/TOML source files; demo targets and cloud example contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
