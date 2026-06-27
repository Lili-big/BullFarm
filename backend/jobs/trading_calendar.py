from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.settings import get_settings


CALENDAR_CONFIG = Path("config/trading_calendar.json")
DATE_FORMATS = ("%Y%m%d", "%Y-%m-%d")


def parse_compact_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")

    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise ValueError(f"Expected YYYYMMDD or YYYY-MM-DD, got {value!r}.")


def iso_date(value: str | date | datetime) -> str:
    return datetime.strptime(parse_compact_date(value), "%Y%m%d").date().isoformat()


def app_timezone():
    settings = get_settings()
    try:
        return ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=8))


def local_datetime(now: datetime | None = None) -> datetime:
    tz = app_timezone()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def calendar_path(project_root: Path | None = None) -> Path:
    root = project_root or get_settings().project_root
    return root / CALENDAR_CONFIG


def _date_values(payload: dict[str, Any], *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        raw_values = payload.get(key) or []
        if isinstance(raw_values, dict):
            raw_values = raw_values.keys()
        values.update(parse_compact_date(value) for value in raw_values)
    return values


def load_trading_calendar(project_root: Path | None = None) -> dict[str, set[str]]:
    path = calendar_path(project_root)
    payload: dict[str, Any] = {}
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8-sig"))

    return {
        "holidays": _date_values(payload, "holidays", "closed_days", "non_trading_days"),
        "makeup_trading_days": _date_values(payload, "makeup_trading_days", "open_days"),
        "trading_days": _date_values(payload, "trading_days"),
    }


def is_trading_day(value: str | date | datetime, project_root: Path | None = None) -> bool:
    key = parse_compact_date(value)
    calendar = load_trading_calendar(project_root)
    if calendar["trading_days"]:
        return key in calendar["trading_days"]
    if key in calendar["makeup_trading_days"]:
        return True
    if key in calendar["holidays"]:
        return False
    day = datetime.strptime(key, "%Y%m%d").date()
    return day.weekday() < 5


def previous_trading_day(value: str | date | datetime, project_root: Path | None = None) -> date:
    key = parse_compact_date(value)
    current = datetime.strptime(key, "%Y%m%d").date() - timedelta(days=1)
    while not is_trading_day(current, project_root=project_root):
        current -= timedelta(days=1)
    return current


def previous_trading_day_key(now: datetime | None = None, project_root: Path | None = None) -> str:
    return previous_trading_day(local_datetime(now), project_root=project_root).strftime("%Y%m%d")


def is_current_trading_day(now: datetime | None = None, project_root: Path | None = None) -> bool:
    return is_trading_day(local_datetime(now).date(), project_root=project_root)
