from socket import socket, AF_INET, SOCK_STREAM, SHUT_RDWR
import json
import time
import sqlite3
import configparser
import logging
import os
import codecs
from contextlib import closing

logger = logging.getLogger(__name__)

from meshtastic import BROADCAST_NUM

from command_handlers import handle_help_command
from utils import send_message, update_user_state

config_file = 'config.ini'
MAX_RECV_BUFFER = 1024 * 1024 # 1MB limit for safety

def get_js8_db_path(config_path=None):
    """Resolve JS8Call DB path at call time"""
    if config_path is None:
        # Resolve relative to this module's directory instead of CWD
        config_path = os.path.join(os.path.dirname(__file__), config_file)
        config_path = os.path.abspath(config_path)
        
    config = configparser.ConfigParser()
    try:
        config.read(config_path)
        db_file = config.get('js8call', 'db_file', fallback='js8call.db')
        
        # If relative, anchor to the directory of the config file
        if not os.path.isabs(db_file):
            config_dir = os.path.dirname(config_path)
            db_file = os.path.abspath(os.path.join(config_dir, db_file))
            
        return db_file
    except (configparser.Error, OSError):
        # Fallback to module-relative default if resolution fails
        return os.path.abspath(os.path.join(os.path.dirname(__file__), 'js8call.db'))

# Cache DB path once at module load
JS8_DB_PATH = get_js8_db_path()

def to_message(typ, value='', params=None):
    """
    Helper to create a JS8Call message dictionary.
    """
    if params is None:
        params = {}
    return {'type': typ, 'value': value, 'params': params}


