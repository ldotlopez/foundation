from datetime import datetime, timezone


def now_local_ts() -> float:
    return datetime.now().timestamp()


def now_utc_ts() -> float:
    return datetime.now(timezone.utc).timestamp()
