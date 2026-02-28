import sqlite3
import threading
import logging
import os
import configparser
from pathlib import Path

logger = logging.getLogger(__name__)
thread_local = threading.local()
_connections = {}
_connections_lock = threading.Lock()
_db_path_version = 0

DEFAULT_DB_PATH = 'bbs.db'
_custom_db_path = None

def set_db_path(path):
    global _custom_db_path, _db_path_version
    _custom_db_path = path
    # Close and clear all tracked connections
    with _connections_lock:
        for tid, conn in list(_connections.items()):
            try:
                conn.close()
            except Exception:
                logger.exception(f"Error closing tracked connection for thread {tid}")
        _connections.clear()
        _db_path_version += 1
    
    # Also clear for current thread if it exists
    if hasattr(thread_local, 'connection'):
        thread_local.connection = None

def get_db_path():
    # Resolve relative to this module's directory
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
            pass
            
    if not db_path:
        db_path = DEFAULT_DB_PATH
        
    # If the path is relative, resolve it against the module directory
    path_obj = Path(db_path)
    if not path_obj.is_absolute():
        path_obj = (module_dir / path_obj).resolve()
        
    return str(path_obj)

def get_db_connection():
    global _db_path_version
    db_path = get_db_path()
    
    # Check if we need to discard current connection due to path change
    if hasattr(thread_local, 'connection') and thread_local.connection is not None:
        if getattr(thread_local, 'conn_version', -1) != _db_path_version:
            try:
                thread_local.connection.close()
            except sqlite3.Error as e:
                logger.debug(f"Error closing stale connection: {e}")
            thread_local.connection = None

    if not hasattr(thread_local, 'connection') or thread_local.connection is None:
        try:
            conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
            # Enable Write-Ahead Logging (WAL) for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            
            thread_local.connection = conn
            thread_local.conn_version = _db_path_version
            with _connections_lock:
                _connections[threading.get_ident()] = conn
        except sqlite3.Error:
            logger.exception(f"Failed to connect to database at {db_path}")
            return None
    return thread_local.connection

def close_db_connection():
    if hasattr(thread_local, 'connection') and thread_local.connection is not None:
        try:
            conn = thread_local.connection
            conn.close()
            with _connections_lock:
                _connections.pop(threading.get_ident(), None)
        except sqlite3.Error:
            logger.exception("Error closing database connection")
        finally:
            thread_local.connection = None

def _migrate_legacy_data(conn):
    """
    Migrates data from legacy table names to the new prefixed tables.
    """
    cursor = conn.cursor()
    
    # Mapping of (legacy_table, new_table, columns)
    # Note: These identifiers are hardcoded compile-time constants.
    migrations = [
        ('bulletins', 'mesh_bulletins', 'board, sender_short_name, date, subject, content, unique_id'),
        ('mail', 'mesh_mail', 'sender, sender_short_name, recipient, date, subject, content, unique_id'),
        ('channels', 'mesh_channels', 'name, url'),
        ('messages', 'ham_messages', 'sender, receiver, message, timestamp'),
        ('groups', 'ham_groups', 'sender, groupname, message, timestamp'),
        ('urgent', 'ham_urgent', 'sender, groupname, message, timestamp')
    ]
    
    try:
        migrated_any = False
        for old_table, new_table, cols in migrations:
            # Check if old table exists
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{old_table}'")
            if cursor.fetchone():
                logger.info(f"Migrating legacy data from {old_table} to {new_table}...")
                
                # Note: Table and column names are compile-time constants from the migrations list.
                # SQLite does not support parameterized identifiers, so this pattern is intentional.
                
                # Deduplication strategy:
                # 1. Mesh tables (mesh_bulletins, mesh_mail) have a UNIQUE(unique_id) constraint.
                # 2. Ham tables (ham_messages, ham_groups, ham_urgent) and channels do not.
                # We use INSERT OR IGNORE for mesh tables and a SELECT DISTINCT approach for the others.
                if new_table in ('mesh_bulletins', 'mesh_mail'):
                    cursor.execute(f"INSERT OR IGNORE INTO {new_table} ({cols}) SELECT {cols} FROM {old_table}")
                else:
                    # For ham tables and channels, avoid exact duplicate rows during migration
                    cursor.execute(f"INSERT INTO {new_table} ({cols}) SELECT DISTINCT {cols} FROM {old_table}")
                
                # Rename old table to prevent repeated migrations
                cursor.execute(f"ALTER TABLE {old_table} RENAME TO legacy_{old_table}")
                logger.info(f"Successfully migrated {old_table}.")
                migrated_any = True
        
        if migrated_any:
            conn.commit()
            logger.info("Database migration completed successfully.")
            
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Database migration failed. Rolled back changes.")
        raise

def initialize_database():
    conn = get_db_connection()
    if conn is None:
        return
    
    c = conn.cursor()
    # Meshtastic tables (mesh_ prefix)
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
                    url TEXT NOT NULL
                )''')
    
    # Create indexes for hot filter columns
    c.execute('CREATE INDEX IF NOT EXISTS idx_mesh_bulletins_board ON mesh_bulletins(board)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_mesh_mail_recipient ON mesh_mail(recipient)')
    
    # JS8Call tables (ham_ prefix)
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
    
    # Commit table creation before starting migration transaction
    conn.commit()
    
    # Migrations are self-committing or rolling back
    _migrate_legacy_data(conn)
    
    logger.info("Database schema initialized with mesh_ and ham_ prefixes.")
