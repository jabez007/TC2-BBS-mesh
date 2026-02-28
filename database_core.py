import sqlite3
import threading
import logging
import os
import configparser

logger = logging.getLogger(__name__)
thread_local = threading.local()

DEFAULT_DB_PATH = 'bbs.db'
_custom_db_path = None

def set_db_path(path):
    global _custom_db_path
    _custom_db_path = path
    # Reset connection if path changes
    if hasattr(thread_local, 'connection') and thread_local.connection:
        try:
            thread_local.connection.close()
        except Exception:
            logger.exception("Error closing database connection during path change")
        thread_local.connection = None

def get_db_path():
    if _custom_db_path:
        return _custom_db_path
        
    # Resolve relative to this module's directory
    config_file = os.path.join(os.path.dirname(__file__), 'config.ini')
    config = configparser.ConfigParser()
    db_path = os.environ.get('BBS_DB_PATH')
    
    if not db_path and os.path.exists(config_file):
        try:
            config.read(config_file)
            db_path = config.get('database', 'db_path', fallback=None)
        except configparser.Error:
            pass
            
    return db_path or DEFAULT_DB_PATH

def get_db_connection():
    db_path = get_db_path()
    if not hasattr(thread_local, 'connection') or thread_local.connection is None:
        try:
            thread_local.connection = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
            # Enable Write-Ahead Logging (WAL) for better concurrency
            thread_local.connection.execute("PRAGMA journal_mode=WAL")
            thread_local.connection.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            logger.exception(f"Failed to connect to database at {db_path}")
            return None
    return thread_local.connection

def close_db_connection():
    if hasattr(thread_local, 'connection') and thread_local.connection is not None:
        try:
            thread_local.connection.close()
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
    migrations = [
        ('bulletins', 'mesh_bulletins', 'board, sender_short_name, date, subject, content, unique_id'),
        ('mail', 'mesh_mail', 'sender, sender_short_name, recipient, date, subject, content, unique_id'),
        ('channels', 'mesh_channels', 'name, url'),
        ('messages', 'ham_messages', 'sender, receiver, message, timestamp'),
        ('groups', 'ham_groups', 'sender, groupname, message, timestamp'),
        ('urgent', 'ham_urgent', 'sender, groupname, message, timestamp')
    ]
    
    for old_table, new_table, cols in migrations:
        try:
            # Check if old table exists
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{old_table}'")
            if cursor.fetchone():
                logger.info(f"Migrating legacy data from {old_table} to {new_table}...")
                # INSERT OR IGNORE handles deduplication via the UNIQUE(unique_id) constraint
                cursor.execute(f"INSERT OR IGNORE INTO {new_table} ({cols}) SELECT {cols} FROM {old_table}")
                # Rename old table to prevent repeated migrations
                cursor.execute(f"ALTER TABLE {old_table} RENAME TO legacy_{old_table}")
                logger.info(f"Successfully migrated {old_table}.")
        except sqlite3.Error:
            logger.exception(f"Failed to migrate legacy table {old_table}")

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
    
    # Run migrations before committing
    _migrate_legacy_data(conn)
    
    conn.commit()
    logger.info("Database schema initialized with mesh_ and ham_ prefixes.")
