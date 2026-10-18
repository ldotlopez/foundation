import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from foundation.dblib import SQLite3DB
from foundation.dtlib import timestamp_as_dt_aware
from foundation.jsonlib import dump_json_compatible, load_json_compatible
from foundation.scrapelib import (
    drop_selectors,
    head_meta_get_value_by_name,
    markdownify,
    prune_to_spine,
    soupify,
)
from foundation.textlib import slugify


class UtilityTests(unittest.TestCase):
    def test_json_round_trips_datetime_sets_and_nested_values(self) -> None:
        timestamp = datetime(2025, 1, 2, 3, 4, tzinfo=UTC)
        value = {
            "timestamp": timestamp,
            "tags": {"alpha", "beta"},
            "items": [None, 1, "text"],
        }

        self.assertEqual(load_json_compatible(dump_json_compatible(value)), value)

    def test_timestamp_conversion_returns_requested_aware_timezone(self) -> None:
        converted = timestamp_as_dt_aware(0, ZoneInfo("America/New_York"))

        self.assertEqual(
            converted, datetime(1969, 12, 31, 19, tzinfo=ZoneInfo("America/New_York"))
        )
        self.assertIsNotNone(converted.tzinfo)

    def test_slugify_replaces_each_non_alphanumeric_character(self) -> None:
        self.assertEqual(slugify("Hello, world!", separator="_"), "Hello__world_")

    def test_scraping_helpers_parse_prune_and_convert_markup(self) -> None:
        soup = soupify(
            "<html><head><meta name='description' content='  summary  '></head>"
            "<body><main><aside>remove</aside><article><h1>Title</h1>"
            "<p>Keep this text.</p><span class='remove'>remove</span></article>"
            "<footer>remove</footer></main></body></html>"
        )
        self.assertEqual(head_meta_get_value_by_name(soup, "description"), "summary")

        article = soup.article
        self.assertIsNotNone(article)
        drop_selectors(article, [".remove", "aside"])
        spine = prune_to_spine(article)

        self.assertEqual(
            spine.select_one("article").get_text(" ", strip=True),
            "Title Keep this text.",
        )
        self.assertNotIn("aside", str(spine))
        self.assertIn("# Title", markdownify(article))


class SQLite3DBTests(unittest.TestCase):
    def test_dict_rows_can_be_enabled_for_the_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = SQLite3DB(
                Path(temporary_directory) / "records.sqlite3", use_dict_rows=True
            )
            database.db.execute("CREATE TABLE records (value TEXT)")
            database.db.execute("INSERT INTO records VALUES (?)", ("stored",))

            self.assertEqual(
                database.db.execute("SELECT value FROM records").fetchone(),
                {"value": "stored"},
            )
            database.close()

    def test_custom_row_factory_takes_precedence_over_dict_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = SQLite3DB(
                Path(temporary_directory) / "records.sqlite3",
                use_dict_rows=True,
                row_factory=sqlite3.Row,
            )
            database.db.execute("CREATE TABLE records (value TEXT)")
            database.db.execute("INSERT INTO records VALUES (?)", ("stored",))

            row = database.db.execute("SELECT value FROM records").fetchone()
            self.assertIsInstance(row, sqlite3.Row)
            self.assertEqual(row["value"], "stored")
            database.close()

    def test_connection_applies_recommended_pragmas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = SQLite3DB(Path(temporary_directory) / "records.sqlite3")

            self.assertEqual(
                database.db.execute("PRAGMA foreign_keys").fetchone(), (1,)
            )
            self.assertEqual(
                database.db.execute("PRAGMA busy_timeout").fetchone(), (5000,)
            )
            self.assertTrue(database.db.autocommit)
            self.assertEqual(
                database.db.execute("PRAGMA journal_mode").fetchone(), ("wal",)
            )
            self.assertEqual(database.db.execute("PRAGMA synchronous").fetchone(), (1,))
            self.assertEqual(database.db.execute("PRAGMA temp_store").fetchone(), (2,))
            database.close()

    def test_transition_commits_and_rolls_back_while_propagating_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = SQLite3DB(Path(temporary_directory) / "records.sqlite3")
            database.db.execute("CREATE TABLE records (value TEXT)")

            with database.transition() as cursor:
                cursor.execute("INSERT INTO records VALUES (?)", ("committed",))

            failure = RuntimeError("body failed")
            with (
                self.assertRaises(RuntimeError) as raised,
                database.transition() as cursor,
            ):
                cursor.execute("INSERT INTO records VALUES (?)", ("rolled back",))
                raise failure

            self.assertIs(raised.exception, failure)
            self.assertEqual(
                database.db.execute("SELECT value FROM records").fetchall(),
                [("committed",)],
            )
            self.assertFalse(database.db.in_transaction)
            database.close()

    def test_transition_rolls_back_sqlite_errors_from_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = SQLite3DB(Path(temporary_directory) / "records.sqlite3")
            database.db.execute("CREATE TABLE records (value TEXT UNIQUE)")

            with (
                self.assertRaises(sqlite3.IntegrityError),
                database.transition() as cursor,
            ):
                cursor.execute("INSERT INTO records VALUES (?)", ("duplicate",))
                cursor.execute("INSERT INTO records VALUES (?)", ("duplicate",))

            self.assertEqual(
                database.db.execute("SELECT value FROM records").fetchall(), []
            )
            database.close()

    def test_nested_transition_does_not_rollback_outer_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = SQLite3DB(Path(temporary_directory) / "records.sqlite3")
            database.db.execute("CREATE TABLE records (value TEXT)")

            with database.transition() as cursor:
                self.assertRaisesRegex(
                    RuntimeError,
                    "cannot be nested",
                    database.transition().__enter__,
                )
                cursor.execute("INSERT INTO records VALUES (?)", ("committed",))

            self.assertEqual(
                database.db.execute("SELECT value FROM records").fetchall(),
                [("committed",)],
            )
            database.close()


if __name__ == "__main__":
    unittest.main()
