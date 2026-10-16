import sqlite3
from abc import abstractmethod
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class SQLite3DB:
    def __init__(self, db_path: Path) -> None:
        self.db: sqlite3.Connection = sqlite3.Connection(db_path.as_posix())
        # if self.sqlite3_db_row_factory != SQLite3DB.sqlite3_db_row_factory:
        #     self.db.row_factory = self.sqlite3_db_row_factory

    # Warning: don't change this without checking all the code that uses cursors
    # for doing nested iterations over data
    @property
    def cursor(self) -> sqlite3.Cursor:
        return self.db.cursor()

    @contextmanager
    def transition(self) -> Generator[sqlite3.Cursor]:
        c = self.cursor
        c.execute("BEGIN")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                c.execute("ROLLBACK")
            raise

    @abstractmethod
    def sqlite3_db_row_factory(
        self, cursor: sqlite3.Cursor, row: tuple[Any, ...]
    ) -> Any:
        raise NotImplementedError()
