import argparse
import configparser
import logging
import socket
from typing import Any

import meshtastic.serial_interface
import meshtastic.stream_interface
import meshtastic.tcp_interface
import serial.tools.list_ports

logger = logging.getLogger(__name__)


def init_cli_parser() -> argparse.Namespace:
    """
    Initializes the command-line interface parser and processes arguments.

    Returns:
        argparse.Namespace: Object containing the parsed CLI arguments.
    """
    parser = argparse.ArgumentParser(description="Meshtastic BBS system")

    parser.add_argument(
        "--config", "-c", action="store", help="System configuration file", default=None
    )

    parser.add_argument(
        "--interface-type",
        "-i",
        action="store",
        choices=["serial", "tcp"],
        help="Node interface type",
        default=None,
    )

    parser.add_argument(
        "--port", "-p", action="store", help="Serial port", default=None
    )

    parser.add_argument("--host", action="store", help="TCP host address", default=None)

    parser.add_argument(
        "--mqtt-topic",
        "-t",
        action="store",
        help="MQTT topic to subscribe",
        default="meshtastic.receive",
    )

    parser.add_argument(
        "--heartbeat-interval",
        action="store",
        type=int,
        help="Heartbeat interval in seconds (default: 10)",
        default=None,
    )

    parser.add_argument(
        "--low-power",
        action="store_true",
        help="Enable low power mode (increases intervals)",
        default=False,
    )

    args = parser.parse_args()

    return args


def merge_config(
    system_config: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    """
    Merges CLI arguments into the existing system configuration dictionary.
    CLI arguments take precedence over config file values.

    Args:
        system_config (dict): The configuration dictionary to be updated.
        args (argparse.Namespace): The parsed command-line arguments.

    Returns:
        dict: The updated system configuration dictionary.
    """

    if args.interface_type is not None:
        system_config["interface_type"] = args.interface_type

    if args.port is not None:
        system_config["port"] = args.port

    if args.host is not None:
        system_config["hostname"] = args.host

    if args.heartbeat_interval is not None:
        system_config["heartbeat_interval"] = args.heartbeat_interval

    if args.low_power:
        system_config["low_power"] = True

    return system_config


def initialize_config(config_file: str = None) -> dict[str, Any]:
    """
    Loads and parses the system configuration file.

    Args:
        config_file (str, optional): Path to the .ini config file. 
            Defaults to 'config.ini' if not provided.

    Returns:
        dict: A flat dictionary containing key application settings including 
            interface details, sync nodes, and healthcheck parameters.
    """
    config = configparser.ConfigParser()

    if config_file is None:
        config_file = "config.ini"
    config.read(config_file)

    interface_type = config["interface"]["type"]
    hostname = config["interface"].get("hostname", None)
    port = config["interface"].get("port", None)

    bbs_nodes = config.get("sync", "bbs_nodes", fallback="").split(",")
    if bbs_nodes == [""]:
        bbs_nodes = []

    print(f"Configured to sync with the following BBS nodes: {bbs_nodes}")

    allowed_nodes = config.get("allow_list", "allowed_nodes", fallback="").split(",")
    if allowed_nodes == [""]:
        allowed_nodes = []

    print(f"Nodes with Urgent board permissions: {allowed_nodes}")

    heartbeat_interval = config.getint("healthcheck", "heartbeat_interval", fallback=10)
    low_power = config.getboolean("healthcheck", "low_power", fallback=False)

    return {
        "config": config,
        "interface_type": interface_type,
        "hostname": hostname,
        "port": port,
        "bbs_nodes": bbs_nodes,
        "allowed_nodes": allowed_nodes,
        "mqtt_topic": "meshtastic.receive",
        "heartbeat_interval": heartbeat_interval,
        "low_power": low_power,
    }


def get_interface(
    system_config: dict[str, Any],
) -> meshtastic.stream_interface.StreamInterface:
    """
    Instantiates and configures the appropriate Meshtastic hardware interface.

    Args:
        system_config (dict): Configuration containing interface type and parameters.

    Returns:
        meshtastic.stream_interface.StreamInterface: An active radio interface.

    Raises:
        ValueError: If configuration is incomplete or ambiguous (e.g., multiple ports).
    """
    if system_config["interface_type"] == "serial":
        if system_config["port"]:
            return meshtastic.serial_interface.SerialInterface(system_config["port"])
        else:
            # Auto-detect ports if only one is available to simplify setup for single-radio nodes.
            ports = list(serial.tools.list_ports.comports())
            if len(ports) == 1:
                return meshtastic.serial_interface.SerialInterface(ports[0].device)
            elif len(ports) > 1:
                port_list = ", ".join([p.device for p in ports])
                raise ValueError(
                    f"Multiple serial ports detected: {port_list}. Specify one with the 'port' argument."
                )
            else:
                raise ValueError("No serial ports detected.")
    elif system_config["interface_type"] == "tcp":
        if not system_config["hostname"]:
            raise ValueError("Hostname must be specified for TCP interface")
        interface = meshtastic.tcp_interface.TCPInterface(
            hostname=system_config["hostname"]
        )

        # TCP Keep-Alive is configured to prevent WiFi routers or NAT gateways 
        # from silently dropping the connection during mesh inactivity.
        if hasattr(interface, "socket") and interface.socket:
            try:
                sock = interface.socket
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, "TCP_KEEPIDLE"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                if hasattr(socket, "TCP_KEEPINTVL"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                if hasattr(socket, "TCP_KEEPCNT"):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                logger.info("TCP Keep-Alive enabled for Meshtastic interface.")
            except (AttributeError, OSError) as e:
                logger.debug(f"Could not set TCP Keep-Alive: {e}")
        return interface
    else:
        raise ValueError("Invalid interface type specified in config file")