class JS8CallClient:
    def __init__(self, interface, logger=None):
        self.logger = logger or logging.getLogger('js8call')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = True

        self.config = configparser.ConfigParser()
        # Ensure we read from the same resolved config path as the helper
        config_path = os.path.join(os.path.dirname(__file__), config_file)
        self.config.read(config_path)

        self.server = (
            self.config.get('js8call', 'host', fallback=None),
            self.config.getint('js8call', 'port', fallback=None)
        )
        self.db_file = JS8_DB_PATH
        self.js8groups = self.config.get('js8call', 'js8groups', fallback='').split(',')
        self.store_messages = self.config.getboolean('js8call', 'store_messages', fallback=True)
        self.js8urgent = self.config.get('js8call', 'js8urgent', fallback='').split(',')
        self.js8groups = [group.strip() for group in self.js8groups]
        self.js8urgent = [group.strip() for group in self.js8urgent]

        self.connected = False
        self.sock = None
        self.db_conn = None
        self.interface = interface
        self.recv_buffer = bytearray()
        self.decoder = codecs.getincrementaldecoder('utf-8')()

        if self.config.has_section('js8call'):
            try:
                # check_same_thread=False allows background thread to use the connection
                self.db_conn = sqlite3.connect(self.db_file, check_same_thread=False, timeout=30)
                # Enable Write-Ahead Logging (WAL) for better concurrency
                try:
                    self.db_conn.execute("PRAGMA journal_mode=WAL")
                    self.db_conn.execute("PRAGMA synchronous=NORMAL")
                    self.db_conn.commit()
                except sqlite3.Error:
                    self.logger.exception("Failed to set WAL mode on JS8Call database")
                self.create_tables()
            except sqlite3.Error:
                self.logger.exception(f"Failed to initialize JS8Call database at {self.db_file}")
                self.db_conn = None
        else:
            self.logger.info("JS8Call configuration not found. Skipping JS8Call integration.")

    def create_tables(self):
        if not self.db_conn:
            return

        with self.db_conn:
            self.db_conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT,
                    receiver TEXT,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.db_conn.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT,
                    groupname TEXT,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.db_conn.execute('''
                CREATE TABLE IF NOT EXISTS urgent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT,
                    groupname TEXT,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        self.logger.info("Database tables created or verified.")

    def insert_message(self, table, sender, recipient, message):
        """
        Inserts a message into the specified table in the database.
        """
        if not self.db_conn:
            self.logger.error("Database connection is not available.")
            return

        # Prebuilt queries map to prevent SQL injection (Ruff S608)
        prebuilt_queries = {
            'messages': "INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)",
            'groups': "INSERT INTO groups (sender, groupname, message) VALUES (?, ?, ?)",
            'urgent': "INSERT INTO urgent (sender, groupname, message) VALUES (?, ?, ?)"
        }

        if table not in prebuilt_queries:
            self.logger.error(f"Attempted access to invalid/unauthorized table: {table}")
            return

        sql = prebuilt_queries[table]

        try:
            with self.db_conn:
                self.db_conn.execute(sql, (sender, recipient, message))
        except sqlite3.Error:
            self.logger.exception(f"Failed to insert message into {table} table")

    def process(self, message):
        typ = message.get('type', '')
        value = message.get('value', '')
        params = message.get('params', {})

        if not typ:
            return

        rx_types = [
            'RX.ACTIVITY', 'RX.DIRECTED', 'RX.SPOT', 'RX.CALL_ACTIVITY',
            'RX.CALL_SELECTED', 'RX.DIRECTED_ME', 'RX.ECHO', 'RX.DIRECTED_GROUP',
            'RX.META', 'RX.MSG', 'RX.PING', 'RX.PONG', 'RX.STREAM'
        ]

        if typ not in rx_types:
            return

        if typ == 'RX.DIRECTED' and value:
            parts = value.split(' ')
            if len(parts) < 3:
                self.logger.warning(f"Unexpected message format: {value}")
                return

            sender = parts[0]
            receiver = parts[1]
            msg = ' '.join(parts[2:]).strip()

            self.logger.info(f"Received JS8Call message: {sender} to {receiver} - {msg}")

            if receiver in self.js8urgent:
                self.insert_message('urgent', sender, receiver, msg)
                notification_message = f"💥 URGENT JS8Call Message Received 💥\nFrom: {sender}\nCheck BBS for message"
                send_message(notification_message, BROADCAST_NUM, self.interface)
            elif receiver in self.js8groups:
                self.insert_message('groups', sender, receiver, msg)
            elif self.store_messages:
                self.insert_message('messages', sender, receiver, msg)
        else:
            pass

    def _set_connected(self, value, lock=None):
        """Internal helper to set connected state with optional lock"""
        if lock:
            with lock:
                self.connected = value
        else:
            self.connected = value

    def send(self, typ, value='', params=None):
        if not self.sock or not self.connected:
            self.logger.error("JS8Call socket is not connected. Cannot send message.")
            return

        # Defensive copy to avoid mutating caller's dict
        params_copy = dict(params) if params is not None else {}
        
        if '_ID' not in params_copy:
            params_copy['_ID'] = '{}'.format(int(time.time() * 1000))
        
        message_dict = to_message(typ, value, params_copy)
        message = json.dumps(message_dict)
        
        try:
            self.sock.sendall((message + '\n').encode('utf-8'))  # Use sendall for guaranteed delivery
        except OSError:
            self.logger.exception("Failed to send message to JS8Call")
            # Force unblock recv thread
            try:
                self.sock.shutdown(SHUT_RDWR)
                self.sock.close()
            except (OSError, AttributeError):
                pass
            self.sock = None
            self._set_connected(False)

    def connect(self, lock=None):
        if not self.server[0] or not self.server[1]:
            self.logger.info("JS8Call server configuration not found. Skipping JS8Call connection.")
            return

        self.logger.info(f"Connecting to {self.server}")
        self.sock = socket(AF_INET, SOCK_STREAM)
        self.recv_buffer = bytearray()
        self.decoder.reset()
        
        try:
            self.sock.connect(self.server)
            self._set_connected(True, lock)
            self.send("STATION.GET_STATUS")

            while self.connected:
                try:
                    data = self.sock.recv(65500)
                    if not data:
                        self.logger.info("JS8Call connection closed by peer.")
                        break  # Connection closed (EOF)

                    # Incremental UTF-8 decoding to handle split characters
                    try:
                        content = self.decoder.decode(data, final=False)
                    except UnicodeDecodeError:
                        self.logger.warning("Malformed UTF-8 bytes received from JS8Call, skipping chunk")
                        continue

                    # Safety cap on recv_buffer to prevent memory exhaustion
                    if len(self.recv_buffer) + len(content.encode('utf-8')) > MAX_RECV_BUFFER:
                        self.logger.warning("JS8Call recv_buffer exceeded cap, clearing buffer")
                        self.recv_buffer.clear()
                        if len(content.encode('utf-8')) > MAX_RECV_BUFFER:
                            continue

                    self.recv_buffer.extend(content.encode('utf-8'))
                    
                    # Process lines from buffer
                    while b'\n' in self.recv_buffer:
                        line_bytes, remaining = self.recv_buffer.split(b'\n', 1)
                        self.recv_buffer = bytearray(remaining)
                        
                        line = line_bytes.decode('utf-8', errors='replace').strip()
                        if not line:
                            continue
                        try:
                            message = json.loads(line)
                            if message:
                                self.process(message)
                        except json.JSONDecodeError as e:
                            self.logger.warning(f"Invalid JSON content received: {line}. Error: {e}")
                            continue

                except OSError:
                    if self.connected: # Only log if we didn't expect the closure
                        self.logger.exception("Socket error during recv")
                    break
        except ConnectionRefusedError:
            self.logger.exception(f"Connection to JS8Call server {self.server} refused")
        except Exception:
            self.logger.exception("Unexpected error in JS8Call connection")
        finally:
            self._set_connected(False, lock)
            # Flush decoder
            try:
                self.decoder.decode(b'', final=True)
            except UnicodeDecodeError:
                pass
                
            if self.sock:
                try:
                    self.sock.shutdown(SHUT_RDWR)
                    self.sock.close()
                except (OSError, AttributeError):
                    pass
                self.sock = None

    def close(self, lock=None):
        self._set_connected(False, lock)
        if self.sock:
            try:
                self.sock.shutdown(SHUT_RDWR)
                self.sock.close()
            except (OSError, AttributeError):
                pass
            self.sock = None
        
        if self.db_conn:
            try:
                self.db_conn.close()
            except Exception:
                self.logger.exception("Failed to close db_conn")
            self.db_conn = None


def handle_js8call_command(sender_id, interface):
    response = "JS8Call Menu:\n[G]roup Messages\n[S]tation Messages\n[U]rgent Messages\nE[X]IT"
    send_message(response, sender_id, interface)
    update_user_state(sender_id, {'command': 'JS8CALL_MENU', 'step': 1})


def handle_js8call_steps(sender_id, message, step, interface, state):
    message = message.lower().strip()
    if len(message) == 2 and message[1] == 'x':
        message = message[0]

    if step == 1:
        choice = message
        if choice == 'x':
            handle_help_command(sender_id, interface, 'bbs')
            return
        elif choice == 'g':
            handle_group_messages_command(sender_id, interface)
        elif choice == 's':
            handle_station_messages_command(sender_id, interface)
        elif choice == 'u':
            handle_urgent_messages_command(sender_id, interface)
        else:
            send_message("Invalid option. Please choose again.", sender_id, interface)
            handle_js8call_command(sender_id, interface)


def handle_group_messages_command(sender_id, interface):
    try:
        groups = []
        with closing(sqlite3.connect(JS8_DB_PATH, timeout=30)) as conn:
            c = conn.cursor()
            c.execute("SELECT DISTINCT groupname FROM groups ORDER BY groupname ASC")
            groups = c.fetchall()
        
        if groups:
            response = "Group Messages Menu:\n" + "\n".join([f"[{i}] {group[0]}" for i, group in enumerate(groups)])
            send_message(response, sender_id, interface)
            update_user_state(sender_id, {'command': 'GROUP_MESSAGES', 'step': 1, 'groups': groups})
        else:
            send_message("No group messages available.", sender_id, interface)
            handle_js8call_command(sender_id, interface)
    except Exception:
        logger.exception("Error in handle_group_messages_command")
        send_message("Error retrieving group messages.", sender_id, interface)
        handle_js8call_command(sender_id, interface)

def handle_station_messages_command(sender_id, interface):
    try:
        messages = []
        with closing(sqlite3.connect(JS8_DB_PATH, timeout=30)) as conn:
            c = conn.cursor()
            # Order by most recent and limit to prevent oversized responses
            c.execute("SELECT sender, receiver, message, timestamp FROM messages ORDER BY timestamp DESC LIMIT 10")
            messages = c.fetchall()
        
        if messages:
            # Display recent-first
            response = "Recent Station Messages:\n" + "\n".join([f"[{i+1}] {msg[0]} -> {msg[1]}: {msg[2]} ({msg[3]})" for i, msg in enumerate(messages)])
            send_message(response, sender_id, interface)
        else:
            send_message("No station messages available.", sender_id, interface)
        handle_js8call_command(sender_id, interface)
    except Exception:
        logger.exception("Error in handle_station_messages_command")
        send_message("Error retrieving station messages.", sender_id, interface)
        handle_js8call_command(sender_id, interface)

def handle_urgent_messages_command(sender_id, interface):
    try:
        messages = []
        with closing(sqlite3.connect(JS8_DB_PATH, timeout=30)) as conn:
            c = conn.cursor()
            # Order by most recent and limit to prevent oversized responses
            c.execute("SELECT sender, groupname, message, timestamp FROM urgent ORDER BY timestamp DESC LIMIT 10")
            messages = c.fetchall()
        
        if messages:
            # Display recent-first
            response = "Recent Urgent Messages:\n" + "\n".join([f"[{i+1}] {msg[0]} -> {msg[1]}: {msg[2]} ({msg[3]})" for i, msg in enumerate(messages)])
            send_message(response, sender_id, interface)
        else:
            send_message("No urgent messages available.", sender_id, interface)
        handle_js8call_command(sender_id, interface)
    except Exception:
        logger.exception("Error in handle_urgent_messages_command")
        send_message("Error retrieving urgent messages.", sender_id, interface)
        handle_js8call_command(sender_id, interface)

def handle_group_message_selection(sender_id, message, _step, state, interface):
    groups = state['groups']
    try:
        group_index = int(message)
    except ValueError:
        send_message("Invalid input. Please enter a valid group number.", sender_id, interface)
        handle_group_messages_command(sender_id, interface)
        return

    # Explicit bounds check to prevent negative index issues and crashes
    if not (0 <= group_index < len(groups)):
        send_message("Invalid group selection. Please choose again.", sender_id, interface)
        handle_group_messages_command(sender_id, interface)
        return
            
    groupname = groups[group_index][0]
    try:
        messages = []
        with closing(sqlite3.connect(JS8_DB_PATH, timeout=30)) as conn:
            c = conn.cursor()
            # Limit results
            c.execute("SELECT sender, message, timestamp FROM groups WHERE groupname=? ORDER BY timestamp DESC LIMIT 10", (groupname,))
            messages = c.fetchall()

        if messages:
            response = f"Recent messages for group {groupname}:\n" + "\n".join([f"[{i+1}] {msg[0]}: {msg[1]} ({msg[2]})" for i, msg in enumerate(messages)])
            send_message(response, sender_id, interface)
        else:
            send_message(f"No messages for group {groupname}.", sender_id, interface)
        
        handle_js8call_command(sender_id, interface)
    except Exception:
        logger.exception("Error fetching group messages")
        send_message("An error occurred while fetching messages.", sender_id, interface)
        handle_group_messages_command(sender_id, interface)
