#!/usr/bin/env python3

"""
TC²-BBS Server for Meshtastic by TheCommsChannel (TC²)
Date: 02/27/2026
Version: 2.0.0

Description:
A modular Multi-Mode BBS Server. Orchestrates radio drivers,
database operations, and third-party integrations (JS8Call).
"""

import logging
import os
import tempfile
import threading
import time

from pubsub import pub

from config_init import get_interface, init_cli_parser, initialize_config, merge_config
from database_core import initialize_database, set_db_path
from js8call_integration import JS8CallClient
from message_processing import init_executor, on_receive, shutdown_executor
from radio_drivers import MeshtasticDriver

try:
    from pubsub.core.topicmgr import TopicNameError
except ImportError:

    class TopicNameError(Exception):
        pass


# Global logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# JS8Call logging setup
js8call_logger = logging.getLogger("js8call")
js8call_logger.setLevel(logging.DEBUG)
js8call_logger.propagate = False
js8call_handler = logging.StreamHandler()
js8call_handler.setLevel(logging.DEBUG)
js8call_formatter = logging.Formatter(
    "%(asctime)s - JS8Call - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
)
js8call_handler.setFormatter(js8call_formatter)
js8call_logger.addHandler(js8call_handler)

logger = logging.getLogger(__name__)


