#!/usr/bin/env python3

"""
TC²-BBS Server for Meshtastic by TheCommsChannel (TC²)
Date: 07/14/2024
Version: 0.1.6

Description:
The system allows for mail message handling, bulletin boards, and a channel
directory. It uses a configuration file for setup details and an SQLite3
database for data storage. Mail messages and bulletins are synced with
other BBS servers listed in the config.ini file.
"""

import logging
import time
import socket
import threading
import os
import tempfile

from config_init import initialize_config, get_interface, init_cli_parser, merge_config
from db_operations import initialize_database
from js8call_integration import JS8CallClient
from message_processing import on_receive, shutdown_executor, init_executor
from pubsub import pub
try:
    from pubsub.core.topicmgr import TopicNameError
except ImportError:
    # Fallback for different pypubsub versions
    class TopicNameError(Exception):
        pass

# General logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# JS8Call logging
js8call_logger = logging.getLogger('js8call')
js8call_logger.setLevel(logging.DEBUG)
js8call_handler = logging.StreamHandler()
js8call_handler.setLevel(logging.DEBUG)
js8call_formatter = logging.Formatter('%(asctime)s - JS8Call - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S')
js8call_handler.setFormatter(js8call_formatter)
js8call_logger.addHandler(js8call_handler)

js8_thread_lock = threading.Lock()
last_rx_lock = threading.Lock()

def write_atomic_heartbeat(path, content):
    """Atomically writes content to path using a temporary file."""
    dir_name = os.path.dirname(path)
    base_name = os.path.basename(path)
    try:
        # Create temp file in the same directory as the target path
        with tempfile.NamedTemporaryFile('w', dir=dir_name, prefix=f".{base_name}", delete=False) as tf:
            tf.write(content)
            temp_path = tf.name
        # Atomically rename the temp file to the target path
        os.replace(temp_path, path)
    except OSError as e:
        logging.debug(f"Atomic heartbeat write failed: {e}")
        # Cleanup temp file if it exists and wasn't renamed
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

def display_banner():
    banner = """
████████╗ ██████╗██████╗       ██████╗ ██████╗ ███████╗
╚══██╔══╝██╔════╝╚════██╗      ██╔══██╗██╔══██╗██╔════╝
   ██║   ██║      █████╔╝█████╗██████╔╝██████╔╝███████╗
   ██║   ██║     ██╔═══╝ ╚════╝██╔══██╗██╔══██╗╚════██║
   ██║   ╚██████╗███████╗      ██████╔╝██████╔╝███████║
   ╚═╝    ╚═════╝╚══════╝      ╚═════╝ ╚═════╝ ╚══════╝
Meshtastic Version
"""
    print(banner)

