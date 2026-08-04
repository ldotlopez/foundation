from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

UTC_TZ = ZoneInfo("UTC")


def now_local_ts() -> float:
    return datetime.now().timestamp()


def now_utc_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def get_local_tz() -> tzinfo:
    """Get the system local timezone."""

    tz = datetime.now().astimezone().tzinfo
    if tz is None:
        raise ValueError("Could not determine the system local timezone.")

    return tz


def timestamp_as_dt_aware(ts: float | int, tz: tzinfo | None = None) -> datetime:
    """Convert POSIX timestamp (seconds since the epoch, UTC) to an aware datetime in the given tz.

    Interprets the numeric timestamp as UTC to avoid accidental local-time interpretation, then
    converts to the requested timezone.
    """

    tz = tz or get_local_tz()
    dt = datetime.fromtimestamp(ts, tz=UTC_TZ).astimezone(tz)

    return dt
