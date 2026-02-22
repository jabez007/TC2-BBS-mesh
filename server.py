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

from config_init import initialize_config, get_interface, init_cli_parser, merge_config
from db_operations import initialize_database
from js8call_integration import JS8CallClient
from message_processing import on_receive
from pubsub import pub

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

    while True:
        interface = None
        try:
            interface = get_interface(system_config)
            interface.bbs_nodes = system_config['bbs_nodes']
            interface.allowed_nodes = system_config['allowed_nodes']

            def receive_packet(packet, interface=interface):
                on_receive(packet, interface)

            pub.subscribe(receive_packet, system_config['mqtt_topic'])

            # Initialize and start JS8Call Client if configured
            if js8call_client is None:
                js8call_client = JS8CallClient(interface)
                js8call_client.logger = js8call_logger
                if js8call_client.db_conn:
                    import threading
                    js8_thread = threading.Thread(target=js8call_client.connect, daemon=True)
                    js8_thread.start()
            else:
                # Update interface in existing client if we reconnected
                js8call_client.interface = interface

            logging.info("Connected to Meshtastic interface.")

            # Main wait loop - monitoring connection if possible
            while True:
                # Update heartbeat file for Docker healthcheck
                try:
                    with open('/tmp/bbs_heartbeat', 'w') as f:
                        f.write(str(time.time()))
                except:
                    pass

                if hasattr(interface, 'isConnected') and not interface.isConnected():
                    logging.error("Meshtastic interface disconnected.")
                    break
                time.sleep(5)

        except Exception as e:
            logging.error(f"Error in main loop: {e}. Retrying in 10 seconds...")
            time.sleep(10)
        finally:
            if interface:
                try:
                    interface.close()
                except:
                    pass
            pub.unsubAll(system_config['mqtt_topic'])

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        logging.info("Shutting down the server...")
        if interface:
            interface.close()
        if js8call_client and js8call_client.connected:
            js8call_client.close()

if __name__ == "__main__":
    main()
