import sqlite3
import threading
import logging
import os
import configparser
import time
from pathlib import Path

logger = logging.getLogger(__name__)
thread_local = threading.local()
_connections = {}
_connections_lock = threading.Lock()
_db_path_version = 0

DEFAULT_DB_PATH = 'bbs.db'
_custom_db_path = None

def set_db_path(path):
    """
    Sets a custom path for the SQLite database and invalidates all existing connections.

    Args:
        path (str): The new filesystem path for the database.
    """
    global _custom_db_path, _db_path_version
    _custom_db_path = path
    
    # Invalidate existing connections across all threads to ensure the new path is picked up immediately.
    with _connections_lock:
        for tid, conn in list(_connections.items()):
            try:
                conn.close()
            except Exception:
                logger.exception(f"Error closing tracked connection for thread {tid}")
        _connections.clear()
        _db_path_version += 1
    
    if hasattr(thread_local, 'connection'):
        thread_local.connection = None
        thread_local.conn_version = None

def _read_module_config(section, option):
    """Reads one option from the config.ini beside this module, or None."""
    config_file = Path(__file__).parent.resolve() / 'config.ini'
    if not config_file.exists():
        return None
    config = configparser.ConfigParser()
    try:
        config.read(config_file)
        return config.get(section, option, fallback=None)
    except configparser.Error:
        logger.debug(f"Failed to read [{section}] {option} from {config_file}", exc_info=True)
        return None


def get_db_path():
    """
    Resolves the effective path for the SQLite database: a path set with
    set_db_path(), then config.ini [database] db_path, then BBS_DB_PATH, then
    the default.

    Returns:
        str: Absolute path to the database file.
    """
    module_dir = Path(__file__).parent.resolve()
    
    if _custom_db_path:
        path_obj = Path(_custom_db_path)
        if not path_obj.is_absolute():
            path_obj = (module_dir / path_obj).resolve()
        return str(path_obj)
        
    # Config wins over the environment, matching server.py and the healthcheck.
    db_path = _read_module_config('database', 'db_path')

    if not db_path:
        db_path = os.environ.get('BBS_DB_PATH')

    if not db_path:
        db_path = DEFAULT_DB_PATH
        
    path_obj = Path(db_path)
    if not path_obj.is_absolute():
        path_obj = (module_dir / path_obj).resolve()
        
    return str(path_obj)

def get_db_connection():
    """
    Provides a thread-local SQLite connection, creating it if necessary.
    Uses WAL mode for better concurrency in multi-process/multi-thread environments.

    Returns:
        sqlite3.Connection: The active thread-local connection, or None on failure.
    """
    global _db_path_version
    
    if hasattr(thread_local, 'connection') and thread_local.connection is not None:
        if getattr(thread_local, 'conn_version', -1) != _db_path_version:
            try:
                thread_local.connection.close()
            except sqlite3.Error as e:
                logger.debug(f"Error closing stale connection: {e}")
            
            # Ensure the stale connection is removed from tracking to avoid later 
            # attempts to close an already-closed socket.
            with _connections_lock:
                _connections.pop(threading.get_ident(), None)
            thread_local.connection = None

    if not hasattr(thread_local, 'connection') or thread_local.connection is None:
        max_retries = 5
        retry_count = 0
        while retry_count < max_retries:
            current_version = _db_path_version
            db_path = get_db_path()
            conn = None
            try:
                conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
                # WAL mode is essential for allowing simultaneous reads/writes in a shared BBS environment.
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                
                # Verify the path version again after setup to prevent using a connection 
                # that was invalidated during the relatively slow connect() call.
                if _db_path_version != current_version:
                    conn.close()
                    conn = None
                    retry_count += 1
                    time.sleep(0.1)
                    continue

                retry_needed = False
                with _connections_lock:
                    if _db_path_version != current_version:
                        conn.close()
                        conn = None
                        retry_count += 1
                        retry_needed = True
                    else:
                        thread_local.connection = conn
                        thread_local.conn_version = current_version
                        _connections[threading.get_ident()] = conn
                
                if retry_needed:
                    time.sleep(0.1)
                    continue
                break
            except sqlite3.Error:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                logger.exception(f"Failed to connect to database at {db_path}")
                return None
            except Exception:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                raise
        
        if retry_count >= max_retries:
            logger.error(f"Exceeded max retries ({max_retries}) to obtain database connection.")
            return None
    return thread_local.connection

