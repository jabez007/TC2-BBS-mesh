import sqlite3
import unittest
from unittest.mock import patch

import database_core


def get_table_names(conn):
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


class InitializeDatabaseSavepointTests(unittest.TestCase):
    def test_initialize_database_rolls_back_nested_changes_and_releases_savepoint(self):
        conn = sqlite3.connect(":memory:")
        statements = []
        conn.set_trace_callback(statements.append)

        try:
            conn.execute("BEGIN")
            conn.execute("CREATE TABLE outer_table (id INTEGER)")

            with patch.object(database_core, "get_db_connection", return_value=conn), patch.object(
                database_core,
                "_migrate_legacy_data",
                side_effect=sqlite3.Error("boom"),
            ):
                self.assertFalse(database_core.initialize_database())

            self.assertTrue(
                any(statement.startswith("SAVEPOINT ") for statement in statements),
                statements,
            )
            self.assertTrue(
                any(statement.startswith("ROLLBACK TO SAVEPOINT ") for statement in statements),
                statements,
            )
            self.assertTrue(
                any(statement.startswith("RELEASE SAVEPOINT ") for statement in statements),
                statements,
            )
            self.assertEqual(get_table_names(conn), {"outer_table"})
            self.assertTrue(conn.in_transaction)

            conn.execute("CREATE TABLE outer_after_failure (id INTEGER)")
            conn.commit()

            self.assertEqual(
                get_table_names(conn),
                {"outer_after_failure", "outer_table"},
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
