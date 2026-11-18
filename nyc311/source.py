"""Bounded, minimal-field access to official NYC Open Data; no resident-level detail."""
from __future__ import annotations

import gzip
import json
import os
import random
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .contracts import (
    ContractError, SOURCE_FIELDS, SOURCE_TYPES, atomic_json, content_hash, safe_id, utc_now,
)

BASE_URL = "https://data.cityofnewyork.us"


class SourceRedirectHandler(HTTPRedirectHandler):
    """Validate a redirect before urllib forwards the optional application token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destination = urlsplit(newurl)
        try:
            same_origin = (
                destination.scheme == "https"
                and destination.hostname == "data.cityofnewyork.us"
                and destination.port in (None, 443)
                and destination.username is None
                and destination.password is None
            )
        except ValueError:
            same_origin = False
        if not same_origin:
            raise ContractError("Source redirect outside the reviewed HTTPS origin was blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class Socrata:
    def __init__(self, config: dict, sleep=time.sleep):
        self.config = config
        self.sleep = sleep
        self.opener = build_opener(SourceRedirectHandler())

    def get(self, path: str, params: dict | None = None):
        url = BASE_URL + path + (("?" + urlencode(params)) if params else "")
        headers = {"User-Agent": "nyc311-portfolio/0.1 (bounded public-data research)", "Accept": "application/json"}
        if os.environ.get("SOCRATA_APP_TOKEN"):
            headers["X-App-Token"] = os.environ["SOCRATA_APP_TOKEN"]
        attempts = self.config.get("maximum_attempts", 5)
        for attempt in range(attempts):
            try:
                with self.opener.open(Request(url, headers=headers), timeout=self.config.get("request_timeout_seconds", 60)) as response:
                    if not response.url.startswith(BASE_URL + "/"):
                        raise ContractError("Unexpected source redirect")
                    payload = response.read(32 * 1024 * 1024 + 1)
                    if len(payload) > 32 * 1024 * 1024:
                        raise ContractError("Response exceeds bounded page byte limit")
                    return json.loads(payload)
            except HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504):
                    raise ContractError(f"Source HTTP {exc.code}; response body omitted") from None
                error = f"Source HTTP {exc.code} after bounded retries"
            except (URLError, TimeoutError, ConnectionError):
                error = "Source connection failed after bounded retries"
            if attempt + 1 < attempts:
                self.sleep(min(2 ** attempt + random.random(), 30))
        raise ContractError(error)

    def query(self, query: str):
        return self.get("/resource/erm2-nwe9.json", {"$query": query})

    def metadata(self):
        metadata = self.get("/api/views/erm2-nwe9.json")
        columns = {column["fieldName"]: column for column in metadata["columns"]}
        for name, expected_type in SOURCE_TYPES.items():
            if name not in columns or columns[name]["dataTypeName"] != expected_type:
                raise ContractError(f"Source schema drift: required column {name} or its type changed")
        return {
            "dataset_id": metadata["id"], "name": metadata["name"],
            "rows_updated_at": metadata.get("rowsUpdatedAt"),
            "view_last_modified": metadata.get("viewLastModified"),
            "columns": [{key: columns[name].get(key) for key in ("fieldName", "name", "dataTypeName", "description")} for name in SOURCE_FIELDS],
        }

    def where(self, include_problems=True):
        cfg = self.config
        conditions = [f"agency={literal(cfg['agency'])}",
                      f"created_date >= {literal(cfg['cohort_start'] + 'T00:00:00')}",
                      f"created_date < {literal(cfg['cohort_end'] + 'T00:00:00')}"]
        if include_problems:
            conditions.append("complaint_type IN (" + ",".join(literal(value) for value in cfg["problems"]) + ")")
        return " AND ".join(conditions)

    def profile(self):
        query = ("SELECT complaint_type,status,count(*) AS request_count WHERE " + self.where(False)
                 + " GROUP BY complaint_type,status ORDER BY request_count DESC,complaint_type,status LIMIT 1000")
        return {"captured_at": utc_now(), "metadata": self.metadata(), "query": query,
                "cohort_start": self.config["cohort_start"], "cohort_end": self.config["cohort_end"],
                "agency": self.config["agency"], "counts": self.query(query)}

    def capture(self, snapshot_id: str, targets: list[dict], target_version: str):
        safe_id(snapshot_id)
        started = utc_now()
        metadata = self.metadata()
        where = self.where()
        count_query = "SELECT count(*) AS request_count WHERE " + where
        expected = int(self.query(count_query)[0]["request_count"])
        if expected == 0 or expected > self.config["maximum_rows"]:
            raise ContractError(f"Source count {expected} is empty or exceeds maximum_rows")
        rows, seen, cursor = [], set(), None
        while True:
            cursor_clause = "" if cursor is None else " AND unique_key > " + literal(cursor)
            query = ("SELECT " + ",".join(SOURCE_FIELDS) + " WHERE " + where + cursor_clause
                     + f" ORDER BY unique_key ASC LIMIT {self.config['page_size']}")
            page = self.query(query)
            if not page:
                break
            for row in page:
                if set(row) - set(SOURCE_FIELDS):
                    raise ContractError("Source returned an unrequested column")
                key = row.get("unique_key")
                if not key or key in seen or (cursor is not None and key <= cursor):
                    raise ContractError("Missing, duplicate, or out-of-order request key")
                seen.add(key)
                cursor = key
                rows.append({field: row.get(field) for field in SOURCE_FIELDS})
                if len(rows) > self.config["maximum_rows"]:
                    raise ContractError("Capture exceeded maximum_rows")
        after_count = int(self.query(count_query)[0]["request_count"])
        after_metadata = self.metadata()
        if len(rows) != expected or after_count != expected:
            raise ContractError(f"Incomplete or changing extract: before={expected}, loaded={len(rows)}, after={after_count}")
        if metadata != after_metadata:
            raise ContractError("Source metadata changed during extraction; capture must be repeated")
        ended = utc_now()
        scope = {key: self.config[key] for key in ("dataset_id", "agency", "problems", "cohort_start", "cohort_end", "source_timezone")}
        manifest = {
            "snapshot_id": snapshot_id, "observed_at": ended, "extraction_started_at": started,
            "extraction_ended_at": ended, "source_kind": "real", "scope": scope,
            "scope_hash": content_hash(scope), "expected_count": expected, "source_count": len(rows),
            "source_count_after": after_count, "payload_hash": content_hash(rows), "target_version": target_version,
            "source_metadata": metadata, "complete": True,
            "capture_semantics": "Full bounded cohort collected over extraction interval; API does not promise an atomic snapshot.",
        }
        return {"manifest": manifest, "targets": targets, "rows": rows}


def write_capture(path: Path, capture: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(capture, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if path.suffix == ".gz":
        data = gzip.compress(data, mtime=0)
    # Existing captures are immutable, including timestamps and target inputs.
    with path.open("xb") as stream:
        stream.write(data)


def read_capture(path: Path) -> dict:
    data = path.read_bytes()
    capture = json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)
    manifest = capture["manifest"]
    safe_id(manifest["snapshot_id"])
    if not manifest.get("complete") or len(capture["rows"]) != manifest["expected_count"]:
        raise ContractError("Captured input is incomplete")
    if len(capture["rows"]) != manifest["source_count"] or content_hash(capture["rows"]) != manifest["payload_hash"]:
        raise ContractError("Captured row count or payload hash mismatch")
    if content_hash(capture["targets"]) != manifest["target_version"]:
        raise ContractError("Captured target version mismatch")
    if content_hash(manifest["scope"]) != manifest["scope_hash"]:
        raise ContractError("Captured scope hash mismatch")
    return capture
