import sqlite3
from abc import abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SQLite3DB:
    def __init__(self, db_path: Path):
        self.db = sqlite3.Connection(db_path.as_posix())
        # if self.sqlite3_db_row_factory != SQLite3DB.sqlite3_db_row_factory:
        #     self.db.row_factory = self.sqlite3_db_row_factory

    # Warning: don't change this without checking all the code that uses cursors
    # for doing nested iterations over data
    @property
    def cursor(self) -> sqlite3.Cursor:
        return self.db.cursor()

    @contextmanager
    def transition(self) -> Iterator[sqlite3.Cursor]:
        c = self.cursor
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except sqlite3.Error:
            c.execute("ROLLBACK")

    @abstractmethod
    def sqlite3_db_row_factory(self, cursor: sqlite3.Cursor, row: tuple) -> Any:
        raise NotImplementedError()
