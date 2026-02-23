from socket import socket, AF_INET, SOCK_STREAM, SHUT_RDWR
import json
import time
import sqlite3
import configparser
import logging
import os

from meshtastic import BROADCAST_NUM

from command_handlers import handle_help_command
from utils import send_message, update_user_state

config_file = 'config.ini'

def get_js8_db_path(config_path=None):
    """Resolve JS8Call DB path at call time"""
    if config_path is None:
        # Resolve relative to current working directory or script location
        config_path = os.path.abspath(config_file)
        
    config = configparser.ConfigParser()
    try:
        config.read(config_path)
        return config.get('js8call', 'db_file', fallback='js8call.db')
    except (configparser.Error, OSError):
        return 'js8call.db'

def to_message(*args, **kwargs):
    """
    Helper to create a JS8Call message dictionary.
    Signature: to_message(typ, value='', params=None)
    """
    typ = args[0] if len(args) > 0 else kwargs.get('typ', '')
    value = args[1] if len(args) > 1 else kwargs.get('value', '')
    params = args[2] if len(args) > 2 else kwargs.get('params', {})
    return {'type': typ, 'value': value, 'params': params}


class JS8CallClient:
    def __init__(self, interface, logger=None):
        self.logger = logger or logging.getLogger('js8call')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        self.config = configparser.ConfigParser()
        self.config.read(config_file)

        self.server = (
            self.config.get('js8call', 'host', fallback=None),
            self.config.getint('js8call', 'port', fallback=None)
        )
        self.db_file = get_js8_db_path()
        self.js8groups = self.config.get('js8call', 'js8groups', fallback='').split(',')
        self.store_messages = self.config.getboolean('js8call', 'store_messages', fallback=True)
        self.js8urgent = self.config.get('js8call', 'js8urgent', fallback='').split(',')
        self.js8groups = [group.strip() for group in self.js8groups]
        self.js8urgent = [group.strip() for group in self.js8urgent]

        self.connected = False
        self.sock = None
        self.db_conn = None
        self.interface = interface
        self.recv_buffer = ""

        if self.config.has_section('js8call'):
            # check_same_thread=False allows background thread to use the connection
            self.db_conn = sqlite3.connect(self.db_file, check_same_thread=False)
            self.create_tables()
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

    def send(self, *args, **kwargs):
        if not self.sock or not self.connected:
            self.logger.error("JS8Call socket is not connected. Cannot send message.")
            return

        params = kwargs.get('params', {})
        if '_ID' not in params:
            params['_ID'] = '{}'.format(int(time.time() * 1000))
            kwargs['params'] = params
        
        # Helper returns a dict, serialize it to JSON here
        message_dict = to_message(*args, **kwargs)
        message = json.dumps(message_dict)
        
        try:
            self.sock.send((message + '\n').encode('utf-8'))  # Convert to bytes
        except OSError:
            self.logger.exception("Failed to send message to JS8Call")
            # We don't take the lock here because it's a transient failure usually handled by connect loop
            self._set_connected(False)

    def connect(self, lock=None):
        if not self.server[0] or not self.server[1]:
            self.logger.info("JS8Call server configuration not found. Skipping JS8Call connection.")
            return

        self.logger.info(f"Connecting to {self.server}")
        self.sock = socket(AF_INET, SOCK_STREAM)
        self.recv_buffer = ""
        try:
            self.sock.connect(self.server)
            self._set_connected(True, lock)
            self.send("STATION.GET_STATUS")

            while True:
                # Check connected state under lock if possible
                is_still_connected = False
                if lock:
                    with lock:
                        is_still_connected = self.connected
                else:
                    is_still_connected = self.connected
                
                if not is_still_connected:
                    break

                try:
                    data = self.sock.recv(65500)
                    if not data:
                        self.logger.info("JS8Call connection closed by peer.")
                        break  # Connection closed (EOF)

                    try:
                        content = data.decode('utf-8')
                    except UnicodeDecodeError:
                        self.logger.warning("Malformed UTF-8 bytes received from JS8Call, skipping chunk")
                        continue

                    self.recv_buffer += content
                    
                    while '\n' in self.recv_buffer:
                        line, self.recv_buffer = self.recv_buffer.split('\n', 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            message = json.loads(line)
                            if message:
                                self.process(message)
                        except ValueError as e:
                            self.logger.warning(f"Invalid JSON content received: {line}. Error: {e}")
                            continue

                except OSError:
                    self.logger.exception("Socket error during recv")
                    break
        except ConnectionRefusedError:
            self.logger.exception(f"Connection to JS8Call server {self.server} refused")
        except Exception:
            self.logger.exception("Unexpected error in JS8Call connection")
        finally:
            self._set_connected(False, lock)
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
    groups = []
    db_path = get_js8_db_path()
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT groupname FROM groups")
        groups = c.fetchall()
    
    if groups:
        response = "Group Messages Menu:\n" + "\n".join([f"[{i}] {group[0]}" for i, group in enumerate(groups)])
        send_message(response, sender_id, interface)
        update_user_state(sender_id, {'command': 'GROUP_MESSAGES', 'step': 1, 'groups': groups})
    else:
        send_message("No group messages available.", sender_id, interface)
        handle_js8call_command(sender_id, interface)

def handle_station_messages_command(sender_id, interface):
    messages = []
    db_path = get_js8_db_path()
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT sender, receiver, message, timestamp FROM messages")
        messages = c.fetchall()
    
    if messages:
        response = "Station Messages:\n" + "\n".join([f"[{i+1}] {msg[0]} -> {msg[1]}: {msg[2]} ({msg[3]})" for i, msg in enumerate(messages)])
        send_message(response, sender_id, interface)
    else:
        send_message("No station messages available.", sender_id, interface)
    handle_js8call_command(sender_id, interface)

def handle_urgent_messages_command(sender_id, interface):
    messages = []
    db_path = get_js8_db_path()
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        c.execute("SELECT sender, groupname, message, timestamp FROM urgent")
        messages = c.fetchall()
    
    if messages:
        response = "Urgent Messages:\n" + "\n".join([f"[{i+1}] {msg[0]} -> {msg[1]}: {msg[2]} ({msg[3]})" for i, msg in enumerate(messages)])
        send_message(response, sender_id, interface)
    else:
        send_message("No urgent messages available.", sender_id, interface)
    handle_js8call_command(sender_id, interface)

def handle_group_message_selection(sender_id, message, _step, state, interface):
    groups = state['groups']
    try:
        group_index = int(message)
        # Explicit bounds check to prevent negative index issues and crashes
        if not (0 <= group_index < len(groups)):
            raise ValueError("Index out of bounds")
            
        groupname = groups[group_index][0]
        messages = []
        db_path = get_js8_db_path()
        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()
            c.execute("SELECT sender, message, timestamp FROM groups WHERE groupname=?", (groupname,))
            messages = c.fetchall()

        if messages:
            response = f"Messages for group {groupname}:\n" + "\n".join([f"[{i+1}] {msg[0]}: {msg[1]} ({msg[2]})" for i, msg in enumerate(messages)])
            send_message(response, sender_id, interface)
        else:
            send_message(f"No messages for group {groupname}.", sender_id, interface)
        
        handle_js8call_command(sender_id, interface)
    except ValueError:
        send_message("Invalid group selection. Please choose again.", sender_id, interface)
        handle_group_messages_command(sender_id, interface)
