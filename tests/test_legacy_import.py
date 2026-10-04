"""Upgrading from the pre-refactor bulletins.db and js8call.db files."""

import importlib
import logging
import sqlite3
import sys

import pytest

import database_core

# Schemas as created by db_operations.py and js8call_integration.py on main.
MAIN_BULLETINS_SCHEMA = """
CREATE TABLE bulletins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board TEXT NOT NULL,
    sender_short_name TEXT NOT NULL,
    date TEXT NOT NULL,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    unique_id TEXT NOT NULL
);
CREATE TABLE mail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL,
    sender_short_name TEXT NOT NULL,
    recipient TEXT NOT NULL,
    date TEXT NOT NULL,
    subject TEXT NOT NULL,
    content TEXT NOT NULL,
    unique_id TEXT NOT NULL
);
CREATE TABLE channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL
);
"""

MAIN_JS8CALL_SCHEMA = """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT, receiver TEXT, message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT, groupname TEXT, message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE urgent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT, groupname TEXT, message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def make_main_bulletins_db(path, mail_unique_ids=("mail-1",)):
    conn = sqlite3.connect(path)
    conn.executescript(MAIN_BULLETINS_SCHEMA)
    conn.execute(
        "INSERT INTO bulletins (board, sender_short_name, date, subject, content, unique_id) "
        "VALUES ('General', 'SNDR', '2026-01-01 10:00', 'Swap meet', 'Saturday', 'bul-1')"
    )
    for unique_id in mail_unique_ids:
        conn.execute(
            "INSERT INTO mail (sender, sender_short_name, recipient, date, subject, content, unique_id) "
            "VALUES ('!00001234', 'SNDR', '!0000abcd', '2026-01-01 10:00', 'Hello', 'Hi there', ?)",
            (unique_id,),
        )
    conn.execute("INSERT INTO channels (name, url) VALUES ('Local', 'https://meshtastic.org/e/#abc')")
    conn.commit()
    conn.close()


def make_main_js8call_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(MAIN_JS8CALL_SCHEMA)
    conn.execute("INSERT INTO messages (sender, receiver, message) VALUES ('K1ABC', 'W2XYZ', 'QSL')")
    conn.execute("INSERT INTO urgent (sender, groupname, message) VALUES ('K1ABC', '@URGNT', 'Flooding')")
    conn.commit()
    conn.close()


@pytest.fixture
def app_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    database_core.set_db_path(str(tmp_path / "bbs.db"))
    yield tmp_path
    database_core.close_db_connection()
    database_core.set_db_path(None)


@pytest.fixture
def mesh(app_dir):
    sys.modules.pop("mesh_integration", None)
    return importlib.import_module("mesh_integration")


def test_upgrade_imports_mesh_data_from_bulletins_db(app_dir, mesh):
    make_main_bulletins_db(app_dir / "bulletins.db")

    assert database_core.initialize_database()

    assert [row[1] for row in mesh.get_bulletins("General")] == ["Swap meet"]
    assert [row[2] for row in mesh.get_mail("!0000abcd")] == ["Hello"]
    assert mesh.get_channels() == [("Local", "https://meshtastic.org/e/#abc")]


def test_upgrade_imports_js8call_history_from_js8call_db(app_dir):
    make_main_js8call_db(app_dir / "js8call.db")

    assert database_core.initialize_database()

    import db_admin

    assert [row[1:4] for row in db_admin.list_ham_messages()] == [("K1ABC", "W2XYZ", "QSL")]


def restart():
    """Drops cached connections the way a fresh process would start."""
    database_core.close_db_connection()
    database_core.set_db_path(database_core.get_db_path())


def test_mail_deleted_after_upgrade_stays_deleted_on_restart(app_dir, mesh):
    make_main_bulletins_db(app_dir / "bulletins.db")
    assert database_core.initialize_database()
    assert mesh.delete_mail("mail-1", "!0000abcd", [], None)

    restart()
    assert database_core.initialize_database()

    assert mesh.get_mail("!0000abcd") == []


def test_upgrade_warns_about_rows_it_could_not_import(app_dir, caplog):
    # Main didn't enforce unique mail IDs; the new schema does.
    make_main_bulletins_db(app_dir / "bulletins.db", mail_unique_ids=("dup", "dup"))

    with caplog.at_level(logging.WARNING, logger="database_core"):
        assert database_core.initialize_database()

    assert "Skipped 1 of 2 rows" in caplog.text


def test_in_place_migration_keeps_earlier_backups(app_dir, mesh):
    db_file = app_dir / "bbs.db"
    make_main_bulletins_db(db_file, mail_unique_ids=("first",))
    assert database_core.initialize_database()

    # An older release run against the same file recreates the old tables.
    restart()
    make_main_bulletins_db(db_file, mail_unique_ids=("second",))
    restart()
    assert database_core.initialize_database()

    conn = sqlite3.connect(db_file)
    backups = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'legacy_mail%'")}
    conn.close()
    assert backups == {"legacy_mail", "legacy_mail_2"}
    assert sorted(row[4] for row in mesh.get_mail("!0000abcd")) == ["first", "second"]


def test_unreadable_legacy_file_does_not_block_startup_or_other_imports(app_dir):
    (app_dir / "bulletins.db").write_bytes(b"this is not a sqlite database" * 100)
    make_main_js8call_db(app_dir / "js8call.db")

    assert database_core.initialize_database()

    import db_admin

    assert [row[1:4] for row in db_admin.list_ham_messages()] == [("K1ABC", "W2XYZ", "QSL")]
