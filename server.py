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

from config_init import get_driver, init_cli_parser, initialize_config, merge_config
from database_core import initialize_database, set_db_path
from js8call_integration import JS8CallClient
from message_processing import init_executor, on_receive, shutdown_executor

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
    """
    Main application controller for the TC²-BBS. 
    Manages hardware lifecycle, monitoring, and integration threads.
    """

    def __init__(self):
        """
        Initializes the application state and synchronization primitives.
        """
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
        self.heartbeat_interval = 10
        self.running = True

    def _display_banner(self):
        """
        Prints the application splash screen to stdout.
        """
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
        """
        Orchestrates configuration loading and system-wide initialization.
        """
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
        
        parsed_keepalive = self._get_env_int("BBS_KEEPALIVE_INTERVAL", None)
        if parsed_keepalive is not None:
            self.keepalive_interval = parsed_keepalive
        else:
            self.keepalive_interval = self.config.get('keepalive_interval', 120)

        self.heartbeat_interval = self.config.get('heartbeat_interval', 10)

        # Low power mode overrides intervals to minimize radio traffic and local CPU cycles.
        if self.config.get('low_power'):
            self.heartbeat_interval = 120
            self.keepalive_interval = max(self.keepalive_interval, 300)
            logger.info(f"Low power mode enabled. Adjusting intervals: Heartbeat={self.heartbeat_interval}s, Keepalive={self.keepalive_interval}s, Watchdog={self.watchdog_timeout}s")

        # Heartbeat Setup
        runtime_dir = os.path.join(os.getcwd(), "run")
        os.makedirs(runtime_dir, exist_ok=True)
        self.heartbeat_path = os.environ.get(
            "BBS_HEARTBEAT_PATH", os.path.join(runtime_dir, "bbs_heartbeat")
        )

        logger.info(
            f"BBS Starting. Watchdog: {self.watchdog_timeout}s, Keepalive: {self.keepalive_interval}s, Heartbeat: {self.heartbeat_interval}s"
        )

    def _get_env_int(self, key, default):
        """
        Safely retrieves and parses an integer from the environment.

        Args:
            key (str): The environment variable name.
            default (int): Fallback value if parsing fails or result is non-positive.

        Returns:
            int: The parsed value or the default.
        """
        try:
            val = int(os.environ.get(key, default))
            return val if val > 0 else default
        except (ValueError, TypeError):
            return default

    def _write_heartbeat(self, status, reader_alive=True):
        """
        Atomically writes extended health metrics to the heartbeat file.
        Uses a temp-and-move strategy to ensure external monitors never see partial writes.

        Args:
            status (str): Current application status (e.g., 'CONNECTED').
            reader_alive (bool): Whether the underlying radio reader is functional.
        """
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
        """
        Subscriber callback for incoming mesh packets. Updates timers and routes data.

        Args:
            packet (dict): The incoming Meshtastic packet.
        """
        with self.last_rx_lock:
            self.last_rx_time = time.time()
        on_receive(packet, self.driver)

    def _run_monitoring_cycle(self, raw_interface):
        """
        The main health monitoring loop for an active radio session.
        Implements a multi-layered watchdog (Hardware, Protocol, and Data levels).

        Args:
            raw_interface: The underlying library-level radio interface.
        """
        last_keepalive_sent = 0
        transport_watchdog_enabled = raw_interface is not None

        while self.running:
            now = time.time()

            if not transport_watchdog_enabled:
                self._write_heartbeat("CONNECTED", reader_alive=True)
                time.sleep(self.heartbeat_interval)
                continue

            # Layer 1: Hardware-level check for TCP disconnects.
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

            # Layer 2: Protocol-level check for interface responsiveness.
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

            # Layer 3: Data-level check for prolonged mesh silence.
            with self.last_rx_lock:
                rx_delta = now - self.last_rx_time

            if rx_delta > self.watchdog_timeout:
                logger.warning(
                    f"Watchdog trigger: {int(rx_delta)}s of silence. Reconnecting..."
                )
                break

            # Send periodic probes to verify the radio is still accepting commands 
            # and to keep NAT/WiFi sessions active during quiet periods.
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

            self._write_heartbeat("CONNECTED", reader_alive=is_conn)
            time.sleep(self.heartbeat_interval)

    def _session_cleanup(self):
        """
        Performs localized cleanup after a radio session terminates, 
        ensuring drivers and executors are safely released before a restart attempt.
        """
        try:
            pub.unsubAll(self.config["mqtt_topic"])
        except (TopicNameError, Exception) as e:
            logger.debug(f"Failed to unsubscribe from {self.config['mqtt_topic']}: {e}", exc_info=True)

        shutdown_executor(wait=False, cancel_futures=True)

        if self.driver:
            try:
                # close() fences new packet work immediately, then drains any
                # driver calls already in progress before tearing down the radio.
                self.driver.close()
            except Exception:
                logger.exception("Error closing driver")
            self.driver = None

        self._write_heartbeat("DISCONNECTED", reader_alive=False)

    def shutdown(self):
        """
        Final application-level shutdown, releasing all global resources.
        """
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
        """
        The primary execution entry point. Implements the high-level retry loop 
        that keeps the BBS alive across transient hardware failures.
        """
        self._display_banner()
        self._setup_config()
        assert self.config is not None

        try:
            while self.running:
                try:
                    init_executor()

                    self.driver, raw_interface = get_driver(self.config)

                    pub.subscribe(self._handle_packet, self.config["mqtt_topic"])

                    # JS8Call integration runs in a dedicated thread to prevent blocking 
                    # the main Meshtastic reader loop during slow database queries.
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
