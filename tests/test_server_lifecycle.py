"""BBSApp startup, configuration, and shutdown."""

import importlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import database_core

SERVER = Path(__file__).resolve().parents[1] / "server.py"

MENU_CONFIG = (
    "[menu]\n"
    "main_menu_items = Q,B,U,X\n"
    "bbs_menu_items = M,B,C,J,X\n"
    "utilities_menu_items = S,F,W,X\n"
)


def write_config(path, extra=""):
    path.write_text(
        "[interface]\ndriver = meshcore_stub\n\n" + MENU_CONFIG + "\n" + extra,
        encoding="utf-8",
    )


@pytest.fixture
def server(monkeypatch, tmp_path):
    # server imports command_handlers, which reads menu items from ./config.ini.
    write_config(tmp_path / "config.ini")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BBS_KEEPALIVE_INTERVAL", raising=False)
    for name in ("mesh_integration", "command_handlers", "js8call_integration", "message_processing", "server"):
        sys.modules.pop(name, None)
    yield importlib.import_module("server")
    database_core.close_db_connection()
    database_core.set_db_path(None)


def test_keepalive_interval_is_read_from_the_config_file(server, monkeypatch, tmp_path):
    config_file = tmp_path / "bbs.ini"
    write_config(
        config_file,
        f"[database]\ndb_path = {tmp_path / 'bbs.db'}\n\n[healthcheck]\nkeepalive_interval = 45\n",
    )
    monkeypatch.setattr(sys, "argv", ["server.py", "--config", str(config_file)])

    app = server.BBSApp()
    app._setup_config()

    assert app.keepalive_interval == 45


@pytest.mark.parametrize("value", ["0", "-1"])
def test_keepalive_interval_below_one_second_falls_back_to_the_default(server, monkeypatch, tmp_path, value):
    # A non-positive interval would send a radio probe on every monitoring cycle.
    config_file = tmp_path / "bbs.ini"
    write_config(
        config_file,
        f"[database]\ndb_path = {tmp_path / 'bbs.db'}\n\n[healthcheck]\nkeepalive_interval = {value}\n",
    )
    monkeypatch.setattr(sys, "argv", ["server.py", "--config", str(config_file)])

    app = server.BBSApp()
    app._setup_config()

    assert app.keepalive_interval == 120


@pytest.mark.parametrize(
    ("config_value", "cli_args"),
    [("0", []), ("-1", []), ("10", ["--heartbeat-interval", "0"])],
    ids=["config-zero", "config-negative", "cli-zero"],
)
def test_heartbeat_interval_below_one_second_falls_back_to_the_default(
    server, monkeypatch, tmp_path, config_value, cli_args
):
    # A zero interval makes the monitoring loop spin without sleeping.
    config_file = tmp_path / "bbs.ini"
    write_config(
        config_file,
        f"[database]\ndb_path = {tmp_path / 'bbs.db'}\n\n[healthcheck]\nheartbeat_interval = {config_value}\n",
    )
    monkeypatch.setattr(sys, "argv", ["server.py", "--config", str(config_file), *cli_args])

    app = server.BBSApp()
    app._setup_config()

    assert app.heartbeat_interval == 10


def start_server(tmp_path, db_path=None):
    db_path = db_path or tmp_path / "bbs.db"
    write_config(
        tmp_path / "config.ini",
        f"[database]\ndb_path = {db_path}\n\n[healthcheck]\nheartbeat_interval = 1\n",
    )
    env = dict(os.environ, BBS_HEARTBEAT_PATH=str(tmp_path / "bbs_heartbeat"))
    return subprocess.Popen(
        [sys.executable, str(SERVER)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def wait_for(condition, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT], ids=["docker-stop", "ctrl-c"])
def test_stop_signal_shuts_the_server_down_cleanly(tmp_path, signum):
    heartbeat = tmp_path / "bbs_heartbeat"
    proc = start_server(tmp_path)
    try:
        assert wait_for(heartbeat.exists), "server never wrote a heartbeat"

        proc.send_signal(signum)
        # Docker sends SIGKILL 10 seconds after SIGTERM.
        output, _ = proc.communicate(timeout=8)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    assert proc.returncode == 0, output
    assert "BBS Application shutting down" in output
    assert not heartbeat.exists()


@pytest.fixture
def restore_signal_handlers():
    saved = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
    yield
    for signum, handler in saved.items():
        signal.signal(signum, handler)


def test_second_stop_signal_does_not_interrupt_shutdown(server, monkeypatch, tmp_path, restore_signal_handlers):
    config_file = tmp_path / "bbs.ini"
    write_config(config_file, f"[database]\ndb_path = {tmp_path / 'bbs.db'}\n")
    heartbeat = tmp_path / "bbs_heartbeat"
    monkeypatch.setenv("BBS_HEARTBEAT_PATH", str(heartbeat))
    monkeypatch.setattr(sys, "argv", ["server.py", "--config", str(config_file)])

    # docker stop arrives while the monitoring loop sleeps.
    def sleep_then_stop(_seconds):
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr("time.sleep", sleep_then_stop)

    # Shutdown waits for in-flight message handlers, which can take seconds.
    # The operator presses Ctrl-C again during that wait.
    drained = []
    real_shutdown_executor = server.shutdown_executor

    def impatient_shutdown_executor(wait=True, **kwargs):
        if wait:
            os.kill(os.getpid(), signal.SIGINT)
        real_shutdown_executor(wait=wait, **kwargs)
        if wait:
            drained.append(True)

    monkeypatch.setattr(server, "shutdown_executor", impatient_shutdown_executor)

    app = server.BBSApp()
    try:
        app.run()
    except KeyboardInterrupt:
        pytest.fail("the second signal escaped run() and cut shutdown short")

    assert drained == [True]
    assert not heartbeat.exists()


def test_server_exits_with_an_error_when_the_database_cannot_open(tmp_path):
    # A directory can't be opened as a SQLite file.
    unopenable = tmp_path / "not-a-file"
    unopenable.mkdir()

    proc = start_server(tmp_path, db_path=unopenable)
    try:
        output, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate()
        pytest.fail(f"server kept running without a database:\n{output}")

    assert proc.returncode != 0, output
    assert str(unopenable) in output
