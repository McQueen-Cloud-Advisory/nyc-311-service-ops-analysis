"""Input contracts, stable identities, and safe local state operations."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

SOURCE_FIELDS = (
    "unique_key", "created_date", "closed_date", "agency", "complaint_type",
    "status", "borough", "open_data_channel_type",
)
SOURCE_TYPES = {field: "text" for field in SOURCE_FIELDS} | {
    "created_date": "calendar_date", "closed_date": "calendar_date",
}
REPO_ROOT = Path(__file__).resolve().parents[1]


class ContractError(ValueError):
    """An input cannot be accepted or a release cannot be published."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ContractError("IDs must match [a-z][a-z0-9_]{0,62}")
    return value


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ContractError("Observation time must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def load_config(path: Path) -> dict:
    cfg = read_json(path)
    if cfg.get("dataset_id") != "erm2-nwe9":
        raise ContractError("Only the reviewed official NYC 311 source is allowed")
    if cfg.get("source_timezone") != "America/New_York":
        raise ContractError("Source timezone must be America/New_York")
    start, end = date.fromisoformat(cfg["cohort_start"]), date.fromisoformat(cfg["cohort_end"])
    if not 56 <= (end - start).days <= 84:
        raise ContractError("The real creation cohort must span 8–12 weeks")
    if not cfg.get("agency") or not 2 <= len(set(cfg["problems"])) <= 3:
        raise ContractError("Select one agency and two or three unique problems")
    if not 1 <= cfg["page_size"] <= 50000 or not 1 <= cfg["maximum_rows"] <= 500000:
        raise ContractError("Invalid bounded extraction limits")
    if not 1 <= cfg.get("maximum_attempts", 5) <= 8:
        raise ContractError("Maximum attempts must be between 1 and 8")
    return cfg


@contextlib.contextmanager
def operator_lock(state_dir: Path):
    """Exclusive single-operator lock. A crashed process requires explicit recovery."""
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / "operator.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ContractError("Another operation holds operator.lock; see the recovery runbook") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical_json({"pid": os.getpid(), "started_at": utc_now()}))
        yield
    finally:
        lock.unlink(missing_ok=True)
