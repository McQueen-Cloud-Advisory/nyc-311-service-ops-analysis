"""Interpret naive NYC source timestamps conservatively at DST transitions."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .contracts import parse_utc

NYC = ZoneInfo("America/New_York")


def local_timestamp(value: str | None, field: str):
    if value is None or not str(value).strip():
        return None, None, "missing_created" if field == "created" else "valid"
    try:
        local = datetime.fromisoformat(str(value))
        if local.tzinfo is not None:
            return None, None, f"invalid_{field}"
    except (ValueError, TypeError):
        return None, None, f"invalid_{field}"
    choices = set()
    for fold in (0, 1):
        candidate = local.replace(tzinfo=NYC, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(NYC).replace(tzinfo=None) == local:
            choices.add(candidate)
    if not choices:
        return None, local.date().isoformat(), f"nonexistent_{field}"
    if len(choices) > 1:
        return None, local.date().isoformat(), f"ambiguous_{field}"
    return choices.pop().isoformat(), local.date().isoformat(), "valid"


def normalize_temporal(created: str | None, closed: str | None, observed_at: str) -> dict:
    created_at, created_local_date, created_quality = local_timestamp(created, "created")
    closed_at, closed_local_date, closed_quality = local_timestamp(closed, "closed")
    quality = created_quality if created_quality != "valid" else closed_quality
    if quality == "valid":
        observation = parse_utc(observed_at)
        if created_at and parse_utc(created_at) > observation:
            quality = "future_created"
        elif closed_at and parse_utc(closed_at) > observation:
            quality = "future_closed"
        elif created_at and closed_at and parse_utc(closed_at) < parse_utc(created_at):
            quality = "negative_elapsed"
    return dict(created_at=created_at, closed_at=closed_at,
                created_local_date=created_local_date, closed_local_date=closed_local_date,
                temporal_quality=quality)
