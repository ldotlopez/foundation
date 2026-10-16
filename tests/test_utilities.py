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
            database.db.close()

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
            database.db.close()


if __name__ == "__main__":
    unittest.main()
