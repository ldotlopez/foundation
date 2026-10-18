import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

__all__ = [
    "SQLITE_PRAGMAS",
    "RowFactory",
    "SQLite3DB",
    "configure_connection",
    "dict_row_factory",
]

type RowFactory = Callable[[sqlite3.Cursor, tuple[Any, ...]], Any]

# Connection settings every foundation SQLite connection gets; see SQLite3DB.
SQLITE_PRAGMAS = (
    "foreign_keys = ON",
    "busy_timeout = 5000",
    "journal_mode = WAL",
    "synchronous = NORMAL",
    "temp_store = MEMORY",
)


def configure_connection(connection: sqlite3.Connection) -> None:
    """Apply SQLITE_PRAGMAS to a connection opened elsewhere (e.g. by SQLAlchemy)."""
    for pragma in SQLITE_PRAGMAS:
        connection.execute(f"PRAGMA {pragma}")


def dict_row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a SQLite row to a dictionary keyed by column name."""
    columns = cursor.description
    if columns is None:
        raise RuntimeError("SQLite returned a row without column metadata")
    return {column[0]: value for column, value in zip(columns, row, strict=True)}


class SQLite3DB:
    """Small SQLite connection wrapper with explicit transactions.

    File-backed databases use WAL with NORMAL synchronous mode. This
    supports concurrent readers and reduces write synchronization overhead;
    NORMAL mode may lose recent committed transactions after power loss, but
    keeps the database consistent. Use SQLite's backup API while open rather
    than copying only the main database file.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        use_dict_rows: bool = False,
        row_factory: RowFactory | None = None,
    ) -> None:
        self.db = sqlite3.connect(db_path, timeout=5.0, autocommit=True)
        if row_factory is not None:
            self.db.row_factory = row_factory
        elif use_dict_rows:
            self.db.row_factory = dict_row_factory
        configure_connection(self.db)

    @property
    def cursor(self) -> sqlite3.Cursor:
        return self.db.cursor()

    @contextmanager
    def transition(self) -> Generator[sqlite3.Cursor]:
        if self.db.in_transaction:
            raise RuntimeError("SQLite3DB transitions cannot be nested")

        c = self.cursor
        try:
            c.execute("BEGIN")
            yield c
            c.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def close(self) -> None:
        self.db.close()
