#!/usr/bin/env python3
import os
import socket
import sys
import time
import configparser
import tempfile


import math

# Configurable healthcheck timeout (defaults to 10 minutes)
# Usually 2x the server's reconnect watchdog (2 * 300s = 600s)
try:
    RX_TIMEOUT = int(os.environ.get('HEALTHCHECK_RX_TIMEOUT', 600))
    if RX_TIMEOUT <= 0:
        RX_TIMEOUT = 600
except (ValueError, TypeError):
    RX_TIMEOUT = 600


def get_config():
    """Read configuration from expected locations and return (config, path)"""
    config_paths = [
        "/home/mesh/bbs/config.ini",
        "/home/mesh/bbs/config/config.ini",
        "config.ini",
    ]
    for path in config_paths:
        config = configparser.ConfigParser()
        try:
            with open(path, "r") as fh:
                config.read_file(fh)
        except FileNotFoundError:
            continue
        except (configparser.Error, OSError) as e:
            print(f"Error reading config at {path}: {e}")
        else:
            return config, path
    return None, None


def check_meshtastic_connection(host="localhost", port=4403):
    """Test if the meshtastic TCP API port is open and responding with protocol handshake"""
    s = None
    try:
        # 1. Connect to the radio
        s = socket.create_connection((host, port), timeout=3)
        
        # 2. Send a Meshtastic ToRadio protobuf with want_config_id: 1
        # Framing: 0x94 0xc3 (sync), 0x00 0x02 (length), 0x08 0x01 (payload)
        heartbeat_msg = b"\x94\xc3\x00\x02\x08\x01"
        s.sendall(heartbeat_msg)

        # 3. Try to read response to ensure bidirectional communication works
        s.settimeout(2)
        response = s.recv(1024)
        if len(response) >= 2 and response[0] == 0x94 and response[1] == 0xc3:
            return True, "Handshake successful"
        else:
            return False, "Invalid radio response"
            
    except ConnectionRefusedError:
        # This is expected if the radio only allows one connection and the BBS is connected
        return True, "Radio busy (likely connected to BBS)"
    except OSError as e:
        return False, str(e)
    finally:
        if s:
            try:
                s.close()
            except OSError:
                pass

def check_files(config_path):
    """Verify essential application files exist"""
    # SQLite uses bulletins.db in current working directory of server.py
    # Look in CWD and config dir for bulletins.db to match server resolution
    db_paths = [
        "bulletins.db",
        os.path.join(os.path.dirname(config_path), "bulletins.db")
    ]
    
    found_db = False
    for db_path in db_paths:
        if os.path.exists(db_path) and os.access(db_path, os.R_OK):
            found_db = True
            break
            
    if not found_db:
        print("Essential file missing or not readable: bulletins.db (looked in CWD and config dir)")
        return False
        
    return True


def check_process_health():
    """Check if server.py process is running and responsive"""
    try:
        # Check if main process exists
        if not os.path.exists('/proc'):
            print("Error: /proc filesystem not found. Cannot check process health.")
            return False, None
            
        pids = [pid for pid in os.listdir('/proc') if pid.isdigit()]
        if not pids:
            print("Error: No processes found in /proc.")
            return False, None

        found = False
        server_pid = None
        for pid in pids:
            try:
                with open(os.path.join('/proc', pid, 'cmdline'), 'rb') as f:
                    cmdline = f.read().decode('utf-8', errors='ignore')
                    if 'server.py' in cmdline:
                        try:
                            # Test if process is responsive
                            os.kill(int(pid), 0)
                            print(f"Found server.py process at PID {pid}")
                            print(f"Process {pid} is responsive (signal 0 passed)")
                            found = True
                            server_pid = pid
                            break
                        except ProcessLookupError:
                            print(f"PID {pid} exited before check")
                            continue
                        except PermissionError:
                            # If we can't signal it but it exists, consider it found
                            print(f"Found server.py process at PID {pid}")
                            print(f"Process {pid} exists but permission denied for signaling")
                            found = True
                            server_pid = pid
                            break
            except OSError:
                continue
        
        if not found:
            print(f"server.py process not found after scanning {len(pids)} PIDs")
            return False, None
    except OSError as e:
        print(f"Process check failed during /proc scan: {e}")
        return False, None
    else:
        return found, server_pid


