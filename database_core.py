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

def get_db_path():
    """
    Resolves the effective path for the SQLite database based on environment, 
    config, or defaults.

    Returns:
        str: Absolute path to the database file.
    """
    module_dir = Path(__file__).parent.resolve()
    
    if _custom_db_path:
        path_obj = Path(_custom_db_path)
        if not path_obj.is_absolute():
            path_obj = (module_dir / path_obj).resolve()
        return str(path_obj)
        
    config_file = module_dir / 'config.ini'
    config = configparser.ConfigParser()
    db_path = os.environ.get('BBS_DB_PATH')
    
    if not db_path and config_file.exists():
        try:
            config.read(config_file)
            db_path = config.get('database', 'db_path', fallback=None)
        except configparser.Error:
            logger.debug(f"Failed to read database config from {config_file}", exc_info=True)
            
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
            try:
                conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
                # WAL mode is essential for allowing simultaneous reads/writes in a shared BBS environment.
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                
                # Verify the path version again after setup to prevent using a connection 
                # that was invalidated during the relatively slow connect() call.
                if _db_path_version != current_version:
                    conn.close()
                    retry_count += 1
                    time.sleep(0.1)
                    continue

                retry_needed = False
                with _connections_lock:
                    if _db_path_version != current_version:
                        conn.close()
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
                logger.exception(f"Failed to connect to database at {db_path}")
                return None
        
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

def _migrate_legacy_data(conn):
    """
    Orchestrates the migration of data from legacy tables to the new prefixed schema.
    Relies on the caller to manage the transaction.
    
    Args:
        conn (sqlite3.Connection): The database connection to use for the migration.
    """
    cursor = conn.cursor()
    
    migrations = [
        ('bulletins', 'mesh_bulletins', 'board, sender_short_name, date, subject, content, unique_id'),
        ('mail', 'mesh_mail', 'sender, sender_short_name, recipient, date, subject, content, unique_id'),
        ('channels', 'mesh_channels', 'name, url'),
        ('messages', 'ham_messages', 'sender, receiver, message, timestamp'),
        ('groups', 'ham_groups', 'sender, groupname, message, timestamp'),
        ('urgent', 'ham_urgent', 'sender, groupname, message, timestamp')
    ]
    
    migrated_any = False
    for old_table, new_table, cols in migrations:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (old_table,))
        if cursor.fetchone():
            logger.info(f"Migrating legacy data from {old_table} to {new_table}...")
            
            # Tables with strict UNIQUE constraints use INSERT OR IGNORE to handle 
            # duplicates across sync merges. Ham tables don't have unique IDs 
            # so we manually deduplicate on content to prevent sync loops.
            if new_table in ('mesh_bulletins', 'mesh_mail', 'mesh_channels'):
                cursor.execute(f"INSERT OR IGNORE INTO {new_table} ({cols}) SELECT {cols} FROM {old_table}")
            else:
                col_list = [c.strip() for c in cols.split(',')]
                where_clause = " AND ".join([f"n.{c} IS o.{c}" for c in col_list])
                # We GROUP BY all columns from the source to ensure that if the legacy 
                # table contains duplicates, only a single unique row is considered for migration.
                cursor.execute(f"""
                    INSERT INTO {new_table} ({cols}) 
                    SELECT {cols} FROM {old_table} o 
                    WHERE NOT EXISTS (
                        SELECT 1 FROM {new_table} n 
                        WHERE {where_clause}
                    )
                    GROUP BY {cols}
                """)
            
            # We rename the old table to 'legacy_...' instead of dropping it to provide 
            # a manual recovery path if the automated migration logic fails to capture 
            # specific edge-case data.
            cursor.execute(f"DROP TABLE IF EXISTS legacy_{old_table}")
            cursor.execute(f"ALTER TABLE {old_table} RENAME TO legacy_{old_table}")
            logger.info(f"Successfully migrated {old_table}.")
            migrated_any = True
    
    if migrated_any:
        logger.info("Database migration data processed.")

def initialize_database():
    """
    Initializes the database schema and performs data migrations.
    Creates all required tables and indexes if they do not exist.
    Uses an exclusive transaction to prevent race conditions during DDL and migration.

    Returns:
        bool: True if initialization and migration were successful, False otherwise.
    """
    conn = get_db_connection()
    if conn is None:
        return False
    
    try:
        # Wrap everything in an exclusive transaction to ensure DDL and migrations are atomic 
        # and not interleaved with other concurrent initialization attempts.
        conn.execute("BEGIN EXCLUSIVE")
        
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
        
        # Deduplicate existing channels to safely apply the new constraint for older databases.
        c.execute('''
            DELETE FROM mesh_channels 
            WHERE id NOT IN (
                SELECT MIN(id) 
                FROM mesh_channels 
                GROUP BY name, url
            )
        ''')
        
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
        
        # Migrations are processed within the same exclusive transaction.
        _migrate_legacy_data(conn)
        
        conn.commit()
        logger.info("Database schema initialized and migrated successfully.")
        return True
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to initialize database schema")
        return False