def close_db_connection():
    """
    Closes the connection for the current thread and removes it from the shared tracker.
    """
    if hasattr(thread_local, 'connection') and thread_local.connection is not None:
        try:
            conn = thread_local.connection
            conn.close()
        except sqlite3.Error:
            logger.exception("Error closing database connection")
        finally:
            with _connections_lock:
                _connections.pop(threading.get_ident(), None)
            thread_local.connection = None
            thread_local.conn_version = None

# (old table, new table, columns) for data written by the pre-refactor schema.
LEGACY_TABLES = [
    ('bulletins', 'mesh_bulletins', 'board, sender_short_name, date, subject, content, unique_id'),
    ('mail', 'mesh_mail', 'sender, sender_short_name, recipient, date, subject, content, unique_id'),
    ('channels', 'mesh_channels', 'name, url'),
    ('messages', 'ham_messages', 'sender, receiver, message, timestamp'),
    ('groups', 'ham_groups', 'sender, groupname, message, timestamp'),
    ('urgent', 'ham_urgent', 'sender, groupname, message, timestamp')
]

# Database files the pre-refactor code kept next to the application.
LEGACY_DB_FILES = ('bulletins.db', 'js8call.db')
LEGACY_SCHEMA = 'legacy_src'


def _table_exists(cursor, schema, table):
    cursor.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


def _copy_legacy_rows(cursor, source, new_table, cols):
    """
    Copies rows from a legacy table into its new table and reports rows it skipped.

    Args:
        cursor (sqlite3.Cursor): Cursor inside the caller's transaction.
        source (str): Schema-qualified legacy table, e.g. 'main.mail'.
        new_table (str): Destination table.
        cols (str): Comma-separated column list shared by both tables.
    """
    cursor.execute(f"SELECT COUNT(*) FROM {source}")
    total = cursor.fetchone()[0]

    # Tables with strict UNIQUE constraints use INSERT OR IGNORE to handle
    # duplicates across sync merges. Ham tables don't have unique IDs
    # so we manually deduplicate on content to prevent sync loops.
    if new_table in ('mesh_bulletins', 'mesh_mail', 'mesh_channels'):
        cursor.execute(f"INSERT OR IGNORE INTO {new_table} ({cols}) SELECT {cols} FROM {source}")
    else:
        col_list = [c.strip() for c in cols.split(',')]
        where_clause = " AND ".join([f"n.{c} IS o.{c}" for c in col_list])
        # We GROUP BY all columns from the source to ensure that if the legacy
        # table contains duplicates, only a single unique row is considered for migration.
        cursor.execute(f"""
            INSERT INTO {new_table} ({cols})
            SELECT {cols} FROM {source} o
            WHERE NOT EXISTS (
                SELECT 1 FROM {new_table} n
                WHERE {where_clause}
            )
            GROUP BY {cols}
        """)

    skipped = total - cursor.rowcount
    if skipped > 0:
        logger.warning(
            f"Skipped {skipped} of {total} rows from {source} while migrating to {new_table} "
            "(duplicates, or rows missing a required field). The originals are left in place."
        )


def _free_backup_name(cursor, old_table):
    """Returns a legacy_* table name that won't overwrite an earlier backup."""
    name = f"legacy_{old_table}"
    suffix = 2
    while _table_exists(cursor, 'main', name):
        name = f"legacy_{old_table}_{suffix}"
        suffix += 1
    return name


def _migrate_legacy_data(conn):
    """
    Orchestrates the migration of data from legacy tables to the new prefixed schema.
    Relies on the caller to manage the transaction.

    Args:
        conn (sqlite3.Connection): The database connection to use for the migration.
    """
    cursor = conn.cursor()

    migrated_any = False
    for old_table, new_table, cols in LEGACY_TABLES:
        if _table_exists(cursor, 'main', old_table):
            logger.info(f"Migrating legacy data from {old_table} to {new_table}...")
            _copy_legacy_rows(cursor, f"main.{old_table}", new_table, cols)

            # We rename the old table to 'legacy_...' instead of dropping it to provide
            # a manual recovery path if the automated migration logic fails to capture
            # specific edge-case data.
            backup = _free_backup_name(cursor, old_table)
            cursor.execute(f"ALTER TABLE main.{old_table} RENAME TO {backup}")
            logger.info(f"Successfully migrated {old_table}; original kept as {backup}.")
            migrated_any = True

    if migrated_any:
        logger.info("Database migration data processed.")


def _legacy_db_candidates(db_path):
    """
    Lists pre-refactor database files that may still hold data.

    The old code kept bulletins.db and js8call.db beside the application (in
    Docker, beside the database on the config volume), and js8call.db could be
    moved with [js8call] db_file.
    """
    module_dir = Path(__file__).parent.resolve()
    current = Path(db_path).resolve()

    candidates = [d / name for d in (current.parent, module_dir) for name in LEGACY_DB_FILES]

    js8_db_file = _read_module_config('js8call', 'db_file')
    if js8_db_file:
        js8_path = Path(js8_db_file)
        candidates.append(js8_path if js8_path.is_absolute() else module_dir / js8_path)

    result = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate != current and candidate not in result and candidate.is_file():
            result.append(candidate)
    return result


