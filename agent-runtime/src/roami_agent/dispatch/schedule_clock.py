"""Daily reminders use local calendar dates, including skipped and repeated clock times."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roami_agent.protocol.errors import DomainError


def zone(name):
    try:
        if not isinstance(name, str) or not 1 <= len(name) <= 100:
            raise ValueError
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise DomainError("INVALID_SCHEDULE_TIMEZONE") from exc


def minute(value):
    try:
        if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
            raise ValueError
        hour, part = int(value[:2]), int(value[3:])
        if value != f"{hour:02}:{part:02}":
            raise ValueError
        return time(hour, part)
    except (ValueError, TypeError) as exc:
        raise DomainError("INVALID_SCHEDULE_TIME") from exc


def local_instant(day: date, clock: time, timezone_name: str):
    tz = zone(timezone_name)
    label = datetime.combine(day, clock)
    # A spring-forward gap executes at the first valid local minute after the gap.
    for shift in range(181):
        candidate = label + timedelta(minutes=shift)
        for fold in (0, 1):
            instant = candidate.replace(tzinfo=tz, fold=fold)
            if instant.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == candidate:
                return int(instant.timestamp() * 1000)
    raise DomainError("INVALID_SCHEDULE_TIME")


def next_daily(after_ms, daily_at, timezone_name):
    tz, clock = zone(timezone_name), minute(daily_at)
    day = datetime.fromtimestamp(after_ms / 1000, tz).date()
    for offset in range(3):
        due = local_instant(day + timedelta(days=offset), clock, timezone_name)
        if due > after_ms:
            return due
    raise DomainError("INVALID_SCHEDULE_TIME")


def latest_daily(at_ms, daily_at, timezone_name):
    tz, clock = zone(timezone_name), minute(daily_at)
    day = datetime.fromtimestamp(at_ms / 1000, tz).date()
    due = local_instant(day, clock, timezone_name)
    return due if due <= at_ms else local_instant(day - timedelta(days=1), clock, timezone_name)