def check_heartbeat(server_pid, max_age=60):
    """Check if the heartbeat file is recent and status is healthy"""
    # Try custom path from env
    env_heartbeat_path = os.environ.get('BBS_HEARTBEAT_PATH')
    heartbeat_path = env_heartbeat_path
    
    if not heartbeat_path:
        # Match server.py's priority: ./run/ then tempfile.gettempdir()
        search_dirs = [os.path.join(os.getcwd(), "run"), tempfile.gettempdir()]
        
        candidates = []
        for d in search_dirs:
            if not os.path.exists(d):
                continue
            
            try:
                for f in os.listdir(d):
                    # Inner try/except to wrap only per-file operations so one failure doesn't stop scanning
                    try:
                        if f == 'bbs_heartbeat' or f.startswith('bbs_heartbeat_'):
                            full_path = os.path.join(d, f)
                            mtime = os.path.getmtime(full_path)
                            
                            # Store score (PID match priority) and mtime for sorting
                            is_pid_match = server_pid and f == f'bbs_heartbeat_{server_pid}'
                            candidates.append({
                                'path': full_path,
                                'mtime': mtime,
                                'is_pid_match': is_pid_match
                            })
                    except OSError:
                        continue
            except OSError:
                continue
        
        if candidates:
            # Sort: PID match first, then newest mtime
            candidates.sort(key=lambda x: (x['is_pid_match'], x['mtime']), reverse=True)
            heartbeat_path = candidates[0]['path']

    if not heartbeat_path or not os.path.exists(heartbeat_path):
        if env_heartbeat_path:
            print(f"Heartbeat file missing at BBS_HEARTBEAT_PATH: {env_heartbeat_path}")
        else:
            print(f"Heartbeat file missing (searched ./run/ and {tempfile.gettempdir()})")
        return False
    
    try:
        now = time.time()
        with open(heartbeat_path, 'r') as f:
            content = f.read().strip()
            parts = content.split('|')
            
            if len(parts) >= 2:
                ts_str, status = parts[0], parts[1]
                mtime = float(ts_str)
                if not math.isfinite(mtime):
                    print(f"Invalid non-finite timestamp in heartbeat: {ts_str}")
                    return False

                is_connected = (status == "CONNECTED")
                
                # Check extended metrics if available
                reader_alive = True
                if len(parts) >= 3:
                    reader_alive = (parts[2].lower() == 'true')
                
                last_rx_time = mtime
                if len(parts) >= 4:
                    try:
                        val = float(parts[3])
                        if math.isfinite(val):
                            last_rx_time = val
                        else:
                            print(f"Invalid non-finite RX timestamp: {parts[3]}")
                            # fallback to mtime if RX timestamp is corrupt
                            last_rx_time = mtime
                    except ValueError:
                        last_rx_time = mtime
                
                # Double check last_rx_time is finite for safe age calculation
                if not math.isfinite(last_rx_time):
                    print(f"Invalid non-finite last_rx_time: {last_rx_time}")
                    last_rx_time = mtime
            else:
                mtime = os.path.getmtime(heartbeat_path)
                is_connected = False
                reader_alive = False
                last_rx_time = 0
                status = "LEGACY_OR_MALFORMED"

        # Prevent negative ages from future timestamps
        if mtime > now:
            print(f"Warning: Heartbeat timestamp is in the future ({mtime - now:.1f}s). Treating as stale.")
            age = float('inf')
        else:
            age = now - mtime

        if last_rx_time > now:
            print(f"Warning: Last RX timestamp is in the future ({last_rx_time - now:.1f}s). Treating as stale.")
            rx_age = float('inf')
        else:
            rx_age = now - last_rx_time
        
        # 1. Age check (is the process even looping?)
        if age > max_age:
            print(f"Heartbeat file too old: {age:.1f}s (max {max_age}s)")
            return False
        
        # 2. Status check (is the BBS reporting it's connected?)
        if not is_connected:
            print(f"BBS reports unhealthy status: {status}")
            return False
            
        # 3. Reader thread check (deep health check)
        if not reader_alive:
            print("BBS reports internal reader thread is dead")
            return False
            
        # 4. Packet timeout check (has it received anything lately?)
        # Marginal delay (RX_TIMEOUT defaults to 600s = 2 x 300s server reconnect timeout)
        if rx_age > RX_TIMEOUT:
            print(f"No radio data received for {rx_age:.1f}s (zombie state)")
            return False
            
    except (OSError, ValueError) as e:
        print(f"Error checking heartbeat file: {e}")
        return False
    else:
        print(f"BBS is healthy: {status}, Reader: {reader_alive}, LastRX: {int(rx_age)}s ago")
        return True


def main():
    # Run health checks
    config, config_path = get_config()
    if not config_path:
        print("Error: No configuration file (config.ini) found in expected locations.")
        sys.exit(1)

    print(f"Using configuration from: {config_path}")

    print("Running file health checks...")
    if not check_files(config_path):
        print("File health checks failed")
        sys.exit(1)

    # 1. Check process health first
    print("Running process health check...")
    found, server_pid = check_process_health()
    if not found:
        print("Process health check failed")
        sys.exit(1)
    
    # 2. Check heartbeat (Source of Truth for connection health)
    print("Running heartbeat health check...")
    if not check_heartbeat(server_pid):
        print("Heartbeat health check failed")
        sys.exit(1)

    # 3. TCP Port check (Soft check - log results but don't fail healthcheck)
    interface_type = "serial"
    hostname = "localhost"
    tcp_port = 4403 # Meshtastic TCP default

    if config and 'interface' in config:
        interface_type = config['interface'].get('type', 'serial').lower()
        hostname = config['interface'].get('hostname', 'localhost')
        
        if interface_type == 'tcp':
            try:
                tcp_port = config['interface'].getint('port', 4403)
            except ValueError:
                tcp_port = 4403

    if interface_type == "tcp":
        print(f"Running soft TCP connection probe to {hostname}:{tcp_port}...")
        success, detail = check_meshtastic_connection(host=hostname, port=tcp_port)
        status = "SUCCESS" if success else "FAILURE"
        print(f"Soft TCP Probe result: {status} ({detail})")

    print("All health checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