class BBSApp:
    def __init__(self):
        self.config = None
        self.args = None
        self.driver = None
        self.js8call_client = None
        self.js8_thread = None
        self.js8_thread_lock = threading.Lock()

        self.last_rx_time = time.time()
        self.last_rx_lock = threading.Lock()

        self.heartbeat_path = None
        self.watchdog_timeout = 300
        self.keepalive_interval = 120
        self.running = True

    def _display_banner(self):
        banner = """
████████╗ ██████╗██████╗       ██████╗ ██████╗ ███████╗
╚══██╔══╝██╔════╝╚════██╗      ██╔══██╗██╔══██╗██╔════╝
   ██║   ██║      █████╔╝█████╗██████╔╝██████╔╝███████╗
   ██║   ██║     ██╔═══╝ ╚════╝██╔══██╗██╔══██╗╚════██║
   ██║   ╚██████╗███████╗      ██████╔╝██████╔╝███████║
   ╚═╝    ╚═════╝╚══════╝      ╚═════╝ ╚═════╝ ╚══════╝
Multi-Mode BBS Engine
"""
        print(banner)

    def _setup_config(self):
        self.args = init_cli_parser()
        config_file = self.args.config if self.args.config else "config.ini"
        self.config = initialize_config(config_file)
        merge_config(self.config, self.args)

        # Database Setup
        db_config_path = self.config["config"].get("database", "db_path", fallback=None)
        if db_config_path:
            set_db_path(db_config_path)
        initialize_database()

        # Monitor Settings
        self.watchdog_timeout = self._get_env_int("BBS_WATCHDOG_TIMEOUT", 300)
        self.keepalive_interval = self._get_env_int("BBS_KEEPALIVE_INTERVAL", 120)

        # Heartbeat Setup
        runtime_dir = os.path.join(os.getcwd(), "run")
        os.makedirs(runtime_dir, exist_ok=True)
        self.heartbeat_path = os.environ.get(
            "BBS_HEARTBEAT_PATH", os.path.join(runtime_dir, "bbs_heartbeat")
        )

        logger.info(
            f"BBS Starting. Watchdog: {self.watchdog_timeout}s, Keepalive: {self.keepalive_interval}s"
        )

    def _get_env_int(self, key, default):
        try:
            val = int(os.environ.get(key, default))
            return val if val > 0 else default
        except (ValueError, TypeError):
            return default

    def _write_heartbeat(self, status, reader_alive=True):
        """Atomically writes heartbeat metrics."""
        now = time.time()
        with self.last_rx_lock:
            last_rx = self.last_rx_time

        content = f"{now}|{status}|{reader_alive}|{last_rx}"
        dir_name = os.path.dirname(self.heartbeat_path)
        base_name = os.path.basename(self.heartbeat_path)

        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=dir_name, prefix=f".{base_name}", delete=False
            ) as tf:
                tf.write(content)
                temp_path = tf.name
            os.replace(temp_path, self.heartbeat_path)
        except OSError as e:
            logger.debug(f"Heartbeat write failed: {e}")

    def _handle_packet(self, packet):
        """Subscriber callback for incoming packets."""
        with self.last_rx_lock:
            self.last_rx_time = time.time()
        on_receive(packet, self.driver)

    def _run_monitoring_cycle(self, raw_interface):
        """Inner loop for a single connection session."""
        last_keepalive_sent = 0

        while self.running:
            now = time.time()

            # 1. Hardware-level Watchdog (TCP Sockets)
            if (
                self.config["interface_type"] == "tcp"
                and hasattr(raw_interface, "socket")
                and raw_interface.socket
            ):
                try:
                    raw_interface.socket.getpeername()
                except OSError:
                    logger.warning("TCP socket disconnected.")
                    break

            # 2. Protocol-level Watchdog (Connectivity)
            is_conn = True
            if hasattr(raw_interface, "isConnected"):
                conn_status = raw_interface.isConnected
                is_conn = (
                    conn_status.is_set()
                    if isinstance(conn_status, threading.Event)
                    else (conn_status() if callable(conn_status) else bool(conn_status))
                )

            if not is_conn:
                logger.error("Radio interface disconnected.")
                break

            # 3. Data-level Watchdog (Silence Timeout)
            with self.last_rx_lock:
                rx_delta = now - self.last_rx_time

            if rx_delta > self.watchdog_timeout:
                logger.warning(
                    f"Watchdog trigger: {int(rx_delta)}s of silence. Reconnecting..."
                )
                break

            # 4. Keepalive Logic
            if (
                rx_delta > self.keepalive_interval
                and (now - last_keepalive_sent) > self.keepalive_interval
            ):
                try:
                    logger.debug("Mesh quiet, sending keepalive...")
                    target = (
                        self.driver.bbs_nodes[0]
                        if self.driver.bbs_nodes
                        else self.driver.get_my_node_id()
                    )
                    self.driver.getNode(target)
                    last_keepalive_sent = now
                except Exception as e:
                    logger.debug(f"Keepalive failed: {e}")

            # 5. Heartbeat
            self._write_heartbeat("CONNECTED", reader_alive=is_conn)
            time.sleep(5)

    def _session_cleanup(self):
        """Cleanup after a single radio session."""
        try:
            pub.unsubAll(self.config["mqtt_topic"])
        except (TopicNameError, Exception):
            pass

        shutdown_executor(wait=False, cancel_futures=True)

        if self.driver:
            try:
                self.driver.close()
            except Exception:
                logger.exception("Error closing driver")
            self.driver = None

        self._write_heartbeat("DISCONNECTED", reader_alive=False)

    def shutdown(self):
        """Final application-level shutdown."""
        logger.info("BBS Application shutting down...")
        self.running = False
        shutdown_executor(wait=True)

        if self.js8call_client:
            with self.js8_thread_lock:
                self.js8call_client.close(lock=None)

        if self.heartbeat_path and os.path.exists(self.heartbeat_path):
            try:
                os.remove(self.heartbeat_path)
            except OSError:
                pass

    def run(self):
        self._display_banner()
        self._setup_config()

        try:
            while self.running:
                try:
                    init_executor()

                    # 1. Initialize Hardware Interface
                    raw_interface = get_interface(self.config)
                    self.driver = MeshtasticDriver(raw_interface)
                    self.driver.bbs_nodes = self.config["bbs_nodes"]
                    self.driver.allowed_nodes = self.config["allowed_nodes"]

                    # 2. Setup Subscriptions
                    pub.subscribe(self._handle_packet, self.config["mqtt_topic"])

                    # 3. Setup JS8Call Integration
                    if not self.js8call_client:
                        self.js8call_client = JS8CallClient(self.driver)
                        self.js8call_client.logger = js8call_logger
                    else:
                        self.js8call_client.driver = self.driver

                    with self.js8_thread_lock:
                        if (
                            self.js8call_client.db_conn
                            and not self.js8call_client.connected
                        ):
                            if not self.js8_thread or not self.js8_thread.is_alive():
                                logger.info("Starting JS8Call integration thread...")
                                self.js8_thread = threading.Thread(
                                    target=self.js8call_client.connect,
                                    args=(self.js8_thread_lock,),
                                    daemon=True,
                                )
                                self.js8_thread.start()

                    # 4. Reset Timers & Start Monitoring
                    with self.last_rx_lock:
                        self.last_rx_time = time.time()

                    logger.info("BBS Session Active.")
                    self._run_monitoring_cycle(raw_interface)

                except Exception:
                    logger.exception("Session error. Cleanup and retrying...")
                finally:
                    self._session_cleanup()
                    if self.running:
                        time.sleep(10)

        except KeyboardInterrupt:
            self.shutdown()


if __name__ == "__main__":
    app = BBSApp()
    app.run()
