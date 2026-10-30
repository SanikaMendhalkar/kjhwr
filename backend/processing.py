"""Point-in-time forecast selection and interval matching."""
from __future__ import annotations
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

LONDON = ZoneInfo("Europe/London")

def parse_utc(value: str | datetime | None) -> datetime | None:
    if value is None or value == "": return None
    if isinstance(value, datetime): dt = value
    else: dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None: raise ValueError("Timestamp must include a timezone")
    return dt.astimezone(timezone.utc)

def cutoff_utc(delivery_date: date, cutoff_time: time) -> datetime:
    """Convert the configured D-1 Europe/London wall-clock cutoff to UTC."""
    local = datetime.combine(delivery_date - timedelta(days=1), cutoff_time, LONDON)
    return local.astimezone(timezone.utc)

def select_forecasts(records: list[dict[str, Any]], delivery_date: date, cutoff_time: time) -> dict[str, dict[str, Any]]:
    """Select latest eligible publication for each target interval; input duplicates are already normalized."""
    limit = cutoff_utc(delivery_date, cutoff_time)
    selected: dict[str, dict[str, Any]] = {}
    for row in records:
        target = parse_utc(row.get("startTime")); published = parse_utc(row.get("publishTime"))
        if not target or target.astimezone(LONDON).date() != delivery_date or not published or published > limit: continue
        key = target.isoformat()
        prior = selected.get(key)
        if prior is None or parse_utc(prior["publishTime"]) < published: selected[key] = row
    return selected

def horizon_hours(start_time: str | datetime, publish_time: str | datetime) -> float:
    start, published = parse_utc(start_time), parse_utc(publish_time)
    if start is None or published is None: raise ValueError("Horizon timestamps are required")
    return (start - published).total_seconds() / 3600

def horizon_bucket(hours: float) -> str:
    if hours < 0: raise ValueError("Forecast horizon cannot be negative")
    for edge, label in [(6,"0–6 h"),(12,"6–12 h"),(24,"12–24 h"),(48,"24–48 h")]:
        if hours < edge: return label
    return "48+ h"
