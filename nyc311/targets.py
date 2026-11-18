"""Identical CSV and read-only Sheets target schema, versioned by canonical content."""
import csv
import io
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

from .contracts import ContractError, content_hash

TARGET_COLUMNS = ["agency", "problem", "effective_start", "effective_end", "target_hours"]


def validate_targets(rows: list[dict]) -> tuple[list[dict], str]:
    normalized = []
    for row in rows:
        if set(row) != set(TARGET_COLUMNS):
            raise ContractError("Target columns do not match the CSV/Sheets contract")
        agency = str(row["agency"]).strip().upper()
        problem = str(row["problem"]).strip()
        hours = str(row["target_hours"]).strip()
        if not agency or not problem or not re.fullmatch(r"[1-9][0-9]*", hours):
            raise ContractError("Targets require agency, problem, and positive integer hours")
        start = date.fromisoformat(str(row["effective_start"]))
        end = date.fromisoformat(str(row["effective_end"])) if row["effective_end"] else None
        if end and end <= start:
            raise ContractError("Target effective_end must be after effective_start")
        normalized.append(dict(agency=agency, problem=problem, effective_start=start.isoformat(),
                               effective_end=end.isoformat() if end else None, target_hours=int(hours)))
    normalized.sort(key=lambda r: (r["agency"], r["problem"], r["effective_start"]))
    for previous, current in zip(normalized, normalized[1:]):
        if (previous["agency"], previous["problem"]) == (current["agency"], current["problem"]):
            if previous["effective_end"] is None or current["effective_start"] < previous["effective_end"]:
                raise ContractError("Conflicting or overlapping target intervals")
    if not normalized:
        raise ContractError("Target register is empty")
    return normalized, content_hash(normalized)


def load_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != TARGET_COLUMNS:
            raise ContractError("Target CSV header does not match the target contract")
        return validate_targets(list(reader))


def load_sheets(spreadsheet_id: str, range_name: str):
    """ADC user must already have read access; this path never changes sharing or content."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    if not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
        raise ContractError("Invalid spreadsheet ID")
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    session = AuthorizedSession(credentials)
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{quote(range_name, safe='')}"
    response = session.get(url, timeout=30, allow_redirects=False, params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "FORMATTED_STRING"})
    if response.status_code != 200:
        raise ContractError(f"Sheets read failed with HTTP {response.status_code}; response body omitted")
    values = response.json().get("values", [])
    if not values or values[0] != TARGET_COLUMNS:
        raise ContractError("Sheets header does not match the CSV target contract")
    rows = []
    for values_row in values[1:]:
        if not any(str(value).strip() for value in values_row):
            continue
        if len(values_row) > len(TARGET_COLUMNS):
            raise ContractError("Unexpected Sheets target columns")
        rows.append(dict(zip(TARGET_COLUMNS, values_row + [""] * (5 - len(values_row)))))
    return validate_targets(rows)
