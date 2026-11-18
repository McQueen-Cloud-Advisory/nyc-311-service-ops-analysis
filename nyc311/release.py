"""Transactional local reference store with immutable observations and release gates."""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path

from .contracts import ContractError, atomic_json, canonical_json, content_hash, parse_utc, safe_id, utc_now
from .normalize import normalize_rows
from .reference import build_marts, metrics_evidence, write_exports
from .targets import validate_targets

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
 snapshot_id TEXT PRIMARY KEY, input_hash TEXT NOT NULL, scope_hash TEXT NOT NULL,
 observed_at TEXT NOT NULL, source_kind TEXT NOT NULL, capture_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS current_requests (
 scope_hash TEXT NOT NULL, source_kind TEXT NOT NULL, request_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL, snapshot_id TEXT NOT NULL, row_json TEXT NOT NULL,
 PRIMARY KEY(scope_hash, source_kind, request_id)
);
CREATE TABLE IF NOT EXISTS releases (
 release_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, input_hash TEXT NOT NULL,
 metrics_hash TEXT NOT NULL, evidence_json TEXT NOT NULL, marts_json TEXT NOT NULL,
 published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publication (
 slot TEXT PRIMARY KEY CHECK(slot='active'), release_id TEXT NOT NULL
);
"""


def connect_state(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(state_dir / "reference.sqlite")
    connection.executescript(SCHEMA)
    return connection


def input_identity(capture: dict):
    # Extraction interval, observation time, target version and scope are all immutable.
    return content_hash(capture)


def validate_capture(capture: dict):
    manifest = capture["manifest"]
    safe_id(manifest["snapshot_id"])
    parse_utc(manifest["observed_at"])
    if manifest["observed_at"] != manifest["extraction_ended_at"]:
        raise ContractError("Observation as-of time must equal extraction end")
    if parse_utc(manifest["extraction_started_at"]) > parse_utc(manifest["extraction_ended_at"]):
        raise ContractError("Extraction interval is reversed")
    if manifest["source_kind"] not in ("real", "synthetic"):
        raise ContractError("Source kind must explicitly distinguish real and synthetic")
    if not manifest.get("complete") or len(capture["rows"]) != manifest["expected_count"] or len(capture["rows"]) != manifest["source_count"]:
        raise ContractError("Incomplete input cannot become a release")
    if content_hash(capture["rows"]) != manifest["payload_hash"]:
        raise ContractError("Captured row hash mismatch")
    if content_hash(manifest["scope"]) != manifest["scope_hash"]:
        raise ContractError("Captured scope hash mismatch")
    targets, target_hash = validate_targets(capture["targets"])
    if target_hash != manifest["target_version"]:
        raise ContractError("Target input changed under the same captured observation")
    rows = normalize_rows(capture)
    if manifest["source_kind"] == "real":
        scope = manifest["scope"]
        for row in rows:
            local_date = row["created_local_date"]
            if (row["agency"] != scope["agency"] or row["problem"] not in scope["problems"] or
                    local_date is None or not scope["cohort_start"] <= local_date < scope["cohort_end"]):
                raise ContractError("Real captured request falls outside the declared agency/problem/date cohort")
    allowed_statuses = {"closed", "open", "assigned", "in progress", "pending", "started", "unknown", "unspecified", ""}
    unknown_statuses = {str(row["status"] or "").strip().lower() for row in rows} - allowed_statuses
    if unknown_statuses:
        raise ContractError("Unreviewed source status value blocks publication")
    return rows, targets


def publish_local(capture: dict, release_id: str, state_dir: Path, export_dir: Path, simulate_failure=None):
    """Reference runner only. Actual BigQuery/dtb/DAX verification has separate evidence."""
    safe_id(release_id)
    manifest = capture["manifest"]
    audit = {"operation": "local_reference_run", "release_id": release_id,
             "snapshot_id": manifest["snapshot_id"], "started_at": utc_now(), "outcome": "running",
             "source_count": manifest["source_count"], "loaded_count": 0, "rejected_rows": 0,
             "engine": "SQLite persistence + Python reference; not BigQuery"}
    audit_path = state_dir / "audits" / (release_id + "_" + uuid.uuid4().hex[:8] + ".json")
    connection = None
    try:
        rows, targets = validate_capture(capture)
        identity = input_identity(capture)
        connection = connect_state(state_dir)
        existing = connection.execute("SELECT input_hash FROM observations WHERE snapshot_id=?", (manifest["snapshot_id"],)).fetchone()
        if existing and existing[0] != identity:
            raise ContractError("Snapshot ID already exists with different captured inputs")
        prior_release = connection.execute("SELECT input_hash,evidence_json,marts_json FROM releases WHERE release_id=?", (release_id,)).fetchone()
        if prior_release:
            if prior_release[0] != identity:
                raise ContractError("Release ID already exists with different captured inputs")
            evidence, marts = json.loads(prior_release[1]), json.loads(prior_release[2])
            # Replay restores identical exports; it never rewrites the selected publication.
            write_exports(marts, export_dir / release_id)
            atomic_json(export_dir / release_id / "verification.json", evidence)
            active = connection.execute("SELECT release_id FROM publication WHERE slot='active'").fetchone()
            if active and active[0] == release_id:
                atomic_json(state_dir / "published.json", {"release_id": release_id, "snapshot_id": manifest["snapshot_id"],
                    "observed_at": manifest["observed_at"], "marts_hash": evidence["marts_hash"], "verification_engine": evidence["verification_engine"]})
            audit.update(outcome="replayed", loaded_count=len(rows), metrics_hash=evidence["marts_hash"])
            return dict(outcome="replayed", release_id=release_id, **{k: evidence[k] for k in ("overall", "marts_hash")})
        current = connection.execute("SELECT request_id,payload_hash FROM current_requests WHERE scope_hash=? AND source_kind=?",
                                     (manifest["scope_hash"], manifest["source_kind"])).fetchall()
        current_hashes = dict(current)
        captured_keys = {row["request_id"] for row in rows}
        disappeared = set(current_hashes) - captured_keys
        if disappeared:
            audit["disappeared_count"] = len(disappeared)
            raise ContractError("Requests disappeared from a complete extract; retain previous release and investigate")
        later = connection.execute("SELECT max(observed_at) FROM observations WHERE scope_hash=? AND source_kind=?",
                                   (manifest["scope_hash"], manifest["source_kind"])).fetchone()[0]
        if later and parse_utc(manifest["observed_at"]) < parse_utc(later):
            raise ContractError("Cannot promote an older unseen capture over a newer current state")
        history = []
        for (capture_json,) in connection.execute("SELECT capture_json FROM observations WHERE scope_hash=? AND source_kind=? AND snapshot_id!=? ORDER BY observed_at,snapshot_id",
                                                  (manifest["scope_hash"], manifest["source_kind"], manifest["snapshot_id"])):
            prior = json.loads(capture_json)
            if parse_utc(prior["manifest"]["observed_at"]) <= parse_utc(manifest["observed_at"]):
                history.append((normalize_rows(prior), prior["manifest"], prior["targets"]))
        marts = build_marts(rows, manifest, targets, release_id, history)
        evidence = metrics_evidence(marts, manifest, release_id)
        if evidence["overall"]["case_count"] != manifest["source_count"]:
            raise ContractError("Case count changed during transformation")
        if simulate_failure == "validation":
            raise ContractError("Simulated validation failure; publication unchanged")
        # Candidate output stays outside the reporting tree. The release metadata
        # file is the last publication marker Power BI requires before importing.
        candidate_dir = state_dir / "candidates" / release_id
        write_exports(marts, candidate_dir)
        atomic_json(candidate_dir / "verification.json", evidence)
        destination = export_dir / release_id
        destination.mkdir(parents=True, exist_ok=True)
        if (destination / "release_metadata.csv").exists():
            raise ContractError("Unregistered report metadata already exists; investigate before publishing")
        for candidate_file in candidate_dir.iterdir():
            if candidate_file.name != "release_metadata.csv":
                shutil.copyfile(candidate_file, destination / candidate_file.name)
        with connection:
            connection.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)",
                               (manifest["snapshot_id"], identity, manifest["scope_hash"], manifest["observed_at"], manifest["source_kind"], canonical_json(capture)))
            inserted, updated, unchanged = 0, 0, 0
            for row in rows:
                old_hash = current_hashes.get(row["request_id"])
                inserted += old_hash is None
                updated += old_hash is not None and old_hash != row["payload_hash"]
                unchanged += old_hash == row["payload_hash"]
                connection.execute("""INSERT INTO current_requests VALUES (?,?,?,?,?,?)
                    ON CONFLICT(scope_hash,source_kind,request_id) DO UPDATE SET
                    payload_hash=excluded.payload_hash,snapshot_id=excluded.snapshot_id,row_json=excluded.row_json
                    WHERE current_requests.payload_hash != excluded.payload_hash""",
                    (manifest["scope_hash"], manifest["source_kind"], row["request_id"], row["payload_hash"], manifest["snapshot_id"], canonical_json(row)))
            if simulate_failure == "publication":
                raise ContractError("Simulated publication failure; transaction rolled back")
            connection.execute("INSERT INTO releases VALUES (?,?,?,?,?,?,?)", (release_id, manifest["snapshot_id"], identity,
                               evidence["marts_hash"], canonical_json(evidence), canonical_json(marts), utc_now()))
            connection.execute("INSERT INTO publication VALUES ('active',?) ON CONFLICT(slot) DO UPDATE SET release_id=excluded.release_id", (release_id,))
        audit.update(outcome="published", loaded_count=len(rows), inserted_count=inserted, changed_count=updated,
                     unchanged_count=unchanged, temporal_rejected_rows=sum(r["temporal_quality"] != "valid" for r in rows),
                     metrics_hash=evidence["marts_hash"], source_freshness_seconds=(parse_utc(manifest["observed_at"]) - parse_utc(manifest["extraction_started_at"])).total_seconds())
        shutil.copyfile(candidate_dir / "release_metadata.csv", destination / "release_metadata.csv")
        atomic_json(state_dir / "published.json", {"release_id": release_id, "snapshot_id": manifest["snapshot_id"],
                     "observed_at": manifest["observed_at"], "marts_hash": evidence["marts_hash"], "verification_engine": evidence["verification_engine"]})
        return dict(outcome="published", release_id=release_id, inserted_count=inserted, changed_count=updated,
                    **{k: evidence[k] for k in ("overall", "marts_hash")})
    except Exception as exc:
        audit.update(outcome="failed", error_type=type(exc).__name__, error_detail=str(exc) if isinstance(exc, ContractError) else "Unexpected local failure; inspect local exception")
        raise
    finally:
        if connection:
            connection.close()
        audit["ended_at"] = utc_now()
        atomic_json(audit_path, audit)
