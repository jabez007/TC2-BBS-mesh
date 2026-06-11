import importlib
import sys
import types

import pytest

from radio_drivers import MeshCoreStubDriver


class _FakeStreamInterface:
    pass


def _install_fake_radio_modules(monkeypatch):
    fake_meshtastic = types.ModuleType("meshtastic")
    setattr(fake_meshtastic, "BROADCAST_NUM", "^all")

    fake_serial_interface = types.ModuleType("meshtastic.serial_interface")
    fake_stream_interface = types.ModuleType("meshtastic.stream_interface")
    fake_tcp_interface = types.ModuleType("meshtastic.tcp_interface")

    setattr(fake_serial_interface, "SerialInterface", object)
    setattr(fake_stream_interface, "StreamInterface", _FakeStreamInterface)
    setattr(fake_tcp_interface, "TCPInterface", object)
    setattr(fake_meshtastic, "serial_interface", fake_serial_interface)
    setattr(fake_meshtastic, "stream_interface", fake_stream_interface)
    setattr(fake_meshtastic, "tcp_interface", fake_tcp_interface)

    monkeypatch.setitem(sys.modules, "meshtastic", fake_meshtastic)
    monkeypatch.setitem(sys.modules, "meshtastic.serial_interface", fake_serial_interface)
    monkeypatch.setitem(sys.modules, "meshtastic.stream_interface", fake_stream_interface)
    monkeypatch.setitem(sys.modules, "meshtastic.tcp_interface", fake_tcp_interface)

    fake_serial = types.ModuleType("serial")
    fake_serial_tools = types.ModuleType("serial.tools")
    fake_serial_list_ports = types.ModuleType("serial.tools.list_ports")
    setattr(fake_serial_list_ports, "comports", lambda: [])
    setattr(fake_serial_tools, "list_ports", fake_serial_list_ports)
    setattr(fake_serial, "tools", fake_serial_tools)

    monkeypatch.setitem(sys.modules, "serial", fake_serial)
    monkeypatch.setitem(sys.modules, "serial.tools", fake_serial_tools)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", fake_serial_list_ports)


def _write_test_config(tmp_path):
    (tmp_path / "config.ini").write_text(
        "[menu]\n"
        "main_menu_items = Q,B,U,X\n"
        "bbs_menu_items = G,I,N,U,X\n"
        "utilities_menu_items = F,S,W,X\n",
        encoding="utf-8",
    )


@pytest.fixture
def config_init_module(monkeypatch):
    _install_fake_radio_modules(monkeypatch)
    sys.modules.pop("config_init", None)
    return importlib.import_module("config_init")


@pytest.fixture
def message_processing_module(monkeypatch, tmp_path):
    _install_fake_radio_modules(monkeypatch)
    _write_test_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("command_handlers", None)
    sys.modules.pop("message_processing", None)
    sys.modules.pop("js8call_integration", None)
    return importlib.import_module("message_processing")


@pytest.fixture
def command_handlers_module(monkeypatch, tmp_path):
    _install_fake_radio_modules(monkeypatch)
    _write_test_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("command_handlers", None)
    return importlib.import_module("command_handlers")


def test_get_driver_preserves_stub_peer_and_allow_lists(config_init_module):
    system_config = {
        "driver_type": "meshcore_stub",
        "bbs_nodes": ["!peer1", "!peer2"],
        "allowed_nodes": ["!admin1", "!admin2"],
    }

    driver, raw_interface = config_init_module.get_driver(system_config)
    system_config["bbs_nodes"].append("!peer3")
    system_config["allowed_nodes"].append("!admin3")

    assert isinstance(driver, MeshCoreStubDriver)
    assert raw_interface is None
    assert driver.bbs_nodes == ["!peer1", "!peer2"]
    assert driver.allowed_nodes == ["!admin1", "!admin2"]


def test_process_message_uses_stub_bbs_nodes_for_bulletin_sync(
    monkeypatch, message_processing_module
):
    driver = MeshCoreStubDriver({"bbs_nodes": ["!peer1", "!peer2"]})
    captured = {}

    monkeypatch.setattr(message_processing_module, "get_user_state", lambda _sender_id: None)
    monkeypatch.setattr(
        message_processing_module,
        "handle_post_bulletin_command",
        lambda sender_id, message, current_driver, bbs_nodes: captured.update(
            {
                "sender_id": sender_id,
                "message": message,
                "driver": current_driver,
                "bbs_nodes": bbs_nodes,
            }
        ),
    )

    message_processing_module.process_message(77, "pb,,status", driver)

    assert captured == {
        "sender_id": 77,
        "message": "pb,,status",
        "driver": driver,
        "bbs_nodes": ["!peer1", "!peer2"],
    }


def test_urgent_board_permission_check_uses_stub_allow_list(
    monkeypatch, command_handlers_module
):
    driver = MeshCoreStubDriver({"allowed_nodes": ["!admin1"]})
    messages = []
    help_calls = []
    state_updates = []

    monkeypatch.setattr(
        driver,
        "get_nodes",
        lambda: {"!guest": {"num": 123, "user": {"shortName": "GUEST"}}},
    )
    monkeypatch.setattr(
        command_handlers_module,
        "send_message",
        lambda text, _sender_id, _driver: messages.append(text),
    )
    monkeypatch.setattr(
        command_handlers_module,
        "handle_help_command",
        lambda _sender_id, _driver, menu=None: help_calls.append(menu),
    )
    monkeypatch.setattr(
        command_handlers_module,
        "update_user_state",
        lambda _sender_id, state: state_updates.append(state),
    )

    command_handlers_module.handle_bb_steps(
        123,
        "p",
        2,
        {"board": "Urgent"},
        driver,
        driver.bbs_nodes,
    )

    assert messages == ["You don't have permission to post to this board."]
    assert help_calls == ["bbs"]
    assert state_updates == []
