import sqlite3


def create_cleanup_clock(cursor: sqlite3.Cursor, now: float) -> None:
    """Create the single-row table holding the last cleanup time.

    A new clock starts at now: a fresh store has nothing to clean.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS cleanup_clock (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_run REAL NOT NULL
        )
        """
    )
    cursor.execute(
        "INSERT OR IGNORE INTO cleanup_clock (id, last_run) VALUES (1, ?)", (now,)
    )


def claim_cleanup(cursor: sqlite3.Cursor, interval: float, now: float) -> bool:
    """Record a cleanup at now if the last one is at least interval old.

    Check and update are one statement, so concurrent openers cannot both
    claim the same run.
    """
    cursor.execute(
        "UPDATE cleanup_clock SET last_run = ? WHERE id = 1 AND last_run <= ?",
        (now, now - interval),
    )
    return cursor.rowcount == 1
