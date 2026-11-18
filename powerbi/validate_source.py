"""Validate PBIR source without claiming Power BI Desktop or DAX execution.

--schemas additionally validates against Microsoft's public JSON Schemas. Cached
copies are local developer tooling, not report dependencies or credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schemas", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "validation" / "source_validation.json")
    args = parser.parse_args()
    contract = json.loads((ROOT / "export-contract.json").read_text(encoding="utf-8"))
    fields = {table["model"]: set(table["columns"]) for table in contract["tables"]}
    fields["Age Bucket"] = {"bucket", "sort_order"}
    fields["Metrics"] = set()
    measure_source = (ROOT / "NYC311.SemanticModel/definition/tables/Metrics.tmdl").read_text(encoding="utf-8")
    import re
    assert not re.search(r"\['(?:Cases|Backlog|Agency|Problem|Borough|Metrics)'", measure_source), "A table-name quoting pass corrupted a bracketed DAX measure identifier"
    fields["Metrics"] = set(re.findall(r"^\tmeasure '([^']+)' =", measure_source, re.MULTILINE))
    # Desktop rejected this reserved table name during the first actual open.
    assert all(name.lower() != "measures" for name in fields), "Power BI reserves the table name Measures"
    files = sorted((ROOT / "NYC311.Report").rglob("*.json"))
    files += [ROOT / "NYC311.pbip", ROOT / "NYC311.Report/definition.pbir", ROOT / "NYC311.SemanticModel/definition.pbism"]
    checked = []

    def fetch_schema(uri: str) -> dict:
        # Microsoft embeds this alternate $id in some documents even though
        # the published filename uses a hyphen. Keep the schema unchanged.
        fetch_uri = uri.replace("schema.embedded.json", "schema-embedded.json")
        parsed = urlparse(uri)
        if parsed.scheme != "https" or parsed.hostname != "developer.microsoft.com":
            raise ValueError(f"Unexpected schema origin: {parsed.scheme}://{parsed.hostname}")
        cache = ROOT / ".schema-cache" / (hashlib.sha256(uri.encode()).hexdigest() + ".json")
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        with urlopen(fetch_uri, timeout=30) as response:
            content = response.read()
        schema = json.loads(content)
        cache.parent.mkdir(exist_ok=True)
        cache.write_bytes(content)
        return schema

    def check_field_refs(value):
        if isinstance(value, list):
            for item in value:
                check_field_refs(item)
        elif isinstance(value, dict):
            for kind in ("Column", "Measure"):
                item = value.get(kind)
                if isinstance(item, dict):
                    entity = item.get("Expression", {}).get("SourceRef", {}).get("Entity")
                    if entity:
                        assert entity in fields, f"Unknown model entity: {entity}"
                        assert item["Property"] in fields[entity], f"Unknown field: {entity}.{item['Property']}"
            for item in value.values():
                check_field_refs(item)

    for file in files:
        value = json.loads(file.read_text(encoding="utf-8"))
        check_field_refs(value)
        if file.name == "visual.json":
            page = json.loads((file.parent.parent.parent / "page.json").read_text(encoding="utf-8"))
            pos = value["position"]
            assert 0 <= pos["x"] and 0 <= pos["y"]
            assert pos["x"] + pos["width"] <= page["width"]
            assert pos["y"] + pos["height"] <= page["height"]
        if args.schemas:
            from jsonschema import Draft7Validator
            from referencing import Registry, Resource
            from referencing.jsonschema import DRAFT7
            schema = fetch_schema(value["$schema"])
            registry = Registry(retrieve=lambda uri: Resource.from_contents(fetch_schema(uri), default_specification=DRAFT7))
            errors = sorted(Draft7Validator(schema, registry=registry).iter_errors(value), key=lambda e: str(e.path))
            if errors:
                raise ValueError(f"{file.relative_to(ROOT)}: " + "; ".join(f"{list(e.path)}: {e.message}" for e in errors))
        checked.append(str(file.relative_to(ROOT)).replace("\\", "/"))

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "outcome": "passed",
        "default_release_id": contract["release_parameter"],
        "checks": ["JSON parsing", "visual field/measure references", "visual bounds"] + (["Microsoft JSON Schemas"] if args.schemas else []),
        "files_checked": len(checked),
        "files": checked,
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in checked},
        "desktop_open": "unverified",
        "refresh": "unverified",
        "dax_execution": "unverified",
        "note": "Source validation is not Desktop rendering, data refresh, or SQL-to-DAX reconciliation."
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(checked)} Power BI source files; schema checks={args.schemas}. Desktop checks remain unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
