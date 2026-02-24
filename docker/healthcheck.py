#!/usr/bin/env python3
import os
import socket
import sys
import time
import configparser
import tempfile


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
    """Test if the meshtastic TCP API port is open (safely via handshake and peek)"""
    s = None
    try:
        # 1. Test the Handshake
        s = socket.create_connection((host, port), timeout=3)
        
        # 2. Test the READ side to ensure the remote hasn't hung up
        s.settimeout(1)
        try:
            # Peek to see if the connection is still alive (b"" means EOF/Closed)
            # This is safe and doesn't break framing
            if s.recv(1, socket.MSG_PEEK) == b"":
                return False, "EOF from remote"
        except socket.timeout:
            # Timeout is GOOD - it means the connection is open but quiet
            pass
            
    except OSError as e:
        # Note: This is expected if the radio only allows a single connection and the BBS is connected
        return False, str(e)
    else:
        return True, "Handshake successful"
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
    """Check if the heartbeat file is recent"""
    # Try custom path from env
    env_heartbeat_path = os.environ.get('BBS_HEARTBEAT_PATH')
    heartbeat_path = env_heartbeat_path
    
    if not heartbeat_path:
        # Match server.py's priority: ./run/ then tempfile.gettempdir()
        search_dirs = [os.path.join(os.getcwd(), "run"), tempfile.gettempdir()]
        
        found_path = None
        for d in search_dirs:
            if not os.path.exists(d):
                continue
                
            if server_pid:
                test_path = os.path.join(d, f'bbs_heartbeat_{server_pid}')
                if os.path.exists(test_path):
                    found_path = test_path
                    break
            
            # If PID specific file not found or server_pid is None, look for any matching file in this dir
            try:
                for f in os.listdir(d):
                    if f.startswith('bbs_heartbeat_'):
                        found_path = os.path.join(d, f)
                        break
            except OSError:
                continue
                
            if found_path:
                break
        
        heartbeat_path = found_path

    if not heartbeat_path or not os.path.exists(heartbeat_path):
        if env_heartbeat_path:
            print(f"Heartbeat file missing at BBS_HEARTBEAT_PATH: {env_heartbeat_path}")
        else:
            print(f"Heartbeat file missing (searched ./run/ and {tempfile.gettempdir()})")
        return False
    
    try:
        mtime = os.path.getmtime(heartbeat_path)
        age = time.time() - mtime
        if age > max_age:
            print(f"Heartbeat file too old: {age:.1f}s (max {max_age}s)")
            return False
    except OSError as e:
        print(f"Error checking heartbeat file: {e}")
        return False
    else:
        print(f"Heartbeat file is fresh: {age:.1f}s old")
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
