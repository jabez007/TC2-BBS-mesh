#!/usr/bin/env python3
import os
import socket
import sys
import time


def check_meshtastic_connection():
    """Test actual meshtastic TCP connection with protocol handshake"""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("localhost", 4403))

        # Send a simple heartbeat-like message (similar to what causes the BrokenPipeError)
        # This is a minimal ToRadio protobuf message
        heartbeat_msg = b"\\x08\\x01"  # Simple heartbeat message
        s.send(heartbeat_msg)

        # Try to read response to ensure bidirectional communication works
        s.settimeout(2)
        response = s.recv(1024)  # Try to read any response

        return True
    except (
        ConnectionResetError,
        BrokenPipeError,
        OSError,
        socket.timeout,
    ) as e:
        print(f"Connection test failed: {e}")
        return False
    except Exception as e:
        print(f"Unexpected connection error: {e}")
        return False
    finally:
        if s:
            s.close()


def check_process_health():
    """Check if server.py process is running and responsive"""
    try:
        # Check if main process exists
        with open("/proc/1/cmdline", "rb") as f:
            cmdline = f.read().decode("utf-8", errors="ignore")
            if "server.py" not in cmdline:
                print("server.py not running as PID 1")
                return False

        # Send a harmless signal to test if process is responsive
        os.kill(1, 0)  # Signal 0 tests if process exists and is accessible
        return True
    except (ProcessLookupError, PermissionError, OSError) as e:
        print(f"Process check failed: {e}")
        return False


# Run health checks
print("Running connection health check...")
connection_ok = False
for attempt in range(3):
    if check_meshtastic_connection():
        connection_ok = True
        print(f"Connection test attempt {attempt + 1}: PASS")
        break
    else:
        print(f"Connection test attempt {attempt + 1}: FAIL")
        time.sleep(1)

if not connection_ok:
    print("All connection attempts failed")
    sys.exit(1)

print("Running process health check...")
if not check_process_health():
    print("Process health check failed")
    sys.exit(1)

print("All health checks passed")
sys.exit(0)
