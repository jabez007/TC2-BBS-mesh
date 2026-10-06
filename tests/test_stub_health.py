import importlib
import sys
import time

healthcheck = importlib.import_module("docker.healthcheck")


def test_meshcore_stub_stays_healthy_without_radio_traffic(monkeypatch, tmp_path):
    # server imports command_handlers, which reads menu items from ./config.ini.
    (tmp_path / "config.ini").write_text(
        "[menu]\nmain_menu_items = Q,B,U,X\nbbs_menu_items = M,B,C,J,X\nutilities_menu_items = S,F,W,X\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for name in ("mesh_integration", "command_handlers", "js8call_integration", "message_processing", "server"):
        sys.modules.pop(name, None)
    server = importlib.import_module("server")

    app = server.BBSApp()
    app.heartbeat_path = str(tmp_path / "bbs_heartbeat")
    # The stub has no radio, so nothing is ever received.
    app.last_rx_time = time.time() - 3600

    def stop_after_one_cycle(_seconds):
        app.running = False

    monkeypatch.setattr("time.sleep", stop_after_one_cycle)
    app._run_monitoring_cycle(None)

    monkeypatch.setenv("BBS_HEARTBEAT_PATH", app.heartbeat_path)
    assert healthcheck.check_heartbeat(None) is True
