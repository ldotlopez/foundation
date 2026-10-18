import sqlite3


def create_maintenance_clock(cursor: sqlite3.Cursor, now: float) -> None:
    """Create the single-row table holding the last maintenance time.

    A new clock starts at now: a fresh store needs no maintenance.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_clock (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_run REAL NOT NULL
        )
        """
    )
    cursor.execute(
        "INSERT OR IGNORE INTO maintenance_clock (id, last_run) VALUES (1, ?)", (now,)
    )


def claim_maintenance(cursor: sqlite3.Cursor, interval: float, now: float) -> bool:
    """Record a maintenance run at now if the last one is at least interval old.

    Check and update are one statement, so concurrent callers cannot both
    claim the same run.
    """
    cursor.execute(
        "UPDATE maintenance_clock SET last_run = ? WHERE id = 1 AND last_run <= ?",
        (now, now - interval),
    )
    return cursor.rowcount == 1
