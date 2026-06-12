import sqlite3
import threading
import unittest
from unittest.mock import patch

import pytest

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


class FakeConnection:
    def __init__(self, on_execute=None):
        self.on_execute = on_execute
        self.executed = []
        self.close_calls = 0

    def execute(self, sql):
        self.executed.append(sql)
        if self.on_execute is not None:
            return self.on_execute(self, sql)
        return None

    def close(self):
        self.close_calls += 1


@pytest.fixture(autouse=True)
def reset_database_core_state(monkeypatch):
    with database_core._connections_lock:
        database_core._connections.clear()

    for attr in ("connection", "conn_version"):
        if hasattr(database_core.thread_local, attr):
            delattr(database_core.thread_local, attr)

    monkeypatch.setattr(database_core, "_db_path_version", 0)
    monkeypatch.setattr(database_core, "_custom_db_path", None)
    monkeypatch.setattr(database_core, "get_db_path", lambda: "/tmp/test.db")

    yield

    with database_core._connections_lock:
        database_core._connections.clear()

    for attr in ("connection", "conn_version"):
        if hasattr(database_core.thread_local, attr):
            delattr(database_core.thread_local, attr)


def test_get_db_connection_closes_new_connection_when_pragma_setup_fails(monkeypatch):
    def raise_pragma_error(_conn, sql):
        if sql == "PRAGMA journal_mode=WAL":
            raise sqlite3.OperationalError("journal mode failed")
        return None

    fake_conn = FakeConnection(on_execute=raise_pragma_error)
    monkeypatch.setattr(database_core.sqlite3, "connect", lambda *args, **kwargs: fake_conn)

    assert database_core.get_db_connection() is None
    assert fake_conn.close_calls == 1
    assert not hasattr(database_core.thread_local, "connection")
    assert threading.get_ident() not in database_core._connections


def test_get_db_connection_closes_new_connection_before_reraising_non_sqlite_errors(monkeypatch):
    def raise_runtime_error(_conn, sql):
        if sql == "PRAGMA journal_mode=WAL":
            raise RuntimeError("unexpected setup failure")
        return None

    fake_conn = FakeConnection(on_execute=raise_runtime_error)
    monkeypatch.setattr(database_core.sqlite3, "connect", lambda *args, **kwargs: fake_conn)

    with pytest.raises(RuntimeError, match="unexpected setup failure"):
        database_core.get_db_connection()

    assert fake_conn.close_calls == 1
    assert not hasattr(database_core.thread_local, "connection")
    assert threading.get_ident() not in database_core._connections


def test_get_db_connection_closes_transient_connection_before_retrying_version_change(monkeypatch):
    first_conn = FakeConnection()
    second_conn = FakeConnection()
    connections = iter((first_conn, second_conn))

    def fake_connect(*args, **kwargs):
        conn = next(connections)
        if conn is first_conn:
            def bump_version_on_second_pragma(_conn, sql):
                if sql == "PRAGMA synchronous=NORMAL":
                    database_core._db_path_version += 1
                return None

            conn.on_execute = bump_version_on_second_pragma
        return conn

    monkeypatch.setattr(database_core.sqlite3, "connect", fake_connect)
    monkeypatch.setattr(database_core.time, "sleep", lambda _seconds: None)

    conn = database_core.get_db_connection()

    assert conn is second_conn
    assert first_conn.close_calls == 1
    assert second_conn.close_calls == 0
    assert database_core.thread_local.connection is second_conn
    assert database_core.thread_local.conn_version == database_core._db_path_version
    assert database_core._connections[threading.get_ident()] is second_conn


if __name__ == "__main__":
    unittest.main()