def _import_legacy_file(conn, source):
    """
    Copies data from one pre-refactor database file, once.

    The file is left untouched. legacy_imports records the import so rows a
    user deletes afterwards don't come back on the next start.
    """
    conn.execute(f"ATTACH DATABASE ? AS {LEGACY_SCHEMA}", (str(source),))
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM legacy_imports WHERE source_path = ?", (str(source),))
            if cursor.fetchone() is None:
                logger.info(f"Importing data from legacy database {source}...")
                for old_table, new_table, cols in LEGACY_TABLES:
                    if _table_exists(cursor, LEGACY_SCHEMA, old_table):
                        _copy_legacy_rows(cursor, f"{LEGACY_SCHEMA}.{old_table}", new_table, cols)
                cursor.execute("INSERT INTO legacy_imports (source_path) VALUES (?)", (str(source),))
                logger.info(f"Imported {source}. The file was not modified and can be removed.")
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
    finally:
        conn.execute(f"DETACH DATABASE {LEGACY_SCHEMA}")


def initialize_database():
    """
    Initializes the database schema and performs data migrations.
    Creates all required tables and indexes if they do not exist.
    Uses an exclusive transaction to prevent race conditions during DDL and migration.
    Guards against nested transaction errors by checking conn.in_transaction.

    Returns:
        bool: True if initialization and migration were successful, False otherwise.
    """
    conn = get_db_connection()
    if conn is None:
        return False
    
    # If a transaction is already active on this connection (e.g. from a caller),
    # create a savepoint so schema setup can roll back without poisoning the
    # caller's outer transaction.
    manage_transaction = not conn.in_transaction
    savepoint_name = "sp_initialize_database"
    savepoint_active = False
    
    try:
        if manage_transaction:
            conn.execute("BEGIN EXCLUSIVE")
        else:
            conn.execute(f"SAVEPOINT {savepoint_name}")
            savepoint_active = True
        
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS mesh_bulletins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        board TEXT NOT NULL,
                        sender_short_name TEXT NOT NULL,
                        date TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        content TEXT NOT NULL,
                        unique_id TEXT NOT NULL UNIQUE
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS mesh_mail (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT NOT NULL,
                        sender_short_name TEXT NOT NULL,
                        recipient TEXT NOT NULL,
                        date TEXT NOT NULL,
                        subject TEXT NOT NULL,
                        content TEXT NOT NULL,
                        unique_id TEXT NOT NULL UNIQUE
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS mesh_channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        url TEXT NOT NULL,
                        UNIQUE(name, url)
                    )''')
        
        c.execute('CREATE INDEX IF NOT EXISTS idx_mesh_bulletins_board ON mesh_bulletins(board)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_mesh_mail_recipient ON mesh_mail(recipient)')
        
        c.execute('''CREATE TABLE IF NOT EXISTS ham_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT,
                        receiver TEXT,
                        message TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS ham_groups (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT,
                        groupname TEXT,
                        message TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS ham_urgent (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT,
                        groupname TEXT,
                        message TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS legacy_imports (
                        source_path TEXT PRIMARY KEY,
                        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )''')

        # Migrations are processed within the same exclusive transaction.
        _migrate_legacy_data(conn)
        
        if manage_transaction:
            conn.commit()
        elif savepoint_active:
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            savepoint_active = False
            
        # ATTACH can't run inside a transaction, so separate files are
        # imported after the schema commit, each in its own transaction.
        # A bad old file is logged and retried next start; it must not stop
        # the BBS or the import of the other file.
        if manage_transaction:
            for source in _legacy_db_candidates(get_db_path()):
                try:
                    _import_legacy_file(conn, source)
                except sqlite3.Error:
                    logger.exception(f"Could not import legacy database {source}; will retry on next start")

        logger.info("Database schema initialized and migrated successfully.")
        return True
    except sqlite3.Error:
        if manage_transaction:
            conn.rollback()
        elif savepoint_active:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            except sqlite3.Error:
                logger.debug("Failed to rollback to savepoint during initialization", exc_info=True)
            finally:
                try:
                    conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                except sqlite3.Error:
                    logger.debug("Failed to release savepoint during initialization rollback", exc_info=True)
                savepoint_active = False
        logger.exception("Failed to initialize database schema")
        return False
