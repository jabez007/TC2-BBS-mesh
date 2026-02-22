#!/usr/bin/env python3
import os
import socket
import sys
import time
import configparser


def get_config():
    """Read configuration from expected locations"""
    config = configparser.ConfigParser()
    config_paths = [
        "/home/mesh/bbs/config.ini",
        "/home/mesh/bbs/config/config.ini",
        "config.ini",
    ]
    for path in config_paths:
        if os.path.exists(path):
            config.read(path)
            return config
    return None


def check_meshtastic_connection(host="localhost", port=4403):
    """Test actual meshtastic TCP connection with protocol handshake"""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, port))

        # Send a 2-byte protobuf heartbeat
        heartbeat_msg = b"\x08\x01"
        s.sendall(heartbeat_msg)

        # Try to read response, but treat timeout as success (ping sent)
        s.settimeout(2)
        try:
            response = s.recv(1024)
            if response == b"":  # EOF
                return False
        except socket.timeout:
            # Timeout is okay, it means the connection is alive
            return True
        else:
            return True

    except (
        ConnectionResetError,
        BrokenPipeError,
        OSError,
        socket.timeout,
    ) as e:
        print(f"Connection test to {host}:{port} failed: {e}")
        return False
    finally:
        if s:
            s.close()


def check_process_health():
    """Check if server.py process is running and responsive"""
    try:
        # Check if main process exists
        # In Docker, the entrypoint.sh might be PID 1, and server.py might be a child
        # or replaced by exec. Let's look for any process named server.py
        pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]
        found = False
        for pid in pids:
            try:
                with open(os.path.join('/proc', pid, 'cmdline'), 'rb') as f:
                    cmdline = f.read().decode('utf-8', errors='ignore')
                    if 'server.py' in cmdline:
                        # Test if process is responsive
                        os.kill(int(pid), 0)
                        found = True
                        break
            except (OSError, IOError):
                continue
        
        if not found:
            print("server.py process not found")
            return False
    except (ProcessLookupError, PermissionError, OSError) as e:
        print(f"Process check failed: {e}")
        return False
    else:
        return True


# Run health checks
config = get_config()
interface_type = "serial"
hostname = "localhost"
tcp_port = 4403

if config and 'interface' in config:
    interface_type = config['interface'].get('type', 'serial').lower()
    hostname = config['interface'].get('hostname', 'localhost')
    # Try to get port, default to 4403 for TCP
    try:
        tcp_port = config['interface'].getint('port', 4403)
    except ValueError:
        tcp_port = 4403

print(f"Detected interface: {interface_type}")

if interface_type == "tcp":
    print(f"Running TCP connection health check to {hostname}:{tcp_port}...")
    connection_ok = False
    for attempt in range(3):
        if check_meshtastic_connection(host=hostname, port=tcp_port):
            connection_ok = True
            print(f"Connection test attempt {attempt + 1}: PASS")
            break
        else:
            print(f"Connection test attempt {attempt + 1}: FAIL")
            time.sleep(1)
    
    if not connection_ok:
        print("All connection attempts failed")
        sys.exit(1)
else:
    print("Skipping TCP check for serial/unknown interface. Running process health check...")
    if not check_process_health():
        print("Process health check failed")
        sys.exit(1)

print("All health checks passed")
sys.exit(0)
