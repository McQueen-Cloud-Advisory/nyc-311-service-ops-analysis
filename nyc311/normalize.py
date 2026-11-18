"""Normalize captured source fields while retaining defects as explicit flags."""
from .contracts import ContractError, SOURCE_FIELDS, content_hash
from .temporal import normalize_temporal


def normalize_rows(capture: dict) -> list[dict]:
    manifest = capture["manifest"]
    rows, seen = [], set()
    for raw in capture["rows"]:
        if set(raw) - set(SOURCE_FIELDS):
            raise ContractError("Capture includes fields outside the reviewed privacy allowlist")
        request_id = str(raw.get("unique_key") or "").strip()
        if not request_id or request_id in seen:
            raise ContractError("Missing or duplicate request key blocks publication")
        seen.add(request_id)
        row = dict(snapshot_id=manifest["snapshot_id"], request_id=request_id,
                   created_date=raw.get("created_date"), closed_date=raw.get("closed_date"),
                   agency=raw.get("agency"), problem=raw.get("complaint_type"),
                   borough=raw.get("borough"), channel=raw.get("open_data_channel_type"),
                   status=raw.get("status"), payload_hash=content_hash(raw))
        row.update(normalize_temporal(row["created_date"], row["closed_date"], manifest["observed_at"]))
        rows.append(row)
    return sorted(rows, key=lambda row: row["request_id"])