def main():
    display_banner()
    args = init_cli_parser()
    config_file = None
    if args.config is not None:
        config_file = args.config
    system_config = initialize_config(config_file)

    merge_config(system_config, args)

    logging.info(f"TC²-BBS is starting on {system_config['interface_type']} interface...")

    initialize_database()

    js8call_client = None
    interface = None
    js8_thread = None
    
    # Heartbeat path from environment or default to an app-specific runtime directory
    # Avoiding plain /tmp to address Ruff S108
    runtime_dir = os.path.join(os.getcwd(), "run")
    try:
        os.makedirs(runtime_dir, exist_ok=True)
    except OSError:
        # Fallback to platform-native temp dir (satisfies Ruff S108)
        runtime_dir = tempfile.gettempdir()
        
    heartbeat_path = os.environ.get('BBS_HEARTBEAT_PATH', os.path.join(runtime_dir, 'bbs_heartbeat'))
    logging.info(f"Using heartbeat path: {heartbeat_path}")

    # Watchdog and Keepalive configuration
    try:
        WATCHDOG_TIMEOUT = int(os.environ.get('BBS_WATCHDOG_TIMEOUT', 300))
        if WATCHDOG_TIMEOUT <= 0:
            logging.warning("BBS_WATCHDOG_TIMEOUT must be positive. Falling back to default (300).")
            WATCHDOG_TIMEOUT = 300
    except (ValueError, TypeError):
        WATCHDOG_TIMEOUT = 300

    try:
        KEEPALIVE_INTERVAL = int(os.environ.get('BBS_KEEPALIVE_INTERVAL', 120))
        if KEEPALIVE_INTERVAL <= 0:
            logging.warning("BBS_KEEPALIVE_INTERVAL must be positive. Falling back to default (120).")
            KEEPALIVE_INTERVAL = 120
    except (ValueError, TypeError):
        KEEPALIVE_INTERVAL = 120
    
    logging.info(f"Watchdog timeout: {WATCHDOG_TIMEOUT}s, Keepalive interval: {KEEPALIVE_INTERVAL}s")

    # Track last received packet for a deep health check (protected by last_rx_lock)
    last_rx_time = time.time()

    try:
        while True:
            should_sleep = False
            try:
                # Ensure executor is running for this connection cycle
                init_executor()

                interface = get_interface(system_config)
                interface.bbs_nodes = system_config['bbs_nodes']
                interface.allowed_nodes = system_config['allowed_nodes']

                def receive_packet(packet, interface=interface):
                    nonlocal last_rx_time
                    with last_rx_lock:
                        last_rx_time = time.time()
                    on_receive(packet, interface)

                pub.subscribe(receive_packet, system_config['mqtt_topic'])

                # Initialize JS8Call Client if configured
                if js8call_client is None:
                    js8call_client = JS8CallClient(interface)
                    js8call_client.logger = js8call_logger
                else:
                    # Update interface in existing client if we reconnected
                    js8call_client.interface = interface

                # Start/Restart JS8Call connection thread if needed (guarded by lock)
                with js8_thread_lock:
                    if js8call_client.db_conn and not js8call_client.connected:
                        if js8_thread is None or not js8_thread.is_alive():
                            logging.info("Starting JS8Call connection thread...")
                            js8_thread = threading.Thread(target=js8call_client.connect, args=(js8_thread_lock,), daemon=True)
                            js8_thread.start()

                logging.info("Connected to Meshtastic interface.")
                
                # Reset RX time on successful connection to avoid immediate watchdog trigger
                with last_rx_lock:
                    last_rx_time = time.time()
                
                # Throttle keepalive traffic to avoid storms
                last_keepalive_sent = 0

                # Main wait loop - monitoring connection if possible
                while True:
                    now = time.time()
                    
                    # 1. Aggressive socket watchdog for TCP interfaces
                    if system_config['interface_type'] == 'tcp' and hasattr(interface, 'socket') and interface.socket:
                        try:
                            # getpeername() raises OSError if the socket is no longer connected
                            interface.socket.getpeername()
                        except OSError:
                            logging.warning("Detected disconnected socket in underlying TCP watchdog.")
                            should_sleep = True
                            break

                    # 2. Public connectivity check
                    is_conn = True
                    if hasattr(interface, 'isConnected'):
                        conn_status = interface.isConnected
                        if isinstance(conn_status, threading.Event):
                            is_conn = conn_status.is_set()
                        elif callable(conn_status):
                            is_conn = conn_status()
                        else:
                            is_conn = bool(conn_status)
                    
                    # Deriving reader_alive from public is_conn indicator
                    reader_alive = is_conn

                    if not is_conn:
                        logging.error("Meshtastic interface reports disconnected.")
                        should_sleep = True
                        break

                    # 3. Packet receive watchdog and Keepalive
                    with last_rx_lock:
                        current_last_rx = last_rx_time
                    
                    rx_delta = now - current_last_rx
                    
                    if rx_delta > WATCHDOG_TIMEOUT:
                        logging.warning(f"No packets received for {int(rx_delta)}s. Forcing reconnect.")
                        should_sleep = True
                        break
                    elif rx_delta > KEEPALIVE_INTERVAL and (now - last_keepalive_sent) > KEEPALIVE_INTERVAL:
                        # Generate keepalive traffic to maintain connection on quiet meshes
                        # Querying a remote node ID if available to trigger network I/O
                        try:
                            logging.debug("Mesh quiet, generating keepalive traffic...")
                            target_node = interface.myInfo.my_node_id
                            if interface.bbs_nodes:
                                # Use a known remote BBS node
                                target_node = interface.bbs_nodes[0]
                            elif hasattr(interface, 'nodes') and interface.nodes:
                                # Use any known remote node
                                for nid in interface.nodes:
                                    if nid != interface.myInfo.my_node_id:
                                        target_node = nid
                                        break
                            
                            interface.getNode(target_node)
                            last_keepalive_sent = now
                        except Exception as e:
                            logging.debug(f"Keepalive traffic failed: {e}")

                    # 4. Heartbeat update
                    # Format: TIMESTAMP|STATUS|READER_ALIVE|LAST_RX_TIME
                    write_atomic_heartbeat(heartbeat_path, f"{now}|CONNECTED|{reader_alive}|{current_last_rx}")
                    
                    time.sleep(5)

            except Exception:
                logging.exception("Error in main loop. Cleanup then retrying...")
                should_sleep = True
            finally:
                # 1. Unsubscribe first so no more packets reach on_receive
                try:
                    pub.unsubAll(system_config['mqtt_topic'])
                except TopicNameError as e:
                    logging.debug(f"pub.unsubAll TopicNameError: {e}")
                except Exception:
                    logging.debug("pub.unsubAll cleanup", exc_info=True)

                # 2. Before closing the interface, stop the message processing executor
                # so no background tasks try to use the closed interface.
                # wait=True ensures in-flight tasks finish before we close interface.
                shutdown_executor(wait=True, cancel_futures=True)

                # 3. Finally close the hardware interface
                if interface:
                    try:
                        interface.close()
                    except Exception:
                        logging.exception("Error closing interface in main loop finally")
                    interface = None # Ensure reference is cleared for next iteration or shutdown
                
                # Update heartbeat to reflect state during back-off/reconnection
                with last_rx_lock:
                    reported_last_rx = last_rx_time
                write_atomic_heartbeat(heartbeat_path, f"{time.time()}|DISCONNECTED|False|{reported_last_rx}")

                if should_sleep:
                    logging.info("Waiting 10 seconds before reconnection attempt...")
                    time.sleep(10)

    except KeyboardInterrupt:
        logging.info("Shutting down the server...")
    finally:
        # Final shutdown cleanup - shutdown executor FIRST to stop in-flight tasks
        shutdown_executor(wait=True)
        
        if js8call_client:
            try:
                logging.info("Signaling JS8Call client to close...")
                with js8_thread_lock:
                    # We hold the lock here, so we pass lock=None to close() to avoid deadlock
                    js8call_client.close(lock=None)
            except Exception:
                logging.exception("Error closing JS8Call client during shutdown")
        
        # Cleanup heartbeat file
        try:
            os.remove(heartbeat_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logging.debug(f"Error removing heartbeat file during cleanup: {e}")

if __name__ == "__main__":
    main()
